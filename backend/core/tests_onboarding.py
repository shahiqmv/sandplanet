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

    # ---- Phase 2: stage machines ----------------------------------------

    def _approved(self, **kw):
        pk = self._create(**kw).data["id"]
        self._attach_all(pk)
        self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/onboarding/{pk}/action",
                         {"action": "approve"}, format="json")
        return pk

    def _adv(self, pk, **data):
        self.client.force_authenticate(self.hr)
        return self.client.post(f"/api/v1/onboarding/{pk}/stage", data,
                                format="json")

    def _sdata(self, pk, **data):
        self.client.force_authenticate(self.hr)
        return self.client.post(f"/api/v1/onboarding/{pk}/stage-data", data,
                                format="json")

    def _pay_fee(self, pk, stage):
        """Raise the fee PYR for the current payment stage and mark it PAID."""
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/onboarding/{pk}/fee",
                             {"amount": "1500", "payee": "Vendor"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        from .models import OnboardingCase
        fee = OnboardingCase.objects.get(pk=pk).fees.get(stage=stage)
        fee.document.status = "PAID"
        fee.document.save(update_fields=["status"])

    def test_wp_track_walks_to_completion(self):
        pk = self._approved()
        r = self._adv(pk)                              # begin
        self.assertEqual(r.data["status"], "IN_PROGRESS")
        self.assertEqual(r.data["stage"], "WP_APPOINTMENT")
        self.assertEqual(self._adv(pk).data["stage"], "WP_APPLICATION")
        self.assertEqual(self._adv(pk).status_code, 400)   # portal not approved
        self._sdata(pk, portal_status="APPROVED")
        self.assertEqual(self._adv(pk).data["stage"], "WP_APPROVED")
        self.assertEqual(self._adv(pk).data["stage"], "WP_DEPOSIT")
        self._pay_fee(pk, "WP_DEPOSIT")
        self.assertEqual(self._adv(pk).data["stage"], "WP_TICKET")
        self._pay_fee(pk, "WP_TICKET")
        self.assertEqual(self._adv(pk).status_code, 400)   # arrival needs a date
        r = self._adv(pk, arrived_date="2026-08-01")
        self.assertEqual(r.data["stage"], "WP_ARRIVED")
        self.assertEqual(str(r.data["medical_due"]), "2026-08-15")   # +14 days
        self.assertEqual(self._adv(pk).data["stage"], "WP_MEDICAL")
        self.assertEqual(self._adv(pk).status_code, 400)   # no medical result
        self._sdata(pk, medical_result="PASS")
        self.assertEqual(self._adv(pk).data["stage"], "WP_ISSUED")
        self.assertEqual(self._adv(pk).data["status"], "COMPLETED")

    def test_sri_lankan_gets_endorsement_stage(self):
        keys = [s["key"] for s in
                self._adv(self._approved(nationality="Sri Lankan")).data["stages"]]
        self.assertIn("WP_ENDORSEMENT", keys)
        keys2 = [s["key"] for s in
                 self._adv(self._approved(nationality="Indian")).data["stages"]]
        self.assertNotIn("WP_ENDORSEMENT", keys2)

    def test_bv_sequence_has_conversion_tail(self):
        pk = self._approved(route="BV", bv_justification="urgent mobilisation",
                            nationality="Sri Lankan")
        keys = [s["key"] for s in self._adv(pk).data["stages"]]
        self.assertEqual(keys[0], "BV_SPONSOR")
        self.assertIn("BV_ARRIVED", keys)
        self.assertIn("WP_APPOINTMENT", keys)          # in-country conversion
        self.assertIn("WP_ISSUED", keys)
        self.assertNotIn("WP_ENDORSEMENT", keys)       # no endorsement on BV
        self.assertNotIn("WP_TICKET", keys)            # no ticket in conversion

    def test_only_hr_advances_stages(self):
        pk = self._approved()
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/onboarding/{pk}/stage", {}, format="json")
        self.assertEqual(r.status_code, 400)

    def _to_deposit(self, pk):
        self._adv(pk)                    # WP_APPOINTMENT
        self._adv(pk)                    # WP_APPLICATION
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk)                    # WP_APPROVED
        self._adv(pk)                    # WP_DEPOSIT

    def test_payment_gate_blocks_until_fee_paid(self):
        pk = self._approved()            # WP, Indian
        self._to_deposit(pk)
        # blocked — no fee raised
        self.assertEqual(self._adv(pk).status_code, 400)
        # HR raises the fee PYR
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/onboarding/{pk}/fee",
                             {"amount": "1500", "payee": "Immigration Maldives"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["fee"]["raised"])
        self.assertTrue(r.data["fee"]["refundable"])   # deposit is refundable
        self.assertFalse(r.data["fee"]["paid"])
        self.assertEqual(self._adv(pk).status_code, 400)   # not paid yet
        # the refundable deposit PYR is capitalized (posts nothing)
        from .models import OnboardingCase
        fee = OnboardingCase.objects.get(pk=pk).fees.get(stage="WP_DEPOSIT")
        self.assertTrue(fee.document.payment_request.is_capitalized)
        # pay it → the gate opens
        fee.document.status = "PAID"
        fee.document.save(update_fields=["status"])
        self.assertEqual(self._adv(pk).data["stage"], "WP_TICKET")

    def test_fee_paid_notifies_hr(self):
        from . import onboarding as ob
        from .models import Notification, OnboardingCase
        pk = self._approved()
        self._to_deposit(pk)
        self.client.force_authenticate(self.hr)
        self.client.post(f"/api/v1/onboarding/{pk}/fee",
                         {"amount": "1500", "payee": "Immigration"},
                         format="json")
        fee = OnboardingCase.objects.get(pk=pk).fees.get(stage="WP_DEPOSIT")
        Notification.objects.filter(recipient=self.hr).delete()
        ob.on_fee_paid(fee.document, self.hr)
        self.assertTrue(Notification.objects.filter(
            recipient=self.hr, title__icontains="paid").exists())

    def test_medical_fail_blocks_and_flags_pd(self):
        from .models import Notification
        pk = self._approved()
        self._adv(pk); self._adv(pk)                   # → WP_APPLICATION
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk); self._adv(pk)                   # → WP_DEPOSIT
        self._pay_fee(pk, "WP_DEPOSIT")
        self._adv(pk)                                  # → WP_TICKET
        self._pay_fee(pk, "WP_TICKET")
        self._adv(pk, arrived_date="2026-08-01")       # → WP_ARRIVED
        self.assertEqual(self._adv(pk).data["stage"], "WP_MEDICAL")
        self._sdata(pk, medical_result="FAIL")
        self.assertEqual(self._adv(pk).status_code, 400)   # blocked on fail
        self.assertTrue(Notification.objects.filter(
            recipient=self.director, title__icontains="medical").exists())
