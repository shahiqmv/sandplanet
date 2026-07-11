import threading
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from .models import Document, Site, SitePmHistory, User, UserSiteAllocation
from .numbering import next_ref
from .tests import make_user

TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea72d994800000000494e44ae426082"
)


def last_working_days(site, n):
    """Most recent n working days strictly before today."""
    days, d = [], date.today() - timedelta(days=1)
    while len(days) < n:
        if d.isoweekday() in site.working_days:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


class DocBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="SJR", name="Soneva Jani", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=60),
        )
        self.engineer = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.client = APIClient()
        self.client.force_authenticate(self.engineer)

    def create_dpr(self, doc_date=None, payload=None):
        r = self.client.post("/api/v1/documents", {
            "doc_type": "DPR", "site_id": self.site.id,
            "doc_date": (doc_date or date.today()).isoformat(),
            "payload": payload or {"weather_am": "Sunny"},
        }, format="json")
        return r

    def add_photos(self, ref, n, captioned=True):
        for i in range(n):
            f = SimpleUploadedFile(f"p{i}.png", TINY_PNG, content_type="image/png")
            r = self.client.post(f"/api/v1/documents/{ref}/attachments", {
                "file": f, "kind": "PHOTO",
                "caption": f"Villa {i} works" if captioned else "",
            }, format="multipart")
            assert r.status_code == 201, r.data


