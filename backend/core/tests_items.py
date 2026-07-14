"""Item enhancements (Phase 1B): major-material flag + item photo, and the
photo/flag surfacing on document (MR) lines."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Item, User
from .tests import make_user

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
       b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


class ItemFieldTests(TestCase):
    def setUp(self):
        self.purchasing = make_user("hop", User.Role.HO_PURCHASING)
        self.item = Item.objects.create(code="ITM-90001",
                                        description="Cement OPC 50kg",
                                        unit="bag", category="Civil")
        self.client = APIClient()
        self.client.force_authenticate(self.purchasing)

    def test_toggle_major(self):
        r = self.client.patch(f"/api/v1/items/{self.item.id}",
                              {"is_major": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["is_major"])
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_major)

    def test_purchasing_edits_item_details(self):
        """Purchasing corrects site-entered mistakes (owner 2026-07-14)."""
        from .models import ItemCategory

        ItemCategory.objects.get_or_create(name="Structural",
                                           defaults={"is_active": True})
        r = self.client.patch(f"/api/v1/items/{self.item.id}", {
            "description": "Cement OPC 50kg bag", "unit": "bags",
            "category": "Structural", "brand": "Lafarge",
            "spec_ref": "ASTM C150"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.description, "Cement OPC 50kg bag")
        self.assertEqual(self.item.unit, "bags")
        self.assertEqual(self.item.category, "Structural")
        self.assertEqual(self.item.brand, "Lafarge")
        self.assertEqual(self.item.spec_ref, "ASTM C150")

    def test_site_team_adds_item_directly(self):
        # Approval gate is off for now — site-created items are not provisional
        sa = make_user("sa9", User.Role.SITE_ADMIN)
        self.client.force_authenticate(sa)
        r = self.client.post("/api/v1/items",
                             {"description": "New Chemical Anchor 12mm",
                              "unit": "nos"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["is_provisional"])
        self.assertTrue(r.data["code"].startswith("ITM-"))

    def test_site_team_cannot_edit_existing_item(self):
        sa = make_user("sa8", User.Role.SITE_ADMIN)
        self.client.force_authenticate(sa)
        r = self.client.patch(f"/api/v1/items/{self.item.id}",
                              {"description": "hacked"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_ho_approves_provisional_item(self):
        prov = Item.objects.create(code="ITM-90099", description="Site Item",
                                   unit="nos", is_provisional=True)
        r = self.client.post(f"/api/v1/items/{prov.id}/approve")
        self.assertEqual(r.status_code, 200, r.data)
        prov.refresh_from_db()
        self.assertFalse(prov.is_provisional)

    def test_upload_photo_returns_url(self):
        with override_settings(MEDIA_ROOT="test-media"):
            photo = SimpleUploadedFile("cement.png", PNG,
                                       content_type="image/png")
            r = self.client.patch(f"/api/v1/items/{self.item.id}",
                                  {"photo": photo}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["photo_url"])
        self.item.refresh_from_db()
        self.assertTrue(self.item.photo)

    def test_photo_and_major_appear_on_mr_line(self):
        from datetime import date, timedelta

        from .models import Site, SitePmHistory
        site = Site.objects.create(code="SJR", name="Soneva Jani",
                                   status=Site.Status.ACTIVE,
                                   start_date=date.today() - timedelta(days=5))
        sa = make_user("sa", User.Role.SITE_ADMIN, site=site)
        pm = make_user("pm", User.Role.PM, site=site)
        SitePmHistory.objects.create(site=site, pm_user=pm,
                                     from_date=date.today())
        self.item.is_major = True
        with override_settings(MEDIA_ROOT="test-media"):
            self.item.photo = SimpleUploadedFile("c.png", PNG,
                                                 content_type="image/png")
            self.item.save()

            self.client.force_authenticate(sa)
            mr = self.client.post("/api/v1/documents", {
                "doc_type": "MR", "site_id": site.id,
                "payload": {"required_by": "2026-08-01", "stock_attested": True},
                "lines": [{"item_id": self.item.id, "qty_required": 10,
                           "qty_stock": 0, "qty_to_order": 10,
                           "priority": "NORMAL"}],
            }, format="json")
            self.assertEqual(mr.status_code, 201, mr.data)
            line = mr.data["lines"][0]
        self.assertTrue(line["item_is_major"])
        self.assertIsNotNone(line["item_photo_url"])


@override_settings(MEDIA_ROOT="test-media")
class MrLinePhotoTests(TestCase):
    def setUp(self):
        from datetime import date, timedelta

        from .models import Site, SitePmHistory
        self.site = Site.objects.create(
            code="SJR", name="Soneva Jani", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=5))
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        pm = make_user("pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=pm,
                                     from_date=date.today())
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    def test_free_text_line_photo_surfaces_on_line(self):
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id,
            "payload": {"required_by": "2026-08-01", "stock_attested": True},
            "lines": [{"item_id": None, "free_text_desc": "Special gasket 3in",
                       "unit": "nos", "qty_required": 4, "qty_to_order": 4,
                       "priority": "NORMAL"}],
        }, format="json")
        self.assertEqual(mr.status_code, 201, mr.data)
        line_id = mr.data["lines"][0]["id"]
        self.assertIsNone(mr.data["lines"][0]["item_photo_url"])
        photo = SimpleUploadedFile("g.png", PNG, content_type="image/png")
        r = self.client.post(
            f"/api/v1/documents/{mr.data['ref']}/attachments",
            {"file": photo, "kind": "PHOTO", "line_id": line_id},
            format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        fresh = self.client.get(f"/api/v1/documents/{mr.data['ref']}")
        self.assertIsNotNone(fresh.data["lines"][0]["item_photo_url"])


class ItemBulkImportTests(TestCase):
    """Excel template + bulk import from the Items page (owner 2026-07-14)."""

    def setUp(self):
        from .models import ItemCategory
        self.purchasing = make_user("hopb", User.Role.HO_PURCHASING)
        ItemCategory.objects.get_or_create(name="Civil")
        self.client = APIClient()
        self.client.force_authenticate(self.purchasing)

    def _xlsx(self, rows, header=None):
        import io

        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Items"
        ws.append(header or ["Description", "Unit", "Category", "Brand",
                             "Spec Ref", "Key material (yes/no)"])
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return SimpleUploadedFile(
            "items.xlsx", buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet")

    def test_template_downloads(self):
        r = self.client.get("/api/v1/items/import-template")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])

    def test_import_creates_items_and_skips_dupes(self):
        Item.objects.create(code="ITM-90001", description="Existing bar",
                            unit="kg")
        f = self._xlsx([
            ["Rebar 12mm", "kg", "Civil", "Steelco", "B500", "yes"],
            ["PVC pipe 63mm", "m", "", "", "", ""],
            ["Existing bar", "kg", "", "", "", ""],        # duplicate → skip
            ["No unit item", "", "", "", "", ""],          # no unit → error
            ["Bad cat", "nos", "Nonsense", "", "", ""],    # unknown category
        ])
        r = self.client.post("/api/v1/items/import", {"file": f},
                             format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["created"], 3)   # rebar, pvc, bad-cat(no cat)
        self.assertTrue(r.data["skipped"] >= 1)  # duplicate + no-unit
        rebar = Item.objects.get(description="Rebar 12mm")
        self.assertEqual(rebar.category, "Civil")
        self.assertTrue(rebar.is_major)
        self.assertEqual(Item.objects.get(description="Bad cat").category, "")

    def test_import_requires_description_column(self):
        f = self._xlsx([["kg"]], header=["Unit"])
        r = self.client.post("/api/v1/items/import", {"file": f},
                             format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_site_staff_cannot_bulk_import(self):
        self.client.force_authenticate(make_user("sa7", User.Role.SITE_ADMIN))
        f = self._xlsx([["X", "kg", "", "", "", ""]])
        r = self.client.post("/api/v1/items/import", {"file": f},
                             format="multipart")
        self.assertEqual(r.status_code, 403)
