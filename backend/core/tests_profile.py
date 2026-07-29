"""Company Profile — ongoing-entry CRUD + reorder + access + images."""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import ProfileEntry, ProfileGalleryImage, User
from .tests import make_user


def _img(w, h, name="p.jpg"):
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h), "#0E3A5C").save(buf, format="JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


class ProfileEntryTests(TestCase):
    def setUp(self):
        self.mkt = make_user("mkt", User.Role.MARKETING)
        self.eng = make_user("pf_eng", User.Role.SITE_ENGINEER)
        self.client = APIClient()

    def test_marketing_crud_and_reorder(self):
        self.client.force_authenticate(self.mkt)
        a = self.client.post("/api/v1/profile/entries", {
            "project_name": "Soneva Jani", "client_display": "SONEVA JANI",
            "summary": "Villa works.", "start_value": "April 2026"},
            format="json")
        self.assertEqual(a.status_code, 201, a.data)
        a_id = a.data["id"]
        self.assertEqual(a.data["start_label"], "Commenced")
        b_id = self.client.post("/api/v1/profile/entries",
                                {"project_name": "Vakkaru"},
                                format="json").data["id"]
        d = self.client.get("/api/v1/profile/entries").data
        self.assertEqual(len(d["ongoing"]), 2)
        # reorder b before a
        self.client.post("/api/v1/profile/entries/reorder",
                         {"order": [b_id, a_id]}, format="json")
        d = self.client.get("/api/v1/profile/entries").data
        self.assertEqual(d["ongoing"][0]["id"], b_id)
        # edit
        r = self.client.patch(f"/api/v1/profile/entries/{a_id}",
                              {"summary": "Updated."}, format="json")
        self.assertEqual(r.data["summary"], "Updated.")
        # delete
        self.assertEqual(
            self.client.delete(f"/api/v1/profile/entries/{b_id}").status_code,
            204)
        self.assertEqual(ProfileEntry.objects.count(), 1)

    def test_name_required(self):
        self.client.force_authenticate(self.mkt)
        r = self.client.post("/api/v1/profile/entries", {"summary": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_non_profile_role_forbidden(self):
        self.client.force_authenticate(self.eng)
        self.assertEqual(
            self.client.get("/api/v1/profile/entries").status_code, 403)
        self.assertEqual(self.client.post(
            "/api/v1/profile/entries", {"project_name": "x"},
            format="json").status_code, 403)

    def test_featured_is_recropped_to_square(self):
        self.client.force_authenticate(self.mkt)
        eid = self.client.post("/api/v1/profile/entries",
                               {"project_name": "Jani"}, format="json").data["id"]
        r = self.client.post(f"/api/v1/profile/entries/{eid}/featured",
                             {"file": _img(2000, 1200)}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["featured_url"])
        from PIL import Image
        img = Image.open(ProfileEntry.objects.get(pk=eid).featured_image)
        self.assertEqual(img.width, img.height)      # forced 1:1
        self.assertLessEqual(img.width, 1300)

    def test_gallery_add_cap_and_remove(self):
        self.client.force_authenticate(self.mkt)
        eid = self.client.post("/api/v1/profile/entries",
                               {"project_name": "Jani"}, format="json").data["id"]
        for _ in range(6):
            r = self.client.post(f"/api/v1/profile/entries/{eid}/gallery",
                                 {"file": _img(1500, 1000)}, format="multipart")
            self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["gallery"]), 6)
        # seventh is refused
        r7 = self.client.post(f"/api/v1/profile/entries/{eid}/gallery",
                             {"file": _img(1500, 1000)}, format="multipart")
        self.assertEqual(r7.status_code, 400)
        # a stored gallery image is 3:2
        from PIL import Image
        g = ProfileGalleryImage.objects.filter(entry_id=eid).first()
        im = Image.open(g.image)
        self.assertAlmostEqual(im.width / im.height, 1.5, places=2)
        self.assertEqual(self.client.delete(
            f"/api/v1/profile/gallery/{g.id}").status_code, 204)

    def test_completed_entry_is_locked(self):
        e = ProfileEntry.objects.create(
            project_name="Done", status="COMPLETED", snapshot_locked=True)
        self.client.force_authenticate(self.mkt)
        self.assertEqual(self.client.patch(
            f"/api/v1/profile/entries/{e.id}", {"summary": "x"},
            format="json").status_code, 400)
        self.assertEqual(self.client.delete(
            f"/api/v1/profile/entries/{e.id}").status_code, 400)
