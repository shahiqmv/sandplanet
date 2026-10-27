"""Employee warning notices, SP-HSE-F02 (owner 2026-10-26, HSE forms brief
C.2): raised by the site, approved by the PM (never the raiser), printed,
served and made active by the signed copy; the level climbs with his active
warnings; a removal uses the existing flows; no link to fines."""
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import (Employee, EmployeeSiteAllocation, ManpowerCategory,
                     Notification, Site, SitePmHistory, Subcontractor, User, WarningNotice,
                     WorkerChangeRequest, WorkerFine)
from .tests import make_user

MEDIA = __import__("tempfile").mkdtemp(prefix="wn-media-")
DAY = date.today() - timedelta(days=2)


def photo(name="page1.jpg"):
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=300, height=420)
    page.insert_text((40, 60), "signed")
    pix = page.get_pixmap()
    return SimpleUploadedFile(name, pix.tobytes("jpeg"),
                              content_type="image/jpeg")


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": MEDIA}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage."
                               "StaticFilesStorage"}})
class WarningNoticeTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="WNS", name="Warn Isle",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("wn_se", User.Role.SITE_ENGINEER, self.site)
        self.sa = make_user("wn_sa", User.Role.SITE_ADMIN, self.site)
        self.pm = make_user("wn_pm", User.Role.PM, self.site)
        self.hr = make_user("wn_hr", User.Role.HO_HR)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=1)
        self.emp = Employee.objects.create(
            emp_no="EMP-8101", full_name="Rahim Uddin", nationality="Bangladeshi",
            job_category=self.cat, join_date=date(2026, 1, 1),
            preferred_language="BN", is_active=True)
        EmployeeSiteAllocation.objects.create(employee=self.emp, site=self.site,
                                              from_date=date(2026, 1, 1))
        self.c = APIClient()

    def as_(self, u):
        self.c.force_authenticate(u)
        return self.c

    def raise_(self, user=None, **kw):
        body = {"site": self.site.id, "employee": self.emp.id,
                "event_date": DAY.isoformat(), "offences": ["PPE"],
                "what_happened": "No harness on the roof edge, 10:30",
                "corrective_action": "Wear a harness at height"}
        body.update(kw)
        return self.as_(user or self.se).post("/api/v1/hse-warnings", body,
                                              format="json")

    def approve(self, wid, user=None):
        return self.as_(user or self.pm).post(
            f"/api/v1/hse-warnings/{wid}/approve", {}, format="json")

    def serve(self, wid, user=None, **kw):
        body = {"served_on": DAY.isoformat(), "files": [photo(), photo("p2.png")]}
        body.update(kw)
        return self.as_(user or self.sa).post(
            f"/api/v1/hse-warnings/{wid}/serve", body, format="multipart")

    def test_raise_approve_print_serve(self):
        r = self.raise_()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["status"], r.data["level"]),
                         ("PENDING", "VERBAL"))
        self.assertTrue(r.data["ref"].startswith("WN-WNS-"))
        wid = r.data["id"]
        # the raiser can't print it before approval, nor approve it
        self.assertEqual(self.as_(self.se).get(
            f"/api/v1/hse-warnings/{wid}/pdf").status_code, 400)
        self.assertEqual(self.approve(wid, self.se).status_code, 400)
        r = self.approve(wid)
        self.assertEqual(r.data["status"], "APPROVED", r.data)
        pdf = self.as_(self.se).get(f"/api/v1/hse-warnings/{wid}/pdf")
        self.assertEqual(pdf.status_code, 200)
        import fitz
        text = "".join(p.get_text() for p in fitz.open(
            stream=b"".join(pdf.streaming_content) if hasattr(pdf, "streaming_content")
            else pdf.content, filetype="pdf"))
        for want in ("EMPLOYEE WARNING NOTICE", "Rahim Uddin", "EMP-8101",
                     "Not wearing required PPE"):
            self.assertIn(want, text)
        self.assertIsNotNone(WarningNotice.objects.get().printed_at)
        # served with two photos -> one signed PDF; active for 12 months
        r = self.serve(wid)
        self.assertEqual(r.status_code, 200, r.data)
        w = WarningNotice.objects.get()
        self.assertEqual(w.status, "ACTIVE")
        self.assertEqual(w.active_until.year, DAY.year + 1)
        self.assertEqual(len(fitz.open(w.signed_copy.path)), 2)
        # never a fine
        self.assertFalse(WorkerFine.objects.exists())

    def test_the_level_climbs_and_a_different_level_needs_a_reason(self):
        wid = self.raise_().data["id"]
        self.approve(wid)
        self.serve(wid)
        r = self.raise_(user=self.sa)
        self.assertEqual(r.data["suggested_level"], "FIRST")
        self.assertEqual(r.data["level"], "FIRST")
        r = self.raise_(user=self.sa, level="FINAL")
        self.assertEqual(r.status_code, 400)
        self.assertIn("reason", r.data["detail"])
        r = self.raise_(user=self.sa, level="FINAL",
                        level_reason="Second harness breach in a week")
        self.assertEqual(r.status_code, 201, r.data)

    def test_refusing_to_sign_needs_a_witness_and_still_stands(self):
        wid = self.raise_().data["id"]
        self.approve(wid)
        r = self.serve(wid, refused_to_sign="true")
        self.assertEqual(r.status_code, 400)
        r = self.serve(wid, refused_to_sign="true", witness_name="Kamal (foreman)")
        self.assertEqual(r.data["status"], "ACTIVE", r.data)
        self.assertTrue(r.data["refused_to_sign"])

    def test_a_return_goes_back_to_the_site_with_a_note(self):
        wid = self.raise_().data["id"]
        r = self.as_(self.pm).post(f"/api/v1/hse-warnings/{wid}/return", {},
                                   format="json")
        self.assertEqual(r.status_code, 400)
        r = self.as_(self.pm).post(f"/api/v1/hse-warnings/{wid}/return",
                                   {"note": "Add the time"}, format="json")
        self.assertEqual(r.data["status"], "RETURNED")
        r = self.as_(self.se).patch(f"/api/v1/hse-warnings/{wid}", {
            "offences": ["PPE"], "what_happened": "No harness, 10:30 roof B"},
            format="json")
        self.assertEqual(r.data["status"], "PENDING", r.data)

    def test_removal_opens_a_remove_batch_for_a_direct_worker(self):
        for lvl, reason in (("FINAL", "Repeat"), ("REMOVAL", "After final")):
            wid = self.raise_(level=lvl, level_reason=reason).data["id"]
            self.approve(wid)
            self.serve(wid)
        w = WarningNotice.objects.get(level="REMOVAL")
        self.assertIsNotNone(w.removal_batch_id)
        batch = WorkerChangeRequest.objects.get(pk=w.removal_batch_id)
        self.assertEqual((batch.kind, batch.status), ("REMOVE", "SUBMITTED"))

    def test_a_subcontract_worker_can_be_warned_and_removed(self):
        sub = Subcontractor.objects.create(site=self.site, name="Atoll Civil",
                                           status="APPROVED")
        man = Employee.objects.create(
            emp_no="EMP-8102", full_name="Sub Worker", engagement_type="SUBCONTRACT",
            subcontractor=sub, is_active=True, join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(employee=man, site=self.site,
                                              from_date=date(2026, 1, 1))
        workers = self.as_(self.se).get(
            f"/api/v1/hse-warnings/workers?site={self.site.id}&date={DAY}").data
        self.assertIn("Atoll Civil", [x["subcontractor"] for x in workers])
        r = self.raise_(employee=man.id, level="REMOVAL",
                        level_reason="Fighting on site")
        self.assertEqual(r.status_code, 201, r.data)
        self.approve(r.data["id"])
        self.serve(r.data["id"])
        man.refresh_from_db()
        self.assertFalse(man.is_active)

    def test_another_sites_team_cannot_see_or_raise(self):
        other = Site.objects.create(code="WNO", name="Other",
                                    status=Site.Status.ACTIVE)
        far = make_user("wn_far", User.Role.SITE_ENGINEER, other)
        self.raise_()
        self.assertEqual(self.as_(far).get("/api/v1/hse-warnings").data["results"],
                         [])
        self.assertEqual(self.raise_(user=far).status_code, 400)
        # HR sees every site
        self.assertEqual(len(self.as_(self.hr).get(
            "/api/v1/hse-warnings").data["results"]), 1)

    # The warning and induction forms print English and, under it, Bengali,
    # Tamil, Sinhala, Hindi or Nepali (owner 2026-10-26); any other language
    # prints English and says to explain it verbally.

    def test_every_language_file_has_every_line(self):
        from . import form_i18n
        en = form_i18n.english()
        for lang in form_i18n.TRANSLATED:
            words = form_i18n.strings(lang)
            self.assertEqual(set(words), set(en), lang)
            self.assertEqual([k for k, v in words.items() if not v.strip()],
                             [], lang)

    def test_the_warning_prints_in_each_language(self):
        import fitz

        from . import form_i18n
        wid = self.raise_().data["id"]
        self.approve(wid)
        w = WarningNotice.objects.get(pk=wid)
        for lang in (*form_i18n.TRANSLATED, "DV"):
            w.language = lang
            w.save(update_fields=["language"])
            pdf = self.as_(self.se).get(f"/api/v1/hse-warnings/{wid}/pdf")
            self.assertEqual(pdf.status_code, 200, lang)
            text = "".join(p.get_text() for p in fitz.open(
                stream=pdf.content, filetype="pdf"))
            self.assertIn("Not wearing required PPE", text)
            self.assertEqual("explain the warning to him verbally" in text,
                             lang == "DV", lang)

    def test_the_pm_raises_and_approves_his_own(self):
        """On many sites the PM does the safety work himself, so he prepares
        the warning and approves it (owner 2026-10-27). Anyone else still
        can't approve what they raised; the Director stands in only where a
        site has no PM."""
        director = make_user("wn_dir", User.Role.DIRECTOR)
        r = self.raise_(user=self.pm)
        self.assertEqual(r.status_code, 201, r.data)
        wid = r.data["id"]
        self.assertFalse(Notification.objects.filter(
            recipient=self.pm, title__contains="to approve").exists())
        self.assertFalse(self.as_(director).get(
            f"/api/v1/hse-warnings/{wid}").data["can_decide"])
        r = self.approve(wid, self.pm)
        self.assertEqual(r.data["status"], "APPROVED", r.data)
        # the site engineer still can't approve his own
        r = self.raise_()
        self.assertEqual(self.approve(r.data["id"], self.se).status_code, 400)

    def test_the_form_language_is_chosen_on_the_warning(self):
        r = self.raise_(language="TA")
        self.assertEqual(r.data["language"], "TA", r.data)
        r = self.raise_(language="")          # English only
        self.assertEqual(r.data["language"], "")
        r = self.raise_()                     # not given: his own language
        self.assertEqual(r.data["language"], "BN")
        self.assertEqual(self.raise_(language="XX").status_code, 400)
