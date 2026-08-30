"""A photo can be attached to a worker who is still awaiting approval.

The only way to add one used to be from the workforce list after the hire was
approved, or through an onboarding case — so for a site hire the photo was
days late and usually never taken. The site photographs the man on his first
day, which is before the Director activates him (owner 2026-08-30)."""
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from . import worker_mgmt as wm
from .models import Employee, ManpowerCategory, Site, User
from .tests import make_user

# A one-pixel PNG: enough for the endpoint to accept and store.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")


class HirePhotoTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="PHO", name="Photo site",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa_pho", User.Role.SITE_ADMIN, site=self.site)
        self.cat = ManpowerCategory.objects.create(
            name="Mason", list_type="DPR", sort_order=10)
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    def _batch(self):
        batch, err = wm.create_add_batch(self.site, [{
            "full_name": "Ravi Kumar", "passport_no": "N1234567",
            "nationality": "Indian", "basic_pay": "6000",
            "currency": "MVR", "job_category_id": self.cat.id}], self.sa)
        self.assertIsNone(err)
        return batch

    def _upload(self, emp_id):
        return self.client.post(
            f"/api/v1/workers/{emp_id}/photo",
            {"photo": SimpleUploadedFile("face.png", PNG, "image/png")},
            format="multipart")

    def test_a_pending_hire_can_be_photographed(self):
        emp = self._batch().items.first().employee
        self.assertFalse(emp.is_active)
        self.assertTrue(emp.hire_pending)
        r = self._upload(emp.id)
        self.assertEqual(r.status_code, 200, r.data)
        emp.refresh_from_db()
        self.assertTrue(emp.photo)

    def test_the_batch_hands_back_the_ids_to_photograph(self):
        """The form uploads against these, matched on passport number."""
        r = self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                             {"kind": "ADD", "workers": [
                                 {"full_name": "Ravi Kumar",
                                  "passport_no": "N1234567",
                                  "nationality": "Indian",
                                  "basic_pay": "6000", "currency": "MVR",
                                  "job_category_id": self.cat.id}]},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        worker = r.data["workers"][0]
        self.assertTrue(worker["id"])
        self.assertEqual(worker["passport_no"], "N1234567")
        self.assertEqual(self._upload(worker["id"]).status_code, 200)

    def test_another_site_cannot_photograph_the_pending_hire(self):
        """Opening this up to pending hires must not open up the scope."""
        emp = self._batch().items.first().employee
        other = Site.objects.create(code="OTH", name="Other",
                                    status=Site.Status.ACTIVE)
        outsider = make_user("sa_oth", User.Role.SITE_ADMIN, site=other)
        self.client.force_authenticate(outsider)
        self.assertEqual(self._upload(emp.id).status_code, 403)

    def test_an_archived_worker_is_still_refused(self):
        emp = Employee.objects.create(emp_no="EMP-9999", full_name="Gone",
                                      is_active=False, hire_pending=False)
        self.assertEqual(self._upload(emp.id).status_code, 404)

    def test_hr_can_photograph_a_pending_hire_anywhere(self):
        emp = self._batch().items.first().employee
        self.client.force_authenticate(make_user("hr_pho", User.Role.HO_HR))
        self.assertEqual(self._upload(emp.id).status_code, 200)

    def test_the_photo_survives_activation(self):
        batch = self._batch()
        emp = batch.items.first().employee
        self._upload(emp.id)
        emp.refresh_from_db()
        before = emp.photo.name
        emp.is_active = True
        emp.hire_pending = False
        emp.join_date = date.today()
        emp.save(update_fields=["is_active", "hire_pending", "join_date"])
        emp.refresh_from_db()
        self.assertEqual(emp.photo.name, before)
