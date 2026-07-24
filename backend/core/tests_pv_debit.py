"""Payment voucher debit account — set at creation and back-filled on live PVs."""
from django.test import TestCase

from . import vouchers
from .models import CompanyBankAccount, Document, User
from .tests import make_user


class PVDebitAccountTests(TestCase):
    def setUp(self):
        self.fin = make_user("fin1", User.Role.FINANCE)
        self.usd = CompanyBankAccount.objects.create(
            label="BML USD", currency="USD", is_active=True)
        self.mvr = CompanyBankAccount.objects.create(
            label="BML MVR", currency="MVR", is_active=True)

    def _bare_pv(self):
        """A PV document with no lines (currency unknown) for the back-fill
        path — the debit-account setter doesn't depend on voucher sources."""
        from .numbering import next_ref
        from .models import DocumentRevision
        from .views_vouchers import Document as Doc
        from . import vouchers as V
        pv = Doc.objects.create(doc_type="PV", ref=next_ref("PV", None),
                                site=V.ho_site(), doc_date="2026-07-24",
                                status="APPROVED", created_by=self.fin)
        DocumentRevision.objects.create(document=pv, rev_label="R0",
                                        payload={}, created_by=self.fin)
        return pv

    def test_set_debit_account_on_live_voucher(self):
        pv = self._bare_pv()
        self.assertIsNone(pv.debit_account_id)
        out, err = vouchers.set_voucher_debit_account(pv, self.usd.id, self.fin)
        self.assertIsNone(err, err)
        pv.refresh_from_db()
        self.assertEqual(pv.debit_account_id, self.usd.id)
        # clearing it back to none is allowed
        vouchers.set_voucher_debit_account(pv, None, self.fin)
        pv.refresh_from_db()
        self.assertIsNone(pv.debit_account_id)

    def test_currency_mismatch_rejected(self):
        # give the PV a USD line so its currency is USD
        pv = self._bare_pv()
        from .models import PaymentVoucherLine
        PaymentVoucherLine.objects.create(voucher=pv, amount="100",
                                          currency="USD")
        out, err = vouchers.set_voucher_debit_account(pv, self.mvr.id, self.fin)
        self.assertIsNotNone(err)
        self.assertIn("MVR", err)
        pv.refresh_from_db()
        self.assertIsNone(pv.debit_account_id)
        # the matching USD account is accepted
        out, err = vouchers.set_voucher_debit_account(pv, self.usd.id, self.fin)
        self.assertIsNone(err, err)

    def test_action_endpoint_gated_to_finance(self):
        pv = self._bare_pv()
        from rest_framework.test import APIClient
        c = APIClient()
        # a signatory cannot set the debit account
        c.force_authenticate(make_user("sig1", User.Role.SIGNATORY))
        r = c.post(f"/api/v1/payment-vouchers/{pv.ref}/actions/set-debit-account",
                   {"bank_account_id": self.usd.id}, format="json")
        self.assertEqual(r.status_code, 403)
        # finance can
        c.force_authenticate(self.fin)
        r = c.post(f"/api/v1/payment-vouchers/{pv.ref}/actions/set-debit-account",
                   {"bank_account_id": self.usd.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["debit_account"]["label"], "BML USD")
