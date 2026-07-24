"""Project commercial (QS) — BOQ (slice 1)."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Boq, Project, Site, User
from .tests import make_user


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
        r = self.client.post(f"/api/v1/variations/{vid}/status",
                             {"status": "SUBMITTED"}, format="json")
        c = r.data["contract"]
        self.assertEqual(float(c["revised"]), 500000.0)
        self.assertEqual(float(c["pending_net"]), 1400.0)
        self.assertEqual(float(c["forecast"]), 501400.0)
        # approved → folds into the revised contract sum
        r = self.client.post(f"/api/v1/variations/{vid}/status",
                             {"status": "APPROVED"}, format="json")
        c = r.data["contract"]
        self.assertEqual(float(c["revised"]), 501400.0)
        self.assertEqual(float(c["pending_net"]), 0.0)

    def test_omission_subtracts(self):
        v = self._create("OMISSION")
        self.assertEqual(float(v["signed_total"]), -1400.0)
        self.client.post(f"/api/v1/variations/{v['id']}/status",
                         {"status": "SUBMITTED"}, format="json")
        r = self.client.post(f"/api/v1/variations/{v['id']}/status",
                             {"status": "APPROVED"}, format="json")
        self.assertEqual(float(r.data["contract"]["revised"]), 498600.0)

    def test_approved_variation_is_locked_for_edit(self):
        v = self._create()
        self.client.post(f"/api/v1/variations/{v['id']}/status",
                         {"status": "SUBMITTED"}, format="json")
        self.client.post(f"/api/v1/variations/{v['id']}/status",
                         {"status": "APPROVED"}, format="json")
        r = self.client.post(f"/api/v1/variations/{v['id']}/items",
                             {"rows": []}, format="json")
        self.assertEqual(r.status_code, 400)

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
        return self.client.post(f"/api/v1/claims/{cid}/status",
                                {"status": s}, format="json")

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

    def test_back_charge_deducted_after_gst(self):
        # A back charge is deducted flat from the amount payable, AFTER GST.
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
        # net to pay = total-with-GST − the deduction (deduction has no GST)
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
        self.assertIn("Add advance received", ipa)
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
        self.assertIn("Net amount to pay", ipa2)
        inv = render_to_string("pdf/tax_invoice.html",
                               commercial.invoice_pdf_context(cc))
        self.assertIn("Diesel from store", inv)
        self.assertIn("Net amount to pay", inv)

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
        self.client.post(f"/api/v1/variations/{vid}/status",
                         {"status": "SUBMITTED"}, format="json")
        self.client.post(f"/api/v1/variations/{vid}/status",
                         {"status": "APPROVED"}, format="json")
        c = self._create()
        lines = self._detail(c["id"])["lines"]
        vo = next(ln for ln in lines if ln["source"] == "VO")
        self.assertEqual(vo["item_code"], "V1")
        r = self._value_pct(c["id"], {"V1": "100"})
        self.assertEqual(float(r["waterfall"]["k4_variations"]), 500.0)

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
        r = self.client.post(f"/api/v1/claims/{cid}/status",
                             {"status": "CERTIFIED"}, format="json")
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
        return self.client.post(f"/api/v1/claims/{cid}/status",
                                {"status": "CERTIFIED"}, format="json")

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

    def test_amount_in_words(self):
        from decimal import Decimal
        from core.commercial import amount_in_words
        self.assertEqual(amount_in_words(Decimal("540.00")),
                         "US Dollars Five hundred forty and 00/100 only")
        self.assertEqual(
            amount_in_words(Decimal("1234.56")),
            "US Dollars One thousand two hundred thirty-four and 56/100 only")
