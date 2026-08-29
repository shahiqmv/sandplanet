"""The three lead-time legs, and the date an order must go out.

Adopted from a PM's own hand-made schedule (Soneva Fushi casual accommodation,
2026-08-29). Their sheet splits manufacturing / shipping / customs and carries
a PO-issue-date column; ours had one lead-time number, a per-country shipping
guess buried in code, and answered only "will it be late?" — never "when must
I act?"."""
from datetime import date, timedelta

from django.test import TestCase

from .models import (Project, ProcurementSchedule, ScheduleLine,
                     ScheduleSection, Site, User)
from .procurement_pipeline import (lead_legs, line_risk,
                                   suggested_order_by)
from .tests import make_user


class LeadLegTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="PSX", name="Schedule site",
                                        status=Site.Status.ACTIVE)
        self.user = make_user("pm_psx", User.Role.PM, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Casual accommodation",
            status="ACTIVE")
        from .models import Document, DocumentRevision
        doc = Document.objects.create(
            doc_type="PSC", ref="PSC-PSX-001", site=self.site,
            project=self.project, doc_date=date.today(), status="DRAFT",
            created_by=self.user)
        DocumentRevision.objects.create(document=doc, rev_label="R0",
                                        created_by=self.user, payload={})
        self.sched = ProcurementSchedule.objects.create(
            document=doc, project=self.project)
        self.section = ScheduleSection.objects.create(
            schedule=self.sched, code="B", title="Electrical")

    def _line(self, **kw):
        base = dict(schedule=self.sched, section=self.section, s_no=1,
                    description="Panel Board", source_country="India",
                    supply_by="CONTRACTOR")
        base.update(kw)
        return ScheduleLine.objects.create(**base)

    def test_the_three_legs_are_kept_apart(self):
        line = self._line(lead_time_days=7, shipping_days=10,
                          clearance_days=10)
        legs = lead_legs(line)
        self.assertEqual(legs["manufacture_days"], 7)
        self.assertEqual(legs["shipping_days"], 10)
        self.assertEqual(legs["clearance_days"], 10)
        self.assertFalse(legs["shipping_assumed"])
        self.assertFalse(legs["clearance_assumed"])

    def test_an_unstated_leg_falls_back_and_says_so(self):
        """The per-country figure is a guess made in code and is flagged as
        one, rather than passing for something the PM entered."""
        line = self._line(lead_time_days=25)
        legs = lead_legs(line)
        self.assertEqual(legs["shipping_days"], 21)     # India
        self.assertTrue(legs["shipping_assumed"])
        self.assertTrue(legs["clearance_assumed"])

    def test_the_order_by_date_is_the_pms_own(self):
        """Nothing computes it. Product type, season, a war on the lane and
        the state of the port all move it, and none of that is knowable from
        here (owner 2026-08-29)."""
        line = self._line(required_date=date(2026, 10, 5),
                          order_by_date=date(2026, 7, 1))
        self.assertEqual(line_risk(line)["order_by"], date(2026, 7, 1))

    def test_the_suggestion_needs_all_three_legs_stated(self):
        """A country-table guess must never produce a deadline."""
        self.assertIsNone(suggested_order_by(
            self._line(required_date=date(2026, 10, 5), lead_time_days=7)))
        full = self._line(required_date=date(2026, 10, 5), lead_time_days=7,
                          shipping_days=10, clearance_days=10)
        self.assertEqual(suggested_order_by(full),
                         date(2026, 10, 5) - timedelta(days=7 + 10 + 10 + 5))

    def test_no_required_date_means_no_suggestion(self):
        self.assertIsNone(suggested_order_by(
            self._line(lead_time_days=7, shipping_days=10,
                       clearance_days=10)))

    def test_client_supplied_lines_get_no_suggestion(self):
        self.assertIsNone(suggested_order_by(
            self._line(required_date=date(2026, 10, 5), supply_by="CLIENT",
                       lead_time_days=7, shipping_days=10,
                       clearance_days=10)))

    def test_an_unordered_line_past_the_pms_date_says_how_late(self):
        """The sentence a PM can still act on — counted off their own date."""
        line = self._line(required_date=date.today() + timedelta(days=60),
                          order_by_date=date.today() - timedelta(days=12))
        risk = line_risk(line)
        self.assertEqual(risk["order_overdue_days"], 12)
        self.assertTrue(risk["unordered"])

    def test_a_line_with_time_in_hand_is_not_flagged(self):
        line = self._line(required_date=date.today() + timedelta(days=200),
                          order_by_date=date.today() + timedelta(days=30))
        self.assertEqual(line_risk(line)["order_overdue_days"], 0)

    def test_a_line_with_no_order_date_is_never_flagged(self):
        """Silence beats a made-up deadline."""
        line = self._line(required_date=date.today() + timedelta(days=5),
                          lead_time_days=90)
        self.assertEqual(line_risk(line)["order_overdue_days"], 0)
        self.assertIsNone(line_risk(line)["order_by"])

    def test_an_ordered_line_is_not_reported_as_order_overdue(self):
        from .models import Document
        ipr = Document.objects.create(
            doc_type="IPR", ref="IPR-PSX-001", site=self.site,
            doc_date=date.today(), status="AUTHORISED", created_by=self.user)
        line = self._line(required_date=date.today() + timedelta(days=5),
                          order_by_date=date.today() - timedelta(days=40),
                          ipr=ipr)
        self.assertEqual(line_risk(line)["order_overdue_days"], 0)
