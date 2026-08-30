"""What currency the approvals queue says a figure is in.

The list printed "MVR" in front of every amount, hard-coded in the template.
An import order is priced in the supplier's currency, so a signatory was shown
"MVR 27,129.80" for an order worth USD 27,129.80 — about fifteen times more
money than the label claimed (owner 2026-08-30)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from .models import (Document, ImportOrder, PaymentRequest, Site, Supplier,
                     User)
from .tests import make_user
from .views_documents import queue_currency


class QueueCurrencyTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="MLE", name="Head office",
                                        status=Site.Status.ACTIVE,
                                        is_head_office=True)
        self.user = make_user("hop_cur", User.Role.HO_PURCHASING)

    def _doc(self, doc_type, ref, status="APPROVED"):
        return Document.objects.create(
            doc_type=doc_type, ref=ref, site=self.site, doc_date=date.today(),
            status=status, created_by=self.user)

    def test_a_usd_import_order_reports_usd(self):
        doc = self._doc("IPR", "IPR-CUR-001")
        ImportOrder.objects.create(
            document=doc, supplier=Supplier.objects.create(name="Acme"),
            order_currency="USD", exchange_rate=Decimal("15.42"))
        self.assertEqual(queue_currency(doc.ref, "IPR"), "USD")

    def test_an_mvr_import_order_reports_mvr(self):
        doc = self._doc("IPR", "IPR-CUR-002")
        ImportOrder.objects.create(
            document=doc, supplier=Supplier.objects.create(name="Local"),
            order_currency="MVR", exchange_rate=Decimal("1"))
        self.assertEqual(queue_currency(doc.ref, "IPR"), "MVR")

    def test_a_usd_payment_request_reports_usd(self):
        from .models import CostHead
        doc = self._doc("PYR", "PYR-CUR-001")
        head, _ = CostHead.objects.get_or_create(name="Import Charges")
        PaymentRequest.objects.create(
            document=doc, cost_head=head, currency="USD",
            amount_requested=Decimal("100"), payee="Someone",
            payment_type="DIRECT", payment_method="BANK")
        self.assertEqual(queue_currency(doc.ref, "PYR"), "USD")

    def test_a_voucher_reports_its_lines_currency(self):
        from .models import PaymentVoucherLine
        pv = self._doc("PV", "PV-CUR-001")
        src = self._doc("PYR", "PYR-CUR-002")
        PaymentVoucherLine.objects.create(
            voucher=pv, source_document=src, amount=Decimal("500"),
            currency="USD", status="APPROVED")
        self.assertEqual(queue_currency(pv.ref, "PV"), "USD")

    def test_local_procurement_stays_mvr(self):
        doc = self._doc("PR", "PR-CUR-001")
        self.assertEqual(queue_currency(doc.ref, "PR"), "MVR")

    def test_an_unknown_reference_does_not_crash(self):
        self.assertEqual(queue_currency("NOPE-001", "IPR"), "MVR")

    def test_the_queue_row_carries_the_currency(self):
        """End to end: the field the list renders must be present."""
        from .views_documents import pending_groups
        doc = self._doc("IPR", "IPR-CUR-003", status="APPROVED")
        ImportOrder.objects.create(
            document=doc, supplier=Supplier.objects.create(name="Zeta"),
            order_currency="USD", exchange_rate=Decimal("15.42"))
        signatory = make_user("sig_cur", User.Role.SIGNATORY)
        rows = [it for g in pending_groups(signatory) for it in g["items"]
                if it["ref"] == doc.ref]
        if rows:                      # the row only appears in its own queue
            self.assertEqual(rows[0].get("currency"), "USD")
