"""Onboarding case spine — raise → checklist-gated submit → PD (Director)
approve / return / reject, with sensitive-document access control."""
from datetime import date
from decimal import Decimal

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
        base = {"full_name": "Ravi Kumar", "nationality": "Indian",
                "passport_no": "P1234567", "category": "SKILLED",
                "trade_designation": "Mason", "proposed_salary": "8000",
                "route": "WP", **kw}
        if base.get("route") == "BV" and "bv_purpose" not in base:
            base["bv_purpose"] = "RECRUITMENT"
        return base

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
        # missing the required docs
        r = self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Passport copy", r.data["detail"])
        self._attach_all(pk)
        r = self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")

    def test_cv_is_optional(self):
        pk = self._create().data["id"]
        # the three passport docs only — no CV
        for kind in ("PASSPORT_COPY", "PASSPORT_PHOTO", "PASSPORT_OBS"):
            f = SimpleUploadedFile(f"{kind}.pdf", b"x",
                                   content_type="application/pdf")
            self.client.post(f"/api/v1/onboarding/{pk}/documents",
                             {"kind": kind, "file": f}, format="multipart")
        r = self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.assertEqual(r.status_code, 200, r.data)   # submits without a CV
        cv = next(x for x in r.data["checklist"] if x["kind"] == "CV")
        self.assertFalse(cv["required"])

    def test_quota_pool_selected_and_stored(self):
        r = self._create(quota_pool="MARINE")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["quota_pool"], "MARINE")
        self.assertEqual(r.data["quota_pool_label"], "Sand Planet Marine")
        # defaults to Sand Planet when not given
        self.assertEqual(self._create().data["quota_pool"], "SANDPLANET")

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

    def test_director_sends_back_approved_case_for_edits(self):
        # The Director can pull an already-approved case back to RETURNED so the
        # raiser can fix details, then resubmit (owner 2026-08-06).
        pk = self._approved()
        self.assertTrue(self.client.get(
            f"/api/v1/onboarding/{pk}").data["can_send_back"])
        self.client.force_authenticate(self.director)
        self.assertEqual(self.client.post(          # reason still required
            f"/api/v1/onboarding/{pk}/action", {"action": "return"},
            format="json").status_code, 400)
        r = self.client.post(f"/api/v1/onboarding/{pk}/action",
                             {"action": "return", "note": "Passport no. wrong"},
                             format="json")
        self.assertEqual(r.data["status"], "RETURNED", r.data)
        self.client.force_authenticate(self.pm)
        self.client.patch(f"/api/v1/onboarding/{pk}",
                          {"passport_no": "P9999999"}, format="json")
        self.assertEqual(self.client.post(
            f"/api/v1/onboarding/{pk}/submit").data["status"], "SUBMITTED")

    def test_send_back_clean_in_progress_resets_stage(self):
        from core.models import OnboardingCase
        pk = self._approved()
        self._begin(pk)                               # begin → WP_APPOINTMENT
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/onboarding/{pk}/action",
                             {"action": "return", "note": "fix salary"},
                             format="json")
        self.assertEqual(r.data["status"], "RETURNED", r.data)
        self.assertEqual(OnboardingCase.objects.get(pk=pk).stage, "")

    def test_send_back_blocked_once_a_letter_is_issued(self):
        pk = self._approved()
        self._begin(pk)                               # → WP_APPOINTMENT
        self._gen_letter(pk, "LOA")                 # a letter now exists
        self.assertFalse(self.client.get(
            f"/api/v1/onboarding/{pk}").data["can_send_back"])
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/onboarding/{pk}/action",
                             {"action": "return", "note": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("letter", r.data["detail"].lower())

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
        """Advance a stage. Carries a portal reference unless the test is
        deliberately withholding one — lodging an application now requires the
        reference the government portal issues (owner 2026-08-16), and these
        walks are about the rest of the machine, not that gate."""
        self.client.force_authenticate(self.hr)
        data.setdefault("portal_ref", "GSR/2026/00001")
        return self.client.post(f"/api/v1/onboarding/{pk}/stage", data,
                                format="json")

    def _sign_off(self, pk):
        """A signatory signs the case off — the gate every letter and stage
        advance now sits behind (owner 2026-08-11)."""
        from .tests import make_user
        sig = getattr(self, "_signer", None)
        if sig is None:
            sig = self._signer = make_user("ob_signer", User.Role.SIGNATORY)
            self.client.force_authenticate(sig)
            self.client.post("/api/v1/onboarding/my-stamp",
                             {"stamp": self._tiny_png()}, format="multipart")
        self.client.force_authenticate(sig)
        r = self.client.post(f"/api/v1/onboarding/cases/{pk}/sign-off")
        self.client.force_authenticate(self.hr)
        return r

    def _begin(self, pk, **data):
        """Begin processing AND sign off — the normal start of a live case."""
        r = self._adv(pk, **data)
        self._sign_off(pk)
        return r

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
        fee = OnboardingCase.objects.get(pk=pk).fees.get(stage=stage)
        fee.document.status = "PAID"
        fee.document.save(update_fields=["status"])

    def test_wp_track_walks_to_completion(self):
        pk = self._approved()
        r = self._begin(pk)                              # begin
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
        self._begin(pk)                  # WP_APPOINTMENT (signed off)
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
        fee = OnboardingCase.objects.get(pk=pk).fees.get(stage="WP_DEPOSIT")
        self.assertTrue(fee.document.payment_request.is_capitalized)
        # pay it → the gate opens
        fee.document.status = "PAID"
        fee.document.save(update_fields=["status"])
        self.assertEqual(self._adv(pk).data["stage"], "WP_TICKET")

    def test_fee_not_applicable_waives_and_advances(self):
        pk = self._approved()
        self._to_deposit(pk)                     # at WP_DEPOSIT (a fee stage)
        self.assertEqual(self._adv(pk).status_code, 400)   # blocked, no fee
        r = self._adv(pk, waive_fee=True)        # HR: fee not applicable
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["stage"], "WP_TICKET")     # advanced past it
        self.assertIn("WP_DEPOSIT", r.data["waived_stages"])

    def test_cannot_waive_an_already_raised_fee(self):
        pk = self._approved()
        self._to_deposit(pk)
        self.client.force_authenticate(self.hr)
        self.client.post(f"/api/v1/onboarding/{pk}/fee",
                         {"amount": "1500", "payee": "X"}, format="json")
        r = self._adv(pk, waive_fee=True)
        self.assertEqual(r.status_code, 400)
        self.assertIn("already been raised", r.data["detail"])

    def test_onboarding_fee_clears_straight_to_finance(self):
        pk = self._approved()
        self._to_deposit(pk)
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/onboarding/{pk}/fee",
                             {"amount": "1500", "payee": "Immigration"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        pr = (OnboardingCase.objects.get(pk=pk).fees.get(stage="WP_DEPOSIT")
              .document.payment_request)
        # recruitment cost — NO PM and NO Director; cleared straight to Finance
        self.assertEqual(pr.origin, "ONBOARDING")
        self.assertEqual(pr.document.status, "DIRECTOR_APPROVED")   # → Finance

    def test_cancelled_fee_can_be_re_raised(self):
        from .onboarding import active_fee_for
        pk = self._approved()
        self._to_deposit(pk)
        self.client.force_authenticate(self.hr)
        self.client.post(f"/api/v1/onboarding/{pk}/fee",
                         {"amount": "1500", "payee": "X"}, format="json")
        fee = OnboardingCase.objects.get(pk=pk).fees.get(stage="WP_DEPOSIT")
        # a second attempt is refused while the first is still live
        r = self.client.post(f"/api/v1/onboarding/{pk}/fee",
                             {"amount": "1500", "payee": "X"}, format="json")
        self.assertEqual(r.status_code, 400)
        # the wrong PYR gets cancelled — HR must be able to raise a fresh one
        fee.document.status = "CANCELLED"
        fee.document.save(update_fields=["status"])
        case = OnboardingCase.objects.get(pk=pk)
        self.assertIsNone(active_fee_for(case, "WP_DEPOSIT"))
        r = self.client.post(f"/api/v1/onboarding/{pk}/fee",
                             {"amount": "1500", "payee": "X"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        # tracker repointed to the fresh, live PYR (the cancelled Document stays)
        self.assertEqual(case.fees.filter(stage="WP_DEPOSIT").count(), 1)
        live = active_fee_for(OnboardingCase.objects.get(pk=pk), "WP_DEPOSIT")
        self.assertEqual(live.document.status, "DIRECTOR_APPROVED")   # → Finance
        self.assertNotEqual(live.document_id, fee.document_id)

    def test_fee_paid_notifies_hr(self):
        from . import onboarding as ob
        from .models import Notification
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

    def _gen_letter(self, pk, kind, **fields):
        self.client.force_authenticate(self.hr)
        return self.client.post(f"/api/v1/onboarding/{pk}/letter",
                                {"kind": kind, "fields": fields}, format="json")

    def test_loa_generates_at_appointment(self):
        pk = self._approved()                 # WP, Indian
        self._begin(pk)                          # begin → WP_APPOINTMENT
        detail = self.client.get(f"/api/v1/onboarding/{pk}").data
        opts = {o["kind"]: o for o in detail["letter_options"]}
        self.assertTrue(opts["LOA"]["available"])
        self.assertFalse(opts["SPL"]["available"])   # not a BV case
        r = self._gen_letter(pk, "LOA", work_site="Hulhumale' Tower")
        self.assertEqual(r.status_code, 201, r.data)
        letters = r.data["letters"]
        self.assertEqual(len(letters), 1)
        self.assertEqual(letters[0]["ref"], "LOA-001")
        self.assertEqual(letters[0]["version"], 1)
        self.assertTrue(letters[0]["download"].endswith(
            f"/letters/{letters[0]['id']}.pdf"))

    def test_spl_only_on_bv_track(self):
        pk = self._approved(route="BV", bv_justification="urgent mobilisation",
                            nationality="Sri Lankan")
        self._begin(pk)                          # begin → BV_SPONSOR
        detail = self.client.get(f"/api/v1/onboarding/{pk}").data
        opts = {o["kind"]: o for o in detail["letter_options"]}
        self.assertTrue(opts["SPL"]["available"])
        # LOA rolled back to the appointment stage — not issuable pre-arrival.
        self.assertFalse(opts["LOA"]["available"])
        r = self._gen_letter(pk, "SPL", project_site="Ha. Dhidhdhoo Harbour",
                             addressee_line_1="The Controller of Immigration")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["letters"][0]["ref"], "SPL-001")

    def test_appointment_confirmation_available_early_for_recruitment(self):
        # The lean Appointment Confirmation is available from the start of
        # processing for any recruitment case (owner 2026-08-04), replacing the
        # old advance-LOA. The detailed LOA is NOT available pre-arrival.
        pk = self._approved(route="BV", bv_justification="urgent mobilisation")
        self._begin(pk)                          # → BV_SPONSOR (pre-arrival)
        opts = {o["kind"]: o for o in self.client.get(
            f"/api/v1/onboarding/{pk}").data["letter_options"]}
        self.assertTrue(opts["AC"]["available"])
        self.assertFalse(opts["LOA"]["available"])

    def test_appointment_confirmation_not_for_subcontract(self):
        pk = self._approved(route="BV", bv_justification="short job",
                            nationality="Indian", bv_purpose="SUBCONTRACT")
        self._begin(pk)
        opts = {o["kind"]: o for o in self.client.get(
            f"/api/v1/onboarding/{pk}").data["letter_options"]}
        self.assertFalse(opts["AC"]["available"])

    def test_loa_not_available_for_subcontract_bv(self):
        pk = self._approved(route="BV", bv_justification="short job",
                            nationality="Indian", bv_purpose="SUBCONTRACT")
        self._begin(pk)
        opts = {o["kind"]: o for o in self.client.get(
            f"/api/v1/onboarding/{pk}").data["letter_options"]}
        self.assertFalse(opts["LOA"]["available"])   # no appointment on subcon

    def test_regenerating_a_letter_bumps_version(self):
        pk = self._approved()
        self._begin(pk)                          # → WP_APPOINTMENT
        self._gen_letter(pk, "LOA")
        r = self._gen_letter(pk, "LOA", contract_duration="1 year")
        self.assertEqual(r.status_code, 201, r.data)
        refs = sorted(x["ref"] for x in r.data["letters"])
        self.assertEqual(refs, ["LOA-001", "LOA-002"])
        versions = sorted(x["version"] for x in r.data["letters"])
        self.assertEqual(versions, [1, 2])

    def test_only_hr_generates_letters(self):
        pk = self._approved()
        self._begin(pk)
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/onboarding/{pk}/letter",
                             {"kind": "LOA"}, format="json")
        self.assertIn(r.status_code, (400, 403))

    def test_letter_pdf_downloads(self):
        pk = self._approved()
        self._begin(pk)
        lid = self._gen_letter(pk, "LOA").data["letters"][0]["id"]
        self.client.force_authenticate(self.hr)
        r = self.client.get(f"/api/v1/onboarding/{pk}/letters/{lid}.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")

    def _tiny_png(self):
        import io

        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGBA", (160, 80), (0, 0, 0, 0)).save(buf, "PNG")
        return SimpleUploadedFile("stamp.png", buf.getvalue(),
                                  content_type="image/png")

    def test_im30_available_only_for_sri_lankan_wp(self):
        # Indian WP → no IM30; Sri-Lankan WP → IM30; SL subcontract BV → none.
        pk = self._approved(nationality="Indian")     # WP
        self._begin(pk)
        opts = {o["kind"]: o for o in self.client.get(
            f"/api/v1/onboarding/{pk}").data["letter_options"]}
        self.assertFalse(opts["IM30"]["available"])

        sl = self._approved(nationality="Sri Lankan")  # WP
        self._begin(sl)
        opts = {o["kind"]: o for o in self.client.get(
            f"/api/v1/onboarding/{sl}").data["letter_options"]}
        self.assertTrue(opts["IM30"]["available"])
        # prefilled: work site carries the company tax no, purpose is Employment
        f = opts["IM30"]["fields"]
        self.assertEqual(f["purpose_of_stay"], "Employment")
        self.assertIn("ST00042609", f["work_site"])

        sub = self._approved(route="BV", bv_justification="short job",
                             nationality="Sri Lankan", bv_purpose="SUBCONTRACT")
        self._adv(sub)
        opts = {o["kind"]: o for o in self.client.get(
            f"/api/v1/onboarding/{sub}").data["letter_options"]}
        self.assertFalse(opts["IM30"]["available"])

    def test_im30_generates_pdf(self):
        pk = self._approved(nationality="Sri Lankan")
        self._begin(pk)
        r = self._gen_letter(pk, "IM30", marital_status="Married",
                             old_passport_no="N999")
        self.assertEqual(r.status_code, 201, r.data)
        im = next(x for x in r.data["letters"] if x["kind"] == "IM30")
        self.assertEqual(im["ref"], "IM30-001")
        self.client.force_authenticate(self.hr)
        pdf = self.client.get(f"/api/v1/onboarding/{pk}/letters/{im['id']}.pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        body = b"".join(pdf.streaming_content)
        self.assertTrue(body[:4] == b"%PDF")

    def test_signatory_stamp_reused_for_marks(self):
        # Once a signatory has uploaded a stamp, it is reused as the signature
        # mark without any re-approval (owner 2026-08-05).
        from . import onboarding as ob
        sig = make_user("ob_sig2", User.Role.SIGNATORY)
        self.assertIsNone(ob._signatory_stamp_bytes())
        self.client.force_authenticate(sig)
        self.client.post("/api/v1/onboarding/my-stamp",
                         {"stamp": self._tiny_png()}, format="multipart")
        self.assertTrue(ob._signatory_stamp_bytes())

    def test_nothing_generates_before_signoff(self):
        # Owner 2026-08-11: staff were generating the LOA and lodging the
        # work-permit application while the sign-off was still pending. Now
        # the signatory signs the CASE first — no letter and no stage advance
        # before that — and every letter comes out stamped.
        from .models import Notification, OnboardingLetter
        sig = make_user("ob_sig", User.Role.SIGNATORY)
        pk = self._approved()                  # WP recruitment
        self._adv(pk)                          # begin → IN_PROGRESS (unsigned)
        # no letter may be generated yet
        r = self._gen_letter(pk, "AC")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(OnboardingLetter.objects.filter(case__document=pk)
                         .exists())
        # and the case cannot advance a stage either
        adv = self._adv(pk)
        self.assertEqual(adv.status_code, 400)
        self.assertIn("sign-off", adv.data["detail"])
        # the signatory sees the case in their queue on its own merits —
        # no drafted letter is needed to get there
        self.client.force_authenticate(sig)
        q = self.client.get("/api/v1/onboarding/letters/to-sign").data
        self.assertEqual([c["case_id"] for c in q["cases"]], [pk])
        self.assertEqual(q["cases"][0]["letters"], [])
        self.assertTrue(q["cases"][0]["terms"]["passport_no"])
        self.assertFalse(q["has_stamp"])
        # can't sign off without a stamp
        self.assertEqual(self.client.post(
            f"/api/v1/onboarding/cases/{pk}/sign-off").status_code, 400)
        self.client.post("/api/v1/onboarding/my-stamp",
                         {"stamp": self._tiny_png()}, format="multipart")
        r = self.client.post(f"/api/v1/onboarding/cases/{pk}/sign-off")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["cases"], [])              # queue cleared
        self.assertTrue(Notification.objects.filter(
            recipient=self.hr, title__icontains="signed off").exists())
        # now HR can generate — and it is stamped from birth
        r = self._gen_letter(pk, "AC")
        self.assertEqual(r.status_code, 201, r.data)
        ac = next(x for x in r.data["letters"] if x["kind"] == "AC")
        self.assertEqual(ac["status"], "SIGNED")
        self.assertEqual(OnboardingLetter.objects.get(pk=ac["id"]).approved_by_id,
                         sig.id)
        # and the stage moves again
        self.assertEqual(self._adv(pk).status_code, 200)

    def test_letters_generated_after_signoff_are_stamped(self):
        sig = make_user("ob_sig3", User.Role.SIGNATORY)
        self.client.force_authenticate(sig)
        self.client.post("/api/v1/onboarding/my-stamp",
                         {"stamp": self._tiny_png()}, format="multipart")
        pk = self._approved()
        self._begin(pk)
        self._gen_letter(pk, "AC")
        self.client.force_authenticate(sig)
        self.client.post(f"/api/v1/onboarding/cases/{pk}/sign-off")
        # a letter generated AFTER sign-off comes out already SIGNED
        r = self._gen_letter(pk, "LOA")
        loa = next(x for x in r.data["letters"] if x["kind"] == "LOA")
        self.assertEqual(loa["status"], "SIGNED")

    def test_only_signatory_can_sign_or_see_queue(self):
        pk = self._approved()
        self._begin(pk)
        self._gen_letter(pk, "AC")
        self.client.force_authenticate(self.pm)
        self.assertEqual(self.client.get(
            "/api/v1/onboarding/letters/to-sign").status_code, 403)
        self.assertEqual(self.client.post(
            f"/api/v1/onboarding/cases/{pk}/sign-off").status_code, 400)

    def test_allowances_captured_and_on_appointment_letter(self):
        from core.models import OnboardingCase
        from core.onboarding import _clean_allowances, letter_defaults
        # the cleaner keeps valid rows and drops blank / non-positive ones, and
        # each line carries its own MVR/USD currency (default from the case)
        self.assertEqual(
            _clean_allowances([{"type": "Food", "amount": "500", "currency": "USD"},
                               {"type": "", "amount": "9"},      # no type
                               {"type": "T", "amount": "0"}],    # non-positive
                              default_currency="MVR"),
            [{"type": "Food", "amount": "500", "currency": "USD"}])
        # a missing/invalid currency falls back to the case default
        self.assertEqual(
            _clean_allowances([{"type": "Food", "amount": "500", "currency": "x"}],
                              default_currency="USD"),
            [{"type": "Food", "amount": "500", "currency": "USD"}])
        pk = self._create().data["id"]
        self.client.force_authenticate(self.pm)
        r = self.client.patch(f"/api/v1/onboarding/{pk}", {"allowances": [
            {"type": "Food", "amount": "500", "currency": "USD"},
            {"type": "Transport", "amount": "300"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["allowances"]), 2)
        # they format onto the appointment letter in each line's own currency
        case = OnboardingCase.objects.get(document_id=pk)
        allw = letter_defaults(case, "LOA")["allowances"]
        self.assertEqual(allw[0], {"label": "Food", "amount": "USD 500.00"})
        self.assertEqual(allw[1], {"label": "Transport", "amount": "MVR 300.00"})

    def test_passport_scan_extracts_and_normalises(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from . import passport_extract as px
        orig = px._call_claude
        px._call_claude = lambda block, model: {
            "full_name": "  Ravi Kumar ", "passport_no": "N1234567",
            "nationality": "Indian", "date_of_birth": "1990-03-14",
            "passport_expiry": "not-a-date", "gender": "male"}
        try:
            f = SimpleUploadedFile("p.jpg", b"\xff\xd8fake",
                                   content_type="image/jpeg")
            fields = px.scan(f, model="x")
        finally:
            px._call_claude = orig
        self.assertEqual(fields["full_name"], "Ravi Kumar")
        self.assertEqual(fields["date_of_birth"], "1990-03-14")
        self.assertEqual(fields["passport_expiry"], "")   # unparseable → blank
        self.assertEqual(fields["gender"], "Male")

    def test_passport_scan_endpoint_gated(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from . import passport_extract as px
        orig = px.scan
        px.scan = lambda up, model=None: {
            "full_name": "Nuwan", "passport_no": "N9", "nationality": "Sri Lankan",
            "date_of_birth": "", "passport_expiry": "", "gender": ""}
        try:
            self.client.force_authenticate(self.pm)      # a raiser
            f = SimpleUploadedFile("p.jpg", b"x", content_type="image/jpeg")
            r = self.client.post("/api/v1/onboarding/passport-scan",
                                 {"file": f}, format="multipart")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.data["fields"]["full_name"], "Nuwan")
            self.client.force_authenticate(self.se)      # not a raiser
            f2 = SimpleUploadedFile("p.jpg", b"x", content_type="image/jpeg")
            r2 = self.client.post("/api/v1/onboarding/passport-scan",
                                  {"file": f2}, format="multipart")
            self.assertEqual(r2.status_code, 403)
        finally:
            px.scan = orig

    def test_checklist_document_is_downloadable(self):
        pk = self._create().data["id"]
        self._attach_all(pk)                           # pm is authenticated
        detail = self.client.get(f"/api/v1/onboarding/{pk}").data
        cv = next(x for x in detail["checklist"] if x["kind"] == "CV")
        self.assertTrue(cv["present"])
        self.assertIsNotNone(cv["att_id"])
        dl = self.client.get(
            f"/api/v1/onboarding/{pk}/attachments/{cv['att_id']}")
        self.assertEqual(dl.status_code, 200)
        self.assertIsNotNone(detail["photo_att_id"])   # passport photo exposed

    def test_fee_invoice_attaches_to_pyr(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pk = self._approved()
        self._begin(pk); self._adv(pk)
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk); self._adv(pk)                   # → WP_DEPOSIT
        self.client.force_authenticate(self.hr)
        inv = SimpleUploadedFile("invoice.pdf", b"%PDF inv",
                                 content_type="application/pdf")
        r = self.client.post(f"/api/v1/onboarding/{pk}/fee",
                             {"amount": "1500", "payee": "Immigration",
                              "file": inv}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        pyr = OnboardingCase.objects.get(pk=pk).fees.get(
            stage="WP_DEPOSIT").document
        self.assertTrue(pyr.attachments.filter(kind="QUOTATION").exists())
        self.assertTrue(pyr.payment_request.has_supporting_doc)

    def test_stage_document_upload_and_download(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pk = self._approved()
        self._begin(pk); self._adv(pk)                 # → WP_APPLICATION
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk)                                  # → WP_APPROVED
        self.client.force_authenticate(self.hr)
        f = SimpleUploadedFile("entrypass.pdf", b"%PDF-1.4 pass",
                               content_type="application/pdf")
        r = self.client.post(f"/api/v1/onboarding/{pk}/stage-doc",
                             {"slot": "ENTRY_PASS", "file": f},
                             format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        docs = {d["slot"]: d for d in r.data["documents"]}
        self.assertIn("ENTRY_PASS", docs)             # WP milestone, reached
        self.assertIsNotNone(docs["ENTRY_PASS"]["doc"])
        self.assertNotIn("DEPOSIT_RECEIPT", docs)     # its stage not reached yet
        att_id = docs["ENTRY_PASS"]["doc"]["id"]
        dl = self.client.get(f"/api/v1/onboarding/{pk}/attachments/{att_id}")
        self.assertEqual(dl.status_code, 200)

    def test_stage_document_refused_before_stage_reached(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pk = self._approved()
        self._begin(pk)                                  # WP_APPOINTMENT only
        self.client.force_authenticate(self.hr)
        f = SimpleUploadedFile("x.pdf", b"x")
        r = self.client.post(f"/api/v1/onboarding/{pk}/stage-doc",
                             {"slot": "ENTRY_PASS", "file": f},
                             format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_fee_slot_surfaces_finance_payment_slip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import Attachment
        pk = self._approved()
        self._begin(pk); self._adv(pk)
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk); self._adv(pk)                   # → WP_DEPOSIT
        self.client.force_authenticate(self.hr)
        self.client.post(f"/api/v1/onboarding/{pk}/fee",
                         {"amount": "1500", "payee": "Immigration"},
                         format="json")
        pyr = OnboardingCase.objects.get(pk=pk).fees.get(
            stage="WP_DEPOSIT").document
        Attachment.objects.create(
            document=pyr, revision=pyr.current_revision, kind="PAYMENT_SLIP",
            file=SimpleUploadedFile("slip.pdf", b"%PDF slip"),
            file_name="slip.pdf", content_type="application/pdf",
            size_bytes=9, uploaded_by=self.hr)
        detail = self.client.get(f"/api/v1/onboarding/{pk}").data
        dep = next(d for d in detail["documents"]
                   if d["slot"] == "DEPOSIT_RECEIPT")
        self.assertEqual(dep["pyr_ref"], pyr.ref)
        self.assertIsNotNone(dep["slip"])             # Finance slip surfaced
        dl = self.client.get(
            f"/api/v1/onboarding/{pk}/attachments/{dep['slip']['id']}")
        self.assertEqual(dl.status_code, 200)

    def test_bv_certificate_slot_on_bv_track(self):
        from . import onboarding as ob
        pk = self._approved(route="BV", bv_justification="urgent",
                            nationality="Indian")
        self._begin(pk)                                  # begin → BV_SPONSOR
        OnboardingCase.objects.filter(pk=pk).update(stage="BV_APPROVED")
        case = OnboardingCase.objects.get(pk=pk)
        slots = {d["slot"] for d in ob.documents_list(case)}
        self.assertIn("BV_CERTIFICATE", slots)
        self.assertIn("INSURANCE_POLICY", slots)      # earlier BV fee slot
        self.assertNotIn("ENTRY_PASS", slots)         # WP conversion not reached

    def _walk_to_arrival(self, pk, arrived="2026-08-01"):
        self._begin(pk); self._adv(pk)                   # → WP_APPLICATION
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk); self._adv(pk)                     # → WP_DEPOSIT
        self._pay_fee(pk, "WP_DEPOSIT")
        self._adv(pk)                                    # → WP_TICKET
        self._pay_fee(pk, "WP_TICKET")
        return self._adv(pk, arrived_date=arrived)       # → WP_ARRIVED

    def _raise_fee(self, pk, **extra):
        self.client.force_authenticate(self.hr)
        body = {"amount": "2954.47", "payee": "Travel agent", **extra}
        return self.client.post(f"/api/v1/onboarding/{pk}/fee", body,
                                format="json")

    def test_a_ticket_fee_can_be_raised_in_dollars(self):
        """The ticket is bought abroad and invoiced in dollars; the builder
        hard-coded rufiyaa for every onboarding fee (owner 2026-09-05)."""
        from .models import PaymentRequest
        pk = self._approved()
        self._begin(pk); self._adv(pk)                   # → WP_APPLICATION
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk); self._adv(pk)                     # → WP_DEPOSIT
        self._pay_fee(pk, "WP_DEPOSIT")
        self._adv(pk)                                    # → WP_TICKET
        r = self._raise_fee(pk, currency="USD")
        self.assertEqual(r.status_code, 201, r.data)
        fee = OnboardingCase.objects.get(pk=pk).fees.get(stage="WP_TICKET")
        pr = PaymentRequest.objects.get(document=fee.document)
        self.assertEqual(pr.currency, "USD")
        self.assertEqual(pr.amount_requested, Decimal("2954.47"))

    def test_a_fee_is_still_rufiyaa_unless_asked_otherwise(self):
        from .models import PaymentRequest
        pk = self._approved()
        self._begin(pk); self._adv(pk)
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk); self._adv(pk)                     # → WP_DEPOSIT
        r = self._raise_fee(pk)
        self.assertEqual(r.status_code, 201, r.data)
        fee = OnboardingCase.objects.get(pk=pk).fees.get(stage="WP_DEPOSIT")
        self.assertEqual(
            PaymentRequest.objects.get(document=fee.document).currency, "MVR")

    def test_an_unknown_currency_is_refused(self):
        pk = self._approved()
        self._begin(pk); self._adv(pk)
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk); self._adv(pk)
        r = self._raise_fee(pk, currency="EUR")
        self.assertEqual(r.status_code, 400)
        self.assertIn("MVR or USD", r.data["detail"])

    def test_the_job_title_on_the_case_reaches_the_employee(self):
        """The case states the occupation; the record never carried it — all
        fifteen live conversions had an empty job title (owner 2026-09-05)."""
        pk = self._approved()
        self._walk_to_arrival(pk)
        emp = OnboardingCase.objects.get(pk=pk).employee
        self.assertEqual(emp.job_title, "Mason")         # case trade_designation

    def test_a_man_already_on_file_gets_the_new_case_terms(self):
        """He is linked to the record that holds his history rather than given
        a second one — but the engagement being mobilised is this case's, so
        its title, salary and start date are the ones that apply. All three
        were being dropped (owner 2026-09-05)."""
        from decimal import Decimal

        from datetime import date
        from .models import Employee, EmployeeSiteAllocation
        old = Employee.objects.create(
            emp_no="EMP-9100", full_name="Returning Man",
            passport_no="P1234567",                      # same as the case
            basic_pay=Decimal("5000"), currency="MVR",
            join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(
            employee=old, site=self.site, from_date=date(2026, 1, 1))
        pk = self._approved()
        self._walk_to_arrival(pk, arrived="2026-08-01")
        case = OnboardingCase.objects.get(pk=pk)
        self.assertEqual(case.employee_id, old.id)       # linked, not minted
        old.refresh_from_db()
        self.assertEqual(old.job_title, "Mason")
        self.assertEqual(old.basic_pay, Decimal("8000"))  # the case's salary
        self.assertEqual(str(old.join_date), "2026-08-01")   # the day he landed
        self.assertEqual(str(old.site_allocations.get().from_date), "2026-08-01")
        self.assertEqual(Employee.objects.filter(
            passport_no="P1234567").count(), 1)

    def test_a_blank_on_the_case_never_wipes_the_record(self):
        from decimal import Decimal

        from datetime import date
        from .models import Employee
        old = Employee.objects.create(
            emp_no="EMP-9101", full_name="Returning Man",
            passport_no="P1234567", basic_pay=Decimal("5000"),
            currency="MVR", join_date=date(2026, 1, 1), job_title="Foreman")
        pk = self._approved()
        case = OnboardingCase.objects.get(pk=pk)
        case.trade_designation = ""
        case.proposed_salary = None
        case.save(update_fields=["trade_designation", "proposed_salary"])
        self._walk_to_arrival(pk)
        old.refresh_from_db()
        self.assertEqual(old.job_title, "Foreman")       # kept
        self.assertEqual(old.basic_pay, Decimal("5000"))  # kept

    def test_arrival_hands_over_to_employee_db(self):
        from .models import Employee, Notification
        pk = self._approved()
        self._begin(pk); self._adv(pk)                   # → WP_APPLICATION
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk); self._adv(pk)                   # → WP_DEPOSIT
        self._pay_fee(pk, "WP_DEPOSIT")
        self._adv(pk)                                  # → WP_TICKET
        self._pay_fee(pk, "WP_TICKET")
        r = self._adv(pk, arrived_date="2026-08-01")   # → WP_ARRIVED + handover
        # the worker joins the Employee DB on ARRIVAL (salary starts then),
        # not at completion
        self.assertTrue(r.data["employee_no"].startswith("EMP-"))
        self._adv(pk)                                  # → WP_MEDICAL
        self._sdata(pk, medical_result="PASS")
        self._adv(pk)                                  # → WP_ISSUED
        r = self._adv(pk)                              # → COMPLETED
        self.assertEqual(r.data["status"], "COMPLETED")
        case = OnboardingCase.objects.get(pk=pk)
        emp = case.employee
        self.assertIsNotNone(emp)
        self.assertEqual(emp.engagement_type, "DIRECT")
        self.assertEqual(emp.employment_type, "PERMANENT")
        self.assertEqual(emp.full_name, case.full_name)
        self.assertEqual(emp.passport_no, case.passport_no)
        self.assertEqual(str(emp.join_date), "2026-08-01")   # arrival date
        self.assertTrue(emp.is_active)
        self.assertFalse(emp.hire_pending)                   # already approved
        alloc = emp.site_allocations.filter(to_date__isnull=True).first()
        self.assertEqual(alloc.site_id, case.document.site_id)
        self.assertEqual(str(alloc.from_date), "2026-08-01")
        self.assertTrue(bool(emp.photo))              # passport photo carried over
        # only one employee across the whole walk (arrival + completion)
        self.assertEqual(Employee.objects.filter(pk=emp.pk).count(), 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.hr, title__icontains="on site").exists())

    def test_editing_arrival_date_moves_salary_start(self):
        pk = self._approved()
        self._begin(pk); self._adv(pk)                   # → WP_APPLICATION
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk); self._adv(pk)                   # → WP_DEPOSIT
        self._pay_fee(pk, "WP_DEPOSIT")
        self._adv(pk)                                  # → WP_TICKET
        self._pay_fee(pk, "WP_TICKET")
        self._adv(pk, arrived_date="2026-08-10")       # → WP_ARRIVED (recorded late)
        emp = OnboardingCase.objects.get(pk=pk).employee
        self.assertEqual(str(emp.join_date), "2026-08-10")
        # HR corrects it to the day the worker actually landed
        self._sdata(pk, arrived_date="2026-08-03")
        case = OnboardingCase.objects.get(pk=pk)
        emp.refresh_from_db()
        self.assertEqual(str(case.arrived_date), "2026-08-03")
        self.assertEqual(str(case.medical_due), "2026-08-17")   # +14 recomputed
        self.assertEqual(str(emp.join_date), "2026-08-03")      # salary start moved
        alloc = emp.site_allocations.filter(to_date__isnull=True).first()
        self.assertEqual(str(alloc.from_date), "2026-08-03")

    def _subcontractor(self):
        from .models import Subcontractor
        return Subcontractor.objects.create(
            site=self.site, name="Reef Builders",
            status=Subcontractor.Status.APPROVED)

    def test_no_medical_on_business_visa(self):
        from . import onboarding as ob
        # recruitment BV — medical belongs to the WP conversion, not the BV
        pk = self._approved(route="BV", bv_justification="urgent",
                            nationality="Indian")
        case = OnboardingCase.objects.get(pk=pk)
        seq = ob.sequence(case)
        self.assertNotIn("BV_MEDICAL", seq)
        self.assertIn("WP_MEDICAL", seq)               # only in the conversion
        self.assertLess(seq.index("WP_APPROVED"), seq.index("WP_MEDICAL"))

    def test_subcontract_bv_has_no_conversion_or_medical(self):
        from . import onboarding as ob
        sub = self._subcontractor()
        pk = self._approved(route="BV", bv_justification="short job",
                            nationality="Indian", bv_purpose="SUBCONTRACT",
                            subcontractor_id=sub.id, proposed_salary="")
        case = OnboardingCase.objects.get(pk=pk)
        seq = ob.sequence(case)
        self.assertEqual(seq[-1], "BV_ARRIVED")        # ends on arrival
        self.assertNotIn("WP_ISSUED", seq)
        self.assertNotIn("WP_MEDICAL", seq)

    def test_subcontract_worker_joins_as_subcontract_not_payroll(self):
        sub = self._subcontractor()
        pk = self._approved(route="BV", bv_justification="short job",
                            nationality="Indian", bv_purpose="SUBCONTRACT",
                            subcontractor_id=sub.id, proposed_salary="")
        # walk to arrival: begin → BV_SPONSOR, BV_INSURANCE(fee), BV_APPLICATION
        # (portal), BV_APPROVED, BV_VISA_FEE(fee), BV_TICKET(fee), BV_ARRIVED
        self._begin(pk)                                  # BV_SPONSOR
        self._adv(pk)                                  # BV_INSURANCE
        self._pay_fee(pk, "BV_INSURANCE")
        self._adv(pk)                                  # BV_APPLICATION
        self._sdata(pk, portal_status="APPROVED")
        # The visa's dates are captured the moment it is approved — the
        # clock starts there, not on arrival (owner 2026-08-21).
        self._adv(pk, bv_approved_date="2026-07-15", bv_expiry="2026-10-30")   # BV_APPROVED
        self._adv(pk)                                  # BV_VISA_FEE
        self._pay_fee(pk, "BV_VISA_FEE")
        self._adv(pk)                                  # BV_TICKET
        self._pay_fee(pk, "BV_TICKET")
        r = self._adv(pk, arrived_date="2026-08-01", bv_expiry="2026-10-30")
        self.assertEqual(r.data["stage"], "BV_ARRIVED")
        case = OnboardingCase.objects.get(pk=pk)
        emp = case.employee
        self.assertIsNotNone(emp)
        self.assertEqual(emp.engagement_type, "SUBCONTRACT")
        self.assertIsNone(emp.basic_pay)               # never on payroll
        self.assertEqual(emp.subcontractor_id, sub.id)
        self.assertTrue(emp.is_active)
        self.assertIsNone(case.medical_due)            # no medical clock
        # advancing past arrival is refused — close on departure instead
        self.assertEqual(self._adv(pk).status_code, 400)

    def test_subcontract_close_on_departure(self):
        sub = self._subcontractor()
        pk = self._approved(route="BV", bv_justification="short job",
                            nationality="Indian", bv_purpose="SUBCONTRACT",
                            subcontractor_id=sub.id, proposed_salary="")
        self._begin(pk); self._adv(pk); self._pay_fee(pk, "BV_INSURANCE")
        self._adv(pk); self._sdata(pk, portal_status="APPROVED")
        self._adv(pk, bv_approved_date="2026-07-15", bv_expiry="2026-10-30")
        self._adv(pk); self._pay_fee(pk, "BV_VISA_FEE")
        self._adv(pk); self._pay_fee(pk, "BV_TICKET")
        self._adv(pk, arrived_date="2026-08-01", bv_expiry="2026-10-30")
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/onboarding/{pk}/close",
                             {"departed_date": "2026-09-15"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "COMPLETED")
        case = OnboardingCase.objects.get(pk=pk)
        emp = case.employee
        self.assertFalse(emp.is_active)                # left the country
        alloc = emp.site_allocations.first()
        self.assertEqual(str(alloc.to_date), "2026-09-15")

    def test_extend_visa_pushes_expiry_and_raises_fee(self):
        sub = self._subcontractor()
        pk = self._approved(route="BV", bv_justification="short job",
                            nationality="Indian", bv_purpose="SUBCONTRACT",
                            subcontractor_id=sub.id, proposed_salary="")
        self._begin(pk); self._adv(pk); self._pay_fee(pk, "BV_INSURANCE")
        self._adv(pk); self._sdata(pk, portal_status="APPROVED")
        self._adv(pk, bv_approved_date="2026-07-15", bv_expiry="2026-10-30")
        self._adv(pk); self._pay_fee(pk, "BV_VISA_FEE")
        self._adv(pk); self._pay_fee(pk, "BV_TICKET")
        self._adv(pk, arrived_date="2026-08-01", bv_expiry="2026-10-30")
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/onboarding/{pk}/extend",
                             {"new_expiry": "2027-01-30", "amount": "800",
                              "payee": "Immigration"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        case = OnboardingCase.objects.get(pk=pk)
        self.assertEqual(str(case.bv_expiry), "2027-01-30")
        self.assertEqual(case.bv_renewals, 1)
        self.assertTrue(case.fees.filter(stage="BV_EXT_1").exists())
        # a shorter/earlier expiry is rejected
        r2 = self.client.post(f"/api/v1/onboarding/{pk}/extend",
                             {"new_expiry": "2026-12-01", "amount": "800",
                              "payee": "x"}, format="json")
        self.assertEqual(r2.status_code, 400)

    def test_subcontract_needs_a_subcontractor(self):
        pk = self._create(route="BV", bv_justification="job",
                          bv_purpose="SUBCONTRACT", proposed_salary="").data["id"]
        self._attach_all(pk)
        r = self.client.post(f"/api/v1/onboarding/{pk}/submit")
        self.assertEqual(r.status_code, 400)
        self.assertIn("subcontractor", r.data["detail"].lower())

    def _mobile_as(self, user):
        user.set_password("verify-123")
        user.save()
        m = APIClient()
        tok = m.post("/api/mobile/v1/auth/login",
                     {"username": user.username, "password": "verify-123"},
                     format="json").data["token"]
        m.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
        return m

    def test_director_approves_onboarding_on_mobile(self):
        r = self._create()
        pk, ref = r.data["id"], r.data["ref"]
        self._attach_all(pk)
        self.client.post(f"/api/v1/onboarding/{pk}/submit")
        m = self._mobile_as(self.director)
        q = m.get("/api/mobile/v1/queue")
        self.assertIn(ref, [i["ref"] for i in q.data["items"]])
        detail = m.get(f"/api/mobile/v1/documents/{ref}")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(any(f["k"] == "Candidate"
                            for f in detail.data["summary"]))
        a = m.post(f"/api/mobile/v1/documents/{ref}/approve", {}, format="json")
        self.assertEqual(a.status_code, 200, a.data)
        self.assertEqual(Document.objects.get(pk=pk).status, "APPROVED")
        # second tap → 409 already actioned
        self.assertEqual(m.post(f"/api/mobile/v1/documents/{ref}/approve", {},
                                format="json").status_code, 409)

    def test_mobile_onboarding_return_requires_reason(self):
        r = self._create()
        pk, ref = r.data["id"], r.data["ref"]
        self._attach_all(pk)
        self.client.post(f"/api/v1/onboarding/{pk}/submit")
        m = self._mobile_as(self.director)
        self.assertEqual(m.post(f"/api/mobile/v1/documents/{ref}/return", {},
                                format="json").status_code, 400)
        ok = m.post(f"/api/mobile/v1/documents/{ref}/return",
                    {"comment": "Passport expires too soon"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(Document.objects.get(pk=pk).status, "RETURNED")

    def test_medical_clock_alerts_then_escalates_and_is_idempotent(self):
        from datetime import date, timedelta
        from . import onboarding as ob
        from .models import Notification
        pk = self._approved()
        self._begin(pk)                                  # begin → IN_PROGRESS
        case = OnboardingCase.objects.get(pk=pk)
        today = date(2026, 8, 1)
        case.arrived_date = today - timedelta(days=8)
        case.medical_due = today + timedelta(days=6)   # 6 days out → T-7 band
        case.save()
        res = ob.run_clocks(today=today)
        self.assertEqual(res["medical"], 1)
        case.refresh_from_db()
        self.assertEqual(case.medical_alert, "T7")
        self.assertTrue(Notification.objects.filter(
            recipient=self.hr, title__icontains="medical due").exists())
        self.assertFalse(Notification.objects.filter(   # not escalated yet
            recipient=self.director, title__icontains="medical").exists())
        # same day re-run → no repeat
        before = Notification.objects.filter(recipient=self.hr).count()
        ob.run_clocks(today=today)
        self.assertEqual(before,
                         Notification.objects.filter(recipient=self.hr).count())
        # overdue → escalates to the Director
        Notification.objects.all().delete()
        ob.run_clocks(today=case.medical_due + timedelta(days=2))
        case.refresh_from_db()
        self.assertEqual(case.medical_alert, "OVERDUE")
        self.assertTrue(Notification.objects.filter(
            recipient=self.director,
            title__icontains="medical OVERDUE").exists())

    def test_medical_clock_stops_once_result_recorded(self):
        from datetime import date, timedelta
        from . import onboarding as ob
        pk = self._approved()
        self._begin(pk)
        case = OnboardingCase.objects.get(pk=pk)
        today = date(2026, 8, 1)
        case.arrived_date = today - timedelta(days=10)
        case.medical_due = today - timedelta(days=1)   # overdue…
        case.medical_result = "PASS"                   # …but already passed
        case.save()
        res = ob.run_clocks(today=today)
        self.assertEqual(res["medical"], 0)

    def test_bv_expiry_clock_escalates_to_director(self):
        from datetime import date, timedelta
        from . import onboarding as ob
        from .models import Notification
        pk = self._approved(route="BV", bv_justification="urgent",
                            nationality="Indian")
        self._begin(pk)                                  # begin → BV_SPONSOR
        case = OnboardingCase.objects.get(pk=pk)
        today = date(2026, 8, 1)
        case.bv_expiry = today + timedelta(days=12)    # T-14 band → HR only
        case.save()
        ob.run_clocks(today=today)
        case.refresh_from_db()
        self.assertEqual(case.bv_alert, "T14")
        self.assertFalse(Notification.objects.filter(
            recipient=self.director,
            title__icontains="business visa").exists())
        # 10 days on → 2 days left → T-3 escalates to the Director
        ob.run_clocks(today=today + timedelta(days=10))
        case.refresh_from_db()
        self.assertEqual(case.bv_alert, "T3")
        self.assertTrue(Notification.objects.filter(
            recipient=self.director,
            title__icontains="business visa expires").exists())

    def test_stale_pre_arrival_digest_dedupes(self):
        from datetime import timedelta
        from django.utils import timezone
        from . import onboarding as ob
        from .models import Notification
        pk = self._approved()
        self._begin(pk)                                  # pre-arrival, IN_PROGRESS
        OnboardingCase.objects.filter(pk=pk).update(
            updated_at=timezone.now() - timedelta(days=20))
        res = ob.run_clocks()
        self.assertEqual(res["stale"], 1)
        self.assertTrue(res["digest_sent"])
        self.assertTrue(Notification.objects.filter(
            recipient=self.hr, title__icontains="stale").exists())
        res2 = ob.run_clocks()                          # same day → deduped
        self.assertFalse(res2["digest_sent"])

    def test_medical_fail_blocks_and_flags_pd(self):
        from .models import Notification
        pk = self._approved()
        self._begin(pk); self._adv(pk)                   # → WP_APPLICATION
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

    def _bv_to_approval(self):
        """Walk a subcontract BV case up to the point the visa is approved."""
        sub = self._subcontractor()
        pk = self._approved(route="BV", bv_justification="short job",
                            nationality="Indian", bv_purpose="SUBCONTRACT",
                            subcontractor_id=sub.id, proposed_salary="")
        self._begin(pk); self._adv(pk); self._pay_fee(pk, "BV_INSURANCE")
        self._adv(pk); self._sdata(pk, portal_status="APPROVED")
        return pk

    def test_the_visa_clock_starts_at_approval_not_arrival(self):
        """A visa runs from the day it is approved. A man approved three weeks
        before he flies has already spent three weeks of it, and the register
        used to show him with no clock at all until he landed (owner
        2026-08-21)."""
        from datetime import timedelta

        from django.utils import timezone as tz

        from . import onboarding as ob
        from .models import OnboardingCase
        today = tz.localdate()
        pk = self._bv_to_approval()
        r = self._adv(pk, bv_approved_date=str(today - timedelta(days=20)),
                      bv_expiry=str(today + timedelta(days=10)))
        self.assertEqual(r.status_code, 200, r.data)
        case = OnboardingCase.objects.get(pk=pk)
        self.assertEqual(case.stage, "BV_APPROVED")
        self.assertEqual(case.bv_approved_date, today - timedelta(days=20))
        self.assertIsNone(case.arrived_date)         # not flown yet
        # ...and the countdown is already running against him.
        reg = ob.bv_register()
        row = next(r for r in reg["pipeline"] if r["case_id"] == pk)
        self.assertEqual(row["days_left"], 10)
        self.assertEqual(row["level"], "T14")
        self.assertEqual(row["approved_on"], today - timedelta(days=20))
        # He counts as expiring even though he is still overseas.
        self.assertEqual(reg["counts"]["expiring"], 1)

    def test_approval_stage_demands_the_visa_dates(self):
        from datetime import timedelta

        from django.utils import timezone as tz
        today = tz.localdate()
        pk = self._bv_to_approval()
        r = self._adv(pk)
        self.assertEqual(r.status_code, 400)
        self.assertIn("approved", r.data["detail"].lower())
        r = self._adv(pk, bv_approved_date=str(today))
        self.assertEqual(r.status_code, 400)
        self.assertIn("expiry", r.data["detail"].lower())
        # An expiry on or before the approval date is not a visa.
        r = self._adv(pk, bv_approved_date=str(today),
                      bv_expiry=str(today - timedelta(days=1)))
        self.assertEqual(r.status_code, 400)

    def test_arrival_does_not_re_ask_for_an_expiry_it_already_has(self):
        from datetime import timedelta

        from django.utils import timezone as tz

        from . import onboarding as ob
        from .models import OnboardingCase
        today = tz.localdate()
        pk = self._bv_to_approval()
        self._adv(pk, bv_approved_date=str(today - timedelta(days=20)),
                  bv_expiry=str(today + timedelta(days=10)))
        self._adv(pk); self._pay_fee(pk, "BV_VISA_FEE")
        self._adv(pk); self._pay_fee(pk, "BV_TICKET")
        case = OnboardingCase.objects.get(pk=pk)
        self.assertEqual(ob.case_dict(case)["next_needs"], "arrival")
        r = self._adv(pk, arrived_date=str(today))     # no expiry re-entered
        self.assertEqual(r.status_code, 200, r.data)
        case.refresh_from_db()
        # The expiry captured at approval is still the one on the case — it did
        # not silently reset to a fresh count from the arrival date.
        self.assertEqual(case.bv_expiry, today + timedelta(days=10))

    def test_a_case_past_approval_with_no_expiry_is_flagged(self):
        """The cases that were mid-flight when this changed have a visa running
        and no date recorded — the register has to say so rather than show a
        blank countdown."""
        from . import onboarding as ob
        from .models import OnboardingCase
        pk = self._bv_to_approval()
        OnboardingCase.objects.filter(pk=pk).update(stage="BV_TICKET")
        reg = ob.bv_register()
        row = next(r for r in reg["pipeline"] if r["case_id"] == pk)
        self.assertTrue(row["expiry_missing"])
        self.assertEqual(reg["counts"]["awaiting_expiry"], 1)

    def test_visa_dates_can_be_recorded_after_the_approval_stage(self):
        """The cases already past approval when the clock moved there have a
        visa running and nothing entered — HR must be able to record it without
        walking the case backwards (owner 2026-08-21)."""
        from datetime import timedelta

        from django.utils import timezone as tz

        from . import onboarding as ob
        from .models import OnboardingCase
        today = tz.localdate()
        pk = self._bv_to_approval()
        OnboardingCase.objects.filter(pk=pk).update(stage="BV_TICKET")
        case = OnboardingCase.objects.get(pk=pk)
        self.assertTrue(ob.case_dict(case)["can_set_visa_dates"])
        self.client.force_authenticate(self.hr)
        r = self.client.post(
            f"/api/v1/onboarding/{pk}/stage-data",
            {"bv_approved_date": str(today - timedelta(days=15)),
             "bv_expiry": str(today + timedelta(days=5))}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        case.refresh_from_db()
        self.assertEqual(case.bv_expiry, today + timedelta(days=5))
        row = next(x for x in ob.bv_register()["pipeline"]
                   if x["case_id"] == pk)
        self.assertEqual(row["days_left"], 5)
        self.assertFalse(row["expiry_missing"])

    def test_visa_dates_are_refused_before_the_visa_is_approved(self):
        from django.utils import timezone as tz
        today = tz.localdate()
        pk = self._bv_to_approval()          # still at BV_APPLICATION
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/onboarding/{pk}/stage-data",
                             {"bv_expiry": str(today)}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not been approved", r.data["detail"])

    def test_arrival_asks_for_the_arrival_date_only(self):
        """One date, one field. Arrival used to ask for the BV expiry as well,
        which after the clock moved to approval put two inputs for the same
        date on one panel (owner 2026-08-21)."""
        from django.utils import timezone as tz

        from . import onboarding as ob
        from .models import OnboardingCase
        pk = self._bv_to_approval()
        OnboardingCase.objects.filter(pk=pk).update(stage="BV_TICKET")
        case = OnboardingCase.objects.get(pk=pk)
        # Even with NO expiry recorded, arrival asks only for the arrival date
        # — the visa dates are entered on their own row.
        self.assertIsNone(case.bv_expiry)
        self.assertEqual(ob.case_dict(case)["next_needs"], "arrival")
        self.assertTrue(ob.case_dict(case)["can_set_visa_dates"])
        # ...and it refuses to mark him arrived until they are recorded, rather
        # than silently starting a clock from the arrival date.
        self._pay_fee(pk, "BV_TICKET")
        r = self._adv(pk, arrived_date=str(tz.localdate()))
        self.assertEqual(r.status_code, 400)
        self.assertIn("since it was approved", r.data["detail"])

    def test_visa_dates_stay_editable_after_arrival_and_into_conversion(self):
        """The men already in the country on a running visa are the ones whose
        dates matter most — they are racing to convert before it lapses. The
        first cut hardcoded the BV stages, so the field vanished the moment a
        case moved on to the work-permit conversion (owner 2026-08-21)."""
        from datetime import timedelta

        from django.utils import timezone as tz

        from . import onboarding as ob
        from .models import OnboardingCase
        today = tz.localdate()
        # A recruitment BV — it converts, so it has the WP tail.
        pk = self._approved(route="BV", bv_justification="urgent",
                            nationality="Indian")
        self._begin(pk)
        case = OnboardingCase.objects.get(pk=pk)
        self.assertIn("WP_APPOINTMENT", ob.sequence(case))
        for stage in ("BV_ARRIVED", "WP_APPOINTMENT", "WP_APPLICATION",
                      "WP_MEDICAL"):
            OnboardingCase.objects.filter(pk=pk).update(stage=stage)
            case.refresh_from_db()
            self.assertTrue(ob.case_dict(case)["can_set_visa_dates"],
                            f"visa dates not editable at {stage}")
        # ...and they can actually be recorded there.
        self.client.force_authenticate(self.hr)
        r = self.client.post(
            f"/api/v1/onboarding/{pk}/stage-data",
            {"bv_approved_date": str(today - timedelta(days=25)),
             "bv_expiry": str(today + timedelta(days=5))}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        case.refresh_from_db()
        self.assertEqual(case.bv_approved_date, today - timedelta(days=25))

    def test_visa_dates_are_not_editable_before_approval(self):
        from . import onboarding as ob
        from .models import OnboardingCase
        pk = self._approved(route="BV", bv_justification="urgent",
                            nationality="Indian")
        case = OnboardingCase.objects.get(pk=pk)
        for stage in ("BV_SPONSOR", "BV_INSURANCE", "BV_APPLICATION"):
            OnboardingCase.objects.filter(pk=pk).update(stage=stage)
            case.refresh_from_db()
            self.assertFalse(ob.case_dict(case)["can_set_visa_dates"],
                             f"visa dates offered at {stage}, before approval")

    def test_bv_register_buckets_and_countdown(self):
        """The BV register splits in-country (soonest expiry first, with a
        countdown level), pipeline (not arrived) and closed (converted or
        departed), and counts the expiring ones."""
        from datetime import timedelta

        from django.utils import timezone as tz

        from . import onboarding as ob
        sub = self._subcontractor()
        # in-country: walk a subcontract BV to arrival, expiry 10 days out
        pk1 = self._approved(route="BV", bv_justification="short job",
                             nationality="Indian", bv_purpose="SUBCONTRACT",
                             subcontractor_id=sub.id, proposed_salary="")
        today = tz.localdate()
        self._begin(pk1); self._adv(pk1); self._pay_fee(pk1, "BV_INSURANCE")
        self._adv(pk1); self._sdata(pk1, portal_status="APPROVED")
        self._adv(pk1, bv_approved_date=str(today - timedelta(days=20)),
                  bv_expiry=str(today + timedelta(days=10)))
        self._adv(pk1); self._pay_fee(pk1, "BV_VISA_FEE")
        self._adv(pk1); self._pay_fee(pk1, "BV_TICKET")
        self._adv(pk1, arrived_date=str(today))
        # pipeline: a BV case still before arrival
        pk2 = self._approved(route="BV", bv_justification="urgent",
                             nationality="Indian")
        reg = ob.bv_register()
        in_ids = [r["case_id"] for r in reg["in_country"]]
        self.assertIn(pk1, in_ids)
        row = next(r for r in reg["in_country"] if r["case_id"] == pk1)
        self.assertEqual(row["days_left"], 10)
        self.assertEqual(row["level"], "T14")            # inside 14 days
        self.assertEqual(row["subcontractor"], sub.name)
        self.assertIn(pk2, [r["case_id"] for r in reg["pipeline"]])
        self.assertEqual(reg["counts"]["expiring"], 1)
        # departure closes it out of the live buckets
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/onboarding/{pk1}/close",
                             {"departed_date": str(today)}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        reg = ob.bv_register()
        self.assertNotIn(pk1, [r["case_id"] for r in reg["in_country"]])
        self.assertIn(pk1, [r["case_id"] for r in reg["closed"]])

    def test_bv_register_endpoint_roles(self):
        self.client.force_authenticate(self.hr)
        r = self.client.get("/api/v1/onboarding/bv-register")
        self.assertEqual(r.status_code, 200)
        self.assertIn("in_country", r.data)
        # PMs use the case list — the register is an HR/PD tool
        self.client.force_authenticate(self.pm)
        self.assertEqual(
            self.client.get("/api/v1/onboarding/bv-register").status_code, 403)

    def test_employment_agreement_sri_lankan_at_wp_approved(self):
        """The embassy-attestation Employment Agreement (EA) unlocks for a
        Sri Lankan once the work permit is approved — never for other
        nationalities (owner 2026-08-09)."""
        pk = self._approved(nationality="Sri Lankan")
        self._begin(pk)                                  # begin → WP_APPOINTMENT
        opts = {o["kind"]: o for o in self.client.get(
            f"/api/v1/onboarding/{pk}").data["letter_options"]}
        self.assertFalse(opts["EA"]["available"])      # not yet — WP not approved
        self._adv(pk)                                  # WP_APPLICATION
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk)                                  # WP_APPROVED
        opts = {o["kind"]: o for o in self.client.get(
            f"/api/v1/onboarding/{pk}").data["letter_options"]}
        self.assertTrue(opts["EA"]["available"])
        self.assertTrue(opts["EA"]["needs_sign"])
        # the signatory identity comes from the case sign-off, not HR's form
        self.assertNotIn("signatory_name", opts["EA"]["fields"])
        self.assertNotIn("signatory_designation", opts["EA"]["fields"])
        # generate it — fields prefill from the case, ref gets its own series
        r = self.client.post(f"/api/v1/onboarding/{pk}/letter",
                             {"kind": "EA", "fields": {
                                 "passport_issue_date": "12 Aug 2021"}},
                             format="json")
        self.assertIn(r.status_code, (200, 201), r.data)
        case = OnboardingCase.objects.get(pk=pk)
        lt = case.letters.get(kind="EA")
        self.assertTrue(lt.ref.startswith("EA-"))
        self.assertEqual(lt.fields["passport_issue_date"], "12 Aug 2021")

    def test_employment_agreement_not_for_other_nationalities(self):
        pk = self._approved(nationality="Bangladeshi")
        self._begin(pk)
        self._begin(pk)
        self._sdata(pk, portal_status="APPROVED")
        self._adv(pk)                                  # WP_APPROVED
        opts = {o["kind"]: o for o in self.client.get(
            f"/api/v1/onboarding/{pk}").data["letter_options"]}
        self.assertFalse(opts["EA"]["available"])

    def test_employment_agreement_template_renders_contract(self):
        from django.template.loader import render_to_string

        from . import onboarding as ob
        from .pdf import company_info
        pk = self._approved(nationality="Sri Lankan")
        case = OnboardingCase.objects.get(pk=pk)
        fields = ob.letter_defaults(case, "EA")
        html = render_to_string("pdf/letter_employment_agreement.html", {
            "co": company_info(), "ref": "EA-001",
            "issue_date": "09 Aug 2026", "draft": True, **fields})
        self.assertIn("Employment Agreement", html)
        self.assertIn(case.full_name, html)
        self.assertIn("Bureau of Foreign Employment", html)
        self.assertIn("Registered at the Embassy", html)
        self.assertIn("DRAFT", html)                   # unsigned = watermark

    def test_signed_letters_carry_the_actual_signers_name_and_title(self):
        """The rendered letter must carry WHO signed the case off — name and
        title from the sign-off approval, overriding whatever the draft had
        (owner 2026-08-09)."""
        from unittest.mock import patch

        sig = make_user("ob_sig_id", User.Role.SIGNATORY)
        sig.full_name = "Ibrahim Fikury Hussain"
        sig.designation = "Director"          # each signatory's OWN title
        sig.save(update_fields=["full_name", "designation"])
        pk = self._approved()
        self._adv(pk)                          # begin, still unsigned
        self.client.force_authenticate(sig)
        self.client.post("/api/v1/onboarding/my-stamp",
                         {"stamp": self._tiny_png()}, format="multipart")
        r = self.client.post(f"/api/v1/onboarding/cases/{pk}/sign-off")
        self.assertEqual(r.status_code, 200, r.data)
        rendered = []
        real = __import__("core.pdf", fromlist=["x"]).render_onboarding_letter
        def spy(document, kind, ref, fields, issue_date, **kw):
            rendered.append((kind, dict(fields), kw))
            return real(document, kind, ref, fields, issue_date, **kw)
        # the letter is produced AFTER the sign-off and carries that signer
        with patch("core.pdf.render_onboarding_letter", side_effect=spy):
            r = self._gen_letter(pk, "AC")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(rendered)
        kind, fields, kw = rendered[0]
        self.assertEqual(fields["signatory_name"], "Ibrahim Fikury Hussain")
        self.assertEqual(fields["signatory_designation"], "Director")
        self.assertTrue(kw.get("stamp_src"))           # signature stamp applied
        self.assertFalse(kw.get("draft"))              # official copy

    def test_admin_signoff_prints_authorised_signatory_title(self):
        # Only SIGNATORY/ADMIN may sign off; an admin signer prints as
        # "Authorised Signatory" with their own name.
        from unittest.mock import patch

        admin = make_user("ob_adm_id", User.Role.ADMIN)
        self.client.force_authenticate(admin)
        self.client.post("/api/v1/onboarding/my-stamp",
                         {"stamp": self._tiny_png()}, format="multipart")
        pk = self._approved()
        self._adv(pk)                          # begin, still unsigned
        self.client.force_authenticate(admin)
        r = self.client.post(f"/api/v1/onboarding/cases/{pk}/sign-off")
        self.assertEqual(r.status_code, 200, r.data)
        rendered = []
        real = __import__("core.pdf", fromlist=["x"]).render_onboarding_letter
        def spy(document, kind, ref, fields, issue_date, **kw):
            rendered.append(dict(fields))
            return real(document, kind, ref, fields, issue_date, **kw)
        with patch("core.pdf.render_onboarding_letter", side_effect=spy):
            r = self._gen_letter(pk, "AC")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(rendered[0]["signatory_name"], admin.full_name)
        self.assertEqual(rendered[0]["signatory_designation"],
                         "Authorised Signatory")


class SignOffReachesTheQueueTests(TestCase):
    """The appointment sign-off belongs in the approvals queue.

    It had a queue of its own inside the onboarding module, so it reached
    neither My Tasks nor the phone, and a signatory had to go looking for it
    (owner 2026-08-15).
    """

    def setUp(self):
        from datetime import date
        from .models import Document, OnboardingCase, Site, User
        from .tests import make_user
        self.sig = make_user("so_sig", User.Role.SIGNATORY)
        site = Site.objects.create(code="SOB", name="Sob Isle",
                                   status=Site.Status.ACTIVE)
        doc = Document.objects.create(doc_type="OBR", ref="OBR-SOB-001",
                                      site=site, doc_date=date(2026, 8, 1),
                                      status="IN_PROGRESS",
                                      created_by=self.sig)
        self.case = OnboardingCase.objects.create(
            document=doc, full_name="A Candidate",
            trade_designation="Carpenter")

    def test_it_appears_in_the_signatorys_pending_queue(self):
        from .views_documents import pending_groups
        titles = {g["title"]: g for g in pending_groups(self.sig)}
        self.assertIn("To sign off — onboarding appointments", titles)
        row = titles["To sign off — onboarding appointments"]["items"][0]
        self.assertEqual(row["ref"], "OBR-SOB-001")
        self.assertEqual(row["doc_type"], "OBR")
        self.assertIn("A Candidate", row["hint"])

    def test_the_phone_treats_it_as_actionable(self):
        from .views_mobile import APPROVABLE
        self.assertIn(("OBR", "IN_PROGRESS"), APPROVABLE)

    def test_a_signed_case_leaves_the_queue(self):
        from django.utils import timezone
        from .views_documents import pending_groups
        self.case.signatory_approved_at = timezone.now()
        self.case.signatory_approved_by = self.sig
        self.case.save(update_fields=["signatory_approved_at",
                                      "signatory_approved_by"])
        titles = {g["title"] for g in pending_groups(self.sig)}
        self.assertNotIn("To sign off — onboarding appointments", titles)


class CaseListDatesAndOrderTests(TestCase):
    """The dashboard carried no date and no dependable order (2026-08-16).

    There was no telling a case raised this morning from one that had been
    sitting six weeks, and same-day cases came back in whatever order the
    database felt like, so the list reshuffled between loads.
    """

    def setUp(self):
        from datetime import date
        from .models import Document, OnboardingCase, Site, User
        from .tests import make_user
        self.hr = make_user("ocd_hr", User.Role.HO_HR)
        self.site = Site.objects.create(code="OCD", name="Ocd Isle",
                                        status=Site.Status.ACTIVE)
        self.refs = []
        for n, day in ((1, date(2026, 8, 1)), (2, date(2026, 8, 9)),
                       (3, date(2026, 8, 9))):
            doc = Document.objects.create(
                doc_type="OBR", ref=f"OBR-OCD-00{n}", site=self.site,
                doc_date=day, status="IN_PROGRESS", created_by=self.hr)
            OnboardingCase.objects.create(document=doc, full_name=f"Cand {n}",
                                          nationality="Nepali")
            self.refs.append(doc.ref)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _rows(self):
        r = self.client.get("/api/v1/onboarding")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_a_case_carries_the_date_it_was_raised(self):
        row = self._rows()[0]
        self.assertIn("doc_date", row)
        self.assertIn("created_at", row)
        self.assertIsNotNone(row["created_at"])

    def test_it_carries_when_it_last_moved(self):
        self.assertIsNotNone(self._rows()[0]["updated_at"])

    def test_newest_first(self):
        dates = [str(r["doc_date"]) for r in self._rows()]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_same_day_cases_come_back_in_a_stable_order(self):
        first = [r["ref"] for r in self._rows()]
        for _ in range(3):
            self.assertEqual([r["ref"] for r in self._rows()], first)
        # and the tiebreak is the newer case first, not chance
        same_day = [r for r in self._rows()
                    if str(r["doc_date"]) == "2026-08-09"]
        self.assertEqual([r["ref"] for r in same_day],
                         ["OBR-OCD-003", "OBR-OCD-002"])


class PaymentClearsTheGateTests(TestCase):
    """A paid fee moves the case on (owner 2026-08-16).

    Paying only notified HR, so a case sat at "insurance pending" or "visa fee
    pending" until somebody read the message and pressed Advance — cases were
    stuck at payment for weeks with the money long gone.
    """

    def setUp(self):
        from datetime import date
        from decimal import Decimal
        from django.utils import timezone
        from .models import (CostHead, Document, OnboardingCase,
                             OnboardingFee, PaymentRequest, Site, User)
        from .tests import make_user
        from . import onboarding as ob
        self.ob = ob
        self.hr = make_user("pg_hr", User.Role.HO_HR)
        self.fin = make_user("pg_fin", User.Role.FINANCE)
        self.sig = make_user("pg_sig", User.Role.SIGNATORY)
        site = Site.objects.create(code="PGT", name="Gate Isle",
                                   status=Site.Status.ACTIVE)
        doc = Document.objects.create(
            doc_type="OBR", ref="OBR-PGT-001", site=site,
            doc_date=date(2026, 8, 1), status="IN_PROGRESS",
            created_by=self.hr)
        self.case = OnboardingCase.objects.create(
            document=doc, full_name="Candidate", nationality="Bangladeshi",
            route="BV", stage="BV_VISA_FEE",
            signatory_approved_at=timezone.now(),
            signatory_approved_by=self.sig)
        head = CostHead.objects.filter(name="Labour & Staff").first()
        self.pyr = Document.objects.create(
            doc_type="PYR", ref="PYR-PGT-001", site=site,
            doc_date=date(2026, 8, 2), status="AUTHORISED",
            created_by=self.hr)
        PaymentRequest.objects.create(
            document=self.pyr, cost_head=head, payee="Insurer",
            amount_requested=Decimal("1200"), purpose="Travel insurance",
            origin="ONBOARDING")
        OnboardingFee.objects.create(case=self.case, document=self.pyr,
                                     stage="BV_VISA_FEE")

    def test_the_case_waits_while_the_fee_is_unsettled(self):
        """Approved onto a voucher is not the same as authorised — nothing
        has left the bank yet."""
        self.pyr.status = "DIRECTOR_APPROVED"
        self.pyr.save(update_fields=["status"])
        err = self.ob.advance_stage(self.case, {}, self.hr)
        self.assertIn("Awaiting payment", err)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage, "BV_VISA_FEE")

    def test_paying_it_moves_the_case_on(self):
        self.pyr.status = "PAID"
        self.pyr.save(update_fields=["status"])
        self.ob.on_fee_paid(self.pyr, self.fin)
        self.case.refresh_from_db()
        self.assertNotEqual(self.case.stage, "BV_VISA_FEE")

    def test_finance_paying_it_is_enough_without_hr_touching_it(self):
        """The actor is Finance, who is not an HR processing role — the point
        of the system advance."""
        self.pyr.status = "PAID"
        self.pyr.save(update_fields=["status"])
        self.assertIn("Only HR",
                      self.ob.advance_stage(self.case, {}, self.fin) or "")
        self.ob.on_fee_paid(self.pyr, self.fin)
        self.case.refresh_from_db()
        self.assertNotEqual(self.case.stage, "BV_VISA_FEE")

    def test_it_never_forces_a_case_past_a_gate_it_cannot_clear(self):
        """Sign-off is still the start line: an unsigned case does not move,
        however much has been paid."""
        self.case.signatory_approved_at = None
        self.case.save(update_fields=["signatory_approved_at"])
        self.pyr.status = "PAID"
        self.pyr.save(update_fields=["status"])
        self.ob.on_fee_paid(self.pyr, self.fin)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage, "BV_VISA_FEE")

    def test_a_fee_for_a_stage_the_case_has_left_changes_nothing(self):
        self.case.stage = "BV_TICKET"
        self.case.save(update_fields=["stage"])
        self.pyr.status = "PAID"
        self.pyr.save(update_fields=["status"])
        self.ob.on_fee_paid(self.pyr, self.fin)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage, "BV_TICKET")

    def test_an_authorised_fee_is_settled_enough_to_advance(self):
        """Finance's paid stamp lags by weeks; authorisation is when the money
        goes (owner 2026-08-16) — the same rule as salary-advance recovery."""
        self.assertEqual(self.pyr.status, "AUTHORISED")
        self.ob.on_fee_settled(self.pyr, self.fin)
        self.case.refresh_from_db()
        self.assertNotEqual(self.case.stage, "BV_VISA_FEE")

    def test_a_fee_still_awaiting_authorisation_holds_the_case(self):
        self.pyr.status = "DIRECTOR_APPROVED"
        self.pyr.save(update_fields=["status"])
        err = self.ob.advance_stage(self.case, {}, self.hr)
        self.assertIn("Awaiting payment", err)

    def test_it_will_not_lodge_an_application_without_the_portal_reference(self):
        """The decline path, with the case that shows it: an insurance fee
        settles, but the next stage is the application, and only HR has the
        reference the portal issued (owner 2026-08-16)."""
        from .models import OnboardingFee
        self.case.stage = "BV_INSURANCE"
        self.case.save(update_fields=["stage"])
        self.pyr.status = "PAID"
        self.pyr.save(update_fields=["status"])
        OnboardingFee.objects.filter(case=self.case).update(
            stage="BV_INSURANCE")
        self.ob.on_fee_settled(self.pyr, self.fin)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage, "BV_INSURANCE")
        # ...and it moves the moment HR supplies it
        err = self.ob.advance_stage(
            self.case, {"portal_ref": "GSR/2026/27757"}, self.hr)
        self.assertIsNone(err)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage, "BV_APPLICATION")

    def test_an_authorised_unpaid_fee_stays_visible_after_the_case_moves(self):
        """The one that was missed: the case advances on authorisation, and
        the money that has not actually gone must not vanish with the stage
        (owner 2026-08-16, OBR-SFR-008)."""
        self.ob.on_fee_settled(self.pyr, self.fin)
        self.case.refresh_from_db()
        self.assertNotEqual(self.case.stage, "BV_VISA_FEE")   # it moved on
        row = self.ob.case_dict(self.case)
        out = row["outstanding_fees"]
        self.assertEqual(len(out), 1, "the unpaid fee disappeared")
        self.assertEqual(out[0]["pyr_ref"], "PYR-PGT-001")
        self.assertTrue(out[0]["authorised"])
        self.assertEqual(float(out[0]["amount"]), 1200.0)

    def test_a_paid_fee_is_not_listed_as_outstanding(self):
        self.pyr.status = "PAID"
        self.pyr.save(update_fields=["status"])
        self.assertEqual(self.ob.case_dict(self.case)["outstanding_fees"], [])

    def test_a_cancelled_fee_is_not_listed_either(self):
        self.pyr.status = "CANCELLED"
        self.pyr.save(update_fields=["status"])
        self.assertEqual(self.ob.case_dict(self.case)["outstanding_fees"], [])


