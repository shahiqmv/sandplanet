"""One supplier directory for Purchasing and Trading (owner 2026-11-18)."""
from datetime import date

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from . import suppliers
from .models import AuditLog, Supplier, SupplierEvaluation, User
from .tests import make_user
from .trading import _tag_trading


def evaluation(s, user, start=date(2026, 1, 1)):
    return SupplierEvaluation.objects.create(
        supplier=s, period_start=start, period_end=date(2026, 6, 30),
        evaluated_by=user)


class NameMatchTests(TestCase):
    def test_company_form_words_do_not_tell_suppliers_apart(self):
        self.assertEqual(suppliers.norm("SFS Ventures India Pvt Ltd"),
                         suppliers.norm("SFS Ventures India Private Limited"))
        self.assertEqual(suppliers.norm("Kelani Cables"),
                         suppliers.norm("Kelani Cables PLC"))

    def test_similar_finds_the_copy_and_ignores_the_unrelated(self):
        kc = Supplier.objects.create(name="Kelani Cables PLC")
        Supplier.objects.create(name="Kelani Steel")
        Supplier.objects.create(name="Old Kelani Cables Ltd", is_active=False)
        self.assertEqual([s.id for s in suppliers.similar("Kelani Cables")],
                         [kc.id])
        # a short name does not match by containment
        Supplier.objects.create(name="ABC")
        self.assertEqual(suppliers.similar("ABC Trading House"), [])


class DirectoryApiTests(TestCase):
    def setUp(self):
        self.sales = make_user("sales1", User.Role.SALES)
        self.buyer = make_user("buy1", User.Role.HO_PURCHASING)
        self.c = APIClient()
        self.kc = Supplier.objects.create(
            name="Kelani Cables PLC", category="INTERNATIONAL",
            country="Sri Lanka")
        self.fwd = Supplier.objects.create(name="Spedito Express",
                                           category="FORWARDER")

    def test_trading_sees_the_whole_directory_but_not_forwarders(self):
        self.c.force_authenticate(self.sales)
        names = [s["name"] for s in self.c.get("/api/v1/trading/suppliers").data]
        self.assertIn("Kelani Cables PLC", names)
        self.assertNotIn("Spedito Express", names)
        self.assertEqual(
            self.c.get("/api/v1/trading/suppliers?trading=1").data, [])

    def test_a_near_copy_is_offered_back_and_can_be_adopted(self):
        self.c.force_authenticate(self.sales)
        r = self.c.post("/api/v1/trading/suppliers",
                        {"name": "Kelani Cables", "category": "INTERNATIONAL"},
                        format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["similar"][0]["id"], self.kc.id)
        r = self.c.post(f"/api/v1/trading/suppliers/{self.kc.id}/adopt")
        self.assertEqual(r.status_code, 200, r.data)
        self.kc.refresh_from_db()
        self.assertTrue(self.kc.is_trading)
        self.assertEqual(Supplier.objects.filter(
            name__icontains="kelani").count(), 1)

    def test_a_different_company_can_still_be_created(self):
        self.c.force_authenticate(self.sales)
        r = self.c.post("/api/v1/trading/suppliers",
                        {"name": "Kelani Cables", "category": "INTERNATIONAL",
                         "confirm_new": True}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Supplier.objects.get(name="Kelani Cables").is_trading)

    def test_purchasing_gets_the_same_check(self):
        self.c.force_authenticate(self.buyer)
        r = self.c.post("/api/v1/suppliers",
                        {"name": "KELANI CABLES (PVT) LTD",
                         "category": "INTERNATIONAL"}, format="json")
        self.assertEqual(r.status_code, 409)
        r = self.c.post("/api/v1/suppliers",
                        {"name": "KELANI CABLES (PVT) LTD",
                         "category": "INTERNATIONAL", "confirm_new": True},
                        format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_sales_keep_off_name_and_status_of_a_shared_supplier(self):
        evaluation(self.kc, self.buyer)          # Purchasing relies on it
        self.c.force_authenticate(self.sales)
        url = f"/api/v1/trading/suppliers/{self.kc.id}"
        self.assertTrue(self.c.get(url).data["shared"])
        r = self.c.patch(url, {"name": "Kelani"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.c.patch(url, {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.c.patch(url, {"phone": "+94 11 000"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.kc.refresh_from_db()
        self.assertEqual(self.kc.phone, "+94 11 000")
        self.assertTrue(self.kc.is_active)

    def test_sales_may_rename_a_supplier_only_trading_uses(self):
        own = Supplier.objects.create(name="Brintons Carpet Limted",
                                      category="INTERNATIONAL",
                                      is_trading=True)
        self.c.force_authenticate(self.sales)
        r = self.c.patch(f"/api/v1/trading/suppliers/{own.id}",
                         {"name": "Brintons Carpet Limited"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_a_supplier_picked_on_a_trading_line_is_tagged(self):
        _tag_trading({self.kc.id})
        self.kc.refresh_from_db()
        self.assertTrue(self.kc.is_trading)


class MergeTests(TestCase):
    def setUp(self):
        self.admin = make_user("adm", User.Role.ADMIN)
        self.keep = Supplier.objects.create(name="Kelani Cables PLC",
                                            category="INTERNATIONAL")
        self.copy = Supplier.objects.create(
            name="Kelani Cables", category="INTERNATIONAL", is_trading=True,
            phone="+94 11 222", email="sales@kelani.example")

    def test_merge_moves_the_records_fills_blanks_and_retires_the_copy(self):
        ev = evaluation(self.copy, self.admin)
        moved, err = suppliers.merge(self.copy, self.keep, self.admin,
                                     "same company")
        self.assertIsNone(err)
        self.assertEqual(moved, {"SupplierEvaluation.supplier": 1})
        ev.refresh_from_db()
        self.assertEqual(ev.supplier_id, self.keep.id)
        self.keep.refresh_from_db()
        self.copy.refresh_from_db()
        self.assertEqual(self.keep.phone, "+94 11 222")
        self.assertTrue(self.keep.is_trading)
        self.assertFalse(self.copy.is_active)
        self.assertFalse(self.copy.is_trading)
        self.assertIn(f"Merged into #{self.keep.id}", self.copy.notes)
        self.assertEqual(suppliers.usage(self.copy), {})
        self.assertTrue(AuditLog.objects.filter(
            entity="supplier", entity_id=self.keep.id,
            event="SUPPLIER_MERGED").exists())

    def test_a_clash_refuses_the_whole_merge(self):
        evaluation(self.copy, self.admin)
        evaluation(self.keep, self.admin)        # same period on both
        moved, err = suppliers.merge(self.copy, self.keep, self.admin)
        self.assertIsNone(moved)
        self.assertIn("clash", err)
        self.copy.refresh_from_db()
        self.assertTrue(self.copy.is_active)

    def test_the_command_is_a_dry_run_unless_told_to_commit(self):
        call_command("merge_supplier", "--from", str(self.copy.id),
                     "--into", str(self.keep.id), "--actor", "adm")
        self.copy.refresh_from_db()
        self.assertTrue(self.copy.is_active)
        call_command("merge_supplier", "--from", str(self.copy.id),
                     "--into", str(self.keep.id), "--actor", "adm",
                     "--commit")
        self.copy.refresh_from_db()
        self.assertFalse(self.copy.is_active)
