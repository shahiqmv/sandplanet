"""Safety induction sessions, SP-HSE-F01 (owner 2026-10-26, HSE forms brief
C.1): picked from men not yet inducted on the site, printed, the signed
copy gives each his induction; the PM verifies; attendance flags, never
refuses."""
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import (Attendance, Employee, EmployeeSiteAllocation,
                     InductionSession, ManpowerCategory, SafetyInduction, Site,
                     SitePmHistory, Subcontractor, User)
from .tests import make_user

MEDIA = __import__("tempfile").mkdtemp(prefix="ind-media-")
TODAY = date.today()


def photo(name="sheet.jpg"):
    import pymupdf as fitz
    doc = fitz.open()
    page = doc.new_page(width=300, height=420)
    page.insert_text((40, 60), "signed")
    return SimpleUploadedFile(name, page.get_pixmap().tobytes("jpeg"),
                              content_type="image/jpeg")


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": MEDIA}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage."
                               "StaticFilesStorage"}})
class InductionTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="IND", name="Induct Isle",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("in_se", User.Role.SITE_ENGINEER, self.site)
        self.pm = make_user("in_pm", User.Role.PM, self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        cat = ManpowerCategory.objects.create(list_type="DPR", grp="LABOUR",
                                              name="Mason", sort_order=1)
        self.a = self._man("EMP-8201", "New Hire", cat)
        self.b = self._man("EMP-8202", "Old Hand", cat)
        SafetyInduction.objects.create(employee=self.b, site=self.site,
                                       inducted_on=TODAY - timedelta(days=30),
                                       inducted_by=self.se)
        sub = Subcontractor.objects.create(site=self.site, name="Atoll Civil",
                                           status="APPROVED")
        self.s = Employee.objects.create(
            emp_no="EMP-8203", full_name="Sub Man", engagement_type="SUBCONTRACT",
            subcontractor=sub, is_active=True, join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(employee=self.s, site=self.site,
                                              from_date=date(2026, 1, 1))
        self.c = APIClient()

    def _man(self, no, name, cat):
        e = Employee.objects.create(emp_no=no, full_name=name, job_category=cat,
                                    is_active=True, join_date=date(2026, 1, 1),
                                    preferred_language="BN")
        EmployeeSiteAllocation.objects.create(employee=e, site=self.site,
                                              from_date=date(2026, 1, 1))
        return e

    def as_(self, u):
        self.c.force_authenticate(u)
        return self.c

    def grid(self):
        return {r["emp_no"]: r for r in self.as_(self.se).get(
            f"/api/v1/attendance?site={self.site.id}&date={TODAY}")
            .data["rows"]}

    def test_candidates_are_the_men_not_yet_inducted_here(self):
        got = {x["emp_no"] for x in self.as_(self.se).get(
            f"/api/v1/hse-inductions/candidates?site={self.site.id}"
            f"&date={TODAY}").data}
        self.assertEqual(got, {"EMP-8201", "EMP-8203"})    # not the old hand

    def test_the_session_flags_clears_and_records(self):
        rows = self.grid()
        self.assertTrue(rows["EMP-8201"]["not_inducted"])
        self.assertFalse(rows["EMP-8202"]["not_inducted"])
        r = self.as_(self.se).post("/api/v1/hse-inductions", {
            "site": self.site.id, "held_on": TODAY.isoformat(), "language": "BN",
            "trainer_name": "Sanjaya (safety)",
            "employees": [self.a.id, self.s.id]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        sid = r.data["id"]
        self.assertTrue(r.data["ref"].startswith("IND-IND-"))
        # day one: on today's session, so no flag
        self.assertFalse(self.grid()["EMP-8201"]["not_inducted"])
        # printing it moves it on; the PDF carries the topics and the men
        pdf = self.as_(self.se).get(f"/api/v1/hse-inductions/{sid}/pdf")
        self.assertEqual(pdf.status_code, 200)
        import pymupdf as fitz
        text = "".join(p.get_text() for p in fitz.open(stream=pdf.content,
                                                         filetype="pdf"))
        for want in ("SAFETY INDUCTION", "Personal Protective Equipment",
                     "Disciplinary Rules", "New Hire", "Atoll Civil"):
            self.assertIn(want, text)
        self.assertEqual(InductionSession.objects.get().status, "PRINTED")
        # the sub man did not sign on the day
        r = self.as_(self.se).post(f"/api/v1/hse-inductions/{sid}/upload", {
            "files": [photo()], "absent": [self.s.id], "topics_na": ["05"]},
            format="multipart")
        self.assertEqual(r.data["status"], "SIGNED", r.data)
        rec = SafetyInduction.objects.filter(session_id=sid)
        self.assertEqual([x.employee_id for x in rec], [self.a.id])
        self.assertNotIn("05 Key Work Risks", rec[0].topics)
        # the PM verifies; the site engineer cannot
        self.assertEqual(self.as_(self.se).post(
            f"/api/v1/hse-inductions/{sid}/verify", {}).status_code, 400)
        r = self.as_(self.pm).post(f"/api/v1/hse-inductions/{sid}/verify", {})
        self.assertEqual(r.data["status"], "VERIFIED", r.data)
        # tomorrow the new hire is covered by his record, the sub man is not
        tomorrow = TODAY + timedelta(days=1)
        from .hse_inductions import not_inducted_ids
        self.assertEqual(not_inducted_ids(self.site, tomorrow,
                                          [self.a.id, self.s.id]), {self.s.id})

    def test_a_bring_back_after_a_year_is_inducted_again(self):
        from .hse_inductions import not_inducted_ids
        old = TODAY - timedelta(days=600)
        SafetyInduction.objects.create(employee=self.a, site=self.site,
                                       inducted_on=old, inducted_by=self.se)
        alloc = EmployeeSiteAllocation.objects.get(employee=self.a)
        alloc.from_date = TODAY - timedelta(days=10)       # came back lately
        alloc.save()
        self.assertEqual(not_inducted_ids(self.site, TODAY, [self.a.id]),
                         {self.a.id})

    def test_attendance_is_never_refused_and_the_summary_counts(self):
        Attendance.objects.create(employee=self.a, site=self.site, day=TODAY,
                                  remark="PRESENT")
        from .hse_inductions import present_not_inducted
        self.assertEqual(present_not_inducted(self.site, TODAY), 1)

    def test_the_site_box_is_kept_on_the_medical_plan(self):
        r = self.as_(self.pm).put(f"/api/v1/health/plan/{self.site.id}", {
            "assembly_point": "Jetty head", "safety_officer": "Sanjaya 7771234"},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        from .models import SiteMedicalPlan
        p = SiteMedicalPlan.objects.get(site=self.site)
        self.assertEqual((p.assembly_point, p.safety_officer),
                         ("Jetty head", "Sanjaya 7771234"))
