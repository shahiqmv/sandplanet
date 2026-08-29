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
from .procurement_pipeline import lead_legs, line_risk, order_by_date
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

    def test_the_order_by_date_works_backwards_from_the_required_date(self):
        """7 + 10 + 10 legs and the site buffer, counted back from 5 Oct."""
        line = self._line(required_date=date(2026, 10, 5), lead_time_days=7,
                          shipping_days=10, clearance_days=10)
        total = lead_legs(line)["total_days"]
        self.assertEqual(order_by_date(line),
                         date(2026, 10, 5) - timedelta(days=total))

    def test_no_required_date_means_no_order_by_date(self):
        self.assertIsNone(order_by_date(self._line(lead_time_days=7)))

    def test_client_supplied_lines_carry_no_order_date(self):
        line = self._line(required_date=date(2026, 10, 5),
                          supply_by="CLIENT")
        self.assertIsNone(order_by_date(line))

    def test_an_unordered_line_past_its_order_date_says_how_late(self):
        """The sentence a PM can still act on."""
        line = self._line(required_date=date.today() + timedelta(days=10),
                          lead_time_days=7, shipping_days=10,
                          clearance_days=10)
        risk = line_risk(line)
        self.assertGreater(risk["order_overdue_days"], 0)
        self.assertTrue(risk["unordered"])

    def test_a_line_with_time_in_hand_is_not_flagged(self):
        line = self._line(required_date=date.today() + timedelta(days=200),
                          lead_time_days=7, shipping_days=10,
                          clearance_days=10)
        self.assertEqual(line_risk(line)["order_overdue_days"], 0)

    def test_stated_shipping_days_override_the_country_guess(self):
        """A line that knows better than the table wins."""
        slow = self._line(required_date=date(2026, 12, 1), lead_time_days=25,
                          source_country="China")
        fast = self._line(required_date=date(2026, 12, 1), lead_time_days=25,
                          source_country="China", shipping_days=5)
        self.assertLess(order_by_date(slow), order_by_date(fast))

    def test_an_ordered_line_is_not_reported_as_order_overdue(self):
        from .models import Document
        ipr = Document.objects.create(
            doc_type="IPR", ref="IPR-PSX-001", site=self.site,
            doc_date=date.today(), status="AUTHORISED", created_by=self.user)
        line = self._line(required_date=date.today() + timedelta(days=5),
                          lead_time_days=30, ipr=ipr)
        self.assertEqual(line_risk(line)["order_overdue_days"], 0)
