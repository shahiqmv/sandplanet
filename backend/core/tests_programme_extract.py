"""Programme capture from a PDF (AI) — normalisation + the review endpoint."""
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from . import programme_extract as pe
from .models import Project, Site, SitePmHistory, User
from .tests import make_user


class ProgrammeExtractTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pg_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa", pm=self.pm)
        self.client = APIClient()

    def test_normalise_maps_model_rows_to_import_shape(self):
        out = pe.normalise([
            {"name": "Substructure", "level": 0, "duration_days": 30,
             "start": "2026-01-01", "finish": "2026-01-31"},
            {"name": "  Excavation", "level": 1, "duration_days": 0},
            {"name": "", "level": 0},                       # dropped
            {"name": "Handover", "level": 0, "is_milestone": True,
             "start": "bad-date"},
        ])
        self.assertEqual(len(out), 2 + 1)                   # 3 named rows
        self.assertEqual(out[0]["indent"], 0)
        self.assertEqual(out[1]["indent"], 1)
        self.assertTrue(out[1]["is_milestone"])             # duration 0 → milestone
        self.assertEqual(out[0]["start"], "2026-01-01")
        self.assertEqual(out[2]["start"], "")               # invalid date cleared

    def test_structure_batches_long_programme_per_page(self):
        # A long programme's task table is dense; the extractor must batch it
        # across several model calls so no single response is truncated (each
        # was silently dropping to ~16 rows when 5 pages went in one call).
        # ~4k chars/page, like a real MS-Project export, so each exceeds half
        # the per-page batch cap and lands in its own model call.
        pages = [f"[PAGE {i}]\n" + "task row\n" * 500 for i in range(1, 7)]
        calls = {"n": 0}

        def fake_call(content, model):
            calls["n"] += 1                       # one activity per batch/call
            return {"activities": [{"name": f"Task from call {calls['n']}"}]}

        orig = pe._call_claude
        pe._call_claude = fake_call
        try:
            acts = pe.structure(pages, model="x")
        finally:
            pe._call_claude = orig
        # every page batched separately → 6 calls, and structure aggregates all
        # of them (the old single-batch path lost everything past the first ~16)
        self.assertEqual(calls["n"], 6)
        self.assertEqual(len(acts), 6)

    def test_truncated_response_raises_not_silently_drops(self):
        class _Msg:
            stop_reason = "max_tokens"
            content = []

        import os
        os.environ["ANTHROPIC_API_KEY"] = "test-key"

        class _FakeClient:
            class messages:
                @staticmethod
                def create(**_):
                    return _Msg()

        import types
        fake_anthropic = types.SimpleNamespace(
            Anthropic=lambda api_key=None: _FakeClient())
        import sys
        orig = sys.modules.get("anthropic")
        sys.modules["anthropic"] = fake_anthropic
        try:
            with self.assertRaises(pe.ExtractionError):
                pe._call_claude("[PAGE 1] rows", "x")
        finally:
            if orig is not None:
                sys.modules["anthropic"] = orig
            else:
                sys.modules.pop("anthropic", None)
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_capture_endpoint_returns_activities_for_review(self):
        orig = pe.run_capture
        pe.run_capture = lambda upload, model=None: (
            [{"name": "Piling", "indent": 1, "duration_days": 12,
              "start": "2026-02-01", "finish": "2026-02-12",
              "is_milestone": False}], None)
        try:
            self.client.force_authenticate(self.pm)
            f = SimpleUploadedFile("prog.pdf", b"%PDF-1.4 x", "application/pdf")
            r = self.client.post(
                f"/api/v1/projects/{self.project.id}/programme/capture",
                {"file": f}, format="multipart")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.data["count"], 1)
            self.assertEqual(r.data["activities"][0]["name"], "Piling")
        finally:
            pe.run_capture = orig

    def test_capture_needs_a_file(self):
        self.client.force_authenticate(self.pm)
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/programme/capture", {},
            format="multipart")
        self.assertEqual(r.status_code, 400)
