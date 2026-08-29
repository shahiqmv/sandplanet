"""Unit progress tracking on a unit-based BOQ project (owner 2026-08-23)."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Boq, BoqCategory, Document, DocumentRevision, Project,
                     ProjectUnit, Site, SitePmHistory, User)
from .tests import make_user


class UnitBoardBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SFR", name="Fushi",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("u_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.se = make_user("u_se", User.Role.SITE_ENGINEER, site=self.site)
        self.qs = make_user("u_qs", User.Role.QS)
        self.project = Project.objects.create(
            site=self.site, code="19 VILLAS", title="Refurbishment",
            contract_value="500000")
        self.boq = Boq.objects.create(project=self.project, currency="USD",
                                      mode=Boq.Mode.UNIT)
        self.cat = BoqCategory.objects.create(
            boq=self.boq, sort_order=1, ref="Bill 03",
            name="Villa Category - D", qty=3, unit="no")
        self.lump = BoqCategory.objects.create(
            boq=self.boq, sort_order=2, ref="Bill 01", name="Preliminaries",
            qty=1, is_lump=True, lump_amount="10000")
        self.client = APIClient()
        self.client.force_authenticate(self.pm)

    def _generate(self, cat=None):
        return self.client.post(
            f"/api/v1/boq-categories/{(cat or self.cat).id}/generate-units",
            {}, format="json")


class UnitSetupTests(UnitBoardBase):
    def test_units_are_generated_from_the_category_quantity(self):
        r = self._generate()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["created"], 3)
        self.assertEqual([u["ref"] for u in r.data["units"]],
                         ["BILL03-01", "BILL03-02", "BILL03-03"])
        # Every unit starts on the default stage ladder, not started.
        u = r.data["units"][0]
        self.assertEqual(u["status"], "NOT_STARTED")
        self.assertEqual(float(u["percent"]), 0.0)
        self.assertTrue(len(u["stages"]) >= 5)

    def test_a_category_can_be_given_the_real_unit_numbers(self):
        """A refurbishment PM knows the villa numbers — Soneva Fushi's
        Category C is villas 56, 57 and 58, not BILL03-01 (owner
        2026-08-23)."""
        r = self.client.post(
            f"/api/v1/boq-categories/{self.cat.id}/generate-units",
            {"refs": ["Villa 56", "Villa 57", "Villa 58"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual([u["ref"] for u in r.data["units"]],
                         ["Villa 56", "Villa 57", "Villa 58"])
        self.assertEqual(self.cat.units.count(), 3)
        u = r.data["units"][0]
        self.assertEqual(u["category"], self.cat.name)
        self.assertTrue(len(u["stages"]) >= 5)
        # Re-running with an overlapping list adds only what is missing.
        r2 = self.client.post(
            f"/api/v1/boq-categories/{self.cat.id}/generate-units",
            {"refs": ["Villa 57", "Villa 60"]}, format="json")
        self.assertEqual(r2.data["created"], 1)
        self.assertEqual(len(r2.data["units"]), 4)

    def test_generating_twice_tops_up_rather_than_duplicating(self):
        self._generate()
        self.cat.qty = 5
        self.cat.save(update_fields=["qty"])
        r = self._generate()
        self.assertEqual(r.data["created"], 2)
        self.assertEqual(len(r.data["units"]), 5)

    def test_a_lump_bill_has_no_units(self):
        r = self._generate(self.lump)
        self.assertEqual(r.status_code, 400)
        self.assertIn("lump", r.data["detail"].lower())

    def test_the_pm_renames_a_unit_to_the_clients_number(self):
        self._generate()
        uid = ProjectUnit.objects.first().id
        r = self.client.patch(f"/api/v1/units/{uid}",
                              {"ref": "Villa 214", "size": "145 m2",
                               "scope": "Full refurbishment"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        u = next(x for x in r.data["units"] if x["id"] == uid)
        self.assertEqual(u["ref"], "Villa 214")
        self.assertEqual(u["size"], "145 m2")

    def test_a_duplicate_ref_is_refused(self):
        self._generate()
        a, b = ProjectUnit.objects.all()[:2]
        r = self.client.patch(f"/api/v1/units/{b.id}", {"ref": a.ref},
                              format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already used", r.data["detail"])

    def test_every_endpoint_returns_the_full_panel_payload(self):
        """The panel replaces its whole state with each response. A bare board
        made it forget the project was unit-based and fall back to the "not a
        unit BOQ" message the moment units were generated (owner 2026-08-23)."""
        keys = ("is_unit_project", "can_manage", "ladders", "units",
                "categories", "overall_percent")
        r = self._generate()
        for k in keys:
            self.assertIn(k, r.data, f"generate-units is missing {k}")
        self.assertTrue(r.data["is_unit_project"])
        unit = ProjectUnit.objects.first()
        for resp in (
            self.client.post(f"/api/v1/boq-categories/{self.cat.id}/stages",
                             {"stages": [{"name": "A", "weight": 1}]},
                             format="json"),
            self.client.patch(f"/api/v1/units/{unit.id}", {"size": "10 m2"},
                              format="json"),
            self.client.post(f"/api/v1/units/{unit.id}/progress",
                             {"stage_id": self.cat.stages.first().id,
                              "percent": "10"}, format="json"),
        ):
            self.assertEqual(resp.status_code, 200, resp.data)
            for k in keys:
                self.assertIn(k, resp.data, f"{resp.request['PATH_INFO']} "
                                            f"is missing {k}")
            self.assertTrue(resp.data["is_unit_project"])

    def test_units_can_be_put_in_the_order_the_site_walks_them(self):
        """Generated refs rarely match the sequence on the ground (owner
        2026-08-23)."""
        self._generate()
        ids = [u["id"] for u in self.client.get(
            f"/api/v1/projects/{self.project.id}/units").data["units"]]
        r = self.client.post(f"/api/v1/projects/{self.project.id}/reorder-units",
                             {"ids": [ids[2], ids[0], ids[1]]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([u["id"] for u in r.data["units"]],
                         [ids[2], ids[0], ids[1]])
        again = self.client.get(f"/api/v1/projects/{self.project.id}/units")
        self.assertEqual([u["id"] for u in again.data["units"]],
                         [ids[2], ids[0], ids[1]])

    def test_a_partial_order_leaves_the_rest_behind_it(self):
        self._generate()
        ids = [u["id"] for u in self.client.get(
            f"/api/v1/projects/{self.project.id}/units").data["units"]]
        r = self.client.post(f"/api/v1/projects/{self.project.id}/reorder-units",
                             {"ids": [ids[2]]}, format="json")
        self.assertEqual([u["id"] for u in r.data["units"]][0], ids[2])
        self.assertEqual(len(r.data["units"]), 3)

    def test_a_unit_from_another_project_is_refused(self):
        self._generate()
        other = Project.objects.create(site=self.site, code="OTHER",
                                       title="Other")
        stray = ProjectUnit.objects.create(project=other, ref="X-01")
        r = self.client.post(f"/api/v1/projects/{self.project.id}/reorder-units",
                             {"ids": [stray.id]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_only_the_pm_or_qs_sets_up_units(self):
        self.client.force_authenticate(self.se)
        self.assertEqual(self._generate().status_code, 403)


class StageLadderTests(UnitBoardBase):
    def test_the_ladder_is_editable_and_keeps_progress_on_surviving_stages(self):
        self._generate()
        unit = ProjectUnit.objects.first()
        stage = self.cat.stages.all()[2]
        self.client.post(f"/api/v1/units/{unit.id}/progress",
                         {"stage_id": stage.id, "percent": "100"},
                         format="json")
        keep = stage.name
        r = self.client.post(f"/api/v1/boq-categories/{self.cat.id}/stages",
                             {"stages": [{"name": "Set out", "weight": 20},
                                         {"name": keep, "weight": 60},
                                         {"name": "Handover", "weight": 20}]},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        u = next(x for x in r.data["units"] if x["id"] == unit.id)
        self.assertEqual([s["name"] for s in u["stages"]],
                         ["Set out", keep, "Handover"])
        # the surviving stage kept its 100%, and now carries 60% weight
        self.assertEqual(float(u["percent"]), 60.0)

    def test_reordering_the_ladder_keeps_each_stages_progress(self):
        """The ladder's order is the sequence of work, and it is usually typed
        out of sequence first time round — reordering must not cost the
        figures already reported (owner 2026-08-23)."""
        self._generate()
        unit = ProjectUnit.objects.first()
        second = self.cat.stages.all()[1]
        self.client.post(f"/api/v1/units/{unit.id}/progress",
                         {"stage_id": second.id, "percent": "100"},
                         format="json")
        before = [s.name for s in self.cat.stages.all()]
        # Swap the first two — the same names, in a new order.
        swapped = [{"name": before[1], "weight": 50},
                   {"name": before[0], "weight": 50}]
        r = self.client.post(f"/api/v1/boq-categories/{self.cat.id}/stages",
                             {"stages": swapped}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        u = next(x for x in r.data["units"] if x["id"] == unit.id)
        self.assertEqual([s["name"] for s in u["stages"]],
                         [before[1], before[0]])
        # The 100% followed its stage, which is now first and worth half.
        moved = next(s for s in u["stages"] if s["name"] == before[1])
        self.assertEqual(float(moved["percent"]), 100.0)
        self.assertEqual(float(u["percent"]), 50.0)
        self.assertEqual(u["current_stage"], before[0])

    def test_weights_need_not_sum_to_a_hundred(self):
        self._generate()
        r = self.client.post(f"/api/v1/boq-categories/{self.cat.id}/stages",
                             {"stages": [{"name": "A", "weight": 1},
                                         {"name": "B", "weight": 3}]},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        unit = ProjectUnit.objects.first()
        stage_b = self.cat.stages.get(name="B")
        self.client.post(f"/api/v1/units/{unit.id}/progress",
                         {"stage_id": stage_b.id, "percent": "100"},
                         format="json")
        unit.refresh_from_db()
        self.assertEqual(float(unit.percent), 75.0)      # 3 of 4

    def test_an_empty_ladder_is_refused(self):
        r = self.client.post(f"/api/v1/boq-categories/{self.cat.id}/stages",
                             {"stages": []}, format="json")
        self.assertEqual(r.status_code, 400)


class UnitProgressTests(UnitBoardBase):
    def test_the_board_reports_the_stage_a_unit_is_on(self):
        self._generate()
        unit = ProjectUnit.objects.first()
        stages = list(self.cat.stages.all())
        self.client.post(f"/api/v1/units/{unit.id}/progress",
                         {"stage_id": stages[0].id, "percent": "100"},
                         format="json")
        r = self.client.post(f"/api/v1/units/{unit.id}/progress",
                             {"stage_id": stages[1].id, "percent": "50"},
                             format="json")
        u = next(x for x in r.data["units"] if x["id"] == unit.id)
        self.assertEqual(u["current_stage"], stages[1].name)
        self.assertEqual(u["status"], "IN_PROGRESS")
        self.assertTrue(0 < float(u["percent"]) < 100)

    def test_a_finished_unit_reads_complete_with_its_date(self):
        self._generate()
        unit = ProjectUnit.objects.first()
        for st in self.cat.stages.all():
            self.client.post(f"/api/v1/units/{unit.id}/progress",
                             {"stage_id": st.id, "percent": "100"},
                             format="json")
        unit.refresh_from_db()
        self.assertEqual(unit.status, "COMPLETE")
        self.assertEqual(float(unit.percent), 100.0)
        self.assertEqual(unit.completed_on, date.today())

    def test_a_unit_on_hold_keeps_its_percentage_and_says_why(self):
        self._generate()
        unit = ProjectUnit.objects.first()
        st = self.cat.stages.first()
        self.client.post(f"/api/v1/units/{unit.id}/progress",
                         {"stage_id": st.id, "percent": "100"}, format="json")
        r = self.client.patch(f"/api/v1/units/{unit.id}",
                              {"status": "ON_HOLD",
                               "hold_reason": "client changed the finishes"},
                              format="json")
        u = next(x for x in r.data["units"] if x["id"] == unit.id)
        self.assertEqual(u["status"], "ON_HOLD")
        self.assertGreater(float(u["percent"]), 0)
        self.assertIn("finishes", u["hold_reason"])

    def test_the_board_rolls_up_per_category_and_overall(self):
        self._generate()
        units = list(ProjectUnit.objects.all())
        st = self.cat.stages.first()          # first stage, weight 5 of 100
        for u in units[:2]:
            self.client.post(f"/api/v1/units/{u.id}/progress",
                             {"stage_id": st.id, "percent": "100"},
                             format="json")
        r = self.client.get(f"/api/v1/projects/{self.project.id}/units")
        self.assertEqual(r.data["unit_count"], 3)
        cat = next(c for c in r.data["categories"]
                   if c["id"] == self.cat.id)
        self.assertEqual(cat["in_progress"], 2)
        self.assertEqual(cat["not_started"], 1)
        self.assertGreater(float(r.data["overall_percent"]), 0)


class DurationTests(UnitBoardBase):
    """Each unit shows when it started and how long it has been running —
    derived from dates already held, no new bookkeeping (owner 2026-08-23)."""

    def test_a_running_unit_counts_days_since_it_started(self):
        from datetime import timedelta
        self._generate()
        unit = ProjectUnit.objects.first()
        stage = self.cat.stages.first()
        self.client.post(f"/api/v1/units/{unit.id}/progress",
                         {"stage_id": stage.id, "percent": "40"},
                         format="json")
        # Work actually began a fortnight ago; the PM corrects the date.
        began = date.today() - timedelta(days=14)
        r = self.client.patch(f"/api/v1/units/{unit.id}",
                              {"started_on": str(began)}, format="json")
        u = next(x for x in r.data["units"] if x["id"] == unit.id)
        self.assertEqual(str(u["started_on"]), str(began))
        self.assertEqual(u["days_running"], 14)

    def test_a_finished_unit_reports_how_long_it_took(self):
        from datetime import timedelta
        self._generate()
        unit = ProjectUnit.objects.first()
        began = date.today() - timedelta(days=9)
        self.client.patch(f"/api/v1/units/{unit.id}",
                          {"started_on": str(began)}, format="json")
        for st in self.cat.stages.all():
            self.client.post(f"/api/v1/units/{unit.id}/progress",
                             {"stage_id": st.id, "percent": "100"},
                             format="json")
        r = self.client.get(f"/api/v1/projects/{self.project.id}/units")
        u = next(x for x in r.data["units"] if x["id"] == unit.id)
        self.assertEqual(u["status"], "COMPLETE")
        self.assertEqual(str(u["completed_on"]), str(date.today()))
        self.assertEqual(u["days_running"], 9)      # start to finish, not today

    def test_a_unit_not_yet_started_has_no_duration(self):
        self._generate()
        r = self.client.get(f"/api/v1/projects/{self.project.id}/units")
        u = r.data["units"][0]
        self.assertIsNone(u["started_on"])
        self.assertIsNone(u["days_running"])

    def test_finishing_before_starting_is_refused(self):
        from datetime import timedelta
        self._generate()
        unit = ProjectUnit.objects.first()
        for st in self.cat.stages.all():
            self.client.post(f"/api/v1/units/{unit.id}/progress",
                             {"stage_id": st.id, "percent": "100"},
                             format="json")
        r = self.client.patch(
            f"/api/v1/units/{unit.id}",
            {"started_on": str(date.today() + timedelta(days=3))},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("finish before it starts", r.data["detail"])


class DprDrivesTheBoardTests(UnitBoardBase):
    """The DPR stays the record: it reports the unit progress, and the board
    says which DPR each figure came from."""

    def _dpr(self, rows):
        doc = Document.objects.create(
            doc_type="DPR", ref=f"DPR-SFR-{Document.objects.count()+1:03d}",
            site=self.site, doc_date=date.today(), status="DRAFT",
            created_by=self.se)
        doc.current_revision = DocumentRevision.objects.create(
            document=doc, rev_label="R0", created_by=self.se,
            payload={"work_done": rows})
        doc.save(update_fields=["current_revision"])
        return doc

    def test_issuing_a_dpr_moves_the_unit_board(self):
        from core import units as svc
        self._generate()
        unit = ProjectUnit.objects.first()
        first, stage = self.cat.stages.all()[0], self.cat.stages.all()[1]
        # One DPR, two rows — mobilisation finished, the next stage part done.
        doc = self._dpr([{"activity": "Mobilise", "unit_id": unit.id,
                          "stage_id": first.id, "progress_todate": "100"},
                         {"activity": "Civil", "unit_id": unit.id,
                          "stage_id": stage.id, "progress_todate": "40"}])
        applied = svc.apply_dpr(doc, self.se)
        self.assertEqual(applied, 2)
        board = svc.board(self.project)
        u = next(x for x in board["units"] if x["id"] == unit.id)
        self.assertEqual(u["current_stage"], stage.name)
        self.assertEqual(u["last_dpr"], doc.ref)
        st = next(s for s in u["stages"] if s["id"] == stage.id)
        self.assertEqual(float(st["percent"]), 40.0)
        self.assertEqual(st["dpr"], doc.ref)
        self.assertEqual(st["on"], date.today())

    def test_ordinary_work_rows_are_untouched(self):
        """A DPR row with no unit is the existing programme row — the daily
        report must not be narrowed by this feature."""
        from core import units as svc
        self._generate()
        doc = self._dpr([{"activity": "General site works",
                          "progress_todate": "30"},
                         {"activity": "Nothing", "unit_id": None}])
        self.assertEqual(svc.apply_dpr(doc, self.se), 0)
        self.assertEqual(len(doc.current_revision.payload["work_done"]), 2)

    def test_a_unit_from_another_site_is_ignored(self):
        from core import units as svc
        self._generate()
        other = Site.objects.create(code="ZZZ", name="Other",
                                    status=Site.Status.ACTIVE)
        unit = ProjectUnit.objects.first()
        doc = self._dpr([{"unit_id": unit.id,
                          "stage_id": self.cat.stages.first().id,
                          "progress_todate": "50"}])
        doc.site = other
        doc.save(update_fields=["site"])
        self.assertEqual(svc.apply_dpr(doc, self.se), 0)


class ClientPortalUnitTests(UnitBoardBase):
    def _portal(self):
        admin = make_user("u_admin", User.Role.ADMIN)
        c = APIClient()
        c.force_authenticate(admin)
        r = c.post("/api/v1/client-users", {
            "org_name": "Resort", "full_name": "Client", "email": "c@r.mv",
            "site_ids": [self.site.id]}, format="json")
        pw = r.data["temp_password"]
        c.force_authenticate(None)
        tok = c.post("/api/client/auth/login",
                     {"email": "c@r.mv", "password": pw},
                     format="json").data["token"]
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
        return c

    def test_the_client_sees_the_board_without_our_internal_refs(self):
        from core import units as svc
        self._generate()
        unit = ProjectUnit.objects.first()
        stage = self.cat.stages.first()
        doc = Document.objects.create(
            doc_type="DPR", ref="DPR-SFR-900", site=self.site,
            doc_date=date.today(), status="ISSUED", created_by=self.se)
        doc.current_revision = DocumentRevision.objects.create(
            document=doc, rev_label="R0", created_by=self.se, payload={})
        doc.save(update_fields=["current_revision"])
        svc.report_progress(unit, stage, 100, document=doc, on=date.today())
        c = self._portal()
        r = c.get(f"/api/client/projects/{self.project.id}/units")
        self.assertEqual(r.status_code, 200, r.data)
        u = next(x for x in r.data["units"] if x["id"] == unit.id)
        self.assertEqual(u["ref"], unit.ref)
        self.assertGreater(float(u["percent"]), 0)
        self.assertNotIn("last_dpr", u)          # our daily-report ref
        self.assertNotIn("dpr", u["stages"][0])

    def test_a_client_cannot_reach_another_clients_project(self):
        other_site = Site.objects.create(code="OTH", name="Other",
                                         status=Site.Status.ACTIVE)
        other = Project.objects.create(site=other_site, code="X", title="X")
        c = self._portal()
        self.assertEqual(
            c.get(f"/api/client/projects/{other.id}/units").status_code, 404)


class FlatPricedProjectTests(TestCase):
    """VKR's 17 overwater pools: priced flat, BOQ locked with claims against
    it, but the client and the team still need to know where each pool is.
    Tracking is a monitoring concern and must never touch pricing (owner
    2026-08-23)."""

    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("f_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.se = make_user("f_se", User.Role.SITE_ENGINEER, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="17POOL", title="17 Overwater pools",
            contract_value="1426784.78")
        # A conventional, LOCKED BOQ — exactly VKR's shape.
        self.boq = Boq.objects.create(project=self.project, currency="USD",
                                      mode=Boq.Mode.CONVENTIONAL,
                                      is_locked=True)
        self.client = APIClient()
        self.client.force_authenticate(self.pm)

    def test_a_flat_priced_project_can_still_track_units(self):
        r = self.client.get(f"/api/v1/projects/{self.project.id}/units")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["is_unit_project"])   # the board is offered
        self.assertFalse(r.data["unit_priced"])      # ...but not BOQ-priced
        self.assertFalse(r.data["tracks_units"])     # nothing set up yet

    def test_units_are_created_from_the_real_villa_numbers(self):
        refs = ["V211", "V213", "V215"]
        r = self.client.post(f"/api/v1/projects/{self.project.id}/create-units",
                             {"refs": refs}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["created"], 3)
        self.assertEqual([u["ref"] for u in r.data["units"]], refs)
        self.assertTrue(r.data["tracks_units"])
        # A default ladder came with them, hung off the project.
        self.assertTrue(len(r.data["project_stages"]) >= 5)
        self.assertEqual(self.project.units.filter(
            category__isnull=True).count(), 3)
        # ...and the BOQ was not touched.
        self.boq.refresh_from_db()
        self.assertTrue(self.boq.is_locked)
        self.assertEqual(self.boq.mode, "CONVENTIONAL")

    def test_a_count_and_prefix_names_them_when_numbers_are_unknown(self):
        r = self.client.post(f"/api/v1/projects/{self.project.id}/create-units",
                             {"count": 4, "prefix": "POOL"}, format="json")
        self.assertEqual([u["ref"] for u in r.data["units"]],
                         ["POOL-01", "POOL-02", "POOL-03", "POOL-04"])

    def test_creating_again_tops_up_and_never_duplicates(self):
        self.client.post(f"/api/v1/projects/{self.project.id}/create-units",
                         {"refs": ["V211", "V213"]}, format="json")
        r = self.client.post(f"/api/v1/projects/{self.project.id}/create-units",
                             {"refs": ["V213", "V215"]}, format="json")
        self.assertEqual(r.data["created"], 1)
        self.assertEqual([u["ref"] for u in r.data["units"]],
                         ["V211", "V213", "V215"])

    def test_the_project_ladder_is_the_scope_of_works(self):
        self.client.post(f"/api/v1/projects/{self.project.id}/create-units",
                         {"refs": ["V211", "V213"]}, format="json")
        ladder = [{"name": "Precast column", "weight": 15},
                  {"name": "Pool construction", "weight": 35},
                  {"name": "Finishes", "weight": 25},
                  {"name": "MEP fixes", "weight": 15},
                  {"name": "Commissioning", "weight": 10}]
        r = self.client.post(f"/api/v1/projects/{self.project.id}/unit-stages",
                             {"stages": ladder}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([s["name"] for s in r.data["project_stages"]],
                         [x["name"] for x in ladder])
        u = r.data["units"][0]
        self.assertEqual([s["name"] for s in u["stages"]],
                         [x["name"] for x in ladder])
        # Weighted roll-up on the project ladder.
        stage = next(s for s in u["stages"] if s["name"] == "Precast column")
        r2 = self.client.post(f"/api/v1/units/{u['id']}/progress",
                              {"stage_id": stage["id"], "percent": "100"},
                              format="json")
        moved = next(x for x in r2.data["units"] if x["id"] == u["id"])
        self.assertEqual(float(moved["percent"]), 15.0)
        self.assertEqual(moved["current_stage"], "Pool construction")

    def test_the_dpr_reports_against_a_flat_priced_projects_units(self):
        from core import units as svc
        self.client.post(f"/api/v1/projects/{self.project.id}/create-units",
                         {"refs": ["V211"]}, format="json")
        unit = ProjectUnit.objects.get(ref="V211")
        stage = self.project.unit_stages.first()
        # The site's DPR picker offers it.
        picker = self.client.get(f"/api/v1/sites/{self.site.id}/units").data
        row = next(x for x in picker if x["id"] == unit.id)
        self.assertEqual(row["project_code"], "17POOL")
        self.assertTrue(len(row["stages"]) >= 5)
        doc = Document.objects.create(
            doc_type="DPR", ref="DPR-VKR-001", site=self.site,
            doc_date=date.today(), status="DRAFT", created_by=self.se)
        doc.current_revision = DocumentRevision.objects.create(
            document=doc, rev_label="R0", created_by=self.se,
            payload={"work_done": [{"activity": "Slab FW",
                                    "unit_id": unit.id,
                                    "stage_id": stage.id,
                                    "progress_todate": "60"}]})
        doc.save(update_fields=["current_revision"])
        self.assertEqual(svc.apply_dpr(doc, self.se), 1)
        board = svc.board(self.project)
        u = next(x for x in board["units"] if x["id"] == unit.id)
        self.assertEqual(u["last_dpr"], doc.ref)
        self.assertGreater(float(u["percent"]), 0)
