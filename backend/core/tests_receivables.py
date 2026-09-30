"""Receivables — invoice due dates, aging analysis, client statement."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import receivables
from .models import ClientReceipt, ProgressClaim, Project, Site, User
from .tests import make_user


class ReceivablesTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="SFR", name="Soneva Fushi", status=Site.Status.ACTIVE,
            client_name="Bunny Holdings Pvt Ltd",
            client_address="No. 1, Male")
        self.project = Project.objects.create(
            site=self.site, code="V42", title="Villa 42",
            contract_value="10000", advance_payment_pct="20",
            output_gst_pct="8", client_credit_days=30)
        self.qs = make_user("qs1", User.Role.QS)
        self.director = make_user("dir1", User.Role.DIRECTOR)
        self.fin = make_user("fin1", User.Role.FINANCE)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)

    def _make_invoice(self):
        """Raise an advance claim (no BOQ needed), submit, certify → invoice."""
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/claims/create",
            {"claim_type": "ADVANCE"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        cid = r.data["claims"][-1]["id"]
        self.client.post(f"/api/v1/claims/{cid}/status",
                         {"status": "SUBMITTED"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/claims/{cid}/status",
                         {"status": "CERTIFIED"}, format="json")
        self.client.force_authenticate(self.qs)
        return ProgressClaim.objects.get(pk=cid)

    # ---- due dates -------------------------------------------------------
    def test_due_date_is_invoice_date_plus_credit_period(self):
        c = self._make_invoice()
        expected = receivables.invoice_date(c) + timedelta(days=30)
        self.assertEqual(receivables.due_date(c), expected)
        # advance 20% of 10000 = 2000; +8% GST = 2160
        self.assertEqual(float(receivables.invoiced_amount(c)), 2160.0)

    def test_no_credit_period_due_on_issue(self):
        self.project.client_credit_days = None
        self.project.save(update_fields=["client_credit_days"])
        c = self._make_invoice()
        self.assertEqual(receivables.due_date(c), receivables.invoice_date(c))

    # ---- aging -----------------------------------------------------------
    def test_aging_buckets_by_overdue_age(self):
        c = self._make_invoice()
        # back-date the invoice so it is 45 days overdue (credit 30 → 75 days)
        c.certified_at = timezone.now() - timedelta(days=75)
        c.save(update_fields=["certified_at"])
        ag = receivables.aging()
        self.assertEqual(ag["invoice_count"], 1)
        row = ag["clients"][0]
        self.assertEqual(row["client"], "Bunny Holdings Pvt Ltd")
        self.assertEqual(float(row["d31_60"]), 2160.0)   # 45 days overdue
        self.assertEqual(float(row["current"]), 0.0)
        self.assertEqual(float(ag["totals"]["total"]), 2160.0)

    def test_receipt_moves_invoice_out_of_aging(self):
        c = self._make_invoice()
        # pay it in full → it drops off the outstanding aging
        self.client.post(f"/api/v1/projects/{self.project.id}/receipts",
                         {"claim_id": c.id, "amount": "2160",
                          "received_on": str(timezone.localdate())}, format="json")
        ag = receivables.aging()
        self.assertEqual(ag["invoice_count"], 0)
        self.assertEqual(float(ag["totals"]["total"]), 0.0)

    # ---- statement -------------------------------------------------------
    def test_statement_runs_a_balance(self):
        c = self._make_invoice()
        self.client.post(f"/api/v1/projects/{self.project.id}/receipts",
                         {"claim_id": c.id, "amount": "1000",
                          "received_on": str(timezone.localdate())}, format="json")
        s = receivables.client_statement(self.site)
        self.assertEqual(float(s["opening"]), 0.0)
        self.assertEqual(float(s["billed"]), 2160.0)
        self.assertEqual(float(s["received"]), 1000.0)
        self.assertEqual(float(s["closing"]), 1160.0)
        kinds = [r["kind"] for r in s["rows"]]
        self.assertEqual(kinds, ["INVOICE", "RECEIPT"])
        self.assertEqual(float(s["rows"][-1]["balance"]), 1160.0)

    # ---- API + permissions ----------------------------------------------
    def test_api_endpoints_and_role_gate(self):
        self._make_invoice()
        for role_user in (self.qs, self.director, self.fin):
            self.client.force_authenticate(role_user)
            self.assertEqual(
                self.client.get("/api/v1/receivables/aging").status_code, 200)
            r = self.client.get(
                f"/api/v1/receivables/statement?site={self.site.id}")
            self.assertEqual(r.status_code, 200)
        # a site engineer may not see the receivables ledger
        self.client.force_authenticate(self.se)
        self.assertEqual(
            self.client.get("/api/v1/receivables/aging").status_code, 403)

    def test_finance_opens_the_invoice_behind_a_ledger_line(self):
        """Finance had the receivable but no way to open the invoice or its
        PDF from Receivables or the statement (owner 2026-09-30)."""
        c = self._make_invoice()
        ClientReceipt.objects.create(project=self.project, claim=c,
                                     amount=Decimal("1000"),
                                     received_on=date.today(),
                                     reference="TT-77")
        self.client.force_authenticate(self.fin)
        # the ledger and the statement both say where the invoice opens
        row = self.client.get("/api/v1/receivables/invoices").data["invoices"][0]
        self.assertEqual((row["claim_id"], row["pdf_url"], row["ipc_url"]),
                         (c.id, f"/api/v1/claims/{c.id}/invoice.pdf",
                          f"/api/v1/claims/{c.id}/ipa.pdf"))
        st = self.client.get(
            f"/api/v1/receivables/statement?site={self.site.id}").data
        inv = [r for r in st["rows"] if r["kind"] == "INVOICE"][0]
        self.assertEqual((inv["source"], inv["claim_id"]), ("CLAIM", c.id))
        # the detail: the invoice's own figures and what has come in
        d = self.client.get(f"/api/v1/receivables/invoices/claim/{c.id}").data
        self.assertEqual(d["invoice_no"], c.invoice_no)
        self.assertEqual((float(d["net_due"]), float(d["gst"]),
                          float(d["amount"])), (2000.0, 160.0, 2160.0))
        self.assertEqual((float(d["received"]), float(d["outstanding"])),
                         (1000.0, 1160.0))
        self.assertEqual([r["reference"] for r in d["receipts"]], ["TT-77"])
        self.assertTrue(d["summary"])
        # and Finance can pull the PDF itself (503 = no PDF engine here)
        r = self.client.get(row["pdf_url"])
        self.assertIn(r.status_code, (200, 503))
        # a site role gets none of it
        self.client.force_authenticate(self.se)
        self.assertEqual(self.client.get(
            f"/api/v1/receivables/invoices/claim/{c.id}").status_code, 403)
        self.assertEqual(self.client.get(row["pdf_url"]).status_code, 403)

    def test_statement_requires_a_client(self):
        self.assertEqual(
            self.client.get("/api/v1/receivables/statement").status_code, 400)
