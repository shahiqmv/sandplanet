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
        self.client.force_authenticate(self.hr)
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
        self._adv(pk)                                  # BV_APPROVED
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
        self._adv(pk); self._adv(pk); self._pay_fee(pk, "BV_VISA_FEE")
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
        self._adv(pk); self._adv(pk); self._pay_fee(pk, "BV_VISA_FEE")
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
        self._begin(pk1); self._adv(pk1); self._pay_fee(pk1, "BV_INSURANCE")
        self._adv(pk1); self._sdata(pk1, portal_status="APPROVED")
        self._adv(pk1); self._adv(pk1); self._pay_fee(pk1, "BV_VISA_FEE")
        self._adv(pk1); self._pay_fee(pk1, "BV_TICKET")
        today = tz.localdate()
        self._adv(pk1, arrived_date=str(today),
                  bv_expiry=str(today + timedelta(days=10)))
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
