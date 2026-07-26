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

    def _gen_letter(self, pk, kind, **fields):
        self.client.force_authenticate(self.hr)
        return self.client.post(f"/api/v1/onboarding/{pk}/letter",
                                {"kind": kind, "fields": fields}, format="json")

    def test_loa_generates_at_appointment(self):
        pk = self._approved()                 # WP, Indian
        self._adv(pk)                          # begin → WP_APPOINTMENT
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
        self._adv(pk)                          # begin → BV_SPONSOR
        detail = self.client.get(f"/api/v1/onboarding/{pk}").data
        opts = {o["kind"]: o for o in detail["letter_options"]}
        self.assertTrue(opts["SPL"]["available"])
        self.assertFalse(opts["LOA"]["available"])   # conversion not reached
        # asking for an LOA now is refused
        self.assertEqual(self._gen_letter(pk, "LOA").status_code, 400)
        r = self._gen_letter(pk, "SPL", project_site="Ha. Dhidhdhoo Harbour",
                             addressee_line_1="The Controller of Immigration")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["letters"][0]["ref"], "SPL-001")

    def test_regenerating_a_letter_bumps_version(self):
        pk = self._approved()
        self._adv(pk)                          # → WP_APPOINTMENT
        self._gen_letter(pk, "LOA")
        r = self._gen_letter(pk, "LOA", contract_duration="1 year")
        self.assertEqual(r.status_code, 201, r.data)
        refs = sorted(x["ref"] for x in r.data["letters"])
        self.assertEqual(refs, ["LOA-001", "LOA-002"])
        versions = sorted(x["version"] for x in r.data["letters"])
        self.assertEqual(versions, [1, 2])

    def test_only_hr_generates_letters(self):
        pk = self._approved()
        self._adv(pk)
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/onboarding/{pk}/letter",
                             {"kind": "LOA"}, format="json")
        self.assertIn(r.status_code, (400, 403))

    def test_letter_pdf_downloads(self):
        pk = self._approved()
        self._adv(pk)
        lid = self._gen_letter(pk, "LOA").data["letters"][0]["id"]
        self.client.force_authenticate(self.hr)
        r = self.client.get(f"/api/v1/onboarding/{pk}/letters/{lid}.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")

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
            self.client.force_authenticate(self.director)  # not a raiser
            f2 = SimpleUploadedFile("p.jpg", b"x", content_type="image/jpeg")
            r2 = self.client.post("/api/v1/onboarding/passport-scan",
                                  {"file": f2}, format="multipart")
            self.assertEqual(r2.status_code, 403)
        finally:
            px.scan = orig

    def test_stage_document_upload_and_download(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pk = self._approved()
        self._adv(pk); self._adv(pk)                   # → WP_APPLICATION
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
        self._adv(pk)                                  # WP_APPOINTMENT only
        self.client.force_authenticate(self.hr)
        f = SimpleUploadedFile("x.pdf", b"x")
        r = self.client.post(f"/api/v1/onboarding/{pk}/stage-doc",
                             {"slot": "ENTRY_PASS", "file": f},
                             format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_fee_slot_surfaces_finance_payment_slip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import Attachment, OnboardingCase
        pk = self._approved()
        self._adv(pk); self._adv(pk)
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
        from .models import OnboardingCase
        pk = self._approved(route="BV", bv_justification="urgent",
                            nationality="Indian")
        self._adv(pk)                                  # begin → BV_SPONSOR
        OnboardingCase.objects.filter(pk=pk).update(stage="BV_APPROVED")
        case = OnboardingCase.objects.get(pk=pk)
        slots = {d["slot"] for d in ob.documents_list(case)}
        self.assertIn("BV_CERTIFICATE", slots)
        self.assertIn("INSURANCE_POLICY", slots)      # earlier BV fee slot
        self.assertNotIn("ENTRY_PASS", slots)         # WP conversion not reached

    def test_arrival_hands_over_to_employee_db(self):
        from .models import Employee, Notification, OnboardingCase
        pk = self._approved()
        self._adv(pk); self._adv(pk)                   # → WP_APPLICATION
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
        # only one employee across the whole walk (arrival + completion)
        self.assertEqual(Employee.objects.filter(pk=emp.pk).count(), 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.hr, title__icontains="site payroll").exists())

    def test_editing_arrival_date_moves_salary_start(self):
        from .models import OnboardingCase
        pk = self._approved()
        self._adv(pk); self._adv(pk)                   # → WP_APPLICATION
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

    def test_medical_clock_alerts_then_escalates_and_is_idempotent(self):
        from datetime import date, timedelta
        from . import onboarding as ob
        from .models import Notification, OnboardingCase
        pk = self._approved()
        self._adv(pk)                                  # begin → IN_PROGRESS
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
        from .models import OnboardingCase
        pk = self._approved()
        self._adv(pk)
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
        from .models import Notification, OnboardingCase
        pk = self._approved(route="BV", bv_justification="urgent",
                            nationality="Indian")
        self._adv(pk)                                  # begin → BV_SPONSOR
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
        from .models import Notification, OnboardingCase
        pk = self._approved()
        self._adv(pk)                                  # pre-arrival, IN_PROGRESS
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
