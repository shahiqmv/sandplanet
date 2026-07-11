"""Tools & Equipment register: GRN routing, faulty/repair cycle, DPR summary."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from . import procurement, tools
from .models import (Document, DocumentLine, DocumentRevision, Item,
                     ItemCategory, Site, StockMovement, ToolAsset, User)
from .tests import make_user


class ToolsBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE,
                                        start_date=date.today() - timedelta(days=5))
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        ItemCategory.objects.update_or_create(
            name="Tools & Equipment", defaults={"is_tool": True})
        ItemCategory.objects.update_or_create(
            name="Civil", defaults={"is_tool": False})
        self.drill = Item.objects.create(code="ITM-90005",
                                         description="Battery drill", unit="nos",
                                         category="Tools & Equipment",
                                         brand="Makita")
        self.cement = Item.objects.create(code="ITM-90001",
                                          description="Cement", unit="bag",
                                          category="Civil")
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    def verified_grn(self, lines):
        """Build a COUNTED GRN with the given (item, qty) lines and verify it."""
        grn = Document.objects.create(
            doc_type="GRN", site=self.site, doc_date=date.today(),
            status="COUNTED", ref="GRN-SJR-001", created_by=self.sa)
        rev = DocumentRevision.objects.create(document=grn, rev_label="R0",
                                              payload={}, created_by=self.sa)
        grn.current_revision = rev
        grn.save(update_fields=["current_revision"])
        for i, (item, qty) in enumerate(lines, 1):
            DocumentLine.objects.create(revision=rev, line_no=i, item=item,
                                        qty_manifest=qty, qty_received=qty)
        procurement.on_grn_verified(grn, self.sa)
        return grn


class ToolsRoutingTests(ToolsBase):
    def test_grn_tool_lines_go_to_register_not_stock(self):
        self.verified_grn([(self.drill, 3), (self.cement, 100)])
        # 3 drill assets on the register, none for cement
        self.assertEqual(ToolAsset.objects.filter(site=self.site).count(), 3)
        self.assertEqual(
            ToolAsset.objects.filter(name="Battery drill").count(), 3)
        # cement went to stock; the drill did NOT
        self.assertEqual(StockMovement.objects.filter(item=self.cement).count(),
                         1)
        self.assertFalse(StockMovement.objects.filter(item=self.drill).exists())
        a = ToolAsset.objects.filter(name="Battery drill").first()
        self.assertEqual(a.source, "GRN")
        self.assertEqual(a.brand, "Makita")

    def test_summary_groups_in_use_and_flags_down(self):
        self.verified_grn([(self.drill, 3)])
        assets = list(ToolAsset.objects.filter(name="Battery drill"))
        tools.set_state(assets[0], "FAULTY", "chuck broken", self.sa)
        rows = tools.summary(self.site)
        row = next(r for r in rows if r["item"] == "Battery drill")
        self.assertEqual(row["nos"], 2)                 # 2 still in use
        self.assertIn("1 faulty", row["remarks"])


class ToolsApiTests(ToolsBase):
    def test_add_edit_and_state_cycle(self):
        # manual add (mobilisation)
        r = self.client.post(f"/api/v1/tools/{self.site.id}", {
            "name": "Circular saw", "category": "Tools & Equipment",
            "serial_no": "CS-01"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        aid = r.data["id"]
        self.assertEqual(r.data["source"], "MOBILISATION")
        # edit details
        r = self.client.patch(f"/api/v1/tools/asset/{aid}",
                             {"model": "HS7601", "serial_no": "CS-02"},
                             format="json")
        self.assertEqual(r.data["model"], "HS7601")
        # faulty needs a note
        r = self.client.post(f"/api/v1/tools/asset/{aid}/state",
                             {"state": "FAULTY"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/tools/asset/{aid}/state",
                             {"state": "FAULTY", "note": "blade guard"},
                             format="json")
        self.assertEqual(r.data["state"], "FAULTY")
        # send for repair, then back to use
        self.client.post(f"/api/v1/tools/asset/{aid}/state",
                        {"state": "UNDER_REPAIR", "note": "sent to Male"},
                        format="json")
        r = self.client.post(f"/api/v1/tools/asset/{aid}/state",
                            {"state": "IN_USE", "note": "repaired"},
                            format="json")
        self.assertEqual(r.data["state"], "IN_USE")

    def test_register_lists_with_counts(self):
        self.verified_grn([(self.drill, 2)])
        r = self.client.get(f"/api/v1/tools/{self.site.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["tools"]), 2)
        self.assertEqual(r.data["counts"].get("IN_USE"), 2)
        self.assertTrue(r.data["can_manage"])
