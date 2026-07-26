"""Onboarding case spine — raise → checklist-gated submit → PD (Director)
approve / return / reject, with sensitive-document access control."""
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Document, OnboardingCase, Site, SitePmHistory, User
from .tests import make_user


class OnboardingSpineTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="VKR", name="Vakkaru",
                                         status=Site.Status.ACTIVE)
        self.pm = make_user("pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.other_pm = make_user("pm2", User.Role.PM, site=self.other)
        SitePmHistory.objects.create(site=self.other, pm_user=self.other_pm,
                                     from_date=date(2026, 1, 1))
        self.hr = make_user("hr", User.Role.HO_HR)
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.se = make_user("se", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()

    def _body(self, **kw):
        return {"full_name": "Ravi Kumar", "nationality": "Indian",
                "passport_no": "P1234567", "category": "SKILLED",
                "trade_designation": "Mason", "proposed_salary": "8000",
                "route": "WP", **kw}

    def _create(self, actor=None, **kw):
        self.client.force_authenticate(actor or self.pm)
        return self.client.post(f"/api/v1/sites/{self.site.id}/onboarding",
                                self._body(**kw), format="json")

    def _attach_all(self, pk):
        for kind in ("PASSPORT_COPY", "PASSPORT_PHOTO", "PASSPORT_OBS", "CV"):
            f = SimpleUploadedFile(f"{kind}.pdf", b"x", content_type="application/pdf")
            r = self.client.post(f"/api/v1/onboarding/{pk}/documents",
                                 {"kind": kind, "file": f}, format="multipart")
            assert r.status_code == 201, r.data

    def test_only_pm_or_hr_raises(self):
        r = self._create(actor=self.se)
        self.assertIn(r.status_code, (400, 403))   # site engineer is blocked
        self.assertEqual(self._create(actor=self.hr).status_code, 201)
        self.assertEqual(self._create(actor=self.pm).status_code, 201)

    def test_ref_is_site_scoped(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("OBR-SJR-"))

    def test_submit_gated_on_checklist(self):
        pk = self._create().data["id"]
        # missing all four docs
        r = self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Passport copy", r.data["detail"])
        self._attach_all(pk)
        r = self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")

    def test_bv_needs_justification(self):
        pk = self._create(route="BV").data["id"]
        self._attach_all(pk)
        r = self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.assertEqual(r.status_code, 400)
        self.assertIn("justification", r.data["detail"].lower())

    def test_director_approves_and_notifies_hr(self):
        from .models import Notification
        pk = self._create().data["id"]
        self._attach_all(pk)
        self.client.post(f"/api/v1/onboarding/{pk}/submit")
        # a non-director cannot approve
        self.client.force_authenticate(self.pm)
        self.assertEqual(self.client.post(
            f"/api/v1/onboarding/{pk}/action", {"action": "approve"},
            format="json").status_code, 400)
        # Director notified on submit; approves; HR notified
        self.assertTrue(Notification.objects.filter(
            recipient=self.director, category="approval").exists())
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/onboarding/{pk}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "APPROVED")
        self.assertTrue(Notification.objects.filter(recipient=self.hr).exists())

    def test_return_requires_reason_then_resubmit(self):
        pk = self._create().data["id"]
        self._attach_all(pk)
        self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.client.force_authenticate(self.director)
        # no reason → rejected
        self.assertEqual(self.client.post(
            f"/api/v1/onboarding/{pk}/action", {"action": "return"},
            format="json").status_code, 400)
        r = self.client.post(f"/api/v1/onboarding/{pk}/action",
                             {"action": "return", "note": "Fix the passport scan"},
                             format="json")
        self.assertEqual(r.data["status"], "RETURNED")
        # the PM can edit + resubmit a returned case
        self.client.force_authenticate(self.pm)
        self.client.patch(f"/api/v1/onboarding/{pk}",
                          {"trade_designation": "Senior Mason"}, format="json")
        r = self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.assertEqual(r.data["status"], "SUBMITTED")

    def test_other_site_pm_cannot_see_case(self):
        pk = self._create().data["id"]
        self.client.force_authenticate(self.other_pm)
        self.assertEqual(
            self.client.get(f"/api/v1/onboarding/{pk}").status_code, 404)
        # HR + Director can
        self.client.force_authenticate(self.hr)
        self.assertEqual(
            self.client.get(f"/api/v1/onboarding/{pk}").status_code, 200)

    def test_documents_locked_after_submit(self):
        pk = self._create().data["id"]
        self._attach_all(pk)
        self.client.post(f"/api/v1/onboarding/{pk}/submit")
        f = SimpleUploadedFile("cv2.pdf", b"y", content_type="application/pdf")
        r = self.client.post(f"/api/v1/onboarding/{pk}/documents",
                             {"kind": "CV", "file": f}, format="multipart")
        self.assertEqual(r.status_code, 400)
