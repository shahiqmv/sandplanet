"""Variations invoiced separately from the progress claims (owner
2026-11-22): the VO never enters a claim or the contract sum the claims are
valued on; it is billed by its own invoices, whole or in parts."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import commercial
from .models import (ManualInvoice, ProgressClaimItem, Project, Site, User,
                     Variation)
from .tests import make_user
from .tests_commercial import vo_approve

ROWS = [{"item_code": "V1", "description": "Extra deck", "unit": "m2",
         "qty": "10", "rate_combined": "50"},          # 500
        {"item_code": "V2", "description": "Extra lights", "unit": "no",
         "qty": "5", "rate_combined": "100"}]          # 500  → 1,000


class SeparateVoTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="VKR", name="Vakkaru", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=90),
            client_name="Vakkaru Pvt Ltd")
        self.project = Project.objects.create(
            site=self.site, code="POOLS17", title="17 Swimming Pools",
            contract_value="3000", retention_pct="10", output_gst_pct="8",
            client_credit_days=30, status="ACTIVE")
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

    def _billing(self, vid, billing):
        return self.client.post(f"/api/v1/variations/{vid}/billing",
                                {"billing": billing}, format="json")

    def _invoice(self, vid, **body):
        return self.client.post(f"/api/v1/variations/{vid}/invoice", body,
                                format="json")

    def _approve_invoice(self, iid):
        r = self.client.post(
            f"/api/v1/receivables/manual-invoices/{iid}/submit")
        self.assertEqual(r.status_code, 200, r.data)
        self.client.force_authenticate(self.director)
        r = self.client.post(
            f"/api/v1/receivables/manual-invoices/{iid}/approve")
        self.client.force_authenticate(self.qs)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def _claim(self):
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/claims/create", {},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["claims"][-1]

    def _vo_lines(self, claim_id):
        return ProgressClaimItem.objects.filter(claim_id=claim_id,
                                                source="VO").count()

    # ---- the choice ------------------------------------------------------
    def test_a_new_vo_bills_with_the_claims_unless_the_project_says_not(self):
        self.assertEqual(self._vo()["billing"], "CLAIM")
        self.project.vo_billing = "SEPARATE"
        self.project.save()
        self.assertEqual(self._vo()["billing"], "SEPARATE")
        # an omission has nothing to invoice: always with the claims
        self.assertEqual(self._vo(kind="OMISSION")["billing"], "CLAIM")

    def test_an_omission_cannot_be_invoiced_separately(self):
        v = self._vo(kind="OMISSION")
        r = self._billing(v["id"], "SEPARATE")
        self.assertEqual(r.status_code, 400)
        self.assertIn("omission", r.data["detail"])

    # ---- out of the claims and the contract sum --------------------------
    def test_a_separate_vo_stays_out_of_claims_and_the_revised_sum(self):
        v = self._vo(billing="SEPARATE")
        c = self._claim()                        # draft claim open first
        self.assertEqual(vo_approve(self, v["id"]).status_code, 200)
        self.assertEqual(self._vo_lines(c["id"]), 0)
        self.assertEqual(self._vo_lines(self._claim_after(c)), 0)
        cs = commercial.contract_summary(self.project)
        self.assertEqual(cs["approved_net"], Decimal("0"))
        self.assertEqual(cs["revised"], Decimal("3000"))
        self.assertEqual(cs["separate_approved"], Decimal("1000"))
        self.assertEqual(cs["project_value"], Decimal("4000"))

    def _claim_after(self, c):
        """Certify the draft and open the next claim; returns its id."""
        self.client.post(f"/api/v1/claims/{c['id']}/status",
                         {"status": "SUBMITTED"}, format="json")
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/claims/{c['id']}/status",
                             {"status": "CERTIFIED"}, format="json")
        self.client.force_authenticate(self.qs)
        self.assertEqual(r.status_code, 200, r.data)
        return self._claim()["id"]

    def test_switching_moves_the_lines_in_and_out_of_a_draft_claim(self):
        v = self._vo()
        vo_approve(self, v["id"])
        c = self._claim()
        self.assertEqual(self._vo_lines(c["id"]), 2)
        self.assertEqual(self._billing(v["id"], "SEPARATE").status_code, 200)
        self.assertEqual(self._vo_lines(c["id"]), 0)
        self.assertEqual(self._billing(v["id"], "CLAIM").status_code, 200)
        self.assertEqual(self._vo_lines(c["id"]), 2)

    def test_a_vo_with_value_claimed_stays_with_the_claims(self):
        v = self._vo()
        vo_approve(self, v["id"])
        c = self._claim()
        line = ProgressClaimItem.objects.filter(claim_id=c["id"],
                                                source="VO").first()
        line.cumulative_pct = Decimal("50")
        line.save()
        r = self._billing(v["id"], "SEPARATE")
        self.assertEqual(r.status_code, 400)
        self.assertIn("carries value", r.data["detail"])
        self.assertEqual(self._vo_lines(c["id"]), 2)

    # ---- invoicing -------------------------------------------------------
    def test_only_an_approved_separate_vo_is_invoiced(self):
        v = self._vo()
        r = self._invoice(v["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("progress claims", r.data["detail"])
        self._billing(v["id"], "SEPARATE")
        r = self._invoice(v["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("not approved", r.data["detail"])

    def test_the_whole_vo_goes_on_one_invoice_item_by_item(self):
        v = self._vo(billing="SEPARATE")
        vo_approve(self, v["id"], on="2026-11-10", ref="CL/VO/7")
        r = self._invoice(v["id"])
        self.assertEqual(r.status_code, 201, r.data)
        mi = ManualInvoice.objects.get(pk=r.data["invoice"]["id"])
        self.assertEqual((mi.status, mi.origin, mi.variation_id),
                         ("DRAFT", "ISSUED", v["id"]))
        self.assertEqual([(ln.description, ln.amount)
                          for ln in mi.lines.all()],
                         [("V1 Extra deck", Decimal("500.00")),
                          ("V2 Extra lights", Decimal("500.00"))])
        self.assertEqual((mi.net_amount, mi.gst_amount, mi.amount),
                         (Decimal("1000.00"), Decimal("80.00"),
                          Decimal("1080.00")))
        self.assertIn("VO-01", mi.description)
        self.assertIn("CL/VO/7", mi.note)
        self.assertEqual(mi.due_date, mi.invoice_date + timedelta(days=30))
        # no retention or advance recovery is taken on it
        self.assertFalse(mi.lines.filter(kind="DEDUCTION").exists())
        vv = r.data["variations"][-1]["separate"]
        self.assertEqual((Decimal(str(vv["invoiced"])),
                          Decimal(str(vv["billed"])),
                          Decimal(str(vv["remaining"]))),
                         (Decimal("1000"), Decimal("0"), Decimal("0")))
        self.assertFalse(vv["can_invoice"])
        # nothing left: a second invoice is refused
        r = self._invoice(v["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("in full", r.data["detail"])

    def test_part_billing_never_passes_the_vo_value(self):
        v = self._vo(billing="SEPARATE")
        vo_approve(self, v["id"])
        first = self._invoice(v["id"], percent="50")
        self.assertEqual(first.status_code, 201, first.data)
        mi = ManualInvoice.objects.get(pk=first.data["invoice"]["id"])
        self.assertEqual(mi.net_amount, Decimal("500.00"))
        self.assertIn("50% of the variation value", mi.lines.get().description)
        r = self._invoice(v["id"], amount="600")
        self.assertEqual(r.status_code, 400)
        self.assertIn("500.00", r.data["detail"])
        rest = self._invoice(v["id"])            # the balance by default
        self.assertEqual(rest.status_code, 201, rest.data)
        bal = ManualInvoice.objects.get(pk=rest.data["invoice"]["id"])
        self.assertEqual(bal.net_amount, Decimal("500.00"))
        self.assertIn("balance", bal.lines.get().description)
        # editing a draft cannot push the pair past the VO either
        r = self.client.patch(
            f"/api/v1/receivables/manual-invoices/{bal.id}",
            {"project_id": self.project.id, "origin": "ISSUED",
             "invoice_date": str(bal.invoice_date), "gst_pct": "8",
             "lines": [{"description": "VO-01 balance", "amount": "700"}]},
            format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("VO-01", r.data["detail"])
        # a voided invoice gives its share back
        self.client.post(
            f"/api/v1/receivables/manual-invoices/{bal.id}/void")
        pos = commercial.vo_billing_position(Variation.objects.get(pk=v["id"]))
        self.assertEqual(pos["remaining"], Decimal("500.00"))

    def test_once_invoiced_the_vo_is_locked_to_separate_billing(self):
        v = self._vo(billing="SEPARATE")
        vo_approve(self, v["id"])
        iid = self._invoice(v["id"]).data["invoice"]["id"]
        r = self._billing(v["id"], "CLAIM")
        self.assertEqual(r.status_code, 400)
        self.assertIn("invoice", r.data["detail"])
        r = self.client.post(f"/api/v1/variations/{v['id']}/items",
                             {"rows": ROWS[:1]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Invoices have been raised", r.data["detail"])
        # and its invoice cannot be handed to a claim
        self._approve_invoice(iid)
        from . import manual_invoices as mi_svc
        c = self._claim()
        self._claim_after(c)
        from .models import ProgressClaim
        claim = ProgressClaim.objects.get(pk=c["id"])
        self.assertIn("invoiced separately", mi_svc.link_to_claim(
            ManualInvoice.objects.get(pk=iid), claim, self.qs))

    # ---- the money counts ------------------------------------------------
    def test_an_approved_vo_invoice_is_revenue_and_receivable(self):
        v = self._vo(billing="SEPARATE")
        vo_approve(self, v["id"])
        iid = self._invoice(v["id"], percent="50").data["invoice"]["id"]
        s = commercial.project_revenue_summary(self.project)
        self.assertEqual(s["certified_revenue"], Decimal("0"))   # a draft
        self._approve_invoice(iid)
        s = commercial.project_revenue_summary(self.project)
        self.assertEqual(s["contract_revised"], Decimal("4000"))
        self.assertEqual(s["certified_revenue"], Decimal("500.00"))
        self.assertEqual(s["billed"], Decimal("540.00"))
        self.assertEqual(s["gst_billed"], Decimal("40.00"))
        from . import receivables
        rows = receivables.invoice_rows(self.site.id)
        self.assertEqual([Decimal(str(r["amount"])) for r in rows],
                         [Decimal("540.00")])
        from .report_pnl import certified_revenue
        mi = ManualInvoice.objects.get(pk=iid)
        rev = certified_revenue([self.site.id], mi.invoice_date,
                                mi.invoice_date)
        self.assertEqual(rev[self.site.id][0], Decimal("500.00"))
        self.assertEqual(certified_revenue.per_project, {})

    # ---- the VO as it prints ---------------------------------------------
    def test_the_vo_pdf_says_it_is_invoiced_separately(self):
        other = self._vo(title="In the claims")
        vo_approve(self, other["id"])
        v = self._vo(billing="SEPARATE")
        vo_approve(self, v["id"])
        ctx = commercial.variation_pdf_context(
            Variation.objects.get(pk=v["id"]))
        self.assertTrue(ctx["separate"])
        self.assertIn("invoiced separately", ctx["status_note"])
        # ...and it does not count in the build-up of a claimed variation
        ctx = commercial.variation_pdf_context(
            Variation.objects.get(pk=other["id"]))
        self.assertFalse(ctx["separate"])
        self.assertEqual(ctx["prior_approved"], Decimal("0"))
        self.assertEqual(ctx["sum_after"], Decimal("4000"))
        r = self.client.get(f"/api/v1/variations/{v['id']}/vo.pdf")
        self.assertEqual(r.status_code, 200)
