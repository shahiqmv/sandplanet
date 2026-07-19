import threading
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from .models import Document, Site, SitePmHistory, User
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

    def test_photo_can_be_removed_from_a_draft(self):
        # A wrong photo can be deleted while the DPR is still a draft.
        ref = self.create_dpr().data["ref"]
        self.add_photos(ref, 2)
        doc = self.client.get(f"/api/v1/documents/{ref}").data
        photos = [a for a in doc["attachments"] if a["kind"] == "PHOTO"]
        self.assertEqual(len(photos), 2)
        r = self.client.delete(
            f"/api/v1/documents/{ref}/attachments/{photos[0]['id']}")
        self.assertEqual(r.status_code, 204)
        doc = self.client.get(f"/api/v1/documents/{ref}").data
        left = [a for a in doc["attachments"] if a["kind"] == "PHOTO"]
        self.assertEqual([a["id"] for a in left], [photos[1]["id"]])

    def test_photo_cannot_be_removed_after_issue(self):
        ref = self.create_dpr().data["ref"]
        self.add_photos(ref, 1)
        pid = [a for a in self.client.get(f"/api/v1/documents/{ref}").data
               ["attachments"] if a["kind"] == "PHOTO"][0]["id"]
        self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        r = self.client.delete(
            f"/api/v1/documents/{ref}/attachments/{pid}")
        self.assertEqual(r.status_code, 400)

    def test_dpr_consumption_posts_stock_issue(self):
        # Closing the inventory loop: a key-material 'Consumed' figure on an
        # issued DPR draws that quantity down from site stock.
        from core import stock

        from .models import Item, StockMovement
        item = Item.objects.create(code="ITM-70001", description="Cement",
                                   unit="bag", is_major=True)
        stock.record_receipt(self.site, item, 100, actor=self.engineer)
        ref = self.create_dpr(payload={"weather_am": "Sunny", "materials": [
            {"item_id": item.id, "material": "Cement", "unit": "bag",
             "opening": "100", "received": "", "consumed": "15",
             "remarks": ""}]}).data["ref"]
        r = self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(float(stock.balance(self.site, item)), 85.0)
        mv = StockMovement.objects.get(document__ref=ref, kind="ISSUE")
        self.assertEqual(float(mv.qty), -15.0)

    def test_dpr_consumption_ignores_free_text_rows(self):

        from .models import StockMovement
        ref = self.create_dpr(payload={"weather_am": "Sunny", "materials": [
            {"material": "Random sand", "unit": "bag", "consumed": "5"}]}
        ).data["ref"]
        r = self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(StockMovement.objects.filter(
            document__ref=ref).exists())  # no item_id → nothing posted

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


