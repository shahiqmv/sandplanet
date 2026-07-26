"""Procurement Schedule Phase 5 — value totals + committed-value display."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (CostHead, Document, ImportOrder, ImportOrderLine, Item,
                     Project, ScheduleLine, Site, SitePmHistory, Supplier, User)
from .tests import make_user


class ProcurementValuesTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pv_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa Upgrades", pm=self.pm)
        self.purch = make_user("pv_buy", User.Role.HO_PURCHASING)
        self.director = make_user("pv_dir", User.Role.DIRECTOR)
        self.se = make_user("pv_se", User.Role.SITE_ENGINEER, site=self.site)
        self.item = Item.objects.create(code="ITM-1", description="Pump",
                                        unit="nos")
        self.client = APIClient()

    def _line(self, **plan):
        self.client.force_authenticate(self.pm)
        self.pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        line_id = self.client.post(
            f"/api/v1/procurement-schedules/{self.pk}/lines",
            {"description": "Pump", "section_code": "A", "item_id": self.item.id,
             **plan}, format="json").data["lines"][0]["id"]
        self.client.post(f"/api/v1/procurement-schedules/{self.pk}/submit")
        self.client.force_authenticate(self.purch)
        self.client.patch(f"/api/v1/procurement-schedule-lines/{line_id}",
                          {"estimated_value": "900", "currency": "USD"},
                          format="json")
        self.client.post(f"/api/v1/procurement-schedules/{self.pk}/action",
                         {"action": "confirm"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/procurement-schedules/{self.pk}/action",
                         {"action": "sign_off"}, format="json")
        return ScheduleLine.objects.get(pk=line_id)

    def _linked_ipr_order(self, line, qty, price):
        ipr = Document.objects.create(
            doc_type="IPR", ref="IPR-HO-001", site=self.site,
            doc_date=date(2026, 8, 1), status="AUTHORISED", created_by=self.pm)
        supplier = Supplier.objects.create(
            name="AquaPure", category=Supplier.Category.values[0])
        cost_head = CostHead.objects.create(name="Imports")
        order = ImportOrder.objects.create(
            document=ipr, supplier=supplier, order_currency="USD",
            exchange_rate=Decimal("15.42"))
        ImportOrderLine.objects.create(
            order=order, line_no=1, item=self.item, order_qty=Decimal(qty),
            unit_price=Decimal(price), cost_head=cost_head)
        line.ipr = ipr
        line.save(update_fields=["ipr"])

    def _detail(self, user):
        self.client.force_authenticate(user)
        return self.client.get(
            f"/api/v1/procurement-schedules/{self.pk}").data

    def test_committed_and_variance_over(self):
        line = self._line()
        self._linked_ipr_order(line, "10", "100")   # committed 1000 vs est 900
        ln = self._detail(self.director)["lines"][0]
        self.assertEqual(Decimal(str(ln["committed"]["value"])),
                         Decimal("1000"))
        self.assertEqual(ln["committed"]["currency"], "USD")
        self.assertEqual(Decimal(str(ln["variance"])), Decimal("100"))  # over

    def test_committed_none_without_order(self):
        self._line()   # IPR not linked
        ln = self._detail(self.director)["lines"][0]
        self.assertIsNone(ln["committed"])
        self.assertIsNone(ln["variance"])

    def test_totals_sum_estimates(self):
        self._line()
        d = self._detail(self.director)
        self.assertEqual(str(d["totals"]["estimated"]), "900.00")
        self.assertEqual(d["totals"]["currency"], "USD")
        # section subtotal keyed by the line's section id
        sid = d["lines"][0]["section_id"]
        self.assertEqual(Decimal(str(d["totals"]["sections"][sid])),
                         Decimal("900"))

    def test_values_and_totals_hidden_from_site_engineer(self):
        self._line()
        d = self._detail(self.se)
        self.assertFalse(d["show_values"])
        self.assertIsNone(d["totals"])
        self.assertNotIn("committed", d["lines"][0])
        self.assertNotIn("estimated_value", d["lines"][0])
