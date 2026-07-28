"""Procurement Schedule — raise an IPR from the awarded BOQ quote."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (CostHead, ImportOrder, Item, Project, ScheduleLine, Site,
                     SitePmHistory, Supplier, User)
from .tests import make_user


class ProcurementIprTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pi_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa Upgrades", pm=self.pm)
        self.purch = make_user("pi_buy", User.Role.HO_PURCHASING)
        self.item = Item.objects.create(code="ITM-1", description="Pump",
                                        unit="nos")
        CostHead.objects.get_or_create(name="Imports (test)",
                                       defaults={"is_pool": False})
        self.client = APIClient()

    def _line(self, quantity="10"):
        self.client.force_authenticate(self.pm)
        self.pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        lid = self.client.post(
            f"/api/v1/procurement-schedules/{self.pk}/lines",
            {"description": "Pump", "section_code": "A",
             "item_id": self.item.id, "quantity": quantity},
            format="json").data["lines"][0]["id"]
        return ScheduleLine.objects.get(pk=lid)

    def _quote(self, line, value="1000"):
        self.client.force_authenticate(self.purch)
        self.client.post(
            f"/api/v1/procurement-schedule-lines/{line.id}/quotes",
            {"supplier_name": "AquaPure", "country": "China",
             "quoted_value": value, "currency": "USD"}, format="multipart")
        return line.quotes.first()

    def _award(self, line, quote):
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedule-lines/{line.id}/award",
                         {"action": "quote", "quote_id": quote.id},
                         format="json")

    def test_raise_ipr_from_awarded_quote(self):
        line = self._line(quantity="10")
        q = self._quote(line, value="1000")
        self._award(line, q)
        r = self.client.post(
            f"/api/v1/procurement-schedule-lines/{line.id}/raise-ipr")
        self.assertEqual(r.status_code, 200, r.data)
        ref = r.data["raised_ipr"]
        self.assertTrue(ref.startswith("IPR"), ref)
        line.refresh_from_db()
        self.assertEqual(line.ipr.ref, ref)
        self.assertEqual(line.ipr.status, "DRAFT")
        # supplier registered as an international one
        s = Supplier.objects.get(name="AquaPure")
        self.assertEqual(s.category, "INTERNATIONAL")
        # one order line pre-filled from the line + quote
        order = ImportOrder.objects.get(document=line.ipr)
        self.assertEqual(order.supplier_id, s.id)
        oline = order.lines.get()
        self.assertEqual(oline.item_id, self.item.id)
        self.assertEqual(oline.order_qty, 10)
        self.assertEqual(oline.unit_price, 100)          # 1000 / 10
        self.assertEqual(oline.allocations.get().project_id, self.project.id)

    def test_cannot_raise_without_award(self):
        line = self._line()
        self._quote(line)                     # captured but not awarded
        self.client.force_authenticate(self.purch)
        r = self.client.post(
            f"/api/v1/procurement-schedule-lines/{line.id}/raise-ipr")
        self.assertEqual(r.status_code, 400)

    def test_cannot_raise_twice(self):
        line = self._line()
        q = self._quote(line)
        self._award(line, q)
        self.client.force_authenticate(self.purch)
        self.client.post(
            f"/api/v1/procurement-schedule-lines/{line.id}/raise-ipr")
        r = self.client.post(
            f"/api/v1/procurement-schedule-lines/{line.id}/raise-ipr")
        self.assertEqual(r.status_code, 400)      # already linked

    def test_proposer_cannot_raise(self):
        line = self._line()
        q = self._quote(line)
        self._award(line, q)
        self.client.force_authenticate(self.pm)   # PM is not an award role
        r = self.client.post(
            f"/api/v1/procurement-schedule-lines/{line.id}/raise-ipr")
        self.assertEqual(r.status_code, 400)