class PortalReferenceTests(TestCase):
    """The government portal's reference is required to lodge an application.

    The portal issues one (GSR/2026/27757) the moment an application goes in.
    Without it nobody can find the application again, and HR was keeping them
    on paper (owner 2026-08-16).
    """

    def setUp(self):
        from datetime import date
        from django.utils import timezone
        from .models import Document, OnboardingCase, Site, User
        from .tests import make_user
        from . import onboarding as ob
        self.ob = ob
        self.hr = make_user("pr_hr", User.Role.HO_HR)
        site = Site.objects.create(code="PRF", name="Portal Isle",
                                   status=Site.Status.ACTIVE)
        doc = Document.objects.create(
            doc_type="OBR", ref="OBR-PRF-001", site=site,
            doc_date=date(2026, 8, 1), status="IN_PROGRESS",
            created_by=self.hr)
        # sitting on the stage immediately before the BV application
        self.case = OnboardingCase.objects.create(
            document=doc, full_name="Candidate", nationality="Sri Lankan",
            route="BV", stage="BV_INSURANCE",
            waived_stages=["BV_INSURANCE"],
            signatory_approved_at=timezone.now())

    def test_advancing_without_it_says_what_is_missing(self):
        err = self.ob.advance_stage(self.case, {}, self.hr)
        self.assertIn("portal reference", err)
        self.assertIn("GSR", err)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage, "BV_INSURANCE")  # it did not move

    def test_a_blank_reference_is_not_a_reference(self):
        err = self.ob.advance_stage(self.case, {"portal_ref": "   "}, self.hr)
        self.assertIn("portal reference", err)

    def test_supplying_it_advances_and_records_it(self):
        err = self.ob.advance_stage(
            self.case, {"portal_ref": " GSR/2026/27757 "}, self.hr)
        self.assertIsNone(err)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage, "BV_APPLICATION")
        self.assertEqual(self.case.portal_ref, "GSR/2026/27757")

    def test_the_stage_asks_for_it_up_front(self):
        self.assertEqual(self.ob.stage_view(self.case)["next_needs"],
                         "portal_ref")

    def test_hr_can_correct_it_afterwards(self):
        self.ob.advance_stage(self.case, {"portal_ref": "GSR/2026/1"}, self.hr)
        self.case.refresh_from_db()
        err = self.ob.set_stage_data(self.case, {"portal_ref": "GSR/2026/27757"},
                                  self.hr)
        self.assertIsNone(err)
        self.case.refresh_from_db()
        self.assertEqual(self.case.portal_ref, "GSR/2026/27757")

    def test_it_cannot_be_blanked_out_afterwards(self):
        self.ob.advance_stage(self.case, {"portal_ref": "GSR/2026/1"}, self.hr)
        self.case.refresh_from_db()
        err = self.ob.set_stage_data(self.case, {"portal_ref": ""}, self.hr)
        self.assertIn("cannot be blanked", err)

    def test_it_reaches_the_dashboard(self):
        self.ob.advance_stage(self.case,
                              {"portal_ref": "GSR/2026/27757"}, self.hr)
        self.case.refresh_from_db()
        self.assertEqual(self.ob.case_dict(self.case)["portal_ref"],
                         "GSR/2026/27757")