@override_settings(MEDIA_ROOT="test-media")
class NumberingTests(DocBase):
    def test_sequential_refs(self):
        days = last_working_days(self.site, 3)
        refs = [self.create_dpr(doc_date=d).data["ref"] for d in days]
        self.assertEqual(refs, ["DPR-SJR-001", "DPR-SJR-002", "DPR-SJR-003"])

    def test_void_keeps_number_no_reuse(self):
        d1, d2 = last_working_days(self.site, 2)
        ref = self.create_dpr(doc_date=d1).data["ref"]
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/void",
                             {"reason": "wrong date"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.client.force_authenticate(self.engineer)
        ref2 = self.create_dpr(doc_date=d2).data["ref"]
        self.assertEqual(ref2, "DPR-SJR-002")  # 001 kept by the void, never reused

    def test_one_dpr_per_day(self):
        self.create_dpr()
        r = self.create_dpr()
        self.assertEqual(r.status_code, 400)
        self.assertIn("already exists", r.data["detail"])


class NumberingConcurrencyTests(TransactionTestCase):
    """Gap-free numbering under concurrency (brief: risky logic first).
    Meaningful on Postgres (row locks); skipped on the SQLite dev fallback."""

    def test_parallel_issuers_get_unique_sequential_refs(self):
        if connection.vendor != "postgresql":
            self.skipTest("row-lock semantics need Postgres (DECISIONS.md D1)")
        site = Site.objects.create(code="VKR", name="Vakkaru", status="ACTIVE")
        refs, errors = [], []
        barrier = threading.Barrier(8)

        def worker():
            from django.db import transaction
            try:
                barrier.wait()
                with transaction.atomic():
                    refs.append(next_ref("DPR", site))
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertFalse(errors)
        self.assertEqual(sorted(refs),
                         [f"DPR-VKR-{n:03d}" for n in range(1, 9)])


@override_settings(MEDIA_ROOT="test-media")
class DprLifecycleTests(DocBase):
    def test_issue_no_longer_requires_min_photos(self):
        # Owner (Phase C): the photo floor was removed — a DPR issues with any
        # number of photos, including fewer than the old minimum of four.
        ref = self.create_dpr().data["ref"]
        self.add_photos(ref, 1)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "ISSUED")

    def test_issue_then_verify_flow(self):
        ref = self.create_dpr().data["ref"]
        self.add_photos(ref, 4)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "ISSUED")
        # engineer cannot verify
        r = self.client.post(f"/api/v1/documents/{ref}/actions/verify")
        self.assertEqual(r.status_code, 403)
        # PM verifies
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/verify")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "VERIFIED")
        actions = [a["action"] for a in r.data["approvals"]]
        self.assertEqual(actions, ["ISSUE", "VERIFY"])

    def test_issued_revision_immutable(self):
        ref = self.create_dpr().data["ref"]
        self.add_photos(ref, 4)
        self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        r = self.client.patch(f"/api/v1/documents/{ref}",
                              {"payload": {"weather_am": "Rainy"}}, format="json")
        self.assertEqual(r.status_code, 400)
        doc = Document.objects.get(ref=ref)
        self.assertEqual(doc.current_revision.payload["weather_am"], "Sunny")
        # attachments also locked after issue
        f = SimpleUploadedFile("late.png", TINY_PNG, content_type="image/png")
        r = self.client.post(f"/api/v1/documents/{ref}/attachments",
                             {"file": f, "caption": "late"}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_verify_requires_issued(self):
        ref = self.create_dpr().data["ref"]
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/verify")
        self.assertEqual(r.status_code, 400)

    def test_void_requires_reason(self):
        ref = self.create_dpr().data["ref"]
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/void", {},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_closed_site_blocks_creation(self):
        self.site.status = Site.Status.CLOSED
        self.site.save()
        r = self.create_dpr()
        self.assertEqual(r.status_code, 400)

    def test_other_site_user_cannot_see_document(self):
        ref = self.create_dpr().data["ref"]
        other_site = Site.objects.create(code="VKR", name="Vakkaru",
                                         status="ACTIVE")
        outsider = make_user("se2", User.Role.SITE_ENGINEER, site=other_site)
        self.client.force_authenticate(outsider)
        r = self.client.get(f"/api/v1/documents/{ref}")
        self.assertEqual(r.status_code, 404)


@override_settings(MEDIA_ROOT="test-media")
class RegisterTests(DocBase):
    def test_gap_detection_working_days_only(self):
        days = last_working_days(self.site, 4)
        # DPR on days[0] and days[2]; days[1] and days[3] are gaps
        for d in (days[0], days[2]):
            ref = self.create_dpr(doc_date=d).data["ref"]
            self.add_photos(ref, 4)
            self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        r = self.client.get(f"/api/v1/registers/dpr-tws?site={self.site.id}"
                            f"&from={days[0].isoformat()}")
        rows = {row["date"]: row for row in r.data["rows"]}
        self.assertFalse(rows[days[0].isoformat()]["gap"])
        self.assertTrue(rows[days[1].isoformat()]["gap"])
        self.assertFalse(rows[days[2].isoformat()]["gap"])
        self.assertTrue(rows[days[3].isoformat()]["gap"])
        # No Friday rows at all (default working week Sat–Thu, decision 5)
        self.assertNotIn("Friday", [row["day"] for row in r.data["rows"]])

    def test_voided_dpr_shows_but_day_is_gap(self):
        day = last_working_days(self.site, 1)[0]
        ref = self.create_dpr(doc_date=day).data["ref"]
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/documents/{ref}/actions/void",
                         {"reason": "duplicate"}, format="json")
        r = self.client.get(f"/api/v1/registers/dpr-tws?site={self.site.id}"
                            f"&from={day.isoformat()}&to={day.isoformat()}")
        row = r.data["rows"][0]
        self.assertEqual(row["dpr_ref"], ref)      # row remains (spec §4.1)
        self.assertEqual(row["dpr_status"], "VOID")
        self.assertTrue(row["gap"])                # but the day is not satisfied

    def test_awarded_site_never_gaps(self):
        self.site.status = Site.Status.AWARDED
        self.site.save()
        r = self.client.get(f"/api/v1/registers/dpr-tws?site={self.site.id}")
        self.assertFalse(any(row["gap"] for row in r.data["rows"]))

    def test_dashboard_flags(self):
        r = self.client.get(f"/api/v1/dashboards/site/{self.site.id}")
        self.assertIsNone(r.data["dpr_today"])
        day = last_working_days(self.site, 1)[0]
        ref = self.create_dpr(doc_date=day).data["ref"]
        self.add_photos(ref, 4)
        self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        r = self.client.get(f"/api/v1/dashboards/site/{self.site.id}")
        self.assertEqual(r.data["unverified_dprs"], 1)
