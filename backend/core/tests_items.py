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
