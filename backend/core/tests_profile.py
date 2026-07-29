"""Company Profile — Phase 1: ongoing-entry CRUD + reorder + access."""
from django.test import TestCase
from rest_framework.test import APIClient

from .models import ProfileEntry, User
from .tests import make_user


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

    def test_completed_entry_is_locked(self):
        e = ProfileEntry.objects.create(
            project_name="Done", status="COMPLETED", snapshot_locked=True)
        self.client.force_authenticate(self.mkt)
        self.assertEqual(self.client.patch(
            f"/api/v1/profile/entries/{e.id}", {"summary": "x"},
            format="json").status_code, 400)
        self.assertEqual(self.client.delete(
            f"/api/v1/profile/entries/{e.id}").status_code, 400)
