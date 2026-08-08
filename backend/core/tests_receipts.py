"""Official receipts — part payment, multi-invoice settlement, void."""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import receivables
from .models import (ClientReceipt, CompanyBankAccount, OfficialReceipt,
                     ProgressClaim, Project, Site, User)
from .tests import make_user


class OfficialReceiptTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="SFR", name="Soneva Fushi", status=Site.Status.ACTIVE,
            client_name="Bunny Holdings Pvt Ltd", client_address="Male")
        self.p1 = Project.objects.create(
            site=self.site, code="V42", title="Villa 42",
            contract_value="10000", advance_payment_pct="20",
            output_gst_pct="8")
        self.p2 = Project.objects.create(
            site=self.site, code="V43", title="Villa 43",
            contract_value="10000", advance_payment_pct="20",
            output_gst_pct="8")
        self.qs = make_user("qs1", User.Role.QS)
        self.director = make_user("dir1", User.Role.DIRECTOR)
        self.fin = make_user("fin1", User.Role.FINANCE)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.bank = CompanyBankAccount.objects.create(
            label="BML USD", bank_name="Bank of Maldives", currency="USD")
        self.client = APIClient()

    def _invoice(self, project):
        """Advance invoice (20% of 10000 + 8% GST = 2160) — no BOQ needed."""
        self.client.force_authenticate(self.qs)
        r = self.client.post(f"/api/v1/projects/{project.id}/claims/create",
                             {"claim_type": "ADVANCE"}, format="json")
        cid = r.data["claims"][-1]["id"]
        self.client.post(f"/api/v1/claims/{cid}/status",
                         {"status": "SUBMITTED"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/claims/{cid}/status",
                         {"status": "CERTIFIED"}, format="json")
        return ProgressClaim.objects.get(pk=cid)

    def _receipt(self, allocations, **extra):
        self.client.force_authenticate(self.fin)
        body = {"site": self.site.id, "receipt_date": str(timezone.localdate()),
                "method": "TT", "reference": "FT123",
                "bank_account": self.bank.id, "allocations": allocations,
                **extra}
        return self.client.post("/api/v1/receivables/receipts", body,
                                format="json")

    def test_multi_invoice_receipt_settles_all(self):
        a = self._invoice(self.p1)
        b = self._invoice(self.p2)
        r = self._receipt([{"claim_id": a.id, "amount": "2160"},
                           {"claim_id": b.id, "amount": "2160"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["receipt_no"], "OR-0001")
        self.assertEqual(float(r.data["total"]), 4320.0)
        self.assertEqual(len(r.data["lines"]), 2)
        self.assertEqual(ProgressClaim.objects.get(pk=a.id).status, "PAID")
        self.assertEqual(ProgressClaim.objects.get(pk=b.id).status, "PAID")

    def test_part_payment_keeps_invoice_open(self):
        a = self._invoice(self.p1)
        r = self._receipt([{"claim_id": a.id, "amount": "1000"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(ProgressClaim.objects.get(pk=a.id).status, "CERTIFIED")
        # aging still shows the 1160 balance; statement shows the 1000 credit
        ag = receivables.aging()
        self.assertEqual(float(ag["totals"]["total"]), 1160.0)
        s = receivables.client_statement(self.site)
        self.assertEqual(float(s["received"]), 1000.0)
        self.assertEqual(float(s["closing"]), 1160.0)

    def test_over_allocation_rejected(self):
        a = self._invoice(self.p1)
        r = self._receipt([{"claim_id": a.id, "amount": "5000"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(OfficialReceipt.objects.count(), 0)

    def test_void_receipt_reverts_paid_and_restores_balance(self):
        a = self._invoice(self.p1)
        r = self._receipt([{"claim_id": a.id, "amount": "2160"}])
        rid = r.data["id"]
        self.assertEqual(ProgressClaim.objects.get(pk=a.id).status, "PAID")
        self.client.force_authenticate(self.fin)
        d = self.client.delete(f"/api/v1/receivables/receipts/{rid}")
        self.assertEqual(d.status_code, 204)
        self.assertEqual(ProgressClaim.objects.get(pk=a.id).status, "CERTIFIED")
        self.assertEqual(ClientReceipt.objects.filter(claim=a).count(), 0)
        self.assertEqual(float(receivables.aging()["totals"]["total"]), 2160.0)

    def test_only_finance_issues_receipts(self):
        a = self._invoice(self.p1)
        alloc = [{"claim_id": a.id, "amount": "1000"}]
        # QS + Director can view receivables but cannot issue a receipt
        for u in (self.qs, self.director):
            self.client.force_authenticate(u)
            r = self.client.post("/api/v1/receivables/receipts",
                                 {"site": self.site.id,
                                  "receipt_date": str(timezone.localdate()),
                                  "method": "TT", "allocations": alloc},
                                 format="json")
            self.assertEqual(r.status_code, 403)
        # Finance can
        self.assertEqual(self._receipt(alloc).status_code, 201)
        # a site engineer cannot even list receipts
        self.client.force_authenticate(self.se)
        self.assertEqual(
            self.client.get("/api/v1/receivables/receipts").status_code, 403)

    def test_receipt_pdf_renders(self):
        a = self._invoice(self.p1)
        rid = self._receipt([{"claim_id": a.id, "amount": "2160"}]).data["id"]
        self.client.force_authenticate(self.fin)
        r = self.client.get(f"/api/v1/receivables/receipts/{rid}.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_bank_accounts_listed_for_picker(self):
        self.client.force_authenticate(self.fin)
        r = self.client.get("/api/v1/receivables/bank-accounts?active=1")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(b["label"] == "BML USD"
                            for b in r.data["accounts"]))


class ManualInvoiceReceiptTests(OfficialReceiptTests):
    """Receipting manual invoices individually — they carry no claim_id, so the
    per-invoice keying + backend path must handle them (owner 2026-08-08)."""

    def _manual(self, project, no, amount="500"):
        self.client.force_authenticate(self.qs)
        r = self.client.post(
            "/api/v1/receivables/manual-invoices",
            {"origin": "HISTORICAL", "project_id": project.id,
             "invoice_no": no, "invoice_date": str(timezone.localdate()),
             "gst_pct": "0",
             "lines": [{"description": "Old bill", "amount": amount}]},
            format="json")
        self.assertIn(r.status_code, (200, 201), r.data)
        from .models import ManualInvoice
        return ManualInvoice.objects.get(invoice_no=no)

    def test_receipt_one_manual_invoice_leaves_the_other(self):
        from decimal import Decimal

        from .receipts import manual_outstanding
        m1 = self._manual(self.p1, "APSP/2026/0058", "500")
        m2 = self._manual(self.p1, "APSP/2026/0068", "500")
        r = self._receipt([{"manual_invoice_id": m1.id, "amount": "500"}])
        self.assertEqual(r.status_code, 201, r.data)
        m1.refresh_from_db(); m2.refresh_from_db()
        self.assertEqual(manual_outstanding(m1), Decimal("0.00"))
        self.assertEqual(manual_outstanding(m2), Decimal("500.00"))
        # the receipt lists the manual invoice number
        self.assertEqual(r.data["lines"][0]["invoice_no"], "APSP/2026/0058")

    def test_manual_receipt_cannot_overpay(self):
        m1 = self._manual(self.p1, "APSP/2026/0070", "300")
        r = self._receipt([{"manual_invoice_id": m1.id, "amount": "400"}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("exceeds", r.data["detail"])