class HoldACaseTests(TestCase):
    """A case blocked by something outside the process stops, and says why.

    The portal answers an application with things like "the candidate already
    holds an active visa pending cancellation". Nothing in the onboarding
    machine can clear that, so the case must wait — but with no way to record
    it, the case just sat at the application stage looking slow and only the
    person who read the portal knew why (owner 2026-08-16).
    """

    def setUp(self):
        from datetime import date
        from django.utils import timezone
        from .models import Document, OnboardingCase, Site, User
        from .tests import make_user
        from . import onboarding as ob
        self.ob = ob
        self.hr = make_user("hd_hr", User.Role.HO_HR)
        self.pm = make_user("hd_pm", User.Role.PM)
        site = Site.objects.create(code="HLD", name="Hold Isle",
                                   status=Site.Status.ACTIVE)
        doc = Document.objects.create(
            doc_type="OBR", ref="OBR-HLD-001", site=site,
            doc_date=date(2026, 8, 1), status="IN_PROGRESS",
            created_by=self.hr)
        self.case = OnboardingCase.objects.create(
            document=doc, full_name="Candidate", nationality="Sri Lankan",
            route="BV", stage="BV_APPLICATION",
            # the BV application is lodged and approved — this fixture is
            # about holds, not about the portal
            portal_by_stage={"BV_APPLICATION": {"ref": "GSR/2026/1",
                                                "status": "APPROVED"}},
            portal_ref="GSR/2026/1", portal_status="APPROVED",
            signatory_approved_at=timezone.now())

    def test_a_held_case_does_not_advance_and_says_why(self):
        self.assertIsNone(self.ob.set_hold(
            self.case, "active visa pending cancellation", self.hr))
        err = self.ob.advance_stage(self.case, {}, self.hr)
        self.assertIn("On hold", err)
        self.assertIn("pending cancellation", err)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage, "BV_APPLICATION")

    def test_a_hold_needs_a_reason(self):
        self.assertIn("waiting on", self.ob.set_hold(self.case, "  ", self.hr))

    def test_releasing_it_lets_the_case_move_again(self):
        self.ob.set_hold(self.case, "visa pending cancellation", self.hr)
        self.assertIsNone(self.ob.clear_hold(self.case, self.hr))
        self.case.refresh_from_db()
        self.assertEqual(self.case.hold_reason, "")
        # BV_APPROVED is next, and it now wants the visa's own dates.
        self.assertIsNone(self.ob.advance_stage(
            self.case, {"bv_approved_date": "2026-08-05",
                        "bv_expiry": "2026-11-03"}, self.hr))

    def test_only_hr_holds_or_releases(self):
        self.assertIn("Only HR", self.ob.set_hold(self.case, "x", self.pm))
        self.ob.set_hold(self.case, "x", self.hr)
        self.assertIn("Only HR", self.ob.clear_hold(self.case, self.pm))

    def test_the_hold_shows_on_the_case_with_who_and_when(self):
        self.ob.set_hold(self.case, "embassy holding the passport", self.hr)
        self.case.refresh_from_db()
        row = self.ob.case_dict(self.case)
        self.assertEqual(row["hold_reason"], "embassy holding the passport")
        self.assertEqual(row["hold_by"], self.hr.full_name)
        self.assertIsNotNone(row["hold_since"])

    def test_it_counts_days_at_the_current_stage(self):
        from datetime import timedelta
        from django.utils import timezone
        self.case.stage_since = timezone.localdate() - timedelta(days=6)
        self.case.save(update_fields=["stage_since"])
        self.assertEqual(self.ob.case_dict(self.case)["days_at_stage"], 6)

    def test_advancing_stamps_when_the_new_stage_began(self):
        from django.utils import timezone
        # BV_APPROVED is next, and it now wants the visa's own dates.
        self.assertIsNone(self.ob.advance_stage(
            self.case, {"bv_approved_date": "2026-08-05",
                        "bv_expiry": "2026-11-03"}, self.hr))
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage_since, timezone.localdate())
        self.assertEqual(self.ob.case_dict(self.case)["days_at_stage"], 0)


