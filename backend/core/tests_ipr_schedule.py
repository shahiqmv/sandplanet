"""Changing an import order's payment schedule after a voucher has touched it.

A voided voucher kept holding the milestone its line pointed at, and that FK
is PROTECT — so replacing the schedule, which deletes its rows, could not run
and gave no reason. Only APPROVED lines were unwound on void, so a line on a
voucher voided before approval held on for good (owner 2026-08-31, IPR-047).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from . import imports as ipr_svc
from . import vouchers
from .models import (Document, ImportOrder, ImportPaymentMilestone,
                     PaymentVoucherLine, Site, Supplier, User)
from .tests import make_user


class ScheduleAfterAVoucherTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SCH", name="Sch site",
                                        status=Site.Status.ACTIVE)
        self.buyer = make_user("buy_sch", User.Role.HO_PURCHASING)
        self.fin = make_user("fin_sch", User.Role.FINANCE)
        self.supplier = Supplier.objects.create(name="Overseas Ltd")
        self.ipr = Document.objects.create(
            doc_type="IPR", ref="IPR-SCH-001", status="AUTHORISED",
            site=self.site, doc_date=date(2026, 8, 1),
            created_by=self.buyer)
        self.order = ImportOrder.objects.create(
            document=self.ipr, supplier=self.supplier,
            exchange_rate=Decimal("15.42"))
        self.m = ImportPaymentMilestone.objects.create(
            order=self.order, seq=1, label="Advance 30%", trigger="ADVANCE",
            percent=Decimal("100"), status="DUE")
        self.pv = Document.objects.create(
            doc_type="PV", ref="PV-SCH-001", status="SUBMITTED",
            site=self.site, doc_date=date(2026, 8, 10),
            created_by=self.fin)

    def _line(self, status="INCLUDED"):
        return PaymentVoucherLine.objects.create(
            voucher=self.pv, source_milestone=self.m, amount=Decimal("100"),
            currency="USD", status=status)

    def _rows(self):
        return [{"label": "Advance 50%", "trigger": "ADVANCE",
                 "percent": "50"},
                {"label": "Balance 50%", "trigger": "BALANCE",
                 "percent": "50"}]

    # ---- the bug ---------------------------------------------------------

    def test_voiding_releases_a_line_that_was_never_approved(self):
        """The exact case: the voucher was voided while still SUBMITTED, so
        its line was INCLUDED and the old code skipped it."""
        line = self._line("INCLUDED")
        self.assertIsNone(vouchers.void_voucher(self.pv, self.fin, "wrong "
                                                "amount"))
        line.refresh_from_db()
        self.assertIsNone(line.source_milestone_id)
        self.assertIn("IPR-SCH-001", line.source_note)
        self.assertIn("Advance 30%", line.source_note)

    def test_the_schedule_can_then_be_changed(self):
        self._line("INCLUDED")
        vouchers.void_voucher(self.pv, self.fin, "wrong amount")
        self.assertIsNone(ipr_svc.set_milestones(self.order, self._rows()))
        self.assertEqual(
            sorted(self.order.milestones.values_list("label", flat=True)),
            ["Advance 50%", "Balance 50%"])

    def test_an_approved_line_is_released_and_the_milestone_reset(self):
        line = self._line("APPROVED")
        self.m.status = "AUTHORISED"
        self.m.save(update_fields=["status"])
        vouchers.void_voucher(self.pv, self.fin, "wrong supplier")
        line.refresh_from_db()
        self.m.refresh_from_db()
        self.assertIsNone(line.source_milestone_id)
        self.assertEqual(self.m.status, "DUE")

    # ---- the guard -------------------------------------------------------

    def _priced(self):
        """A 1,000 order whose whole schedule is one fixed 1,000 row."""
        self.order.misc_fee = Decimal("1000")
        self.order.save(update_fields=["misc_fee"])
        self.m.percent, self.m.fixed_amount = None, Decimal("1000")
        self.m.save(update_fields=["percent", "fixed_amount"])

    def test_a_vouchered_row_stays_and_a_wrong_sum_names_the_voucher(self):
        """Not a 500: name the voucher, because that row needs it dealt with."""
        self._priced()
        self._line("INCLUDED")
        msg = ipr_svc.set_milestones(self.order, self._rows())
        self.assertIn("must sum", msg)
        self.assertIn("PV-SCH-001", msg)
        self.assertIn("void or withdraw", msg)
        self.assertEqual(list(self.order.milestones.all()), [self.m])

    def test_a_row_can_be_added_beside_a_vouchered_one(self):
        """IPR-087: the advance is on a voucher, and freight came after."""
        self._priced()
        self._line("INCLUDED")
        self.order.misc_fee = Decimal("1254")
        self.order.save(update_fields=["misc_fee"])
        self.assertIsNone(ipr_svc.set_milestones(self.order, [
            {"label": "Freight", "trigger": "BALANCE", "fixed_amount": "254"}]))
        self.assertEqual(
            list(self.order.milestones.values_list("seq", "label")),
            [(1, "Advance 30%"), (2, "Freight")])

    def test_a_paid_row_stays_and_the_rest_can_be_redrawn(self):
        self._priced()
        self.m.status = "PAID"
        self.m.save(update_fields=["status"])
        self.order.misc_fee = Decimal("1100")
        self.order.save(update_fields=["misc_fee"])
        self.assertIsNone(ipr_svc.set_milestones(self.order, [
            {"label": "Extra", "trigger": "BALANCE", "fixed_amount": "100"}]))
        self.assertIsNone(ipr_svc.set_milestones(self.order, [
            {"label": "Extra A", "trigger": "BALANCE", "fixed_amount": "60"},
            {"label": "Extra B", "trigger": "BALANCE", "fixed_amount": "40"}]))
        self.assertEqual(
            list(self.order.milestones.values_list("label", "status")),
            [("Advance 30%", "PAID"), ("Extra A", "PENDING"),
             ("Extra B", "PENDING")])

    def test_with_nothing_holding_it_the_schedule_just_changes(self):
        self.assertIsNone(ipr_svc.set_milestones(self.order, self._rows()))
        self.assertEqual(self.order.milestones.count(), 2)

    def test_the_cleanup_releases_a_voucher_voided_before_the_fix(self):
        """Vouchers voided under the old code still hold their milestone,
        and nothing will run their void path again."""
        from io import StringIO

        from django.core.management import call_command

        line = self._line("INCLUDED")
        # Void it the way the old code did: the flag, and nothing released.
        Document.objects.filter(pk=self.pv.pk).update(is_void=True)
        self.assertIsNotNone(line.source_milestone_id)

        out = StringIO()
        call_command("release_voided_milestones", stdout=out)
        line.refresh_from_db()
        self.assertIsNone(line.source_milestone_id)
        self.assertIn("IPR-SCH-001", line.source_note)
        self.assertIsNone(ipr_svc.set_milestones(self.order, self._rows()))

    def test_the_cleanup_leaves_live_vouchers_alone(self):
        line = self._line("INCLUDED")
        from io import StringIO

        from django.core.management import call_command

        call_command("release_voided_milestones", stdout=StringIO())
        line.refresh_from_db()
        self.assertIsNotNone(line.source_milestone_id)
