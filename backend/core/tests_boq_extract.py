"""BOQ capture from PDF/Excel — extraction pipeline + review/commit flow.

The live Claude call (`_call_claude`) is monkeypatched; everything else — file
reading, normalisation, reconciliation, review edits and the commit into the
live BOQ — is exercised for real.
"""
import io
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from . import boq_extract
from .models import Boq, Project, Site, User
from .tests import make_user


def _xlsx(rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


MODEL_OUT = {
    "rate_mode": "SINGLE",
    "rows": [
        {"section": "Bill 1 — Substructure", "description": "Bill 1",
         "is_heading": True},
        {"section": "Bill 1 — Substructure", "item_code": "1.1",
         "description": "Excavate for foundations", "unit": "m3",
         "qty": "120", "rate_combined": "8.50"},
        {"section": "Bill 1 — Substructure", "item_code": "1.2",
         "description": "Mass concrete blinding", "unit": "m3",
         "qty": "35", "rate_combined": "95.00"},
    ],
    "printed_totals": [4345.0],   # 120*8.5 + 35*95 = 1020 + 3325 = 4345
}


class BoqExtractPureTests(TestCase):
    def test_normalise_cleans_numbers_and_drops_empty(self):
        rows = boq_extract.normalise_rows([
            {"description": "Excavate", "unit": "m3", "qty": "1,200",
             "rate_combined": "$8.50"},
            {"description": "", "section": "", "item_code": ""},   # dropped
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qty"], "1200")
        self.assertEqual(rows[0]["rate_combined"], "8.50")

    def test_row_warnings(self):
        self.assertEqual(boq_extract.row_warnings(
            {"description": "Bill 1", "is_heading": True}), [])
        w = boq_extract.row_warnings(
            {"description": "Excavate", "qty": "10"})   # no unit, no rate
        self.assertIn("missing unit", w)
        self.assertIn("no rate", w)
        w2 = boq_extract.row_warnings(
            {"description": "x", "unit": "m3", "qty": "ten",
             "rate_combined": "5"})
        self.assertTrue(any("isn't a number" in m for m in w2))

    def test_reconcile_matches_and_flags(self):
        rows = boq_extract.normalise_rows(MODEL_OUT["rows"])
        ok = boq_extract.reconcile(rows, [4345.0])
        self.assertEqual(ok["extracted_total"], "4345.00")
        self.assertTrue(ok["reconciled"])
        bad = boq_extract.reconcile(rows, [9999.0])
        self.assertFalse(bad["reconciled"])


class BoqCaptureFlowTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(
            site=self.site, code="POOLS", title="Pools", contract_value="50000")
        self.qs = make_user("qs1", User.Role.QS)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)

    def _upload(self):
        return SimpleUploadedFile(
            "client-boq.xlsx", _xlsx([["Section", "Code", "Description"],
                                      ["Bill 1", "", "Excavation"]]),
            content_type="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet")

    @patch("core.boq_extract._call_claude", return_value=MODEL_OUT)
    def test_capture_review_commit(self, _mock):
        # 1) extract → draft
        r = self.client.post(f"/api/v1/projects/{self.project.id}/boq/capture",
                             {"file": self._upload()}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        imp_id = r.data["id"]
        self.assertEqual(r.data["rate_mode"], "SINGLE")
        self.assertEqual(len(r.data["rows"]), 3)
        self.assertTrue(r.data["meta"]["reconciled"])
        self.assertEqual(r.data["meta"]["extracted_total"], "4345.00")

        # 2) the QS corrects a rate in the working draft
        rows = [{k: v for k, v in row.items()
                 if k in boq_extract.FIELDS} for row in r.data["rows"]]
        rows[1]["rate_combined"] = "9.00"
        r2 = self.client.put(f"/api/v1/boq-imports/{imp_id}",
                             {"rows": rows}, format="json")
        self.assertEqual(r2.status_code, 200, r2.data)
        # 120*9 + 35*95 = 1080 + 3325 = 4405 → now off the printed 4345
        self.assertEqual(r2.data["meta"]["extracted_total"], "4405.00")
        self.assertFalse(r2.data["meta"]["reconciled"])

        # 3) commit → the live BOQ is populated
        r3 = self.client.post(f"/api/v1/boq-imports/{imp_id}/commit")
        self.assertEqual(r3.status_code, 200, r3.data)
        boq = Boq.objects.get(project=self.project)
        items = list(boq.items.all())
        self.assertEqual(len(items), 3)
        priced = [i for i in items if not i.is_heading]
        self.assertEqual(len(priced), 2)
        self.assertEqual(float(priced[0].rate_supply), 9.0)   # combined→supply

        # committing again is refused
        r4 = self.client.post(f"/api/v1/boq-imports/{imp_id}/commit")
        self.assertEqual(r4.status_code, 400)

    @patch("core.boq_extract._call_claude", return_value=MODEL_OUT)
    def test_site_engineer_cannot_capture(self, _mock):
        self.client.force_authenticate(self.se)
        r = self.client.post(f"/api/v1/projects/{self.project.id}/boq/capture",
                             {"file": self._upload()}, format="multipart")
        self.assertEqual(r.status_code, 403)

    def test_missing_api_key_is_a_clear_error(self):
        # no monkeypatch + no ANTHROPIC_API_KEY → friendly 400
        with patch.dict("os.environ", {}, clear=False) as _env:
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            r = self.client.post(
                f"/api/v1/projects/{self.project.id}/boq/capture",
                {"file": self._upload()}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ANTHROPIC_API_KEY", r.data["detail"])

    @patch("core.boq_extract._call_claude", return_value=MODEL_OUT)
    def test_pdf_is_read(self, _mock):
        # render a small text PDF with WeasyPrint so pdf_pages has real text
        try:
            from weasyprint import HTML
        except Exception:
            self.skipTest("WeasyPrint unavailable")
        pdf = HTML(string="<h1>BOQ</h1><table><tr><td>1.1</td>"
                   "<td>Excavate</td><td>m3</td><td>120</td></tr></table>"
                   ).write_pdf()
        up = SimpleUploadedFile("boq.pdf", pdf, content_type="application/pdf")
        r = self.client.post(f"/api/v1/projects/{self.project.id}/boq/capture",
                             {"file": up}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["source"], "PDF")
