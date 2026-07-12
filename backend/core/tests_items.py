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
