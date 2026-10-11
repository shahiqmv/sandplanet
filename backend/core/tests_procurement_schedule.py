"""Procurement Schedule — spine + propose/confirm/sign-off workflow (Phase 1)."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Document, Project, Site, SitePmHistory, User)
from .tests import make_user


class ProcurementScheduleTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("psched_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa Upgrades", pm=self.pm)
        self.purch = make_user("psched_buy", User.Role.HO_PURCHASING)
        self.director = make_user("psched_dir", User.Role.DIRECTOR)
        self.se = make_user("psched_se", User.Role.SITE_ENGINEER, site=self.site)
        self.qs = make_user("psched_qs", User.Role.QS)
        self.client = APIClient()

    def _open(self):
        self.client.force_authenticate(self.pm)
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule")
        assert r.status_code == 201, r.data
        return r.data["id"]

    def _add_line(self, pk, **kw):
        self.client.force_authenticate(self.pm)
        body = {"description": "SS316 handrail", "section_code": "A",
                "section_title": "Villa Upgrades", "trade": "Metalwork",
                "required_date": "2026-10-01", **kw}
        return self.client.post(
            f"/api/v1/procurement-schedules/{pk}/lines", body, format="json")

    def test_open_is_site_scoped_ref(self):
        pk = self._open()
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        self.assertTrue(d["ref"].startswith("PSC-SJR-"))
        self.assertEqual(d["status"], "DRAFT")
        # one schedule per SITE (owner 2026-10-11) — opening it again from
        # the same project, from another project on the site, or from the
        # site itself, returns the same one
        r2 = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule")
        self.assertEqual(r2.data["id"], pk)
        self.assertEqual(r2.data["focus_project_id"], self.project.id)
        other = Project.objects.create(site=self.site, code="SJR-02",
                                       title="Pool", pm=self.pm)
        r3 = self.client.post(
            f"/api/v1/projects/{other.id}/procurement-schedule")
        self.assertEqual(r3.data["id"], pk)
        r4 = self.client.post(
            f"/api/v1/sites/{self.site.id}/procurement-schedule")
        self.assertEqual(r4.data["id"], pk)
        self.assertEqual([p["code"] for p in r4.data["projects"]],
                         ["SJR-01", "SJR-02"])
        self.assertEqual(len(self.client.get(
            "/api/v1/procurement-schedules").data), 1)

    def test_lines_belong_to_projects_and_sections_are_per_project(self):
        """Two projects on one site, each with a section "A": the lines sit
        under their own project's section, and the client plan reads
        project-wise with the project code on each section."""
        pk = self._open()
        other = Project.objects.create(site=self.site, code="SJR-02",
                                       title="Pool", pm=self.pm)
        # with two projects a line must say which one it is for
        r = self._add_line(pk)
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("project", r.data["detail"].lower())
        r = self._add_line(pk, project_id=self.project.id)
        self.assertEqual(r.status_code, 201, r.data)
        r = self._add_line(pk, project_id=other.id, description="Pool pump",
                           section_title="Pool plant")
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data
        self.assertEqual(sorted((s["code"], s["project_id"])
                                for s in d["sections"]),
                         sorted([("A", other.id), ("A", self.project.id)]))
        by_proj = {ln["project_code"]: ln["section_title"]
                   for ln in d["lines"]}
        self.assertEqual(by_proj, {"SJR-01": "Villa Upgrades",
                                   "SJR-02": "Pool plant"})
        self.assertEqual(sorted(d["totals"]["projects"]) if d["totals"]
                         else None, sorted([self.project.id, other.id]))
        from . import procurement_client as pc
        from .models import ProcurementSchedule
        plan = pc.client_plan(ProcurementSchedule.objects.get(pk=pk))
        self.assertEqual([s["title"] for s in plan["sections"]],
                         ["SJR-01 · Villa Upgrades", "SJR-02 · Pool plant"])
        self.assertEqual(plan["project_code"], "SJR")
        # moving a line to the other project takes it to that project's own
        # section "A" (which keeps its title)
        line = next(ln for ln in d["lines"] if ln["project_code"] == "SJR-01")
        r = self.client.patch(f"/api/v1/procurement-schedule-lines/{line['id']}",
                              {"project_id": other.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        moved = next(ln for ln in r.data["lines"] if ln["id"] == line["id"])
        self.assertEqual((moved["project_code"], moved["section_title"]),
                         ("SJR-02", "Pool plant"))
        self.assertEqual(sorted(s["title"] for s in r.data["sections"]),
                         ["Pool plant", "Villa Upgrades"])

    def test_per_project_schedules_fold_into_one_per_site(self):
        """What production had: a schedule per project. The merge keeps the
        biggest, moves the others' sections and lines under it tagged with
        their project, voids the folded documents and keeps their client
        links working (owner 2026-10-11)."""
        from django.core.management import call_command
        from .models import (Document, DocumentRevision, ProcurementSchedule,
                             ScheduleLine, ScheduleSection)
        from .procurement_client import generate_share_token

        def legacy(project, ref, n, status="DRAFT"):
            doc = Document.objects.create(
                doc_type="PSC", ref=ref, site=self.site, project=project,
                doc_date=date(2026, 8, 1), status=status, created_by=self.pm)
            rev = DocumentRevision.objects.create(
                document=doc, rev_label="R0", payload={}, created_by=self.pm)
            doc.current_revision = rev
            doc.save(update_fields=["current_revision"])
            s = ProcurementSchedule.objects.create(document=doc, site=self.site,
                                                   project=project)
            sec = ScheduleSection.objects.create(schedule=s, project=project,
                                                 code="A", title="Main")
            for i in range(n):
                ScheduleLine.objects.create(
                    schedule=s, project=project, section=sec, s_no=i + 1,
                    description=f"{project.code} item {i + 1}",
                    created_by=self.pm)
            return s
        other = Project.objects.create(site=self.site, code="SJR-02",
                                       title="Pool", pm=self.pm)
        big = legacy(self.project, "PSC-SJR-001", 5, status="SUBMITTED")
        small = legacy(other, "PSC-SJR-002", 2)
        generate_share_token(small, self.pm)
        old_token = small.share_token
        call_command("merge_procurement_schedules", site="SJR",
                     actor=self.pm.username)
        big.refresh_from_db(); small.refresh_from_db()
        self.assertEqual(small.merged_into_id, big.pk)
        self.assertTrue(small.document.is_void)
        self.assertEqual(big.lines.count(), 7)
        self.assertEqual(sorted((s.code, s.project.code)
                                for s in big.sections.all()),
                         [("A", "SJR-01"), ("A", "SJR-02")])
        self.assertEqual(big.lines.filter(project=other).count(), 2)
        self.assertEqual(big.document.status, "DRAFT")   # re-submit as one
        # the folded schedule's client link opens the site's plan
        self.assertEqual(big.share_token, old_token)
        r = self.client.get(f"/share/procurement/{old_token}")
        self.assertEqual(r.status_code, 200)
        # the register lists one schedule for the site, with both projects
        self.client.force_authenticate(self.pm)
        lst = self.client.get("/api/v1/procurement-schedules").data
        self.assertEqual([(x["ref"], x["projects"]) for x in lst],
                         [("PSC-SJR-001", ["SJR-01", "SJR-02"])])
        # running it again changes nothing
        call_command("merge_procurement_schedules", site="SJR",
                     actor=self.pm.username)
        self.assertEqual(ProcurementSchedule.objects.filter(
            merged_into__isnull=True, document__is_void=False).count(), 1)

    def test_qs_and_site_engineer_can_also_propose(self):
        # QS opens the schedule (starts from the commercial side)
        self.client.force_authenticate(self.qs)
        pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/lines",
                             {"description": "Chiller unit", "section_code": "B"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        # a site engineer can add a line too (no over-segregation)
        self.client.force_authenticate(self.se)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/lines",
                             {"description": "Cable tray", "section_code": "B"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["show_values"])          # SE still no values
        # Purchasing is the gate, not a proposer
        self.client.force_authenticate(self.purch)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/lines",
                             {"description": "x", "section_code": "B"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_stale_item_id_does_not_500(self):
        # a "linked to catalog" id for an item that no longer exists must save
        # as free-text, not crash the whole save (owner: "difficulty saving")
        pk = self._open()
        r = self._add_line(pk, item_id=99999999, quantity="5", uom="Kg")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(r.data["lines"][0]["item_id"])
        self.assertEqual(r.data["lines"][0]["uom"], "Kg")

    def test_line_links_to_item_master(self):
        from .models import Item
        item = Item.objects.create(code="ITM-90001", description="SS316 rail",
                                   unit="m", category="Steel & Metalwork")
        pk = self._open()
        r = self._add_line(pk, item_id=item.id, quantity="12", uom="m",
                           category="Steel & Metalwork")
        self.assertEqual(r.status_code, 201, r.data)
        ln = r.data["lines"][0]
        self.assertEqual(ln["item_id"], item.id)
        self.assertEqual(ln["item_code"], "ITM-90001")
        self.assertEqual(str(ln["quantity"]), "12.00")
        self.assertEqual(ln["uom"], "m")
        self.assertEqual(ln["category"], "Steel & Metalwork")

    def test_editing_section_title_renames_the_section(self):
        from .models import ScheduleSection
        pk = self._open()
        ln = self._add_line(pk).data["lines"][0]
        # The Edit form spreads the whole line into its PATCH, so section_id is
        # sent; a changed section_title must still rename the section.
        self.client.force_authenticate(self.pm)
        r = self.client.patch(
            f"/api/v1/procurement-schedule-lines/{ln['id']}",
            {"section_id": ln["section_id"], "section_code": "A",
             "section_title": "Villa Upgrades - REVISED",
             "description": "SS316 handrail"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(ScheduleSection.objects.get(pk=ln["section_id"]).title,
                         "Villa Upgrades - REVISED")

    def test_propose_confirm_signoff(self):
        pk = self._open()
        r = self._add_line(pk)
        self.assertEqual(r.status_code, 201, r.data)
        line_id = r.data["lines"][0]["id"]
        # PM submits → SUBMITTED (Purchasing queue)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.assertEqual(r.data["status"], "SUBMITTED")
        # Purchasing edits a commercial field then confirms
        self.client.force_authenticate(self.purch)
        self.client.patch(
            f"/api/v1/procurement-schedule-lines/{line_id}",
            {"planned_supplier": "Reef Steel", "source_country": "India",
             "estimated_value": "4200", "lead_time_days": 45}, format="json")
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "confirm"}, format="json")
        self.assertEqual(r.data["status"], "CONFIRMED")
        self.assertEqual(r.data["lines"][0]["state"], "CONFIRMED")
        self.assertEqual(r.data["lines"][0]["lead_time_days"], 45)
        # Director signs off → SIGNED_OFF + baseline stamped
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "sign_off"}, format="json")
        self.assertEqual(r.data["status"], "SIGNED_OFF")
        self.assertEqual(r.data["lines"][0]["state"], "SIGNED_OFF")
        self.assertTrue(r.data["baseline_signed_at"])

    def test_signed_off_shows_no_false_edit_then_reopen_edits(self):
        # Build a signed-off schedule.
        pk = self._open()
        line_id = self._add_line(pk).data["lines"][0]["id"]
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "sign_off"}, format="json")
        # PM sees no misleading Edit affordance, but a reopen path.
        self.client.force_authenticate(self.pm)
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        self.assertFalse(d["can_edit_plan"])
        self.assertTrue(d["can_reopen"])
        # The line itself is locked while signed off (the baseline) — but
        # the remark is the PM's living note and stays open (owner
        # 2026-10-06).
        self.assertTrue(d["can_edit_remarks"])
        r = self.client.patch(
            f"/api/v1/procurement-schedule-lines/{line_id}",
            {"description": "Something else"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("only the remarks", r.data["detail"])
        r = self.client.patch(
            f"/api/v1/procurement-schedule-lines/{line_id}",
            {"remarks": "Supplier confirmed shipping 12 Oct"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["lines"][0]["remarks"],
                         "Supplier confirmed shipping 12 Oct")
        self.assertEqual(r.data["status"], "SIGNED_OFF")
        # Reopen → DRAFT → the PM can edit again.
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/reopen")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "DRAFT")
        self.assertTrue(r.data["can_edit_plan"])
        r = self.client.patch(
            f"/api/v1/procurement-schedule-lines/{line_id}",
            {"remarks": "typo fix"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def _sign_off(self, pk):
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "sign_off"}, format="json")
        self.assertEqual(r.data["status"], "SIGNED_OFF", r.data)
        self.client.force_authenticate(self.pm)

    def test_an_amended_signed_batch_goes_back_round(self):
        # BVR 2026-09-03: reopened, one signed line edited, nothing
        # "proposed" — and no button to send it back to Purchasing.
        pk = self._open()
        line_id = self._add_line(pk).data["lines"][0]["id"]
        self._sign_off(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/reopen")
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        self.assertTrue(d["can_submit"])          # reopened → can go round
        r = self.client.patch(
            f"/api/v1/procurement-schedule-lines/{line_id}",
            {"remarks": "brand changed"}, format="json")
        ln = next(x for x in r.data["lines"] if x["id"] == line_id)
        self.assertEqual((ln["state"], ln["amended"]), ("SIGNED_OFF", True))
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "sign_off"}, format="json")
        ln = next(x for x in r.data["lines"] if x["id"] == line_id)
        self.assertEqual((r.data["status"], ln["state"], ln["amended"]),
                         ("SIGNED_OFF", "SIGNED_OFF", False))

    def test_eta_is_entered_by_the_team_not_computed(self):
        # Dates relative to today. They were fixed at 1 and 5 October 2026,
        # which read as "required date passed" from 2 October onwards and
        # failed the build on a day nothing in this module had changed.
        from datetime import timedelta
        required = date.today() + timedelta(days=30)
        eta = required + timedelta(days=4)
        pk = self._open()
        line_id = self._add_line(pk, required_date=required.isoformat(),
                                 lead_time_days=30).data["lines"][0]["id"]
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        ln = next(x for x in d["lines"] if x["id"] == line_id)
        self.assertIsNone(ln["risk"]["projected"])
        self.assertEqual(ln["risk"]["reason"], "No ETA entered")
        eta_stage = next(s for s in ln["pipeline"] if s["key"] == "eta")
        self.assertEqual(eta_stage["detail"], "No ETA entered")
        r = self.client.post(f"/api/v1/procurement-schedule-lines/{line_id}/eta",
                             {"eta_date": eta.isoformat()}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        ln = next(x for x in r.data["lines"] if x["id"] == line_id)
        self.assertEqual(ln["eta_date"], eta)
        self.assertEqual(ln["risk"]["level"], "LATE")   # after the required date
        eta_stage = next(s for s in ln["pipeline"] if s["key"] == "eta")
        self.assertEqual(eta_stage["detail"], f"Late — {eta.isoformat()}")
        from .models import ScheduleLine
        from .procurement_client import client_row
        self.assertEqual(client_row(ScheduleLine.objects.get(pk=line_id))["eta"],
                         eta)
        # Purchasing may enter it too; a Site Engineer may not.
        self.client.force_authenticate(self.purch)
        r = self.client.post(f"/api/v1/procurement-schedule-lines/{line_id}/eta",
                             {"eta_date": ""}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(next(x for x in r.data["lines"]
                               if x["id"] == line_id)["eta_date"])

    def test_a_mistaken_signoff_can_be_withdrawn(self):
        pk = self._open()
        line_id = self._add_line(pk).data["lines"][0]["id"]
        self._sign_off(pk)
        from .models import ProcurementSchedule
        from .procurement_schedule import withdraw_signoff
        sched = ProcurementSchedule.objects.get(document_id=pk)
        # A reason is required, and only a sign-off role may withdraw.
        self.assertIn("reason", withdraw_signoff(sched, self.director, "  "))
        self.assertIsNotNone(withdraw_signoff(sched, self.pm, "oops"))
        self.assertIsNone(withdraw_signoff(sched, self.director,
                                           "signed off by mistake"))
        sched.refresh_from_db()
        self.assertIsNone(sched.baseline_signed_at)
        self.assertEqual(sched.document.status, "DRAFT")
        ln = sched.lines.get(pk=line_id)
        self.assertEqual((ln.state, ln.amended_at), ("PROPOSED", None))
        self.assertEqual(
            sched.document.approvals.filter(
                action="WITHDRAW_SIGNOFF").first().comment,
            "signed off by mistake")
        # The PM can take it round again from there.
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        self.assertTrue(d["can_submit"])
        self.assertTrue(d["can_edit_plan"])

    def test_a_second_signoff_blocks_a_blind_withdrawal(self):
        pk = self._open()
        self._add_line(pk)
        self._sign_off(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/reopen")
        self._add_line(pk, description="Second batch item")
        self._sign_off(pk)
        from .models import ProcurementSchedule
        from .procurement_schedule import withdraw_signoff
        sched = ProcurementSchedule.objects.get(document_id=pk)
        err = withdraw_signoff(sched, self.director, "wrong one")
        self.assertIn("more than once", err)
        sched.refresh_from_db()
        self.assertIsNotNone(sched.baseline_signed_at)

    def test_the_pm_can_take_a_submitted_schedule_back(self):
        """Submitted to Purchasing, the PM was shut out until it came back
        or was signed off. He owns it (owner 2026-10-06)."""
        pk = self._open()
        line_id = self._add_line(pk).data["lines"][0]["id"]
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.se)
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        self.assertEqual((d["status"], d["can_edit_plan"], d["can_reopen"],
                          d["can_edit_remarks"]),
                         ("SUBMITTED", False, True, True))
        r = self.client.patch(
            f"/api/v1/procurement-schedule-lines/{line_id}",
            {"remarks": "Awaiting the client's colour choice"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.client.force_authenticate(self.purch)
        self.assertFalse(self.client.get(
            f"/api/v1/procurement-schedules/{pk}").data["can_reopen"])
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/reopen")
        self.assertEqual((r.status_code, r.data["status"], r.data["can_edit_plan"]),
                         (200, "DRAFT", True))

    def test_reopen_only_from_signed_off_and_by_team(self):
        pk = self._open()                              # DRAFT
        self.client.force_authenticate(self.pm)
        self.assertEqual(
            self.client.post(
                f"/api/v1/procurement-schedules/{pk}/reopen").status_code, 400)
        # Purchasing isn't a proposer → can't reopen even a signed-off one
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "sign_off"}, format="json")
        self.client.force_authenticate(self.purch)
        self.assertEqual(
            self.client.post(
                f"/api/v1/procurement-schedules/{pk}/reopen").status_code, 400)

    def test_purchasing_returns_to_pm(self):
        pk = self._open()
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "return", "note": "Confirm the brand"},
                             format="json")
        self.assertEqual(r.data["status"], "DRAFT")
        self.assertEqual(r.data["lines"][0]["state"], "PROPOSED")

    def test_return_needs_reason(self):
        pk = self._open()
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "return"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_only_purchasing_confirms_only_director_signs(self):
        pk = self._open()
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        # PM cannot confirm
        self.client.force_authenticate(self.pm)
        self.assertEqual(self.client.post(
            f"/api/v1/procurement-schedules/{pk}/action",
            {"action": "confirm"}, format="json").status_code, 400)
        # Purchasing confirms; a non-director cannot sign off
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        self.assertEqual(self.client.post(
            f"/api/v1/procurement-schedules/{pk}/action",
            {"action": "sign_off"}, format="json").status_code, 400)

    def test_values_hidden_from_site_engineer(self):
        pk = self._open()
        self._add_line(pk)
        # PM sees estimated_value key; SE never does
        pm_line = self.client.get(
            f"/api/v1/procurement-schedules/{pk}").data["lines"][0]
        self.assertIn("estimated_value", pm_line)
        self.client.force_authenticate(self.se)
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        self.assertFalse(d["show_values"])
        self.assertNotIn("estimated_value", d["lines"][0])

    def test_adding_line_after_signoff_reopens_batch(self):
        pk = self._open()
        r = self._add_line(pk)
        first_line = r.data["lines"][0]["id"]
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "sign_off"}, format="json")
        # PM adds a second line to the signed schedule → reopens to DRAFT
        r = self._add_line(pk, description="Pump valve")
        self.assertEqual(r.data["status"], "DRAFT")
        states = {ln["id"]: ln["state"] for ln in r.data["lines"]}
        self.assertEqual(states[first_line], "SIGNED_OFF")   # baseline stays
        new_line = next(i for i in states if i != first_line)
        self.assertEqual(states[new_line], "PROPOSED")

    def test_director_signs_off_on_mobile(self):
        pk = self._open()
        ref = self.client.get(
            f"/api/v1/procurement-schedules/{pk}").data["ref"]
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        # Director on mobile
        self.director.set_password("verify-123")
        self.director.save()
        m = APIClient()
        tok = m.post("/api/mobile/v1/auth/login",
                     {"username": self.director.username,
                      "password": "verify-123"}, format="json").data["token"]
        m.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
        q = m.get("/api/mobile/v1/queue")
        self.assertIn(ref, [i["ref"] for i in q.data["items"]])
        detail = m.get(f"/api/mobile/v1/documents/{ref}")
        self.assertTrue(any(f["k"] == "Project"
                            for f in detail.data["summary"]))
        a = m.post(f"/api/mobile/v1/documents/{ref}/approve", {}, format="json")
        self.assertEqual(a.status_code, 200, a.data)
        self.assertEqual(Document.objects.get(ref=ref).status, "SIGNED_OFF")


class ScheduleDeleteTests(ProcurementScheduleTests):
    """Admin deletes a draft schedule a PM opened in error (owner 2026-08-08)."""

    def setUp(self):
        super().setUp()
        self.admin = make_user("psched_admin", User.Role.ADMIN)

    def test_admin_deletes_a_draft(self):
        pk = self._open()
        self._add_line(pk)
        self.client.force_authenticate(self.admin)
        r = self.client.delete(f"/api/v1/procurement-schedules/{pk}")
        self.assertEqual(r.status_code, 204, getattr(r, "data", r))
        # gone — document, schedule and its lines all cascade away
        self.assertFalse(Document.objects.filter(pk=pk).exists())
        self.assertEqual(self.client.get(
            f"/api/v1/procurement-schedules/{pk}").status_code, 404)

    def test_non_admin_cannot_delete(self):
        pk = self._open()
        for who in (self.pm, self.purch, self.director, self.qs):
            self.client.force_authenticate(who)
            r = self.client.delete(f"/api/v1/procurement-schedules/{pk}")
            self.assertEqual(r.status_code, 400, f"{who.role}: {r.data}")
        self.assertTrue(Document.objects.filter(pk=pk).exists())

    def test_only_a_draft_can_be_deleted(self):
        pk = self._open()
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.admin)
        r = self.client.delete(f"/api/v1/procurement-schedules/{pk}")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Document.objects.filter(pk=pk).exists())
