"""Closing a procurement line that no document will close, and reading a
consignment that is at customs.

Both from the same schedule (owner 2026-08-31, BAO-LI Fish Pond): the HDPE
liner arrived and was installed before the import module existed, so nothing
can ever link to it; and the galvanized bridge sat at "Shipped" while its
shipment was UNDER_CLEARING.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import procurement_pipeline as pp
from .models import (Document, ImportOrder, ImportShipment, ProcurementSchedule,
                     Project, ScheduleLine, Site, User)
from .tests import make_user


class LineStageTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="PSD", name="Psc site",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(
            site=self.site, code="FP", title="Fish Pond", status="ACTIVE")
        doc = Document.objects.create(doc_type="PSC", ref="PSC-PSD-001",
                                      site=self.site, project=self.project,
                                      status="DRAFT", doc_date=date.today(),
                                      created_by=make_user("mk", User.Role.PM,
                                                           site=self.site))
        self.sched = ProcurementSchedule.objects.create(document=doc,
                                                        project=self.project)
        self.buyer = make_user("buy_psd", User.Role.HO_PURCHASING)
        from .models import Supplier
        self.supplier = Supplier.objects.create(name="Acme Ltd")
        self.pm = make_user("pm_psd", User.Role.PM, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.buyer)

    def _line(self, **kw):
        return ScheduleLine.objects.create(schedule=self.sched, s_no=1,
                                           description="Thing", **kw)

    def _shipped_line(self, status):
        ipr = Document.objects.create(doc_type="IPR", ref=f"IPR-{status[:3]}",
                                      site=self.site, status="AUTHORISED",
                                      doc_date=date.today(),
                                      created_by=self.buyer)
        order = ImportOrder.objects.create(
            document=ipr, supplier=self.supplier,
            exchange_rate=Decimal("15.42"))
        ImportShipment.objects.create(order=order, seq=1,
                                      status=status)
        return self._line(ipr=ipr)

    # ---- a consignment at customs ---------------------------------------

    def test_a_shipment_being_cleared_reads_as_clearing_not_shipped(self):
        """It has plainly landed — the agent is at customs with it."""
        line = self._shipped_line("UNDER_CLEARING")
        self.assertEqual(pp.line_stage(line)["label"], "Clearing")

    def test_a_cleared_shipment_says_so(self):
        line = self._shipped_line("CLEARED")
        self.assertEqual(pp.line_stage(line)["label"], "Cleared")

    def test_an_arrived_shipment_says_so(self):
        line = self._shipped_line("ARRIVED")
        self.assertEqual(pp.line_stage(line)["label"], "Arrived")

    def test_one_still_at_sea_is_shipped(self):
        for st in ("BOOKED", "SHIPPED", "IN_TRANSIT"):
            self.assertEqual(pp.line_stage(self._shipped_line(st))["label"],
                             "Shipped")

    # ---- closing a line by hand -----------------------------------------

    def test_a_line_can_be_marked_received_without_a_grn(self):
        line = self._line(production_status="COMPLETED",
                          required_date=date(2026, 8, 10))
        self.assertEqual(pp.line_stage(line)["label"], "Produced")
        msg = pp.set_delivered(line, "2026-08-05", "Installed before the "
                               "import module existed", self.buyer)
        self.assertIsNone(msg, msg)
        line.refresh_from_db()
        self.assertEqual(pp.line_stage(line)["label"], "Delivered")
        self.assertEqual(line.delivered_by, self.buyer)

    def test_marking_it_received_clears_the_late_flag(self):
        """A line nobody can close flags Late forever."""
        line = self._line(production_status="COMPLETED",
                          required_date=date(2026, 8, 10))
        self.assertEqual(pp.line_risk(line)["level"], "LATE")
        pp.set_delivered(line, "2026-08-05", "Installed on site", self.buyer)
        line.refresh_from_db()
        self.assertEqual(pp.line_risk(line)["level"], "DELIVERED")

    def test_a_note_is_required(self):
        """The one stage with no document behind it should say on what
        basis it was asserted."""
        line = self._line()
        msg = pp.set_delivered(line, "2026-08-05", "", self.buyer)
        self.assertIn("Say how this was received", msg)
        line.refresh_from_db()
        self.assertIsNone(line.delivered_on)

    def test_a_future_date_is_refused(self):
        line = self._line()
        ahead = (timezone.localdate() + timedelta(days=3)).isoformat()
        self.assertIn("future", pp.set_delivered(line, ahead, "x", self.buyer))

    def test_a_line_with_a_grn_is_not_closed_by_hand(self):
        """Its delivery comes from the receipt, which is the better record."""
        grn = Document.objects.create(doc_type="GRN", ref="GRN-PSD-001",
                                      site=self.site, status="COMPLETE",
                                      doc_date=date.today(),
                                      created_by=self.buyer)
        line = self._line(grn=grn)
        self.assertIn("has a GRN",
                      pp.set_delivered(line, "2026-08-05", "x", self.buyer))

    def test_it_can_be_reopened(self):
        line = self._line(production_status="COMPLETED")
        pp.set_delivered(line, "2026-08-05", "Installed", self.buyer)
        self.assertIsNone(pp.set_delivered(line, None, "", self.buyer))
        line.refresh_from_db()
        self.assertIsNone(line.delivered_on)
        self.assertEqual(pp.line_stage(line)["label"], "Produced")

    def test_the_endpoint_marks_it(self):
        line = self._line(production_status="COMPLETED")
        r = self.client.post(
            f"/api/v1/procurement-schedule-lines/{line.id}/delivered",
            {"on": "2026-08-05", "note": "Installed before IPRs existed"},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        line.refresh_from_db()
        self.assertEqual(line.delivered_on, date(2026, 8, 5))

    def test_a_role_that_cannot_plan_cannot_close_a_line(self):
        line = self._line()
        outsider = make_user("fin_psd", User.Role.FINANCE)
        self.assertIn("Not permitted",
                      pp.set_delivered(line, "2026-08-05", "x", outsider))
