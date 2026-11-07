"""Time-lapse intake from OneDrive (owner 2026-11-07), run against a plain
directory standing in for the drive — rclone treats one the same way."""
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import drive
from .models import (Site, SiteTimelapse, TimelapseCamera, TimelapseDriveItem,
                     User)
from .tests import make_user

HAVE_TOOLS = (shutil.which("rclone") is not None
              and shutil.which("ffmpeg") is not None)


def _clip(path, created="2026-10-18T06:00:00"):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc=duration=1:size=160x90:rate=5",
                    "-pix_fmt", "yuv420p", "-metadata",
                    f"creation_time={created}", path], check=True)


@unittest.skipUnless(HAVE_TOOLS, "rclone and ffmpeg needed")
class DriveIntakeTests(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="od-")
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(drive, "REMOTE", self.root + "/")
        p.start()
        self.addCleanup(p.stop)
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("od_pm", User.Role.PM, site=self.site)
        self.cam = TimelapseCamera.objects.create(
            site=self.site, name="North jetty", location="Jetty",
            drive_folder="NORTH JETTY")
        os.makedirs(os.path.join(self.root, "NORTH JETTY"))
        self.c = APIClient()
        self.c.force_authenticate(self.pm)

    def put(self, name, created="2026-10-18T06:00:00", mtime=None):
        path = os.path.join(self.root, "NORTH JETTY", name)
        _clip(path, created)
        if mtime:
            t = mtime.timestamp()
            os.utime(path, (t, t))
        return path

    def sweep(self, later_by=None):
        now = timezone.now() + (later_by or timedelta())
        return drive.sync_camera(self.cam, now=now)

    def test_a_new_file_waits_one_pass_then_comes_in_with_its_dates(self):
        self.put("TLC00005.MP4", mtime=timezone.make_aware(
            timezone.datetime(2026, 10, 23, 18, 30)))
        self.assertEqual(self.sweep(), (0, 0, 0))        # seen, left to settle
        item = TimelapseDriveItem.objects.get()
        self.assertEqual(item.status, "SEEN")
        self.assertEqual(self.sweep(timedelta(minutes=9)), (1, 0, 0))
        item.refresh_from_db()
        clip = SiteTimelapse.objects.get()
        self.assertEqual((item.status, item.clip_id), ("IMPORTED", clip.id))
        self.assertEqual((clip.week_from, clip.week_to),
                         (date(2026, 10, 18), date(2026, 10, 23)))
        self.assertEqual((clip.file_name, clip.uploaded_by_id),
                         ("TLC00005.MP4", None))
        # the file is left where it was
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "NORTH JETTY", "TLC00005.MP4")))

    def test_a_file_still_growing_is_not_fetched(self):
        path = self.put("TLC00006.MP4")
        self.sweep()
        with open(path, "ab") as f:
            f.write(b"\\0" * 1000)                      # still uploading
        self.assertEqual(self.sweep(timedelta(minutes=9)), (0, 0, 0))
        self.assertEqual(TimelapseDriveItem.objects.get().status, "SEEN")

    def test_the_same_file_under_another_name_is_a_repeat(self):
        a = self.put("TLC00005.MP4")
        self.sweep()
        self.sweep(timedelta(minutes=9))
        shutil.copy(a, os.path.join(self.root, "NORTH JETTY", "18_10.MP4"))
        self.sweep(timedelta(minutes=10))
        self.assertEqual(self.sweep(timedelta(minutes=20)), (0, 1, 0))
        dup = TimelapseDriveItem.objects.get(name="18_10.MP4")
        self.assertEqual(dup.status, "DUPLICATE")
        self.assertIn("TLC00005.MP4", dup.note)
        self.assertEqual(SiteTimelapse.objects.count(), 1)

    def test_a_deleted_upload_stays_out_until_asked_for(self):
        self.put("TLC00005.MP4")
        self.sweep()
        self.sweep(timedelta(minutes=9))
        clip = SiteTimelapse.objects.get()
        r = self.c.delete(f"/api/v1/timelapses/{clip.id}")
        self.assertEqual(r.status_code, 204)
        item = TimelapseDriveItem.objects.get()
        self.assertEqual(item.status, "IGNORED")
        self.assertEqual(self.sweep(timedelta(minutes=30)), (0, 0, 0))
        self.assertFalse(SiteTimelapse.objects.exists())
        r = self.c.post(f"/api/v1/timelapse-drive-items/{item.id}/retry", {},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.sweep(timedelta(minutes=31)), (1, 0, 0))

    def test_dates_can_be_corrected_without_deleting(self):
        self.put("TLC00005.MP4")
        self.sweep()
        self.sweep(timedelta(minutes=9))
        clip = SiteTimelapse.objects.get()
        r = self.c.patch(f"/api/v1/timelapses/{clip.id}",
                         {"week_from": "2026-10-19", "week_to": "2026-10-21"},
                         format="json")
        self.assertEqual(r.status_code, 200, r.data)
        clip.refresh_from_db()
        self.assertEqual((clip.week_from, clip.week_to),
                         (date(2026, 10, 19), date(2026, 10, 21)))

    def test_the_folder_is_set_on_the_camera_and_shown_with_its_files(self):
        r = self.c.patch(f"/api/v1/timelapse-cameras/{self.cam.id}",
                         {"name": "North jetty", "location": "Jetty",
                          "drive_folder": "/NORTH JETTY/"}, format="json")
        self.assertEqual(r.data["drive_folder"], "NORTH JETTY")
        other = TimelapseCamera.objects.create(site=self.site, name="Two",
                                               location="x")
        r = self.c.patch(f"/api/v1/timelapse-cameras/{other.id}",
                         {"name": "Two", "location": "x",
                          "drive_folder": "north jetty"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.put("TLC00007.MP4")
        self.sweep()
        d = self.c.get("/api/v1/timelapses").data["drive"]
        self.assertTrue(d["connected"])
        self.assertEqual([(i["name"], i["status"]) for i in d["items"]],
                         [("TLC00007.MP4", "SEEN")])

    def test_a_folder_that_is_not_there_is_reported_not_crashed(self):
        self.cam.drive_folder = "NOWHERE"
        self.cam.save()
        with self.assertRaises(drive.DriveError):
            drive.list_folder("NOWHERE/deeper")
        self.assertEqual(drive.sync_all(), (0, 0, 1))


class ProbeDatesTests(TestCase):
    def test_an_unset_camera_clock_falls_back_to_the_file_time(self):
        with mock.patch.object(drive.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout='{"format": {"tags": '
                                         '{"creation_time": "1904-01-01T00:00:00Z"}}}')
            end = timezone.make_aware(timezone.datetime(2026, 10, 23, 18, 0))
            self.assertEqual(drive.probe_dates("x.mp4", end),
                             (date(2026, 10, 23), date(2026, 10, 23)))
            self.assertEqual(drive.probe_dates("x.mp4", None), (None, None))
