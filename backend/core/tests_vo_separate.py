"""Variations claimed separately from the main scope (owner 2026-11-22): the
VO never enters a main claim or the contract sum those claims are valued on;
it has a claim series of its own — application, certificate, invoice — with
the contract's retention and advance terms applied to the VO's value."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import commercial
from .models import (ProgressClaim, ProgressClaimItem, Project, Site, User,
                     Variation)
from .tests import make_user
from .tests_commercial import vo_approve

ROWS = [{"item_code": "V1", "description": "Extra deck", "unit": "m2",
         "qty": "10", "rate_combined": "50"},          # 500
        {"item_code": "V2", "description": "Extra lights", "unit": "no",
         "qty": "5", "rate_combined": "100"}]          # 500  → 1,000
D = Decimal


class SeparateVoTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="VKR", name="Vakkaru", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=90),
            client_name="Vakkaru Pvt Ltd")
        self.project = Project.objects.create(
            site=self.site, code="POOLS17", title="17 Swimming Pools",
            contract_value="3000", advance_payment_pct="40",
            retention_pct="10", output_gst_pct="8", client_credit_days=30,
            status="ACTIVE")
        self.qs = make_user("qs1", User.Role.QS)
        self.director = make_user("dir1", User.Role.DIRECTOR)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)
        self.client.post(
            f"/api/v1/projects/{self.project.id}/boq/items",
            {"rows": [{"item_code": "A", "description": "Item A",
                       "unit": "no", "qty": "100", "rate_combined": "30"}]},
            format="json")

    # ---- helpers ---------------------------------------------------------
    def _vo(self, **over):
        body = {"title": "Extra deck and lights", "rows": ROWS}
        body.update(over)
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/variations/create", body,
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["variations"][-1]

    def _separate_vo(self, approve=True):
        v = self._vo(billing="SEPARATE")
        if approve:
            self.assertEqual(vo_approve(self, v["id"]).status_code, 200)
        return v

    def _billing(self, vid, billing):
        return self.client.post(f"/api/v1/variations/{vid}/billing",
                                {"billing": billing}, format="json")

    def _raise(self, **body):
        return self.client.post(
            f"/api/v1/projects/{self.project.id}/claims/create", body,
            format="json")

    def _claim(self, **body):
        r = self._raise(**body)
        self.assertEqual(r.status_code, 201, r.data)
        return next(c for c in r.data["claims"]
                    if c["id"] == r.data["created_id"])

    def _value(self, cid, pct):
        d = self.client.get(f"/api/v1/claims/{cid}").data
        rows = [{"id": ln["id"], "cumulative_pct": pct} for ln in d["lines"]]
        r = self.client.post(f"/api/v1/claims/{cid}/items", {"rows": rows},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def _certify(self, cid):
        r = self.client.post(f"/api/v1/claims/{cid}/status",
                             {"status": "SUBMITTED"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/claims/{cid}/status",
                             {"status": "CERTIFIED"}, format="json")
        self.client.force_authenticate(self.qs)
        self.assertEqual(r.status_code, 200, r.data)

    def _w(self, cid):
        return commercial.claim_valuation(
            ProgressClaim.objects.get(pk=cid))["waterfall"]

    def _vo_lines(self, claim_id):
        return ProgressClaimItem.objects.filter(claim_id=claim_id,
                                                source="VO").count()

    # ---- the choice is the site's ----------------------------------------
    def test_a_new_vo_follows_the_site_setting(self):
        self.assertEqual(self._vo()["billing"], "CLAIM")
        self.client.force_authenticate(make_user("adm1", User.Role.ADMIN))
        r = self.client.patch(f"/api/v1/sites/{self.site.id}",
                              {"vo_billing": "SEPARATE"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.client.force_authenticate(self.qs)
        self.assertEqual(self._vo()["billing"], "SEPARATE")
        # an omission always stays with the main claims
        self.assertEqual(self._vo(kind="OMISSION")["billing"], "CLAIM")
        r = self._billing(self._vo(kind="OMISSION")["id"], "SEPARATE")
        self.assertEqual(r.status_code, 400)
        self.assertIn("omission", r.data["detail"])

    # ---- out of the main claims and the contract sum ---------------------
    def test_a_separate_vo_stays_out_of_main_claims_and_the_revised_sum(self):
        v = self._vo(billing="SEPARATE")
        main = self._claim()                     # a draft main claim is open
        self.assertEqual(vo_approve(self, v["id"]).status_code, 200)
        self.assertEqual(self._vo_lines(main["id"]), 0)
        self._certify(main["id"])
        self.assertEqual(self._vo_lines(self._claim()["id"]), 0)
        cs = commercial.contract_summary(self.project)
        self.assertEqual((cs["approved_net"], cs["revised"]),
                         (D("0"), D("3000")))
        self.assertEqual((cs["separate_approved"], cs["project_value"]),
                         (D("1000"), D("4000")))

    def test_switching_moves_the_lines_in_and_out_of_a_draft_main_claim(self):
        v = self._vo()
        vo_approve(self, v["id"])
        c = self._claim()
        self.assertEqual(self._vo_lines(c["id"]), 2)
        self.assertEqual(self._billing(v["id"], "SEPARATE").status_code, 200)
        self.assertEqual(self._vo_lines(c["id"]), 0)
        self.assertEqual(self._billing(v["id"], "CLAIM").status_code, 200)
        self.assertEqual(self._vo_lines(c["id"]), 2)
        # once the main claim carries value on it, it stays there
        line = ProgressClaimItem.objects.filter(claim_id=c["id"],
                                                source="VO").first()
        line.cumulative_pct = D("50")
        line.save()
        r = self._billing(v["id"], "SEPARATE")
        self.assertEqual(r.status_code, 400)
        self.assertIn("carries value", r.data["detail"])

    # ---- the VO's own claims ---------------------------------------------
    def test_only_an_approved_separate_vo_is_claimed(self):
        v = self._vo()
        r = self._raise(variation_id=v["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("main claims", r.data["detail"])
        self._billing(v["id"], "SEPARATE")
        r = self._raise(variation_id=v["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("not approved", r.data["detail"])

    def test_a_vo_claim_runs_its_own_series_with_retention(self):
        """No advance claimed on the VO: retention is held, nothing is
        recovered, and each claim follows the VO's previous one."""
        self._certify(self._claim()["id"])       # main IPA-01 exists
        v = self._separate_vo()
        c1 = self._claim(variation_id=v["id"])
        self.assertEqual((c1["ref"], c1["seq"], c1["variation_ref"]),
                         ("VO-01/IPA-01", 1, "VO-01"))
        self.assertEqual(self._vo_lines(c1["id"]), 2)
        self.assertEqual(ProgressClaimItem.objects.filter(
            claim_id=c1["id"]).count(), 2)       # the VO's items only
        # one open claim per VO at a time
        r = self._raise(variation_id=v["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("still open", r.data["detail"])
        self._value(c1["id"], "50")
        w = self._w(c1["id"])
        self.assertEqual((w["original"], w["k4_variations"], w["k_gross"]),
                         (D("1000"), D("500"), D("500")))
        self.assertEqual((w["advance_received"], w["advance_recovered"]),
                         (D("0"), D("0")))
        self.assertEqual(w["retention_held"], D("50"))
        self.assertEqual((w["net_due"], w["gst"], w["net_to_pay"]),
                         (D("450"), D("36"), D("486")))
        self._certify(c1["id"])
        done = ProgressClaim.objects.get(pk=c1["id"])
        self.assertTrue(done.invoice_no.startswith("INV-"))
        self.assertEqual(done.ipc_ref, "VO-01/IPC-01")
        # the next claim carries the 50% forward and bills the rest
        c2 = self._claim(variation_id=v["id"])
        self.assertEqual(c2["ref"], "VO-01/IPA-02")
        self._value(c2["id"], "100")
        w = self._w(c2["id"])
        self.assertEqual((w["k_gross"], w["retention_held"],
                          w["previously_certified"], w["net_due"]),
                         (D("1000"), D("100"), D("450"), D("450")))
        # the main series is untouched by the VO's numbering
        nxt = self._claim()
        self.assertEqual((nxt["ref"], nxt["seq"], nxt["variation_id"]),
                         ("IPA-02", 2, None))
        self.assertEqual(self._vo_lines(nxt["id"]), 0)

    def test_the_vos_own_advance_is_claimed_then_recovered(self):
        v = self._separate_vo()
        adv = self._claim(variation_id=v["id"], claim_type="ADVANCE")
        self.assertEqual(adv["ref"], "VO-01/IPA-01")
        w = self._w(adv["id"])
        # 40% of the VO's 1,000 — not of the contract's 3,000
        self.assertEqual((w["advance_total"], w["net_due"]),
                         (D("400"), D("400")))
        self._certify(adv["id"])
        r = self._raise(variation_id=v["id"], claim_type="ADVANCE")
        self.assertEqual(r.status_code, 400)
        c = self._claim(variation_id=v["id"])
        self._value(c["id"], "50")
        w = self._w(c["id"])
        # gross 500 + advance 400 − recovery 40% × 500 − retention 50 = 650;
        # less the 400 already certified
        self.assertEqual((w["advance_received"], w["advance_recovered"],
                          w["retention_held"], w["net_cumulative"],
                          w["net_due"]),
                         (D("400"), D("200"), D("50"), D("650"), D("250")))
        # the main contract's advance is its own: 40% of 3,000
        self.assertEqual(self._w(self._claim(claim_type="ADVANCE")["id"])
                         ["advance_total"], D("1200"))

    def test_a_claimed_vo_is_locked_to_separate_billing(self):
        v = self._separate_vo()
        c = self._claim(variation_id=v["id"])
        r = self._billing(v["id"], "CLAIM")
        self.assertEqual(r.status_code, 400)
        self.assertIn("VO-01/IPA-01", r.data["detail"])
        # deleting its only (draft) claim frees the choice again
        r = self.client.delete(f"/api/v1/claims/{c['id']}/delete")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self._billing(v["id"], "CLAIM").status_code, 200)

    def test_a_vo_with_value_certified_cannot_be_edited(self):
        v = self._separate_vo()
        c = self._claim(variation_id=v["id"])
        self._value(c["id"], "50")
        self._certify(c["id"])
        r = self.client.post(f"/api/v1/variations/{v['id']}/items",
                             {"rows": ROWS[:1]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("correcting variation", r.data["detail"])

    def test_an_edited_vo_gets_its_lines_back_on_its_draft_claim(self):
        v = self._separate_vo()
        c = self._claim(variation_id=v["id"])
        r = self.client.post(f"/api/v1/variations/{v['id']}/items",
                             {"rows": ROWS[:1]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)     # back to draft
        self.assertEqual(self._vo_lines(c["id"]), 0)
        self.assertEqual(vo_approve(self, v["id"]).status_code, 200)
        self.assertEqual(self._vo_lines(c["id"]), 1)

    # ---- the money counts ------------------------------------------------
    def test_a_certified_vo_claim_is_revenue_and_receivable(self):
        v = self._separate_vo()
        c = self._claim(variation_id=v["id"])
        self._value(c["id"], "50")
        s = commercial.project_revenue_summary(self.project)
        self.assertEqual(s["certified_revenue"], D("0"))     # still a draft
        self._certify(c["id"])
        s = commercial.project_revenue_summary(self.project)
        self.assertEqual(s["contract_revised"], D("4000"))
        self.assertEqual((s["certified_revenue"], s["retention_held"],
                          s["billed"], s["gst_billed"]),
                         (D("500"), D("50"), D("486"), D("36")))
        from . import receivables
        rows = receivables.invoice_rows(self.site.id)
        self.assertEqual([D(str(r["amount"])) for r in rows], [D("486.00")])
        from .report_pnl import certified_revenue
        today = date.today()
        rev = certified_revenue([self.site.id], today, today)
        self.assertEqual(rev[self.site.id], (D("500"), D("500")))
        self.assertEqual(certified_revenue.per_project, {})
        pos = commercial.vo_claim_position(Variation.objects.get(pk=v["id"]))
        self.assertEqual((pos["certified"], pos["remaining"]),
                         (D("500.00"), D("500.00")))

    # ---- the documents ---------------------------------------------------
    def test_the_documents_name_the_variation(self):
        other = self._vo(title="In the claims")
        vo_approve(self, other["id"])
        v = self._separate_vo()
        ctx = commercial.variation_pdf_context(
            Variation.objects.get(pk=v["id"]))
        self.assertTrue(ctx["separate"])
        self.assertIn("separately", ctx["status_note"])
        # ...and it does not count in the build-up of a claimed variation
        ctx = commercial.variation_pdf_context(
            Variation.objects.get(pk=other["id"]))
        self.assertEqual((ctx["separate"], ctx["sum_after"]),
                         (False, D("4000")))
        c = self._claim(variation_id=v["id"])
        self._value(c["id"], "100")
        self._certify(c["id"])
        claim = ProgressClaim.objects.get(pk=c["id"])
        self.assertEqual(commercial.claim_pdf_context(claim)["variation"].ref,
                         "VO-02")
        self.assertIn("Variation Order VO-02",
                      commercial.invoice_pdf_context(claim)["scope_label"])
        for doc in ("vo.pdf",):
            r = self.client.get(f"/api/v1/variations/{v['id']}/{doc}")
            self.assertEqual(r.status_code, 200)
        for doc in ("ipa.pdf", "invoice.pdf"):
            r = self.client.get(f"/api/v1/claims/{c['id']}/{doc}")
            self.assertEqual(r.status_code, 200, doc)
