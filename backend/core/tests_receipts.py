"""Official receipts — part payment, multi-invoice settlement, void."""
from datetime import date

from django.test import TestCase
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
        body = {"site": self.site.id, "receipt_date": str(date.today()),
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
                                  "receipt_date": str(date.today()),
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