class ApplicationStateTests(TestCase):
    """An application stage is three different waits wearing one label.

    OBR-SFR-008 was lodged on the portal, its reference recorded, and the list
    still read "BV application pending" with nothing else — indistinguishable
    from five cases nobody had lodged yet, and from one the portal had come
    back on asking for more information (owner 2026-08-17).
    """

    def setUp(self):
        from datetime import date
        from django.utils import timezone
        from .models import Document, OnboardingCase, Site, User
        from .tests import make_user
        from . import onboarding as ob
        self.ob = ob
        hr = make_user("as_hr", User.Role.HO_HR)
        site = Site.objects.create(code="APP", name="Application Isle",
                                   status=Site.Status.ACTIVE)
        doc = Document.objects.create(
            doc_type="OBR", ref="OBR-APP-001", site=site,
            doc_date=date(2026, 8, 1), status="IN_PROGRESS", created_by=hr)
        self.case = OnboardingCase.objects.create(
            document=doc, full_name="Candidate", nationality="Sri Lankan",
            route="BV", stage="BV_APPLICATION",
            signatory_approved_at=timezone.now())

    def state(self, portal_ref="", portal_status=""):
        self.ob.set_portal(self.case, self.case.stage,
                           ref=portal_ref, status=portal_status)
        return self.ob.application_state(self.case)

    def test_nothing_lodged_is_ours_to_move(self):
        s = self.state(portal_ref="", portal_status="")
        self.assertEqual(s["state"], "WAIT_US")
        self.assertIn("not lodged", s["note"])

    def test_lodged_and_submitted_is_with_the_portal(self):
        """The OBR-SFR-008 case itself."""
        s = self.state(portal_ref="GSR/2026/27789", portal_status="SUBMITTED")
        self.assertEqual(s["state"], "WAIT_PORTAL")
        self.assertEqual(s["ref"], "GSR/2026/27789")
        self.assertIn("awaiting the portal", s["note"])

    def test_a_reference_with_no_status_still_reads_as_lodged(self):
        """One live case had the reference but no status — it is with them,
        and the note says the status is missing rather than inventing one."""
        s = self.state(portal_ref="GSR/2026/27785", portal_status="")
        self.assertEqual(s["state"], "WAIT_PORTAL")
        self.assertIn("not recorded", s["note"])

    def test_additional_info_comes_back_to_us(self):
        s = self.state(portal_ref="GSR/2026/26385",
                       portal_status="ADDITIONAL_INFO")
        self.assertEqual(s["state"], "WAIT_US")
        self.assertIn("more information", s["note"])

    def test_rejected_comes_back_to_us(self):
        s = self.state(portal_ref="GSR/2026/26385", portal_status="REJECTED")
        self.assertEqual(s["state"], "WAIT_US")

    def test_approved_is_ready_to_advance(self):
        s = self.state(portal_ref="GSR/2026/26385", portal_status="APPROVED")
        self.assertEqual(s["state"], "READY")

    def test_no_state_off_an_application_stage(self):
        self.case.stage = "BV_TICKET"
        self.assertIsNone(self.ob.application_state(self.case))

    def test_the_case_payload_carries_it(self):
        self.ob.set_portal(self.case, "BV_APPLICATION",
                           ref="GSR/2026/27789", status="SUBMITTED")
        self.case.save()
        row = self.ob.case_dict(self.case)
        self.assertEqual(row["application"]["state"], "WAIT_PORTAL")
        self.assertEqual(row["application"]["ref"], "GSR/2026/27789")


