"""Manual client invoices — historical + Planet-issued, folded into the same
receivables aging / statement / receipts as claim invoices."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from . import receivables
from .models import ManualInvoice, Project, Site, User
from .tests import make_user


class ManualInvoiceTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="SFR", name="Soneva Fushi", status=Site.Status.ACTIVE,
            client_name="Bunny Holdings Pvt Ltd", client_address="No. 1, Male")
        self.project = Project.objects.create(
            site=self.site, code="V42", title="Villa 42",
            contract_value="10000", output_gst_pct="8", client_credit_days=30)
        self.qs = make_user("qs1", User.Role.QS)
        self.fin = make_user("fin1", User.Role.FINANCE)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)

    def _create(self, lines=None, gst_pct="0", **over):
        # Default: a single 5000 line, GST 0 → total 5000, so the receivables
        # totals the aging/receipt tests assert stay clean.
        if lines is None:
            lines = [{"description": "Value of work", "amount": "5000"}]
        body = {"project_id": self.project.id, "origin": "HISTORICAL",
                "invoice_no": "CL-2024-07", "invoice_date": "2024-05-01",
                "gst_pct": gst_pct, "lines": lines}
        body.update(over)
        return self.client.post("/api/v1/receivables/manual-invoices", body,
                                format="json")

    # ---- creation --------------------------------------------------------
    def test_historical_uses_client_number_and_back_dates(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["invoice_no"], "CL-2024-07")
        self.assertEqual(r.data["origin"], "HISTORICAL")
        self.assertEqual(str(r.data["invoice_date"]), "2024-05-01")
        self.assertEqual(float(r.data["amount"]), 5000.0)
        self.assertFalse(r.data["can_pdf"])

    def test_issued_gets_a_planet_number_and_auto_computes_gst_and_total(self):
        # net 1000, GST @ 8% auto = 80, total = 1080 — all system-computed.
        r = self._create(origin="ISSUED", invoice_no="",
                         invoice_date="2026-07-01", gst_pct="8",
                         lines=[{"description": "Interim work", "amount": "1000"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["invoice_no"].startswith("INV-"))
        self.assertEqual(float(r.data["net_amount"]), 1000.0)
        self.assertEqual(float(r.data["gst_amount"]), 80.0)
        self.assertEqual(float(r.data["amount"]), 1080.0)   # net + gst
        self.assertTrue(r.data["can_pdf"])

    def test_multi_line_sums_net_then_adds_gst(self):
        # Unrelated charges on one invoice: equipment rental + food provision.
        r = self._create(gst_pct="8", lines=[
            {"description": "Excavator rental", "quantity": "2",
             "unit_price": "1500", "amount": "3000"},
            {"description": "Food provision to tiling crew", "amount": "1200"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["lines"]), 2)
        self.assertEqual(float(r.data["net_amount"]), 4200.0)   # 3000 + 1200
        self.assertEqual(float(r.data["gst_amount"]), 336.0)    # 8% of 4200
        self.assertEqual(float(r.data["amount"]), 4536.0)

    def test_historical_needs_a_client_number(self):
        r = self._create(invoice_no="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("number", r.data["detail"].lower())

    def test_needs_at_least_one_line(self):
        r = self._create(lines=[])
        self.assertEqual(r.status_code, 400)
        self.assertIn("line", r.data["detail"].lower())

    def test_site_staff_cannot_record_invoices(self):
        self.client.force_authenticate(self.se)
        self.assertEqual(self._create().status_code, 403)

    # ---- receivables integration ----------------------------------------
    def test_shows_in_aging_and_shared_numbering(self):
        # a historical invoice, 90+ days overdue (issued 2024, due +30)
        self._create()
        ag = receivables.aging()
        self.assertEqual(ag["invoice_count"], 1)
        self.assertEqual(float(ag["totals"]["total"]), 5000.0)
        self.assertEqual(float(ag["totals"]["d90p"]), 5000.0)
        # a Planet-issued invoice takes the next INV- number, not colliding
        r = self._create(origin="ISSUED", invoice_no="",
                         invoice_date="2026-07-01",
                         lines=[{"description": "Work", "amount": "2000"}])
        self.assertTrue(r.data["invoice_no"].endswith("-0001"))

    def test_receipt_settles_a_manual_invoice(self):
        mid = self._create().data["id"]
        r = self.client.post(f"/api/v1/projects/{self.project.id}/receipts",
                             {"manual_invoice_id": mid, "amount": "2000",
                              "received_on": "2024-06-01"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rows = receivables.invoice_rows()
        row = next(x for x in rows if x["manual_invoice_id"] == mid)
        self.assertEqual(float(row["received"]), 2000.0)
        self.assertEqual(float(row["outstanding"]), 3000.0)
        # statement shows the invoice debit and the receipt credit
        stmt = receivables.client_statement(self.site)
        kinds = [t["kind"] for t in stmt["rows"]]
        self.assertIn("INVOICE", kinds)
        self.assertIn("RECEIPT", kinds)
        self.assertEqual(float(stmt["closing"]), 3000.0)

    # ---- void ------------------------------------------------------------
    def test_void_drops_it_from_receivables(self):
        mid = self._create().data["id"]
        r = self.client.post(
            f"/api/v1/receivables/manual-invoices/{mid}/void")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["is_void"])
        self.assertEqual(receivables.aging()["invoice_count"], 0)

    def test_cannot_void_with_receipts(self):
        mid = self._create().data["id"]
        self.client.post(f"/api/v1/projects/{self.project.id}/receipts",
                         {"manual_invoice_id": mid, "amount": "1000",
                          "received_on": "2024-06-01"}, format="json")
        r = self.client.post(
            f"/api/v1/receivables/manual-invoices/{mid}/void")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ManualInvoice.objects.get(pk=mid).is_void)

    # ---- pdf -------------------------------------------------------------
    def test_issued_has_pdf_historical_does_not(self):
        issued = self._create(origin="ISSUED", invoice_no="",
                              invoice_date="2026-07-01", gst_pct="8",
                              lines=[{"description": "Work",
                                      "amount": "1500"}]).data
        r = self.client.get(
            f"/api/v1/receivables/manual-invoices/{issued['id']}.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        hist = self._create().data
        self.assertEqual(self.client.get(
            f"/api/v1/receivables/manual-invoices/{hist['id']}.pdf")
            .status_code, 400)
