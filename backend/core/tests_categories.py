"""Controlled item & worker categories (owner, 2026-07-08)."""
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Employee, Item, ItemCategory, ManpowerCategory, User
from .tests import make_user


class ItemCategoryTests(TestCase):
    def setUp(self):
        self.purchasing = make_user("pur", User.Role.HO_PURCHASING)
        self.se = make_user("se1", User.Role.SITE_ENGINEER)
        self.client = APIClient()
        # "Civil" and the other defaults are already seeded by migration 0014

    def test_defaults_seeded(self):
        # migration seeds a starter list
        self.assertTrue(ItemCategory.objects.filter(name="MEP").exists())

    def test_purchasing_manages_only(self):
        self.client.force_authenticate(self.se)
        r = self.client.post("/api/v1/item-categories", {"name": "Marine X"},
                             format="json")
        self.assertEqual(r.status_code, 403)
        self.client.force_authenticate(self.purchasing)
        r = self.client.post("/api/v1/item-categories", {"name": "Marine X"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_item_category_must_be_known(self):
        self.client.force_authenticate(self.purchasing)
        r = self.client.post("/api/v1/items", {
            "description": "Cement OPC", "unit": "bag",
            "category": "Nonsense"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not a known item category", str(r.data))
        r = self.client.post("/api/v1/items", {
            "description": "Cement OPC", "unit": "bag",
            "category": "Civil"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_delete_used_category_deactivates(self):
        self.client.force_authenticate(self.purchasing)
        cat = ItemCategory.objects.get(name="Finishes")
        Item.objects.create(code="ITM-9001", description="Tile",
                            unit="m2", category="Finishes")
        r = self.client.delete(f"/api/v1/item-categories/{cat.id}")
        self.assertEqual(r.status_code, 204)
        cat.refresh_from_db()
        self.assertFalse(cat.is_active)  # kept, deactivated


class WorkerCategoryTests(TestCase):
    def setUp(self):
        self.admin = make_user("adm", User.Role.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_admin_crud_and_used_deactivates(self):
        r = self.client.post("/api/v1/manpower-categories", {
            "list_type": "DPR", "grp": "LABOUR", "name": "Diver",
            "sort_order": 50}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        cat_id = r.data["id"]
        # unused: deletes outright
        r = self.client.delete(f"/api/v1/manpower-categories/{cat_id}")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(ManpowerCategory.objects.filter(id=cat_id).exists())
        # used by an employee: deactivates instead
        cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Rigger", sort_order=51)
        Employee.objects.create(emp_no="EMP-7001", full_name="X",
                                job_category=cat)
        r = self.client.delete(f"/api/v1/manpower-categories/{cat.id}")
        self.assertEqual(r.status_code, 204)
        cat.refresh_from_db()
        self.assertFalse(cat.is_active)