class BvThenWorkPermitTests(TestCase):
    """A candidate flies in on a business visa and converts to a work permit
    here, so the case lodges TWO applications.

    OBR-SJR-006 did exactly that: BV approved 10 Aug, arrived 11 Aug, onto
    WP_APPLICATION 17 Aug — still carrying the BV's reference GSR/2026/26767
    and its APPROVED status. The work-permit application had not been lodged at
    all, but read as approved and could be advanced past (owner 2026-08-18).
    """

    def setUp(self):
        from datetime import date
        from django.utils import timezone
        from .models import Document, OnboardingCase, Site, User
        from .tests import make_user
        from . import onboarding as ob
        self.ob = ob
        self.hr = make_user("bw_hr", User.Role.HO_HR)
        site = Site.objects.create(code="BWP", name="Convert Isle",
                                   status=Site.Status.ACTIVE)
        doc = Document.objects.create(
            doc_type="OBR", ref="OBR-BWP-001", site=site,
            doc_date=date(2026, 8, 1), status="IN_PROGRESS",
            created_by=self.hr)
        self.case = OnboardingCase.objects.create(
            document=doc, full_name="Candidate", nationality="Sri Lankan",
            route="BV", stage="BV_APPLICATION",
            signatory_approved_at=timezone.now())
        # the business visa: lodged and approved
        self.ob.set_portal(self.case, "BV_APPLICATION",
                           ref="GSR/2026/26767", status="APPROVED")
        self.case.save()

    def test_the_bv_approval_does_not_cover_the_wp_application(self):
        self.case.stage = "WP_APPLICATION"
        self.ob._load_portal_for_stage(self.case)
        self.case.save()
        state = self.ob.application_state(self.case)
        self.assertEqual(state["state"], "WAIT_US")
        self.assertIn("not lodged", state["note"])
        self.assertEqual(state["ref"], "")

    def test_the_case_cannot_be_advanced_on_the_bv_approval(self):
        self.case.stage = "WP_APPLICATION"
        self.ob._load_portal_for_stage(self.case)
        self.case.save()
        err = self.ob.advance_stage(self.case, {}, self.hr)
        self.assertIsNotNone(err)
        self.assertIn("portal reference", err)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stage, "WP_APPLICATION")   # held

    def test_the_bv_reference_stays_on_record(self):
        """He flew in on it and his BV expiry counts from it — losing it would
        be worse than showing it in the wrong place."""
        self.case.stage = "WP_APPLICATION"
        self.ob._load_portal_for_stage(self.case)
        self.case.save()
        hist = self.ob.case_dict(self.case)["portal_history"]
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["stage"], "BV_APPLICATION")
        self.assertEqual(hist[0]["ref"], "GSR/2026/26767")
        self.assertEqual(hist[0]["status"], "APPROVED")

    def test_each_application_keeps_its_own_reference(self):
        self.case.stage = "WP_APPLICATION"
        self.ob._load_portal_for_stage(self.case)
        self.case.save()
        self.ob.set_stage_data(self.case, {"portal_ref": "WR1/2026/73059"},
                               self.hr)
        self.case.refresh_from_db()
        self.assertEqual(self.ob.portal_for(self.case, "WP_APPLICATION")["ref"],
                         "WR1/2026/73059")
        self.assertEqual(self.ob.portal_for(self.case, "BV_APPLICATION")["ref"],
                         "GSR/2026/26767")
        # and the flat column tracks the stage in hand
        self.assertEqual(self.case.portal_ref, "WR1/2026/73059")

    def test_an_outcome_cannot_be_set_before_the_application_exists(self):
        self.case.stage = "WP_APPLICATION"
        self.ob._load_portal_for_stage(self.case)
        self.case.save()
        err = self.ob.set_stage_data(self.case, {"portal_status": "APPROVED"},
                                     self.hr)
        self.assertIn("reference", err)


