"""Site time-lapse: weekly uploads joined into one video per camera
(owner 2026-10-13: "per week video will be messy")."""
import shutil
import subprocess
import tempfile
import unittest
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import timelapse as tl
from .models import Site, SiteTimelapse, TimelapseReel, User
from .tests import make_user

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
MEDIA = tempfile.mkdtemp(prefix="tl-media-")


def make_video(seconds, ext="mp4", size="640x360"):
    """A small test video — an AVI one stands in for the Brinno's files."""
    out = tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False).name
    codec = ["-c:v", "mjpeg"] if ext == "avi" else ["-c:v", "libx264",
                                                     "-pix_fmt", "yuv420p"]
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc=duration={seconds}:size={size}:rate=15",
                    *codec, out], check=True)
    with open(out, "rb") as f:
        return SimpleUploadedFile(f"week.{ext}", f.read())


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": MEDIA}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage."
                               "StaticFilesStorage"}})
class TimelapseTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="VKR", name="Vakkaru",
                                         status=Site.Status.ACTIVE)
        self.se = make_user("tl_se", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("tl_pm", User.Role.PM, site=self.site)
        self.far = make_user("tl_far", User.Role.SITE_ADMIN, site=self.other)
        self.c = APIClient()

    def upload(self, user, video, week_from, week_to, label="Brinno north"):
        self.c.force_authenticate(user)
        return self.c.post("/api/v1/timelapses", {
            "site_id": self.site.id, "camera_label": label,
            "week_from": week_from, "week_to": week_to, "file": video},
            format="multipart")

    def test_an_upload_needs_a_camera_a_week_and_a_video(self):
        tiny = SimpleUploadedFile("week.avi", b"RIFF0000AVI ")
        r = self.upload(self.se, tiny, "2026-10-03", "2026-10-09", label="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("camera", r.data["detail"].lower())
        r = self.upload(self.se, SimpleUploadedFile("notes.txt", b"x"),
                        "2026-10-03", "2026-10-09")
        self.assertEqual(r.status_code, 400)
        r = self.upload(self.se, tiny, "2026-10-09", "2026-10-03")
        self.assertEqual(r.status_code, 400)
        r = self.upload(self.se, tiny, "2026-10-03", "2026-10-09")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "PENDING")
        self.assertTrue(TimelapseReel.objects.get().needs_build)
        # another site's staff cannot upload here or see it
        self.c.force_authenticate(self.far)
        self.assertEqual(self.c.post("/api/v1/timelapses", {
            "site_id": self.site.id, "camera_label": "x",
            "week_from": "2026-10-03", "week_to": "2026-10-09",
            "file": SimpleUploadedFile("w.mp4", b"x")},
            format="multipart").status_code, 403)
        self.assertEqual(self.c.get("/api/v1/timelapses").data["reels"], [])

    def test_a_file_that_is_not_video_is_marked_unreadable(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg not installed")
        self.upload(self.se, SimpleUploadedFile("week.avi", b"not a video"),
                    "2026-10-03", "2026-10-09")
        self.assertEqual(tl.build_pending(), (0, 1, 0))
        clip = SiteTimelapse.objects.get()
        self.assertEqual(clip.status, "FAILED")
        self.assertTrue(clip.error)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
    def test_weeks_are_joined_into_one_video_in_date_order(self):
        # week 2 arrives before week 1, and week 1 is the camera's AVI
        self.upload(self.se, make_video(2), "2026-10-03", "2026-10-09")
        self.upload(self.se, make_video(3, "avi"), "2026-09-26", "2026-10-02")
        self.assertEqual(tl.build_pending(), (2, 0, 1))
        reel = TimelapseReel.objects.get()
        self.assertEqual(reel.weeks, 2)
        self.assertEqual((reel.covers_from, reel.covers_to),
                         (date(2026, 9, 26), date(2026, 10, 9)))
        self.assertAlmostEqual(float(reel.duration_s), 5.0, delta=0.5)
        self.assertTrue(reel.file.name.endswith(".mp4"))
        self.assertEqual(set(SiteTimelapse.objects.values_list(
            "status", flat=True)), {"JOINED"})
        # every piece is now a standard MP4 — the AVI is gone
        self.assertTrue(all(c.file.name.endswith(".mp4")
                            for c in SiteTimelapse.objects.all()))
        # a third week extends the same video; nothing to do afterwards
        self.upload(self.se, make_video(1), "2026-10-10", "2026-10-16")
        tl.build_pending()
        reel.refresh_from_db()
        self.assertEqual(reel.weeks, 3)
        self.assertAlmostEqual(float(reel.duration_s), 6.0, delta=0.5)
        self.assertEqual(tl.build_pending(), (0, 0, 0))
        # removing a week rebuilds without it
        self.c.force_authenticate(self.pm)
        wk = SiteTimelapse.objects.get(week_from=date(2026, 10, 3))
        self.assertEqual(self.c.delete(
            f"/api/v1/timelapses/{wk.id}").status_code, 204)
        tl.build_pending()
        reel.refresh_from_db()
        self.assertEqual(reel.weeks, 2)
        self.assertAlmostEqual(float(reel.duration_s), 4.0, delta=0.5)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
    def test_the_client_sees_one_video_per_camera_once_published(self):
        from .models import ClientUser  # noqa: F401  (portal account model)
        self.upload(self.se, make_video(2), "2026-10-03", "2026-10-09")
        tl.build_pending()
        reel = TimelapseReel.objects.get()
        # the site engineer cannot publish; the PM can
        self.c.force_authenticate(self.se)
        self.assertEqual(self.c.patch(f"/api/v1/timelapse-reels/{reel.id}",
                                      {"client_visible": True},
                                      format="json").status_code, 403)
        admin = make_user("tl_admin", User.Role.ADMIN)
        self.c.force_authenticate(admin)
        temp = self.c.post("/api/v1/client-users", {
            "org_name": "Soneva", "full_name": "Client", "email": "c@s.mv",
            "site_ids": [self.site.id]}, format="json").data["temp_password"]
        portal = APIClient()
        tok = portal.post("/api/client/auth/login",
                          {"email": "c@s.mv", "password": temp},
                          format="json").data["token"]
        portal.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
        url = f"/api/client/sites/{self.site.id}/timelapses"
        self.assertEqual(portal.get(url).data["timelapses"], [])
        self.c.force_authenticate(self.pm)
        r = self.c.patch(f"/api/v1/timelapse-reels/{reel.id}",
                         {"client_visible": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        rows = portal.get(url).data["timelapses"]
        self.assertEqual([x["camera_label"] for x in rows], ["Brinno north"])
        self.assertTrue(rows[0]["play_url"])
        self.assertNotIn("client_visible", rows[0])      # no staff detail

    def test_a_camera_behind_on_its_weeks_is_flagged(self):
        TimelapseReel.objects.create(site=self.site, camera_label="Brinno",
                                     covers_from=date(2026, 1, 3),
                                     covers_to=date(2026, 1, 9), weeks=1,
                                     needs_build=False)
        self.c.force_authenticate(self.pm)
        d = self.c.get("/api/v1/timelapses").data
        self.assertEqual(d["behind"], ["SJR · Brinno"])
        self.assertTrue(d["can_publish"])