class DprScopedReportTests(DocBase):
    """One site DPR → filtered client reports by project / trade
    (owner 2026-07-14)."""

    def _dpr(self):
        from .models import Project
        Project.objects.create(site=self.site, code="VILLAS",
                               title="Overwater Villas", pm=self.pm)
        payload = {"weather_am": "Sunny", "manpower": {}, "work_done": [
            {"project": "VILLAS", "trade": "MEP", "activity": "Cable pull",
             "progress_today": "10", "progress_todate": "40"},
            {"project": "VILLAS", "trade": "Civil", "activity": "Blockwork",
             "progress_today": "5", "progress_todate": "30"},
            {"project": "POOL", "trade": "MEP", "activity": "Pump wiring",
             "progress_today": "8", "progress_todate": "20"},
        ], "materials": [
            {"material": "Cable", "project": "VILLAS", "consumed": "5"},
            {"material": "Cement", "project": "POOL", "consumed": "2"},
        ], "machinery": [
            {"item": "Excavator", "project": "POOL", "nos": "1"},
        ]}
        r = self.create_dpr(payload=payload)
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["ref"]

    def _nrows(self, ctx):
        return sum(len(g["rows"]) for g in ctx["work_groups"])

    def test_context_filters_by_project_and_trade(self):
        from .models import Document
        from .pdf import _dpr_context
        rev = Document.objects.get(ref=self._dpr()).current_revision
        doc = rev.document
        self.assertEqual(self._nrows(_dpr_context(doc, rev)), 3)
        self.assertFalse(_dpr_context(doc, rev)["scoped"])
        mep = _dpr_context(doc, rev, {"trade": "MEP"})
        self.assertEqual(self._nrows(mep), 2)
        self.assertTrue(mep["scoped"])
        villas = _dpr_context(doc, rev, {"project": "VILLAS"})
        self.assertEqual(self._nrows(villas), 2)
        self.assertIn("Overwater Villas", villas["scope_label"])
        self.assertEqual(villas["scope_pm"], self.pm.full_name)
        combo = _dpr_context(doc, rev, {"project": "VILLAS", "trade": "MEP"})
        self.assertEqual(self._nrows(combo), 1)

    def test_project_manpower_comes_from_the_dma(self):
        from .models import Document, ManpowerCategory
        from .pdf import _dpr_context
        ManpowerCategory.objects.create(name="Mason", grp="LABOUR",
                                        list_type="DPR", sort_order=1)
        ref = self._dpr()
        # the day's DMA allocates crew to two projects
        self.client.post("/api/v1/documents", {
            "doc_type": "DMA", "site_id": self.site.id,
            "doc_date": date.today().isoformat(),
            "payload": {"tasks": [
                {"task": "Cabling", "project": "VILLAS", "category": "Mason",
                 "workers": "6"},
                {"task": "Pump base", "project": "POOL", "category": "Mason",
                 "workers": "4"}]}}, format="json")
        rev = Document.objects.get(ref=ref).current_revision
        doc = rev.document
        villas = _dpr_context(doc, rev, {"project": "VILLAS"})
        self.assertTrue(villas["manpower_from_dma"])
        self.assertEqual(villas["manpower_total"], 6)   # VILLAS crew only
        # full report keeps the DPR's own (site-wide) manpower, not the DMA
        self.assertFalse(_dpr_context(doc, rev)["manpower_from_dma"])

    def test_scoped_report_filters_materials_and_machinery(self):
        from .models import Document
        from .pdf import _dpr_context
        rev = Document.objects.get(ref=self._dpr()).current_revision
        doc = rev.document
        full = _dpr_context(doc, rev)
        self.assertEqual(len(full["material_rows"]), 2)
        self.assertEqual(len(full["machinery_rows"]), 1)
        villas = _dpr_context(doc, rev, {"project": "VILLAS"})
        self.assertEqual(len(villas["material_rows"]), 1)   # Cable only
        self.assertEqual(len(villas["machinery_rows"]), 0)  # excavator is POOL
        self.assertTrue(villas["scope_project"])
        # trade-only report: materials/machinery aren't trade-tagged → hidden
        mep = _dpr_context(doc, rev, {"trade": "MEP"})
        self.assertFalse(mep["scope_project"])

    @override_settings(MEDIA_ROOT="test-media")
    def test_report_pdf_endpoint_renders(self):
        try:
            import weasyprint  # noqa: F401
        except Exception:
            self.skipTest("WeasyPrint unavailable")
        ref = self._dpr()
        r = self.client.get(f"/api/v1/dpr/{ref}/report.pdf?trade=MEP")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")


class DashboardTwsTests(DocBase):
    """The dashboard's 'Tomorrow Work Schedule' state keys off the TWS dated
    for the day it covers, so today's schedule is not mistaken for tomorrow's
    (owner 2026-07-14)."""

    def _tws(self, d):
        r = self.client.post("/api/v1/documents", {
            "doc_type": "TWS", "site_id": self.site.id, "doc_date": d.isoformat(),
            "payload": {"activities": []}}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def test_tws_by_date_separates_today_and_tomorrow(self):
        today = date.today()
        tomorrow = today + timedelta(days=1)
        self._tws(today)                       # today's schedule (from yesterday)
        byd = self.client.get(
            f"/api/v1/dashboards/site/{self.site.id}").data["tws_by_date"]
        self.assertIn(today.isoformat(), byd)
        self.assertNotIn(tomorrow.isoformat(), byd)   # tomorrow not done yet
        self._tws(tomorrow)                     # now prepare tomorrow's
        byd = self.client.get(
            f"/api/v1/dashboards/site/{self.site.id}").data["tws_by_date"]
        self.assertIn(tomorrow.isoformat(), byd)
        self.assertEqual(byd[tomorrow.isoformat()]["status"], "DRAFT")