class ConversionPendingLabelTests(TestCase):
    """The work-permit conversion opens at WP_APPOINTMENT, where the pending
    label named a piece of paperwork.

    OBR-SJR-004 arrived on a business visa with 24 days left and read
    "Appointment letter pending" — true, but it hides that the work-permit
    process has not started (owner 2026-08-18).
    """

    def setUp(self):
        from datetime import date
        from django.utils import timezone
        from .models import Site, User
        from .tests import make_user
        from . import onboarding as ob
        self.ob = ob
        hr = make_user("cv_hr", User.Role.HO_HR)
        self.site = Site.objects.create(code="CNV", name="Convert Isle",
                                        status=Site.Status.ACTIVE)
        self.hr, self.now = hr, timezone.now()
        self.day = date(2026, 8, 1)

    def _case(self, route, bv_purpose="", stage="WP_APPOINTMENT", ref="X"):
        from .models import Document, OnboardingCase
        doc = Document.objects.create(
            doc_type="OBR", ref=f"OBR-CNV-{ref}", site=self.site,
            doc_date=self.day, status="IN_PROGRESS", created_by=self.hr)
        return OnboardingCase.objects.create(
            document=doc, full_name="Candidate", nationality="Sri Lankan",
            route=route, bv_purpose=bv_purpose, stage=stage,
            signatory_approved_at=self.now)

    def test_a_converting_bv_case_says_the_wp_has_not_started(self):
        case = self._case("BV", "RECRUITMENT", ref="1")
        label, note = self.ob.pending_summary(case)
        self.assertEqual(label, "Work-permit conversion")
        self.assertIn("not started", note)

    def test_a_straight_wp_case_still_just_needs_the_letter(self):
        """Nothing is hidden there — the letter really is the whole of it."""
        case = self._case("WP", ref="2")
        label, note = self.ob.pending_summary(case)
        self.assertEqual(label, "Appointment letter")
        self.assertEqual(note, "")

    def test_later_conversion_stages_are_unchanged(self):
        case = self._case("BV", "RECRUITMENT", stage="WP_APPLICATION", ref="3")
        label, note = self.ob.pending_summary(case)
        self.assertEqual(label, "WP application")
        self.assertEqual(note, "")

    def test_the_case_payload_carries_the_note(self):
        case = self._case("BV", "RECRUITMENT", ref="4")
        row = self.ob.case_dict(case)
        self.assertEqual(row["pending_label"], "Work-permit conversion")
        self.assertIn("not started", row["pending_note"])


