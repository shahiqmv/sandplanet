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

    def test_a_live_voucher_blocks_the_schedule_with_a_reason(self):
        """Not a 500: name the voucher, because the fix is to deal with it."""
        self._line("INCLUDED")
        msg = ipr_svc.set_milestones(self.order, self._rows())
        self.assertIn("PV-SCH-001", msg)
        self.assertIn("Void or withdraw", msg)

    def test_a_paid_milestone_still_locks_the_schedule(self):
        self.m.status = "PAID"
        self.m.save(update_fields=["status"])
        self.assertIn("already paid",
                      ipr_svc.set_milestones(self.order, self._rows()))

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
