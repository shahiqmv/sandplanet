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
            name="AquaPure", category=Supplier.Category.values[0],
            country="China")
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
        # the linked IPR's supplier + country surface on the row
        self.assertEqual(ln["ipr_supplier"], "AquaPure")
        self.assertEqual(ln["ipr_country"], "China")

    def test_committed_none_without_order(self):
        self._line()   # IPR not linked
        ln = self._detail(self.director)["lines"][0]
        self.assertIsNone(ln["committed"])
        self.assertIsNone(ln["variance"])
        self.assertEqual(ln["ipr_supplier"], "")

    def test_committed_falls_back_to_order_total_without_item_match(self):
        # a line whose item isn't on the order still shows the order's value
        line = self._line()
        line.item = None
        line.save(update_fields=["item"])
        self._linked_ipr_order(line, "10", "100")   # order total 1000
        ln = self._detail(self.director)["lines"][0]
        self.assertEqual(Decimal(str(ln["committed"]["value"])),
                         Decimal("1000"))
        self.assertEqual(ln["ipr_supplier"], "AquaPure")

    def test_shared_ipr_total_split_across_lines(self):
        # Two free-text lines (no item match) linked to ONE IPR order → the
        # order total is split across them, so a bundle doesn't 2x-count it.
        self.client.force_authenticate(self.pm)
        pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        self.client.post(f"/api/v1/procurement-schedules/{pk}/lines",
                         {"description": "Timber A", "section_code": "A"},
                         format="json")
        rows = self.client.post(
            f"/api/v1/procurement-schedules/{pk}/lines",
            {"description": "Timber B", "section_code": "A"},
            format="json").data["lines"]
        ids = [r["id"] for r in rows]
        ipr = Document.objects.create(
            doc_type="IPR", ref="IPR-HO-002", site=self.site,
            doc_date=date(2026, 8, 1), status="AUTHORISED", created_by=self.pm)
        supplier = Supplier.objects.create(
            name="Timberco", category=Supplier.Category.values[0],
            country="Malaysia")
        ch = CostHead.objects.create(name="Imports2")
        order = ImportOrder.objects.create(
            document=ipr, supplier=supplier, order_currency="USD",
            exchange_rate=Decimal("15.42"))
        ImportOrderLine.objects.create(
            order=order, line_no=1, item=self.item, order_qty=Decimal("10"),
            unit_price=Decimal("100"), cost_head=ch)          # order total 1000
        for lid in ids:
            ln = ScheduleLine.objects.get(pk=lid)
            ln.ipr = ipr; ln.item = None; ln.save(update_fields=["ipr", "item"])
        self.pk = pk
        d = self._detail(self.director)
        vals = sorted(Decimal(str(l["committed"]["value"])) for l in d["lines"])
        self.assertEqual(vals, [Decimal("500"), Decimal("500")])
        self.assertEqual(Decimal(str(d["totals"]["committed"])),
                         Decimal("1000"))                       # not 2000

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