class IM30GenerationTests(TestCase):
    """The Maldives Immigration IM30 form could never be generated.

    `OnboardingLetter.kind` was CharField(max_length=3) — sized for LOA / SPL /
    AC / EA — and "IM30" is four characters, so every attempt died on save with
    "value too long for type character varying(3)" (owner 2026-08-20). Postgres
    refuses it; SQLite would not, which is why no test caught it.
    """

    def setUp(self):
        from datetime import date

        from django.utils import timezone
        from .models import Document, OnboardingCase, Site, User
        from .tests import make_user
        from . import onboarding as ob
        self.ob = ob
        self.hr = make_user("im_hr", User.Role.HO_HR)
        site = Site.objects.create(code="IMM", name="Immigration Isle",
                                   status=Site.Status.ACTIVE)
        doc = Document.objects.create(
            doc_type="OBR", ref="OBR-IMM-001", site=site,
            doc_date=date(2026, 8, 1), status="IN_PROGRESS",
            created_by=self.hr)
        self.case = OnboardingCase.objects.create(
            document=doc, full_name="Test Candidate",
            nationality="Sri Lankan", route="WP", stage="WP_APPLICATION",
            passport_no="N1234567", gender="Male", marital_status="Single",
            date_of_birth=date(1990, 1, 1),
            signatory_approved_at=timezone.now())

    def test_the_kind_field_is_wide_enough_for_im30(self):
        """The whole bug in one assertion."""
        from .models import OnboardingLetter
        field = OnboardingLetter._meta.get_field("kind")
        self.assertGreaterEqual(field.max_length, len("IM30"))

    def test_im30_generates_and_is_saved(self):
        self.assertTrue(self.ob.letter_available(self.case, "IM30"))
        fields = self.ob.letter_defaults(self.case, "IM30")
        letter, msg = self.ob.generate_letter(self.case, "IM30", fields,
                                              self.hr)
        self.assertIsNone(msg)
        self.assertIsNotNone(letter)
        self.assertEqual(letter.kind, "IM30")
        self.assertTrue(letter.ref.startswith("IM30-"))

    def test_the_form_carries_the_candidate_details(self):
        import fitz
        fields = self.ob.letter_defaults(self.case, "IM30")
        letter, _ = self.ob.generate_letter(self.case, "IM30", fields, self.hr)
        with letter.attachment.file.open("rb") as f:
            doc = fitz.open("pdf", f.read())
        text = doc[0].get_text().upper()   # the form is filled in capitals
        doc.close()
        for probe in ("TEST CANDIDATE", "N1234567", "SRI LANKAN",
                      "EMPLOYMENT", "VELANA"):
            self.assertIn(probe, text, probe)

    def test_every_letter_kind_fits_the_column(self):
        """Guards the next one added, not just IM30."""
        from .models import OnboardingLetter
        from . import onboarding as ob
        width = OnboardingLetter._meta.get_field("kind").max_length
        for kind in ob.LETTER_META:
            self.assertLessEqual(len(kind), width, kind)

    def test_every_ref_type_fits_the_counter_column(self):
        """The narrow column that actually blocked IM30 was DocCounter's, not
        the letter's: next_ref() could not even create a counter row, so it
        failed before a letter existed. Two columns, one bug, and fixing only
        the obvious one left it still broken (owner 2026-08-20)."""
        from .models import DocCounter, Document
        from .numbering import GLOBAL_TYPES
        width = DocCounter._meta.get_field("doc_type").max_length
        for t in GLOBAL_TYPES:
            self.assertLessEqual(len(t), width, t)
        for t, _label in Document.Type.choices:
            self.assertLessEqual(len(t), width, t)

    def test_a_counter_row_can_be_issued_for_im30(self):
        """Exercises the path that failed, rather than trusting the width."""
        from .numbering import next_ref
        ref = next_ref("IM30", None)
        self.assertTrue(ref.startswith("IM30-"), ref)


