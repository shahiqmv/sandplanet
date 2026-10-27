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
from .models import (Project, Site, SiteTimelapse, TimelapseCamera,
                     TimelapseReel, User)
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
        self.cam = TimelapseCamera.objects.create(
            site=self.site, name="Brinno north", location="Roof of block A")

    def upload(self, user, video, week_from, week_to, camera=None):
        self.c.force_authenticate(user)
        cam = self.cam if camera is None else camera
        return self.c.post("/api/v1/timelapses", {
            "camera_id": cam.id if cam else "",
            "week_from": week_from, "week_to": week_to, "file": video},
            format="multipart")

    def test_cameras_are_registered_with_project_and_location(self):
        proj = Project.objects.create(site=self.site, code="DTE",
                                      title="Deck villas",
                                      status=Project.Status.ACTIVE)
        elsewhere = Project.objects.create(site=self.other, code="VKR-1",
                                           title="Spa",
                                           status=Project.Status.ACTIVE)
        body = {"site_id": self.site.id, "name": "Brinno 2",
                "location": "Jetty head, looking at villas 20-30",
                "project_id": proj.id}
        # the site engineer uploads but does not register cameras
        self.c.force_authenticate(self.se)
        self.assertEqual(self.c.post("/api/v1/timelapse-cameras", body,
                                     format="json").status_code, 403)
        self.c.force_authenticate(self.pm)
        r = self.c.post("/api/v1/timelapse-cameras",
                        {**body, "location": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("mounted", r.data["detail"])
        r = self.c.post("/api/v1/timelapse-cameras",
                        {**body, "project_id": elsewhere.id}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/v1/timelapse-cameras", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["project_code"], r.data["location"]),
                         ("DTE", body["location"]))
        # one name per site
        self.assertEqual(self.c.post("/api/v1/timelapse-cameras",
                                     {**body, "name": "brinno 2"},
                                     format="json").status_code, 400)
        # the site team sees its own site only, chosen for it
        self.c.force_authenticate(self.se)
        d = self.c.get("/api/v1/timelapses").data
        self.assertEqual([s["code"] for s in d["sites"]], ["SJR"])
        self.assertTrue(d["site_locked"])
        self.assertEqual(d["default_site_id"], self.site.id)
        self.assertEqual(d["sites"][0]["projects"][0]["code"], "DTE")
        self.assertEqual(sorted(c["name"] for c in d["cameras"]),
                         ["Brinno 2", "Brinno north"])
        self.assertFalse(d["can_manage_cameras"])
        self.c.force_authenticate(self.far)
        self.assertEqual(self.c.get("/api/v1/timelapses").data["cameras"],
                         [])
        # a retired camera takes no more uploads; one with uploads is
        # retired, not deleted
        cam2 = TimelapseCamera.objects.get(name="Brinno 2")
        tiny = SimpleUploadedFile("week.avi", b"RIFF0000AVI ")
        self.assertEqual(self.upload(self.se, tiny, "2026-10-03",
                                     "2026-10-09", cam2).status_code, 201)
        self.c.force_authenticate(self.pm)
        self.assertEqual(self.c.delete(
            f"/api/v1/timelapse-cameras/{cam2.id}").status_code, 400)
        r = self.c.patch(f"/api/v1/timelapse-cameras/{cam2.id}",
                         {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.upload(self.se, SimpleUploadedFile("w.avi", b"RIFF"),
                        "2026-10-10", "2026-10-16", cam2)
        self.assertEqual(r.status_code, 400)
        self.assertIn("retired", r.data["detail"])
        # a camera never used can be removed outright
        self.c.force_authenticate(self.pm)
        spare = TimelapseCamera.objects.create(site=self.site, name="Spare",
                                               location="store")
        self.assertEqual(self.c.delete(
            f"/api/v1/timelapse-cameras/{spare.id}").status_code, 204)

    def test_an_upload_needs_a_camera_a_week_and_a_video(self):
        tiny = SimpleUploadedFile("week.avi", b"RIFF0000AVI ")
        r = self.upload(self.se, tiny, "2026-10-03", "2026-10-09",
                        camera=False)
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
            "camera_id": self.cam.id,
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
        TimelapseReel.objects.create(site=self.site, camera=self.cam,
                                     covers_from=date(2026, 1, 3),
                                     covers_to=date(2026, 1, 9), weeks=1,
                                     needs_build=False)
        self.c.force_authenticate(self.pm)
        d = self.c.get("/api/v1/timelapses").data
        self.assertEqual(d["behind"], ["SJR · Brinno north"])
        self.assertTrue(d["can_publish"])


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": MEDIA}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage."
                               "StaticFilesStorage"}})
class ChunkedUploadTests(TestCase):
    """A week's video sent in pieces (owner 2026-10-27): SJR's 2 GB file
    never arrived in one request — the server gave up and answered 500."""

    def setUp(self):
        from unittest import mock
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("ch_se", User.Role.SITE_ENGINEER, site=self.site)
        self.other = make_user("ch_pm", User.Role.PM, site=self.site)
        self.cam = TimelapseCamera.objects.create(
            site=self.site, name="Brinno north", location="Roof")
        self.c = APIClient()
        self.c.force_authenticate(self.se)
        # tiny pieces and a private folder for the test
        for name, value in (("CHUNK_BYTES", 4),
                            ("UPLOAD_DIR", tempfile.mkdtemp(prefix="tlup-"))):
            p = mock.patch.object(tl, name, value)
            p.start()
            self.addCleanup(p.stop)

    def start(self, size, name="TLC00001.MP4", **extra):
        body = {"camera_id": self.cam.id, "week_from": "2026-10-18",
                "week_to": "2026-10-23", "file_name": name, "size": size}
        body.update(extra)
        return self.c.post("/api/v1/timelapses/uploads", body, format="json")

    def chunk(self, token, i, data, user=None):
        if user:
            self.c.force_authenticate(user)
        return self.c.post(f"/api/v1/timelapses/uploads/{token}/chunk",
                           {"index": i, "chunk": SimpleUploadedFile("c", data)},
                           format="multipart")

    def test_pieces_in_any_order_make_the_week(self):
        data = b"0123456789"                      # 3 pieces of 4, 4, 2
        r = self.start(len(data))
        self.assertEqual(r.status_code, 201, r.data)
        token = r.data["token"]
        for i in (2, 0, 0, 1):                     # out of order, one twice
            self.assertEqual(self.chunk(token, i, data[i * 4:(i + 1) * 4])
                             .status_code, 200)
        self.assertEqual(self.c.get(f"/api/v1/timelapses/uploads/{token}")
                         .data["received"], [0, 1, 2])
        r = self.c.post(f"/api/v1/timelapses/uploads/{token}/finish", {},
                        format="json")
        self.assertEqual(r.status_code, 201, r.data)
        clip = SiteTimelapse.objects.get()
        self.assertEqual((clip.size_bytes, clip.file_name, clip.status),
                         (10, "TLC00001.MP4", "PENDING"))
        with clip.file.open("rb") as f:
            self.assertEqual(f.read(), data)

    def test_a_missing_piece_is_named_and_nothing_is_saved(self):
        token = self.start(10).data["token"]
        self.chunk(token, 0, b"0123")
        r = self.c.post(f"/api/v1/timelapses/uploads/{token}/finish", {},
                        format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("did not arrive", r.data["detail"])
        self.assertFalse(SiteTimelapse.objects.exists())

    def test_too_big_is_refused_before_a_byte_is_sent(self):
        r = self.start(5 * 1024 ** 3)
        self.assertEqual(r.status_code, 400)
        self.assertIn("over 4 GB", r.data["detail"])
        self.assertEqual(self.start(10, name="notes.pdf").status_code, 400)

    def test_someone_else_cannot_add_to_an_upload(self):
        token = self.start(4).data["token"]
        self.assertEqual(self.chunk(token, 0, b"0123", user=self.other)
                         .status_code, 400)
        # a token that is not one of ours never becomes a path
        self.assertEqual(self.chunk("..evil", 0, b"x").status_code, 400)
