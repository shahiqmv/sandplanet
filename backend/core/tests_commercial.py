"""Project commercial (QS) — BOQ (slice 1)."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Boq, Project, Site, User
from .tests import make_user


def _vo_director(tc):
    """The internal approver. Classes that already make one use it; the rest
    get one on first use."""
    d = getattr(tc, "director", None)
    if d is None:
        d = make_user("vo_dir_auto", User.Role.DIRECTOR)
        tc.director = d
    return d


def vo_send(tc, vid):
    """QS → PD approves internally → QS sends to the Employer. Returns the
    last response (the send). Leaves the client authenticated as the QS."""
    c = tc.client
    c.force_authenticate(tc.qs)
    r = c.post(f"/api/v1/variations/{vid}/status",
               {"status": "PD_PENDING"}, format="json")
    assert r.status_code == 200, r.data
    c.force_authenticate(_vo_director(tc))
    r = c.post(f"/api/v1/variations/{vid}/status",
               {"status": "PD_APPROVED"}, format="json")
    assert r.status_code == 200, r.data
    c.force_authenticate(tc.qs)
    return c.post(f"/api/v1/variations/{vid}/status",
                  {"status": "SUBMITTED"}, format="json")


def vo_approve(tc, vid, on="2026-08-01", ref="CL/VO/1"):
    """...and the Employer approves: recorded with a date and reference.
    Idempotent about the send — a test may already have sent it."""
    from .models import Variation
    if Variation.objects.get(pk=vid).status != "SUBMITTED":
        vo_send(tc, vid)
    tc.client.force_authenticate(tc.qs)
    return tc.client.post(f"/api/v1/variations/{vid}/status",
                          {"status": "APPROVED", "employer_approved_on": on,
                           "employer_ref": ref}, format="json")


class BoqTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="VKR", name="Vakkaru", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=90))
        self.project = Project.objects.create(
            site=self.site, code="POOLS17", title="17 Swimming Pools",
            contract_value="500000")
        self.qs = make_user("qs1", User.Role.QS)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()

    def _url(self, tail=""):
        return f"/api/v1/projects/{self.project.id}/boq{tail}"

    # A supply (material) + install (labour) split BOQ.
    ROWS = [
        {"section": "Bill 1 — Substructure", "description":
         "Bill 1 — Substructure", "is_heading": True},
        {"section": "Bill 1 — Substructure", "item_code": "1.1",
         "description": "Excavate for foundations", "unit": "m3",
         "qty": "120", "rate_supply": "5.00", "rate_install": "3.50"},
        {"section": "Bill 1 — Substructure", "item_code": "1.2",
         "description": "Mass concrete blinding", "unit": "m3",
         "qty": "35", "rate_supply": "80.00", "rate_install": "15.00"},
    ]

    def test_qs_saves_split_boq_totals(self):
        self.client.force_authenticate(self.qs)
        r = self.client.post(self._url("/items"), {"rows": self.ROWS},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["exists"])
        self.assertTrue(r.data["split_rates"])
        self.assertEqual(len(r.data["items"]), 3)
        # supply: 120*5 + 35*80 = 600 + 2800 = 3400
        # labour: 120*3.5 + 35*15 = 420 + 525 = 945 ; total 4345
        self.assertEqual(float(r.data["total_supply"]), 3400.0)
        self.assertEqual(float(r.data["total_install"]), 945.0)
        self.assertEqual(float(r.data["total"]), 4345.0)
        heading = next(i for i in r.data["items"] if i["is_heading"])
        self.assertEqual(float(heading["amount"]), 0.0)

    def test_combined_rate_boq_is_not_split(self):
        self.client.force_authenticate(self.qs)
        rows = [{"item_code": "1.1", "description": "Blockwork", "unit": "m2",
                 "qty": "50", "rate_combined": "20.00"}]
        r = self.client.post(self._url("/items"), {"rows": rows},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["split_rates"])
        self.assertEqual(float(r.data["total"]), 1000.0)

    def test_save_replaces_previous_lines(self):
        self.client.force_authenticate(self.qs)
        self.client.post(self._url("/items"), {"rows": self.ROWS},
                         format="json")
        r = self.client.post(self._url("/items"), {"rows": [self.ROWS[1]]},
                             format="json")
        self.assertEqual(len(r.data["items"]), 1)
        self.assertEqual(float(r.data["total"]), 1020.0)

    def test_locked_boq_rejects_edits(self):
        self.client.force_authenticate(self.qs)
        self.client.post(self._url("/items"), {"rows": self.ROWS},
                         format="json")
        lk = self.client.post(self._url("/lock"), {"locked": True},
                              format="json")
        self.assertTrue(lk.data["is_locked"])
        r = self.client.post(self._url("/items"), {"rows": self.ROWS},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("locked", r.data["detail"].lower())

    def test_site_staff_cannot_see_or_edit_boq(self):
        self.client.force_authenticate(self.se)
        self.assertEqual(self.client.get(self._url()).status_code, 403)
        self.assertEqual(
            self.client.post(self._url("/items"), {"rows": self.ROWS},
                             format="json").status_code, 403)

    def test_empty_boq_reads_cleanly(self):
        self.client.force_authenticate(self.qs)
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["exists"])
        self.assertEqual(r.data["items"], [])
        self.assertFalse(Boq.objects.filter(project=self.project).exists())

    def test_delete_removes_a_draft_boq(self):
        self.client.force_authenticate(self.qs)
        self.client.post(self._url("/items"), {"rows": self.ROWS},
                         format="json")
        r = self.client.delete(self._url("/delete"))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["exists"])
        self.assertFalse(Boq.objects.filter(project=self.project).exists())

    def test_cannot_delete_a_locked_boq(self):
        self.client.force_authenticate(self.qs)
        self.client.post(self._url("/items"), {"rows": self.ROWS},
                         format="json")
        self.client.post(self._url("/lock"), {"locked": True}, format="json")
        r = self.client.delete(self._url("/delete"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("locked", r.data["detail"].lower())
        self.assertTrue(Boq.objects.filter(project=self.project).exists())

    def test_site_staff_cannot_delete_boq(self):
        self.client.force_authenticate(self.qs)
        self.client.post(self._url("/items"), {"rows": self.ROWS},
                         format="json")
        self.client.force_authenticate(self.se)
        self.assertEqual(self.client.delete(self._url("/delete")).status_code,
                         403)


class VariationTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="VKR", name="Vakkaru", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=90))
        self.project = Project.objects.create(
            site=self.site, code="POOLS17", title="17 Swimming Pools",
            contract_value="500000")
        self.qs = make_user("qs1", User.Role.QS)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)

    def _create(self, kind="ADDITION"):
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/variations/create",
            {"title": "Extra pool coping", "kind": kind, "rows": [
                {"item_code": "V1", "description": "Coping stone", "unit": "m",
                 "qty": "40", "rate_supply": "25", "rate_install": "10"}]},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["variations"][-1]

    def test_addition_adjusts_revised_only_when_approved(self):
        v = self._create("ADDITION")
        self.assertEqual(v["ref"], "VO-01")
        self.assertEqual(float(v["gross"]), 1400.0)   # 40 * (25+10)
        self.assertEqual(float(v["signed_total"]), 1400.0)
        vid = v["id"]
        # submitted → shows as a pending provision, revised unchanged
        r = vo_send(self, vid)
        c = r.data["contract"]
        self.assertEqual(float(c["revised"]), 500000.0)
        self.assertEqual(float(c["pending_net"]), 1400.0)
        self.assertEqual(float(c["forecast"]), 501400.0)
        # approved → folds into the revised contract sum
        r = vo_approve(self, vid)
        c = r.data["contract"]
        self.assertEqual(float(c["revised"]), 501400.0)
        self.assertEqual(float(c["pending_net"]), 0.0)

    def test_variation_order_pdf_shows_the_effect_on_the_contract_sum(self):
        """A variation changes what the client owes, so it leaves the building
        as an official document — and the question it answers is what the
        contract sum becomes if they approve it (owner 2026-08-22)."""
        from django.template.loader import render_to_string

        from core import commercial
        from core.models import Variation
        v = self._create("ADDITION")
        vo_send(self, v['id'])
        obj = Variation.objects.get(pk=v["id"])
        html = render_to_string("pdf/variation_order.html",
                                commercial.variation_pdf_context(obj))
        self.assertIn("VARIATION ORDER", html)
        self.assertIn("VO-01", html)
        self.assertIn("Coping stone", html)
        self.assertIn("Extra pool coping", html)          # the brief
        # Money reads the way the tax invoice does — thousands separated.
        self.assertIn("500,000.00", html)                 # original sum
        self.assertIn("1,400.00", html)                   # this variation
        self.assertIn("501,400.00", html)                 # sum if approved
        self.assertNotIn(">501400.00<", html)
        # Priced with a material/labour split, so the client's QS can check the
        # rates against the contract BOQ.
        self.assertIn("Material", html)
        self.assertIn("Labour", html)
        # Not yet approved — it must not read as agreed.
        self.assertIn("Contract sum if this variation is approved", html)
        self.assertIn("Submitted for the Employer&#x27;s approval", html)
        self.assertNotIn("Revised contract sum", html)

    def test_an_approved_variation_order_reads_as_agreed(self):
        from django.template.loader import render_to_string

        from core import commercial
        from core.models import Variation
        v = self._create("ADDITION")
        vo_approve(self, v["id"])
        obj = Variation.objects.get(pk=v["id"])
        html = render_to_string("pdf/variation_order.html",
                                commercial.variation_pdf_context(obj))
        self.assertIn("Revised contract sum", html)
        self.assertIn("APPROVED", html)
        # Its own value must not be double-counted into "approved to date".
        ctx = commercial.variation_pdf_context(obj)
        self.assertEqual(float(ctx["prior_approved"]), 0.0)
        self.assertEqual(float(ctx["sum_before"]), 500000.0)
        self.assertEqual(float(ctx["sum_after"]), 501400.0)

    def test_the_second_variation_counts_the_first_as_already_approved(self):
        from core import commercial
        from core.models import Variation
        first = self._create("ADDITION")
        vo_approve(self, first["id"])
        second = self._create("ADDITION")
        vo_send(self, second['id'])
        ctx = commercial.variation_pdf_context(
            Variation.objects.get(pk=second["id"]))
        self.assertEqual(float(ctx["prior_approved"]), 1400.0)
        self.assertEqual(float(ctx["sum_before"]), 501400.0)
        self.assertEqual(float(ctx["sum_after"]), 502800.0)

    def test_an_omission_reads_as_a_deduction(self):
        from django.template.loader import render_to_string

        from core import commercial
        from core.models import Variation
        v = self._create("OMISSION")
        vo_send(self, v['id'])
        ctx = commercial.variation_pdf_context(
            Variation.objects.get(pk=v["id"]))
        self.assertEqual(float(ctx["signed_total"]), -1400.0)
        self.assertEqual(float(ctx["sum_after"]), 498600.0)
        html = render_to_string("pdf/variation_order.html", ctx)
        # An omission reads as a deduction in the accounting convention the
        # rest of the client-facing money uses.
        self.assertIn("(1,400.00)", html)
        self.assertIn("498,600.00", html)
        self.assertIn("omitted from the contract", html)

    def test_a_draft_variation_is_not_issued_to_the_client(self):
        v = self._create("ADDITION")
        r = self.client.get(f"/api/v1/variations/{v['id']}/vo.pdf")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Director approves", r.data["detail"])

    def test_a_site_role_cannot_pull_a_variation_order(self):
        v = self._create("ADDITION")
        vo_send(self, v['id'])
        self.client.force_authenticate(self.se)
        r = self.client.get(f"/api/v1/variations/{v['id']}/vo.pdf")
        self.assertEqual(r.status_code, 403)

    def test_the_qs_cannot_approve_internally(self):
        """The internal gate is the Director's. The QS used to be able to
        press Approve on a VO nobody had sent anywhere (owner 2026-08-22)."""
        v = self._create()
        self.client.force_authenticate(self.qs)
        self.client.post(f"/api/v1/variations/{v['id']}/status",
                         {"status": "PD_PENDING"}, format="json")
        r = self.client.post(f"/api/v1/variations/{v['id']}/status",
                             {"status": "PD_APPROVED"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Director", r.data["detail"])
        # ...and cannot jump to the Employer without the PD.
        r = self.client.post(f"/api/v1/variations/{v['id']}/status",
                             {"status": "SUBMITTED"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_employer_approval_is_a_date_and_a_reference_not_a_button(self):
        v = self._create()
        vo_send(self, v["id"])
        r = self.client.post(f"/api/v1/variations/{v['id']}/status",
                             {"status": "APPROVED"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("date", r.data["detail"].lower())
        r = self.client.post(f"/api/v1/variations/{v['id']}/status",
                             {"status": "APPROVED",
                              "employer_approved_on": "2026-08-15"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("reference", r.data["detail"].lower())
        r = self.client.post(f"/api/v1/variations/{v['id']}/status",
                             {"status": "APPROVED",
                              "employer_approved_on": "2026-08-15",
                              "employer_ref": "Email 15 Aug, R. Client"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        vv = next(x for x in r.data["variations"] if x["id"] == v["id"])
        self.assertEqual(vv["status"], "APPROVED")
        self.assertEqual(vv["employer_approved_on"], "2026-08-15")
        self.assertEqual(vv["employer_ref"], "Email 15 Aug, R. Client")
        self.assertTrue(vv["pd_approved_by_name"])

    def test_an_internally_approved_vo_is_not_yet_in_the_contract_sum(self):
        v = self._create()
        self.client.force_authenticate(self.qs)
        self.client.post(f"/api/v1/variations/{v['id']}/status",
                         {"status": "PD_PENDING"}, format="json")
        self.client.force_authenticate(_vo_director(self))
        r = self.client.post(f"/api/v1/variations/{v['id']}/status",
                             {"status": "PD_APPROVED"}, format="json")
        c = r.data["contract"]
        self.assertEqual(float(c["revised"]), 500000.0)     # unchanged
        self.assertEqual(float(c["pending_net"]), 0.0)      # not with client
        self.assertEqual(float(c["internal_net"]), 1400.0)  # ours, unsent

    def test_the_director_sees_the_vo_in_my_tasks_and_on_the_phone_key(self):
        v = self._create()
        self.client.force_authenticate(self.qs)
        self.client.post(f"/api/v1/variations/{v['id']}/status",
                         {"status": "PD_PENDING"}, format="json")
        self.client.force_authenticate(_vo_director(self))
        d = self.client.get("/api/v1/approvals/pending").data
        grp = next((g for g in d["groups"]
                    if g["title"] == "To approve — variation orders (internal)"),
                   None)
        self.assertIsNotNone(grp, [g["title"] for g in d["groups"]])
        self.assertEqual(grp["items"][0]["ref"], "POOLS17 VO-01")
        self.assertEqual(grp["items"][0]["doc_type"], "VO")
        self.assertEqual(grp["items"][0]["project_id"], self.project.id)

    def test_pd_approved_vo_pdf_reads_as_submitted_and_approved_as_employer(self):
        from django.template.loader import render_to_string

        from core import commercial
        from core.models import Variation
        v = self._create()
        vo_send(self, v["id"])
        html = render_to_string("pdf/variation_order.html",
            commercial.variation_pdf_context(Variation.objects.get(pk=v["id"])))
        self.assertIn("Submitted for the Employer&#x27;s approval", html)
        self.assertNotIn("APPROVED BY THE EMPLOYER", html)
        vo_approve(self, v["id"], on="2026-08-15", ref="CL/VO/7")
        html = render_to_string("pdf/variation_order.html",
            commercial.variation_pdf_context(Variation.objects.get(pk=v["id"])))
        self.assertIn("APPROVED BY THE EMPLOYER", html)
        self.assertIn("15 Aug 2026", html)
        self.assertIn("CL/VO/7", html)

    def test_rollback_command_returns_a_never_sent_vo_to_ready_to_send(self):
        from io import StringIO

        from django.core.management import call_command

        from core.models import Variation
        v = self._create()
        vo_approve(self, v["id"])
        out = StringIO()
        call_command("rollback_vo_employer_approval", project="POOLS17",
                     apply=True, stdout=out)
        obj = Variation.objects.get(pk=v["id"])
        self.assertEqual(obj.status, "PD_APPROVED")
        self.assertIsNone(obj.employer_approved_on)
        self.assertIn("Rolled back 1", out.getvalue())

    def test_omission_subtracts(self):
        v = self._create("OMISSION")
        self.assertEqual(float(v["signed_total"]), -1400.0)
        vo_send(self, v['id'])
        r = vo_approve(self, v['id'])
        self.assertEqual(float(r.data["contract"]["revised"]), 498600.0)

    def test_approved_edit_reverts_to_draft_for_reapproval(self):
        # Owner 2026-08-11: an approved VO stays fixable while unclaimed, but
        # editing INVALIDATES the approval — it returns to DRAFT, leaves the
        # revised contract sum, and runs submit → approve again.
        v = self._create()
        vo_approve(self, v["id"])
        r = self.client.post(f"/api/v1/variations/{v['id']}/items",
                             {"rows": [
                                 {"item_code": "V1", "description":
                                  "Coping stone", "unit": "m", "qty": "50",
                                  "rate_supply": "25", "rate_install": "10"}]},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        vv = next(x for x in r.data["variations"] if x["id"] == v["id"])
        self.assertEqual(vv["status"], "DRAFT")               # back for approval
        self.assertEqual(float(vv["gross"]), 1750.0)          # 50 × 35
        self.assertEqual(float(r.data["contract"]["revised"]), 500000.0)
        vo_approve(self, v["id"])                                # re-approve
        r = self.client.get(f"/api/v1/projects/{self.project.id}/variations")
        self.assertEqual(float(r.data["contract"]["revised"]), 501750.0)

    def test_approved_edit_reseeds_draft_claims_and_locks_after_claiming(self):
        from .models import ProgressClaim
        v = self._create()
        vo_approve(self, v["id"])
        self.client.post(f"/api/v1/projects/{self.project.id}/boq/items",
                         {"rows": [{"item_code": "A", "description": "Item A",
                                    "unit": "no", "qty": "10",
                                    "rate_combined": "10"}]}, format="json")
        cid = self.client.post(
            f"/api/v1/projects/{self.project.id}/claims/create", {},
            format="json").data["claims"][-1]["id"]
        claim = ProgressClaim.objects.get(pk=cid)
        self.assertEqual(
            claim.items.filter(variation_item__isnull=False).count(), 1)
        # editing the approved VO drops it to DRAFT; the draft claim's VO
        # lines cascade off and come back when the VO is re-approved
        r = self.client.post(f"/api/v1/variations/{v['id']}/items",
                             {"rows": [
                                 {"item_code": "V1", "description": "Coping",
                                  "unit": "m", "qty": "40",
                                  "rate_supply": "30", "rate_install": "10"},
                                 {"item_code": "V2", "description": "Lights",
                                  "unit": "no", "qty": "10",
                                  "rate_supply": "8", "rate_install": "2"}]},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(
            claim.items.filter(variation_item__isnull=False).count(), 0)
        vo_approve(self, v["id"])                                # re-approve
        self.assertEqual(
            claim.items.filter(variation_item__isnull=False).count(), 2)
        # claim value against it and submit → the VO is locked
        ci = claim.items.filter(variation_item__isnull=False).first()
        from decimal import Decimal
        ci.cumulative_qty = Decimal("5")
        ci.save()
        claim.status = "SUBMITTED"
        claim.save(update_fields=["status"])
        r = self.client.post(f"/api/v1/variations/{v['id']}/items",
                             {"rows": []}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("correcting variation", r.data["detail"])

    def test_site_staff_cannot_see_variations(self):
        self.client.force_authenticate(self.se)
        r = self.client.get(f"/api/v1/projects/{self.project.id}/variations")
        self.assertEqual(r.status_code, 403)


class ProgressClaimTests(TestCase):
    """The interim claim (IPA) waterfall: BOQ + approved VOs valued to date,
    advance recovery, retention, previous-claim chaining and output GST."""

    def setUp(self):
        self.site = Site.objects.create(
            code="VKR", name="Vakkaru", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=90))
        # small numbers so the 40% advance actually bites the recovery cap
        self.project = Project.objects.create(
            site=self.site, code="POOLS17", title="17 Swimming Pools",
            contract_value="3000", contract_type="LUMP_SUM",
            advance_payment_pct="40", retention_pct="10", output_gst_pct="8")
        self.qs = make_user("qs1", User.Role.QS)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.director = make_user("dir1", User.Role.DIRECTOR)
        self.admin = make_user("adm1", User.Role.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)
        # BOQ: A = 100 × 10 = 1000, B = 100 × 20 = 2000  (total 3000)
        self.client.post(
            f"/api/v1/projects/{self.project.id}/boq/items",
            {"rows": [
                {"item_code": "A", "description": "Item A", "unit": "no",
                 "qty": "100", "rate_combined": "10"},
                {"item_code": "B", "description": "Item B", "unit": "no",
                 "qty": "100", "rate_combined": "20"}]},
            format="json")

    def _create(self, data=None):
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/claims/create",
            data or {}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["claims"][-1]

    def _detail(self, cid):
        return self.client.get(f"/api/v1/claims/{cid}").data

    def _value_pct(self, cid, mapping):
        d = self._detail(cid)
        rows = [{"id": ln["id"], "cumulative_pct": mapping[ln["item_code"]]}
                for ln in d["lines"] if ln["item_code"] in mapping]
        return self.client.post(f"/api/v1/claims/{cid}/items",
                                {"rows": rows}, format="json").data

    def _status(self, cid, s):
        # Certifying is the Director's clearance; other moves stay with the QS.
        if s == "CERTIFIED":
            self.client.force_authenticate(self.director)
            r = self.client.post(f"/api/v1/claims/{cid}/status",
                                 {"status": s}, format="json")
            self.client.force_authenticate(self.qs)
            return r
        return self.client.post(f"/api/v1/claims/{cid}/status",
                                {"status": s}, format="json")

    def test_only_director_can_certify_claim(self):
        cid = self._create({"claim_type": "ADVANCE"})["id"]
        self._status(cid, "SUBMITTED")
        # QS submits but cannot clear the IPA.
        r = self.client.post(f"/api/v1/claims/{cid}/status",
                             {"status": "CERTIFIED"}, format="json")
        self.assertIn(r.status_code, (400, 403))
        from .models import ProgressClaim
        self.assertEqual(ProgressClaim.objects.get(pk=cid).status, "SUBMITTED")
        # Director clears it.
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/claims/{cid}/status",
                             {"status": "CERTIFIED"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.client.force_authenticate(self.qs)
        c = ProgressClaim.objects.get(pk=cid)
        self.assertEqual(c.status, "CERTIFIED")
        self.assertEqual(c.certified_by_id, self.director.id)

    def test_admin_reopens_certified_claim_to_amend(self):
        from .models import ProgressClaim
        cid = self._create({"claim_type": "ADVANCE"})["id"]
        self._status(cid, "SUBMITTED")
        self._status(cid, "CERTIFIED")          # director certifies
        inv = ProgressClaim.objects.get(pk=cid).invoice_no
        self.assertTrue(inv)
        # the QS cannot reopen a certified claim
        r = self.client.post(f"/api/v1/claims/{cid}/status",
                             {"status": "DRAFT"}, format="json")
        self.assertIn(r.status_code, (400, 403))
        self.assertEqual(ProgressClaim.objects.get(pk=cid).status, "CERTIFIED")
        # an Admin can — and the invoice number is preserved
        self.client.force_authenticate(self.admin)
        r = self.client.post(f"/api/v1/claims/{cid}/status",
                             {"status": "DRAFT"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.client.force_authenticate(self.qs)
        c = ProgressClaim.objects.get(pk=cid)
        self.assertEqual(c.status, "DRAFT")
        self.assertEqual(c.invoice_no, inv)

    def test_boq_delete_blocked_once_a_claim_exists(self):
        from .models import Boq
        # raise a claim (locks the BOQ), then a Director unlocks it
        self._create()
        self.client.post(f"/api/v1/projects/{self.project.id}/boq/lock",
                         {"locked": False}, format="json")
        r = self.client.delete(
            f"/api/v1/projects/{self.project.id}/boq/delete")
        self.assertEqual(r.status_code, 400)
        self.assertIn("claim", r.data["detail"].lower())
        self.assertTrue(Boq.objects.filter(project=self.project).exists())

    def test_advance_claim_then_interim_recovers_it(self):
        # Advance = 40% of 3000 = 1200; + 8% GST = 1296. No work lines.
        a = self._create({"claim_type": "ADVANCE"})
        self.assertEqual(a["claim_type"], "ADVANCE")
        wa = self._detail(a["id"])["waterfall"]
        self.assertEqual(float(wa["advance_received"]), 1200.0)
        self.assertEqual(float(wa["net_due"]), 1200.0)
        self.assertEqual(float(wa["total"]), 1296.0)
        self.assertEqual(self._detail(a["id"])["lines"], [])   # no work lines
        # it submits + certifies without any valued line
        self.assertEqual(self._status(a["id"], "SUBMITTED").status_code, 200)
        self.assertEqual(self._status(a["id"], "CERTIFIED").status_code, 200)
        # Interim: value work at 50% (k_gross 1500). Recovery = 40%×1500 = 600.
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "50"})
        wc = self._detail(c["id"])["waterfall"]
        self.assertEqual(float(wc["k_gross"]), 1500.0)
        self.assertEqual(float(wc["advance_recovered"]), 600.0)
        self.assertEqual(float(wc["previously_certified"]), 1200.0)
        # net due = work 1500 − recovery 600 − retention 150 = 750
        self.assertEqual(float(wc["net_due"]), 750.0)

    def test_previous_column_carries_from_prior_claim(self):
        # The reported bug: a subsequent claim showed the previous claim's
        # progress as 0. Claim 1 values A at 50% and is certified; claim 2 must
        # report A's previous figure as that locked 50% / 500, not 0.
        c1 = self._create()
        self._value_pct(c1["id"], {"A": "50", "B": "40"})
        self._status(c1["id"], "SUBMITTED")
        self._status(c1["id"], "CERTIFIED")
        c2 = self._create()
        line_a = next(ln for ln in self._detail(c2["id"])["lines"]
                      if ln["item_code"] == "A")
        self.assertEqual(float(line_a["previous_value"]), 500.0)   # 50% × 1000
        self.assertEqual(float(line_a["previous_pct"]), 50.0)

    def test_basis_inherits_but_can_switch_mid_contract(self):
        # A later claim inherits the previous basis, but the QS may switch it
        # (owner 2026-08-11: North Jetty moved from % to site measurements).
        # Prior claims keep valuing by THEIR basis, so the chain stays exact.
        c1 = self._create()
        self.assertEqual(c1["basis"], "PERCENT")
        self._value_pct(c1["id"], {"A": "50"})           # 50% of 1000 = 500
        self._status(c1["id"], "SUBMITTED")
        self._status(c1["id"], "CERTIFIED")
        c2 = self._create()
        d2 = self._detail(c2["id"])["claim"]
        self.assertEqual(d2["basis"], "PERCENT")          # inherited
        self.assertTrue(d2["basis_inherited"])
        r = self.client.post(f"/api/v1/claims/{c2['id']}/meta",
                             {"basis": "MEASURED"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # measured going forward: A now 70 no cumulative → 700; the previous
        # %-based 500 still reads correctly, current = 200
        d = self._detail(c2["id"])
        row = next(ln for ln in d["lines"] if ln["item_code"] == "A")
        self.client.post(f"/api/v1/claims/{c2['id']}/items",
                         {"rows": [{"id": row["id"],
                                    "cumulative_qty": "70"}]}, format="json")
        d = self._detail(c2["id"])
        row = next(ln for ln in d["lines"] if ln["item_code"] == "A")
        self.assertEqual(float(row["previous_value"]), 500.0)
        self.assertEqual(float(row["cumulative_value"]), 700.0)
        self.assertEqual(float(row["current_value"]), 200.0)
        self.assertEqual(float(row["contract_qty"]), 100.0)  # shown on screen
        self.assertEqual(float(row["rate"]), 10.0)

    def test_previous_value_survives_a_legacy_basis_mismatch(self):
        # Safety net for pre-lock data: even if a chained claim carries a
        # different basis than its predecessor, the previous figure is valued
        # on the PREVIOUS claim's own basis — so it never collapses to 0.
        from .models import ProgressClaim
        c1 = self._create()
        self._value_pct(c1["id"], {"A": "50", "B": "40"})
        self._status(c1["id"], "SUBMITTED")
        self._status(c1["id"], "CERTIFIED")
        c2 = self._create()
        # force the mismatch the API would now refuse
        ProgressClaim.objects.filter(pk=c2["id"]).update(basis="MEASURED")
        line_a = next(ln for ln in self._detail(c2["id"])["lines"]
                      if ln["item_code"] == "A")
        self.assertEqual(float(line_a["previous_value"]), 500.0)

    def test_recovery_can_be_reduced_then_caught_up(self):
        # advance 1200; interim work 50% (k_gross 1500) → formula recovery 600
        self._status(self._create({"claim_type": "ADVANCE"})["id"], "SUBMITTED")
        adv = self.project.claims.get(claim_type="ADVANCE")
        self._status(adv.id, "CERTIFIED")
        c1 = self._create()
        self._value_pct(c1["id"], {"A": "50", "B": "50"})
        # client agrees to recover only 200 on this claim
        self.client.post(f"/api/v1/claims/{c1['id']}/meta",
                         {"advance_recovered_override": "200"}, format="json")
        w1 = self._detail(c1["id"])["waterfall"]
        self.assertEqual(float(w1["advance_recovered"]), 200.0)
        # net due rises vs the 600 default: 1500 − 200 − 150 = 1150
        self.assertEqual(float(w1["net_due"]), 1150.0)
        self._status(c1["id"], "SUBMITTED")
        self._status(c1["id"], "CERTIFIED")
        # next claim (work 100%, k_gross 3000) uses the formula again and
        # catches the deferred recovery up to the full 1200
        c2 = self._create()
        self._value_pct(c2["id"], {"A": "100", "B": "100"})
        w2 = self._detail(c2["id"])["waterfall"]
        self.assertEqual(float(w2["advance_recovered"]), 1200.0)   # cumulative

    def test_back_charge_is_contra_after_gst(self):
        # A back charge is a GST-inclusive client contra: GST is charged on the
        # full certified work, then the back charge is deducted AFTER GST (owner
        # 2026-07-25). It never reduces the taxable value / our output GST.
        c = self._create()
        self._value_pct(c["id"], {"A": "65", "B": "65"})
        r = self.client.post(
            f"/api/v1/claims/{c['id']}/deductions",
            {"rows": [{"label": "Materials from store",
                       "cumulative_amount": "112.52"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        d = self._detail(c["id"])
        w = d["waterfall"]
        self.assertEqual(float(w["deductions_present"]), 112.52)
        # net due (taxable) = gross − advance recovery − retention (NO back charge)
        self.assertEqual(
            round(float(w["net_due"]), 2),
            round(float(w["k_gross"]) - float(w["advance_recovered"])
                  - float(w["retention_held"]), 2))
        # GST is on the full certified work; the back charge comes off after
        self.assertEqual(round(float(w["gst"]), 2),
                         round(float(w["net_due"]) * 8 / 100, 2))
        self.assertEqual(round(float(w["total"]), 2),
                         round(float(w["net_due"]) + float(w["gst"]), 2))
        self.assertEqual(round(float(w["net_to_pay"]), 2),
                         round(float(w["total"]) - 112.52, 2))
        self.assertEqual(d["deduction_lines"][0]["label"], "Materials from store")

    def test_ipa_and_invoice_pdfs_show_advance_and_deductions(self):
        from django.template.loader import render_to_string

        from core import commercial
        from core.models import ProgressClaim
        # advance claim → IPA shows the advance-received line
        a = self._create({"claim_type": "ADVANCE"})
        ac = ProgressClaim.objects.get(pk=a["id"])
        ipa = render_to_string("pdf/claim_ipa.html",
                               commercial.claim_pdf_context(ac))
        self.assertIn("Advance received", ipa)
        # advance invoice figures carry thousands separators like the interim
        # Payment Summary (advance = 40% of 3000 = 1,200.00)
        adv_inv = render_to_string(
            "pdf/tax_invoice.html", commercial.invoice_pdf_context(ac))
        self.assertIn("1,200.00", adv_inv)
        self.assertNotIn(">1200.00<", adv_inv)
        # the 4-column Payment Summary (Contract / Cumulative / Previous /
        # Present) is present
        for col in ("Cumulative", "Previous", "Present"):
            self.assertIn(col, ipa)
        self._status(a["id"], "SUBMITTED")
        self._status(a["id"], "CERTIFIED")
        # interim with a back-charge → IPA + invoice show it + net-to-pay
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "50"})
        self.client.post(
            f"/api/v1/claims/{c['id']}/deductions",
            {"rows": [{"label": "Diesel from store",
                       "cumulative_amount": "112.52"}]}, format="json")
        cc = ProgressClaim.objects.get(pk=c["id"])
        ipa2 = render_to_string("pdf/claim_ipa.html",
                                commercial.claim_pdf_context(cc))
        self.assertIn("Diesel from store", ipa2)
        # back charge is a contra AFTER the certified claim + GST, then net pay
        self.assertIn("Total amount", ipa2)
        self.assertIn("Total with GST", ipa2)
        self.assertIn("Net amount to pay", ipa2)
        # the detailed item-by-item valuation follows the summary sheet
        self.assertIn("Detailed valuation", ipa2)
        self.assertIn("Total value of works", ipa2)
        inv = render_to_string("pdf/tax_invoice.html",
                               commercial.invoice_pdf_context(cc))
        self.assertIn("Diesel from store", inv)
        self.assertIn("Total with GST", inv)

    def test_create_locks_boq_and_seeds_lines(self):
        c = self._create()
        self.assertEqual(c["ref"], "IPA-01")
        self.assertEqual(c["basis"], "PERCENT")     # lump-sum default
        # snapshotted terms
        self.assertEqual(float(c["advance_pct"]), 40.0)
        self.assertEqual(float(c["retention_pct"]), 10.0)
        self.assertEqual(float(c["gst_pct"]), 8.0)
        # BOQ is now locked (baseline frozen)
        boq = self.client.get(
            f"/api/v1/projects/{self.project.id}/boq").data
        self.assertTrue(boq["is_locked"])
        # one claim line per priced item
        self.assertEqual(len(self._detail(c["id"])["lines"]), 2)

    def test_first_claim_waterfall(self):
        c = self._create()
        # A at 50% → 500, B at 25% → 500  (K1 = 1000)
        r = self._value_pct(c["id"], {"A": "50", "B": "25"})
        w = r["waterfall"]
        self.assertEqual(float(w["k1_work_done"]), 1000.0)
        self.assertEqual(float(w["k_gross"]), 1000.0)
        # advance recovery: 40% of 1000 = 400 (cap 1200, not hit)
        self.assertEqual(float(w["advance_recovered"]), 400.0)
        # retention 10% of 1000 = 100 held
        self.assertEqual(float(w["retention_held"]), 100.0)
        # N = 1000 − 400 − 100 = 500 ; nothing previous → Q = 500
        self.assertEqual(float(w["net_cumulative"]), 500.0)
        self.assertEqual(float(w["previously_certified"]), 0.0)
        self.assertEqual(float(w["net_due"]), 500.0)
        # GST 8% of 500 = 40 ; total 540
        self.assertEqual(float(w["gst"]), 40.0)
        self.assertEqual(float(w["total"]), 540.0)

    def test_second_claim_chains_off_the_first(self):
        c1 = self._create()
        self._value_pct(c1["id"], {"A": "50", "B": "25"})
        # a second claim carries the cumulative % forward from the first
        c2 = self._create()
        seeded = {ln["item_code"]: ln["cumulative_pct"]
                  for ln in self._detail(c2["id"])["lines"]}
        self.assertEqual(float(seeded["A"]), 50.0)
        self.assertEqual(float(seeded["B"]), 25.0)
        # bump to A 100% (1000), B 50% (1000) + 200 material on site
        self.client.post(f"/api/v1/claims/{c2['id']}/meta",
                         {"material_on_site": "200"}, format="json")
        r = self._value_pct(c2["id"], {"A": "100", "B": "50"})
        w = r["waterfall"]
        self.assertEqual(float(w["k1_work_done"]), 2000.0)
        self.assertEqual(float(w["k2_material_on_site"]), 200.0)
        self.assertEqual(float(w["k_gross"]), 2200.0)
        self.assertEqual(float(w["advance_recovered"]), 880.0)   # 40% of 2200
        self.assertEqual(float(w["retention_held"]), 220.0)      # 10% of 2200
        self.assertEqual(float(w["net_cumulative"]), 1100.0)
        self.assertEqual(float(w["previously_certified"]), 500.0)  # claim 1 N
        self.assertEqual(float(w["net_due"]), 600.0)             # 1100 − 500
        self.assertEqual(float(w["gst"]), 48.0)
        self.assertEqual(float(w["total"]), 648.0)

    def test_approved_variation_is_claimable(self):
        # add + approve a VO, then a claim should include its line
        v = self.client.post(
            f"/api/v1/projects/{self.project.id}/variations/create",
            {"title": "Extra", "kind": "ADDITION", "rows": [
                {"item_code": "V1", "description": "Extra work", "unit": "no",
                 "qty": "10", "rate_combined": "50"}]}, format="json").data
        vid = v["variations"][-1]["id"]
        vo_send(self, vid)
        vo_approve(self, vid)
        c = self._create()
        lines = self._detail(c["id"])["lines"]
        vo = next(ln for ln in lines if ln["source"] == "VO")
        self.assertEqual(vo["item_code"], "V1")
        r = self._value_pct(c["id"], {"V1": "100"})
        self.assertEqual(float(r["waterfall"]["k4_variations"]), 500.0)

    def test_section_summary_rolls_up_to_bill_headings(self):
        # A BOQ whose bills are heading rows; most priced lines leave their
        # Section box blank, a couple carry a finer sub-tag.
        self.client.post(
            f"/api/v1/projects/{self.project.id}/boq/items", {"rows": [
                {"section": "SUBSTRUCTURE", "is_heading": True},
                {"item_code": "A", "description": "Excavation",
                 "qty": "10", "rate_combined": "5"},          # blank section
                {"item_code": "B", "description": "Concrete",
                 "section": "Concrete Works", "qty": "2",
                 "rate_combined": "100"},                     # sub-tag
                {"section": "SUPERSTRUCTURE", "is_heading": True},
                {"item_code": "C", "description": "Roof",
                 "qty": "1", "rate_combined": "50"}]},        # blank section
            format="json")
        c = self._create()
        self._value_pct(c["id"], {"A": "100", "B": "100", "C": "100"})
        d = self._detail(c["id"])
        secs = {s["section"] for s in d["section_summary"]}
        # blank-section lines inherit their heading; the tagged one keeps it;
        # nothing lands in the "—" bucket
        self.assertEqual(secs, {"SUBSTRUCTURE", "Concrete Works",
                                "SUPERSTRUCTURE"})
        self.assertNotIn("—", secs)
        by_code = {ln["item_code"]: ln["section"] for ln in d["lines"]}
        self.assertEqual(by_code["A"], "SUBSTRUCTURE")   # inherited heading
        self.assertEqual(by_code["B"], "Concrete Works")  # kept its sub-tag
        self.assertEqual(by_code["C"], "SUPERSTRUCTURE")

    def test_measured_basis_uses_quantity(self):
        self.project.contract_type = "REMEASUREMENT"
        self.project.save(update_fields=["contract_type"])
        c = self._create()
        self.assertEqual(c["basis"], "MEASURED")
        d = self._detail(c["id"])
        rows = [{"id": ln["id"], "cumulative_qty": "60"}
                for ln in d["lines"] if ln["item_code"] == "A"]
        r = self.client.post(f"/api/v1/claims/{c['id']}/items",
                             {"rows": rows}, format="json").data
        # 60 × rate 10 = 600
        self.assertEqual(float(r["waterfall"]["k1_work_done"]), 600.0)

    def test_draft_only_editing_and_status_flow(self):
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "25"})
        cid = c["id"]
        self.client.post(f"/api/v1/claims/{cid}/status",
                         {"status": "SUBMITTED"}, format="json")
        # can no longer value a submitted claim
        blocked = self.client.post(f"/api/v1/claims/{cid}/items",
                                   {"rows": []}, format="json")
        self.assertEqual(blocked.status_code, 400)
        r = self._status(cid, "CERTIFIED")   # Director clears it
        self.assertEqual(r.data["claim"]["status"], "CERTIFIED")
        self.assertIsNotNone(r.data["claim"]["certified_at"])

    def test_site_staff_cannot_see_claims(self):
        self._create()
        self.client.force_authenticate(self.se)
        r = self.client.get(f"/api/v1/projects/{self.project.id}/claims")
        self.assertEqual(r.status_code, 403)

    # ---- P4: certified revenue + client receipts --------------------------

    def _certify(self, cid):
        self.client.post(f"/api/v1/claims/{cid}/status",
                         {"status": "SUBMITTED"}, format="json")
        return self._status(cid, "CERTIFIED")   # Director clears it

    def _revenue(self):
        return self.client.get(
            f"/api/v1/projects/{self.project.id}/claims").data["revenue"]

    def test_certified_claim_becomes_project_revenue(self):
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "25"})   # K gross 1000
        r = self._certify(c["id"])
        self.assertEqual(r.data["claim"]["status"], "CERTIFIED")
        rev = self._revenue()
        self.assertEqual(float(rev["certified_revenue"]), 1000.0)  # ex-GST
        self.assertEqual(float(rev["billed"]), 540.0)              # incl GST
        self.assertEqual(float(rev["retention_held"]), 100.0)
        self.assertEqual(float(rev["received"]), 0.0)
        self.assertEqual(float(rev["outstanding"]), 540.0)
        self.assertEqual(rev["claims_certified"], 1)

    def test_draft_claim_is_not_revenue(self):
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "25"})   # left DRAFT
        rev = self._revenue()
        self.assertEqual(float(rev["certified_revenue"]), 0.0)
        self.assertEqual(rev["claims_certified"], 0)

    def test_receipt_reduces_outstanding_and_settles_claim(self):
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "25"})
        self._certify(c["id"])
        url = f"/api/v1/projects/{self.project.id}/receipts"
        self.client.post(url, {"amount": "200", "received_on": "2026-07-16",
                               "claim_id": c["id"], "reference": "TT-1"},
                         format="json")
        rev = self._revenue()
        self.assertEqual(float(rev["received"]), 200.0)
        self.assertEqual(float(rev["outstanding"]), 340.0)
        # settle the balance → claim auto-advances to PAID
        self.client.post(url, {"amount": "340", "received_on": "2026-07-16",
                               "claim_id": c["id"]}, format="json")
        payload = self.client.get(
            f"/api/v1/projects/{self.project.id}/claims").data
        self.assertEqual(float(payload["revenue"]["outstanding"]), 0.0)
        claim = next(x for x in payload["claims"] if x["id"] == c["id"])
        self.assertEqual(claim["status"], "PAID")
        self.assertEqual(len(payload["receipts"]), 2)

    def test_receipt_validation_and_delete(self):
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "25"})
        self._certify(c["id"])
        url = f"/api/v1/projects/{self.project.id}/receipts"
        bad = self.client.post(url, {"amount": "0",
                                     "received_on": "2026-07-16"},
                               format="json")
        self.assertEqual(bad.status_code, 400)
        r = self.client.post(url, {"amount": "540",
                                   "received_on": "2026-07-16"},
                             format="json")
        self.assertEqual(r.status_code, 201)
        rid = r.data["receipts"][0]["id"]
        d = self.client.delete(f"/api/v1/receipts/{rid}/delete")
        self.assertEqual(d.status_code, 200)
        self.assertEqual(float(d.data["revenue"]["received"]), 0.0)

    def test_site_staff_cannot_record_receipt(self):
        self.client.force_authenticate(self.se)
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/receipts",
            {"amount": "100", "received_on": "2026-07-16"}, format="json")
        self.assertEqual(r.status_code, 403)

    # ---- P5: IPA + tax-invoice PDFs ---------------------------------------

    def test_certifying_assigns_invoice_no_and_pdfs_render(self):
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "25"})
        self._certify(c["id"])
        payload = self.client.get(
            f"/api/v1/projects/{self.project.id}/claims").data
        cl = next(x for x in payload["claims"] if x["id"] == c["id"])
        self.assertTrue(cl["invoice_no"].startswith("INV-"))
        for tail in ("ipa", "invoice"):
            r = self.client.get(f"/api/v1/claims/{c['id']}/{tail}.pdf")
            self.assertEqual(r.status_code, 200, getattr(r, "data", tail))
            self.assertEqual(r["Content-Type"], "application/pdf")

    def test_invoice_pdf_blocked_before_certification(self):
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "25"})   # DRAFT
        r = self.client.get(f"/api/v1/claims/{c['id']}/invoice.pdf")
        self.assertEqual(r.status_code, 400)

    # ---- Retention fix + amount override (owner 2026-07-27) ---------------

    def test_retention_rate_refreshes_on_draft_when_set_late(self):
        # Reproduces the reported bug: a project with NO retention % is set up,
        # a claim is opened (snapshot = 0), THEN the retention % is entered on
        # the project. A draft claim must pick the rate up on the next recalc.
        self.project.retention_pct = None
        self.project.save(update_fields=["retention_pct"])
        c = self._create()
        self.assertEqual(float(self._detail(c["id"])["claim"]["retention_pct"]),
                         0.0)
        # owner enters the retention % on the project afterwards
        self.project.refresh_from_db()
        self.project.retention_pct = "10"
        self.project.save(update_fields=["retention_pct"])
        # valuing the draft refreshes the snapshot → retention now bites
        r = self._value_pct(c["id"], {"A": "50", "B": "50"})   # k_gross 1500
        w = r["waterfall"]
        self.assertEqual(float(self._detail(c["id"])["claim"]["retention_pct"]),
                         10.0)
        self.assertEqual(float(w["retention_held"]), 150.0)    # 10% of 1500

    def test_certified_claim_keeps_frozen_retention_rate(self):
        # A certified claim must NOT drift if the project rate later changes.
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "50"})
        self._certify(c["id"])
        self.project.refresh_from_db()
        self.project.retention_pct = "25"
        self.project.save(update_fields=["retention_pct"])
        w = self._detail(c["id"])["waterfall"]
        self.assertEqual(float(w["retention_held"]), 150.0)    # still 10%

    def test_retention_held_override_pins_amount_then_clears(self):
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "50"})       # held = 150
        self.client.post(f"/api/v1/claims/{c['id']}/meta",
                         {"retention_held_override": "90"}, format="json")
        w = self._detail(c["id"])["waterfall"]
        self.assertEqual(float(w["retention_held"]), 90.0)
        # net cumulative = work 1500 − advance recovery 600 − retention 90 = 810
        # (60 higher than the 750 the 10% rate would give: 150 − 90)
        self.assertEqual(float(w["net_cumulative"]), 810.0)
        # blank clears it → back to the 10% rate formula (150)
        self.client.post(f"/api/v1/claims/{c['id']}/meta",
                         {"retention_held_override": ""}, format="json")
        w = self._detail(c["id"])["waterfall"]
        self.assertEqual(float(w["retention_held"]), 150.0)

    # ---- BOQ discount line (owner 2026-07-27) -----------------------------

    def test_discount_line_lowers_boq_and_accrues_by_percent(self):
        # rebuild the BOQ with a discount line: A 1000 + B 2000 − 300 = 2700
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/boq/items",
            {"rows": [
                {"item_code": "A", "description": "Item A", "unit": "no",
                 "qty": "100", "rate_combined": "10"},
                {"item_code": "B", "description": "Item B", "unit": "no",
                 "qty": "100", "rate_combined": "20"},
                {"item_code": "DISC", "description": "Trade discount",
                 "is_discount": True, "rate_supply": "300"}]},
            format="json").data
        self.assertEqual(float(r["total"]), 2700.0)
        disc = next(i for i in r["items"] if i["is_discount"])
        self.assertEqual(float(disc["amount"]), -300.0)
        # claim it: work 50% + discount realised 50% → 1500 − 150 = 1350
        c = self._create()
        w = self._value_pct(
            c["id"], {"A": "50", "B": "50", "DISC": "50"})["waterfall"]
        self.assertEqual(float(w["k1_work_done"]), 1350.0)
        self.assertEqual(float(w["k_gross"]), 1350.0)

    def test_discount_line_is_percent_even_on_measured_claim(self):
        self.project.contract_type = "REMEASUREMENT"
        self.project.save(update_fields=["contract_type"])
        self.client.post(
            f"/api/v1/projects/{self.project.id}/boq/items",
            {"rows": [
                {"item_code": "A", "description": "Item A", "unit": "no",
                 "qty": "100", "rate_combined": "10"},
                {"item_code": "DISC", "description": "Trade discount",
                 "is_discount": True, "rate_supply": "100"}]},
            format="json")
        c = self._create()
        self.assertEqual(c["basis"], "MEASURED")
        d = self._detail(c["id"])
        disc = next(ln for ln in d["lines"] if ln["is_discount"])
        # discount is valued by % even here
        rows = [{"id": ln["id"], "cumulative_qty": "50"}
                for ln in d["lines"] if ln["item_code"] == "A"]
        rows.append({"id": disc["id"], "cumulative_pct": "100"})
        w = self.client.post(f"/api/v1/claims/{c['id']}/items",
                             {"rows": rows}, format="json").data["waterfall"]
        # A: 50 × 10 = 500 ; discount fully realised −100 → 400
        self.assertEqual(float(w["k1_work_done"]), 400.0)

    # ---- 3 dp precision: IPA 3 dp, invoice 2 dp (owner 2026-07-27) --------

    def test_ipa_shows_3dp_and_invoice_2dp(self):
        from django.template.loader import render_to_string

        from core import commercial
        from core.models import ProgressClaim
        # a fractional rate so a third decimal actually appears
        self.client.post(
            f"/api/v1/projects/{self.project.id}/boq/items",
            {"rows": [{"item_code": "A", "description": "Item A", "unit": "no",
                       "qty": "3", "rate_combined": "33.333"}]},
            format="json")
        c = self._create()
        self._value_pct(c["id"], {"A": "100"})     # 3 × 33.333 = 99.999
        self._certify(c["id"])
        cc = ProgressClaim.objects.get(pk=c["id"])
        ipa = render_to_string("pdf/claim_ipa.html",
                               commercial.claim_pdf_context(cc))
        self.assertIn("99.999", ipa)               # IPA carries 3 dp
        inv = render_to_string("pdf/tax_invoice.html",
                               commercial.invoice_pdf_context(cc))
        self.assertNotIn("99.999", inv)            # invoice rounds to 2 dp

    # ---- IPA → IPC relabel + LOA reference (owner 2026-07-27) -------------

    def test_ipa_becomes_ipc_on_certification_with_loa_ref(self):
        from django.template.loader import render_to_string

        from core import commercial
        from core.models import ProgressClaim
        self.project.loa_ref = "LOA/2026/017"
        self.project.save(update_fields=["loa_ref"])
        c = self._create()
        self._value_pct(c["id"], {"A": "50", "B": "25"})
        cc = ProgressClaim.objects.get(pk=c["id"])
        # submitted → prints as the Application (IPA)
        self._status(c["id"], "SUBMITTED")
        cc.refresh_from_db()
        app = render_to_string("pdf/claim_ipa.html",
                               commercial.claim_pdf_context(cc))
        self.assertIn("INTERIM PAYMENT APPLICATION", app)
        self.assertIn("LOA/2026/017", app)
        self.assertNotIn("INTERIM PAYMENT CERTIFICATE", app)
        # certified → the same document is issued as the Certificate (IPC)
        self._status(c["id"], "CERTIFIED")
        cc.refresh_from_db()
        ipc = render_to_string("pdf/claim_ipa.html",
                               commercial.claim_pdf_context(cc))
        self.assertIn("INTERIM PAYMENT CERTIFICATE", ipc)
        self.assertIn("IPC-01", ipc)
        self.assertIn("LOA/2026/017", ipc)
        # the tax invoice cites the IPC ref + LOA ref
        inv = render_to_string("pdf/tax_invoice.html",
                               commercial.invoice_pdf_context(cc))
        self.assertIn("IPC-01", inv)
        self.assertIn("LOA/2026/017", inv)
        self.assertEqual(cc.ipc_ref, "IPC-01")

    def test_amount_in_words(self):
        from decimal import Decimal
        from core.commercial import amount_in_words
        self.assertEqual(amount_in_words(Decimal("540.00")),
                         "US Dollars Five hundred forty and 00/100 only")
        self.assertEqual(
            amount_in_words(Decimal("1234.56")),
            "US Dollars One thousand two hundred thirty-four and 56/100 only")


    def test_rollback_leaves_a_claimed_vo_approved(self):
        from io import StringIO

        from django.core.management import call_command

        from core.models import Variation
        self.client.force_authenticate(self.qs)
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/variations/create",
            {"title": "Extra", "kind": "ADDITION", "rows": [
                {"item_code": "V1", "description": "X", "unit": "m",
                 "qty": "10", "rate_supply": "10"}]}, format="json")
        vid = r.data["variations"][-1]["id"]
        vo_approve(self, vid)
        c = self._create()                      # interim claim seeds VO lines
        self._value_pct(c["id"], {"A": "50", "B": "50"})
        vo_item = next(i for i in self.client.get(
            f"/api/v1/claims/{c['id']}").data["lines"]
            if i.get("source") == "VO")
        self.client.post(f"/api/v1/claims/{c['id']}/value", {"rows": [
            {"line_id": vo_item["id"], "cumulative_pct": "100"}]},
            format="json")
        self._status(c["id"], "SUBMITTED")
        self._status(c["id"], "CERTIFIED")
        out = StringIO()
        call_command("rollback_vo_employer_approval",
                     project=self.project.code, apply=True, stdout=out)
        self.assertEqual(Variation.objects.get(pk=vid).status, "APPROVED")
        self.assertIn("LEFT APPROVED", out.getvalue())


class VoRollbackGuardTests(TestCase):
    """Placeholder kept empty on purpose — the guard test lives on
    ProgressClaimTests, where the claim fixtures are."""


class UnitClaimTests(TestCase):
    """Progress claims against a unit-based BOQ: one line per summary category —
    priced categories valued by units complete, lump bills by %. The
    conventional claim path must be entirely unaffected."""

    def setUp(self):

        from . import boq_unit_extract as ue
        self.site = Site.objects.create(code="SFR", name="Fushi",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("uc_qs", User.Role.QS)
        self.director = make_user("uc_dir", User.Role.DIRECTOR)
        # Preliminaries 132,512.18 (lump) + 11 villas × 26,491.41 = 423,917.69
        self.project = Project.objects.create(
            site=self.site, code="SFR-01", title="Villa Refurb",
            contract_value="423917.69", contract_type="LUMP_SUM",
            retention_pct="0", output_gst_pct="8")
        self.boq, msg = ue.commit(self.project, ue.normalise([
            {"name": "Preliminaries", "amount_per_unit": 132512.18,
             "is_lump": True},
            {"name": "Category D Villas", "quantity": 11, "unit": "no",
             "amount_per_unit": 26491.41},
        ]), self.qs)
        self.assertIsNone(msg)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)

    def _create(self):
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/claims/create", {},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["claims"][-1]

    def _detail(self, cid):
        return self.client.get(f"/api/v1/claims/{cid}").data

    def _value(self, cid, villa_units=None, prelim_pct=None):
        d = self._detail(cid)
        rows = []
        for ln in d["lines"]:
            if ln.get("is_lump") and prelim_pct is not None:
                rows.append({"id": ln["id"], "cumulative_pct": prelim_pct})
            elif not ln.get("is_lump") and villa_units is not None:
                rows.append({"id": ln["id"], "cumulative_qty": villa_units})
        return self.client.post(f"/api/v1/claims/{cid}/items",
                                {"rows": rows}, format="json").data

    def _certify(self, cid):
        self.client.post(f"/api/v1/claims/{cid}/status",
                         {"status": "SUBMITTED"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/claims/{cid}/status",
                         {"status": "CERTIFIED"}, format="json")
        self.client.force_authenticate(self.qs)

    def test_unit_claim_defaults_to_measured_and_values_by_category(self):
        from decimal import Decimal
        c = self._create()
        self.assertEqual(c["basis"], "MEASURED")   # unit BOQ default
        self._value(c["id"], villa_units="4", prelim_pct="50")
        d = self._detail(c["id"])
        # The villa category (single per-unit line, no detail) claims as one
        # work line by units done; the lump prelim stays a category line by %.
        villa = next(ln for ln in d["lines"] if ln["source"] == "BOQ")
        prelim = next(ln for ln in d["lines"] if ln.get("is_lump"))
        # 4 of 11 villas × 26,491.41 = 105,965.64
        self.assertEqual(Decimal(str(villa["cumulative_value"])),
                         Decimal("26491.41") * 4)
        self.assertEqual(villa["source"], "BOQ")
        self.assertFalse(villa["is_percent_only"])
        # lump bill claimed by %: 50% of 132,512.18 = 66,256.09
        self.assertEqual(Decimal(str(prelim["cumulative_value"])),
                         Decimal("132512.18") / 2)
        self.assertTrue(prelim["is_percent_only"])
        # k gross = both categories together
        self.assertEqual(
            Decimal(str(d["waterfall"]["k_gross"])),
            (Decimal("26491.41") * 4 + Decimal("132512.18") / 2)
            .quantize(Decimal("0.001")))

    def test_unit_claim_chains_previous_units(self):
        from decimal import Decimal
        c1 = self._create()
        self._value(c1["id"], villa_units="4", prelim_pct="50")
        self._certify(c1["id"])
        c2 = self._create()
        d2 = self._detail(c2["id"])
        villa = next(ln for ln in d2["lines"] if ln["source"] == "BOQ")
        # the prior 4 units carry forward as this line's previous figure
        self.assertEqual(Decimal(str(villa["previous_qty"])), Decimal("4"))
        self.assertEqual(Decimal(str(villa["previous_value"])),
                         Decimal("26491.41") * 4)
        # bump to 7 villas: current = 3 × rate, cumulative = 7 × rate
        self._value(c2["id"], villa_units="7")
        d2 = self._detail(c2["id"])
        villa = next(ln for ln in d2["lines"] if ln["source"] == "BOQ")
        self.assertEqual(Decimal(str(villa["current_value"])),
                         Decimal("26491.41") * 3)
        self.assertEqual(Decimal(str(villa["cumulative_value"])),
                         Decimal("26491.41") * 7)

    def test_conventional_claim_still_percent_by_default(self):
        # A conventional BOQ project on the same code path is unaffected: its
        # claim basis still derives from the contract type (here % complete).
        site2 = Site.objects.create(code="VKR", name="Vakkaru",
                                    status=Site.Status.ACTIVE)
        proj = Project.objects.create(site=site2, code="POOLS17",
                                      title="Pools", contract_value="3000",
                                      contract_type="LUMP_SUM")
        self.client.post(
            f"/api/v1/projects/{proj.id}/boq/items",
            {"rows": [{"item_code": "A", "description": "Item A", "unit": "no",
                       "qty": "100", "rate_combined": "10"}]}, format="json")
        r = self.client.post(f"/api/v1/projects/{proj.id}/claims/create", {},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        c = r.data["claims"][-1]
        self.assertEqual(c["basis"], "PERCENT")
        line = self._detail(c["id"])["lines"][0]
        self.assertEqual(line["source"], "BOQ")
        self.assertIsNone(line.get("previous_qty"))


class BoqCannotBeRewrittenUnderAClaimTests(TestCase):
    """A QS unlocked a claimed-against BOQ and re-saved it (owner 2026-08-15).

    Saving replaces every line, and the claim lines pointed at the old ones —
    so a PAID and a CERTIFIED claim lost all 120 of their valued lines
    silently. Three things now stand in the way: the unlock, the save, and the
    database itself.
    """

    def setUp(self):
        from datetime import date
        from decimal import Decimal

        from .models import (Boq, BoqItem, Project, ProgressClaim,
                             ProgressClaimItem, Site, User)
        from . import commercial
        self.Decimal, self.commercial = Decimal, commercial
        self.User = User
        self.Boq, self.BoqItem = Boq, BoqItem
        self.Claim, self.ClaimItem = ProgressClaim, ProgressClaimItem
        self.qs = make_user("bq_qs", User.Role.QS)
        site = Site.objects.create(code="BQP", name="Boq Isle",
                                   status=Site.Status.ACTIVE)
        self.project = Project.objects.create(
            site=site, code="BQ1", title="Pools",
            contract_value=Decimal("100"))
        self.boq = Boq.objects.create(project=self.project, created_by=self.qs)
        self.item = BoqItem.objects.create(
            boq=self.boq, sort_order=1, item_code="A", description="Mobilise",
            unit="Item", qty=Decimal("1"), rate_supply=Decimal("100"))
        self.claim = ProgressClaim.objects.create(
            project=self.project, seq=1, ref="IPA-01", status="CERTIFIED",
            basis="PERCENT")
        self.ClaimItem.objects.create(claim=self.claim, source="BOQ",
                                      boq_item=self.item,
                                      cumulative_pct=Decimal("50"))

    def _rows(self):
        return [{"item_code": "A", "description": "Mobilise", "unit": "Item",
                 "qty": "1", "rate": "100"}]

    def test_a_claimed_boq_cannot_be_unlocked(self):
        self.boq.is_locked = True
        self.boq.save(update_fields=["is_locked"])
        _, err = self.commercial.set_boq_lock(self.project, False, self.qs)
        self.assertIsNotNone(err)
        self.assertIn("IPA-01", err)
        self.boq.refresh_from_db()
        self.assertTrue(self.boq.is_locked)

    def test_saving_over_a_claimed_boq_is_refused(self):
        """Even unlocked — the lock is not the only thing holding this up."""
        self.boq.is_locked = False
        self.boq.save(update_fields=["is_locked"])
        _, err = self.commercial.set_boq_items(self.project, self._rows(), self.qs)
        self.assertIsNotNone(err)
        self.assertIn("IPA-01", err)
        self.assertEqual(self.claim.items.count(), 1)   # the valuation stands
        self.assertTrue(self.BoqItem.objects.filter(pk=self.item.pk).exists())

    def test_the_database_refuses_to_cascade_a_claimed_item_away(self):
        """The backstop, for any path that has not thought about claims."""
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.item.delete()
        self.assertEqual(self.claim.items.count(), 1)

    def test_a_draft_claim_does_not_block_the_unlock(self):
        self.claim.status = "DRAFT"
        self.claim.save(update_fields=["status"])
        self.boq.is_locked = True
        self.boq.save(update_fields=["is_locked"])
        _, err = self.commercial.set_boq_lock(self.project, False, self.qs)
        self.assertIsNone(err)

    def test_an_unclaimed_boq_still_saves_normally(self):
        self.claim.items.all().delete()
        self.boq.is_locked = False
        self.boq.save(update_fields=["is_locked"])
        boq, err = self.commercial.set_boq_items(self.project, self._rows(), self.qs)
        self.assertIsNone(err)
        self.assertEqual(self.BoqItem.objects.filter(boq=boq).count(), 1)
