"""Procurement Schedule — splitting a line's order across several IPRs into
sibling sub-lines that share a bundle (owner 2026-08-04)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Item, Project, ScheduleLine, Site, SitePmHistory, User
from .tests import make_user


class ScheduleSplitTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("sp_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa Upgrades", pm=self.pm)
        self.purch = make_user("sp_buy", User.Role.HO_PURCHASING)
        self.eng = make_user("sp_eng", User.Role.SITE_ENGINEER, site=self.site)
        self.item = Item.objects.create(code="ITM-1", description="Heat pump",
                                        unit="nos")
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        self.line_id = self.client.post(
            f"/api/v1/procurement-schedules/{self.pk}/lines",
            {"description": "Pool heat pump", "section_code": "A",
             "item_id": self.item.id, "quantity": "100", "uom": "nos",
             "required_date": "2026-10-01"}, format="json").data["lines"][0]["id"]

    def _line(self):
        return ScheduleLine.objects.get(pk=self.line_id)

    def _split(self, quantities, as_user=None):
        self.client.force_authenticate(as_user or self.purch)
        return self.client.post(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/split",
            {"quantities": quantities}, format="json")

    def _sign_off(self):
        """Push the schedule through propose → confirm → sign off."""
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/procurement-schedules/{self.pk}/submit")
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{self.pk}/action",
                         {"action": "confirm"}, format="json")
        d = make_user("sp_dir", User.Role.DIRECTOR)
        self.client.force_authenticate(d)
        self.client.post(f"/api/v1/procurement-schedules/{self.pk}/action",
                         {"action": "sign_off"}, format="json")

    def test_split_divides_qty_value_and_shares_bundle(self):
        # give the line an estimate so the split divides value proportionally
        ScheduleLine.objects.filter(pk=self.line_id).update(
            estimated_value=Decimal("1000"), currency="USD")
        r = self._split(["60", "40"])
        self.assertEqual(r.status_code, 201, r.data)
        lines = ScheduleLine.objects.filter(schedule__document_id=self.pk)
        self.assertEqual(lines.count(), 2)
        qtys = sorted(str(x.quantity) for x in lines)
        self.assertEqual(qtys, ["40.00", "60.00"])
        # value split proportionally, sums back to the original
        self.assertEqual(sum(x.estimated_value for x in lines), Decimal("1000"))
        # both carry the same bundle → they roll up into one row
        labels = {x.bundle for x in lines}
        self.assertEqual(len(labels), 1)
        self.assertTrue(next(iter(labels)))
        # the two siblings sharing bundle + planned supplier collapse to 1 bundle
        # row in the schedule payload's grouped view
        d = self.client.get(f"/api/v1/procurement-schedules/{self.pk}").data
        bundle_rows = [row for rows in d["groups"].values()
                       for row in rows if row["kind"] == "bundle"]
        self.assertEqual(len(bundle_rows), 1)
        self.assertEqual(bundle_rows[0]["summary"]["count"], 2)

    def test_split_does_not_reopen_signed_off_schedule(self):
        self._sign_off()
        self.assertEqual(self._line().state, "SIGNED_OFF")
        r = self._split(["70", "30"])
        self.assertEqual(r.status_code, 201, r.data)
        # operational: the doc stays SIGNED_OFF and every sibling inherits it
        self.assertEqual(r.data["status"], "SIGNED_OFF")
        for ln in ScheduleLine.objects.filter(schedule__document_id=self.pk):
            self.assertEqual(ln.state, "SIGNED_OFF")

    def test_quantities_must_add_up(self):
        r = self._split(["60", "30"])          # 90 ≠ 100
        self.assertEqual(r.status_code, 400)
        self.assertIn("add up", r.data["detail"])

    def test_needs_two_positive_parts(self):
        self.assertEqual(self._split(["100"]).status_code, 400)      # only one
        self.assertEqual(self._split(["100", "0"]).status_code, 400)  # zero part

    def test_client_line_cannot_be_split(self):
        self.client.force_authenticate(self.pm)
        self.client.patch(f"/api/v1/procurement-schedule-lines/{self.line_id}",
                          {"supply_by": "CLIENT"}, format="json")
        r = self._split(["60", "40"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("contractor", r.data["detail"].lower())

    def test_site_engineer_can_split(self):
        # splitting is operational, like linking — SE (a proposer) may do it
        r = self._split(["60", "40"], as_user=self.eng)
        self.assertEqual(r.status_code, 201, r.data)

    def test_split_sibling_inherits_material_but_not_order_links(self):
        self._split(["60", "40"])
        sib = ScheduleLine.objects.filter(
            schedule__document_id=self.pk).exclude(pk=self.line_id).first()
        self.assertEqual(sib.description, "Pool heat pump")
        self.assertEqual(sib.item_id, self.item.id)
        self.assertEqual(sib.supply_by, "CONTRACTOR")
        self.assertIsNone(sib.ipr_id)      # each split gets its own IPR later
        self.assertIsNone(sib.grn_id)
