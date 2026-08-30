"""Country and lead times belong to whoever plans the schedule.

They were commercial fields, gated on role Purchasing AND status Submitted.
The effect on a DRAFT schedule — which is every schedule being planned — was
that nobody at all could enter a source country or a lead time, so the
order-by date those legs feed could never be worked out (owner 2026-08-30:
"i dont see country ... neither i see order by field or lead time field").
"""
from datetime import date

from django.test import TestCase

from .models import Document, Project, ProcurementSchedule, Site, User
from .procurement_pipeline import suggested_order_by
from .procurement_schedule import add_line, update_line
from .tests import make_user


class PlannerOwnsLeadTimesTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="LDT", name="Lead time site",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_ldt", User.Role.PM, site=self.site)
        self.buyer = make_user("buy_ldt", User.Role.HO_PURCHASING)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE")
        doc = Document.objects.create(doc_type="PSC", ref="PSC-LDT-001",
                                      site=self.site, project=self.project,
                                      status="DRAFT", doc_date=date.today(),
                                      created_by=self.pm)
        self.sched = ProcurementSchedule.objects.create(document=doc,
                                                        project=self.project)

    def _add(self, **extra):
        data = {"description": "Panel Board", "section_code": "A",
                "section_title": "Electrical"}
        data.update(extra)
        line, msg = add_line(self.sched, data, self.pm)
        self.assertIsNone(msg, msg)
        return line

    def test_the_planner_can_set_country_and_the_three_legs(self):
        line = self._add(source_country="India", lead_time_days=7,
                         shipping_days=10, clearance_days=10,
                         required_date="2026-10-05")
        line.refresh_from_db()
        self.assertEqual(line.source_country, "India")
        self.assertEqual(line.lead_time_days, 7)
        self.assertEqual(line.shipping_days, 10)
        self.assertEqual(line.clearance_days, 10)

    def test_the_planner_can_edit_them_afterwards(self):
        line = self._add()
        msg = update_line(line, {"source_country": "Sri Lanka",
                                 "lead_time_days": 21, "shipping_days": 14,
                                 "clearance_days": 10,
                                 "order_by_date": "2026-09-01"}, self.pm)
        self.assertIsNone(msg, msg)
        line.refresh_from_db()
        self.assertEqual(line.source_country, "Sri Lanka")
        self.assertEqual(line.lead_time_days, 21)
        self.assertEqual(line.order_by_date, date(2026, 9, 1))

    def test_the_legs_a_planner_enters_produce_a_suggestion(self):
        """The whole point of the three legs: 5 Oct minus 7+10+10 plus the
        5-day site buffer."""
        line = self._add(lead_time_days=7, shipping_days=10,
                         clearance_days=10, required_date="2026-10-05")
        line.refresh_from_db()
        self.assertEqual(suggested_order_by(line), date(2026, 9, 3))

    def test_purchasing_can_still_refine_them_on_a_submitted_schedule(self):
        """A supplier's quote is where the real lead time turns up."""
        line = self._add(lead_time_days=7, shipping_days=10,
                         clearance_days=10, required_date="2026-10-05")
        self.sched.document.status = "SUBMITTED"
        self.sched.document.save(update_fields=["status"])
        msg = update_line(line, {"lead_time_days": 45,
                                 "source_country": "Germany",
                                 "planned_supplier": "Hager"}, self.buyer)
        self.assertIsNone(msg, msg)
        line.refresh_from_db()
        self.assertEqual(line.lead_time_days, 45)
        self.assertEqual(line.planned_supplier, "Hager")
        # Country must still land from this side — moving it wholesale to the
        # planning form would have dropped Purchasing's edit in silence.
        self.assertEqual(line.source_country, "Germany")
        # ...and the suggestion moves with it: 5 Oct less 45+10+10 and the
        # 5-day site buffer is 70 days back.
        self.assertEqual(suggested_order_by(line), date(2026, 7, 27))

    def test_no_suggestion_until_all_three_legs_are_stated(self):
        """A country guess must never dress itself up as a deadline."""
        line = self._add(source_country="China", lead_time_days=7,
                         required_date="2026-10-05")
        line.refresh_from_db()
        self.assertIsNone(suggested_order_by(line))