class CancelACaseTests(OnboardingSpineTests):
    """A case can be closed for real-world reasons at any point before
    completion (owner 2026-08-25): reason required, unpaid fee PYRs pulled
    back, paid ones stand, and a fee on a live voucher blocks the cancel."""

    def _fee_raised(self):
        pk = self._approved()               # WP, Indian, IN_PROGRESS track
        self._to_deposit(pk)
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/onboarding/{pk}/fee",
                             {"amount": "1500", "payee": "Immigration"},
                             format="json")
        assert r.status_code == 201, r.data
        return pk

    def _cancel(self, pk, note="candidate declined the offer", actor=None):
        self.client.force_authenticate(actor or self.hr)
        return self.client.post(f"/api/v1/onboarding/{pk}/action",
                                {"action": "cancel", "note": note},
                                format="json")

    def test_cancel_needs_a_reason(self):
        pk = self._approved()
        r = self._cancel(pk, note="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("reason", r.data["detail"].lower())

    def test_cancel_in_progress_withdraws_the_unpaid_fee(self):
        pk = self._fee_raised()
        case = OnboardingCase.objects.get(pk=pk)
        pyr = case.fees.get(stage="WP_DEPOSIT").document
        self.assertNotEqual(pyr.status, "PAID")
        r = self._cancel(pk)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "CANCELLED")
        self.assertIn("declined", r.data["closed_note"])
        pyr.refresh_from_db()
        self.assertEqual(pyr.status, "CANCELLED")

    def test_a_paid_fee_stands_when_the_case_dies(self):
        pk = self._fee_raised()
        case = OnboardingCase.objects.get(pk=pk)
        pyr = case.fees.get(stage="WP_DEPOSIT").document
        pyr.status = "PAID"
        pyr.save(update_fields=["status"])
        r = self._cancel(pk)
        self.assertEqual(r.status_code, 200, r.data)
        pyr.refresh_from_db()
        self.assertEqual(pyr.status, "PAID")     # money spent — record stands

    def test_a_fee_on_a_voucher_blocks_the_cancel(self):
        from datetime import date as _date
        from .models import Document, PaymentVoucherLine
        pk = self._fee_raised()
        case = OnboardingCase.objects.get(pk=pk)
        pyr = case.fees.get(stage="WP_DEPOSIT").document
        pv = Document.objects.create(
            doc_type="PV", ref="PV-HO-900", site=case.document.site,
            doc_date=_date.today(), status="SUBMITTED", created_by=self.hr)
        PaymentVoucherLine.objects.create(
            voucher=pv, source_document=pyr, amount=1500, currency="MVR")
        r = self._cancel(pk)
        self.assertEqual(r.status_code, 400)
        self.assertIn(pyr.ref, r.data["detail"])
        case.document.refresh_from_db()
        self.assertNotEqual(case.document.status, "CANCELLED")

    def test_completed_case_cannot_be_cancelled(self):
        pk = self._approved()
        doc = OnboardingCase.objects.get(pk=pk).document
        doc.status = "COMPLETED"
        doc.save(update_fields=["status"])
        r = self._cancel(pk)
        self.assertEqual(r.status_code, 400)
