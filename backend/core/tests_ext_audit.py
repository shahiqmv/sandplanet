"""External audits: a register and its papers (owner 2026-10-04)."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import ExternalAudit, User
from .tests import make_user


class ExternalAuditTests(TestCase):
    def setUp(self):
        self.finance = make_user("aud_fin", User.Role.FINANCE)
        self.director = make_user("aud_pd", User.Role.DIRECTOR)
        self.pm = make_user("aud_pm", User.Role.PM)
        self.c = APIClient()
        self.c.force_authenticate(self.finance)

    def audit(self, **kw):
        body = {"auditor": "Emmjay Associates", "period_start": "2025-01-01",
                "period_end": "2025-12-31"}
        body.update(kw)
        return self.c.post("/api/v1/audits", body, format="json")

    def test_finance_records_an_audit_and_it_names_itself(self):
        r = self.audit()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["ref"], r.data["title"], r.data["status"]),
                         ("AUD-001", "Financial statements 2025", "PLANNED"))
        self.assertEqual(self.audit(auditor="").status_code, 400)
        self.assertEqual(self.audit(period_end="2024-12-31").status_code, 400)

    def test_a_report_issued_needs_its_date(self):
        ref = self.audit().data["ref"]
        r = self.c.patch(f"/api/v1/audits/{ref}", {"status": "COMPLETED"},
                         format="json")
        self.assertEqual(r.status_code, 400)
        r = self.c.patch(f"/api/v1/audits/{ref}",
                         {"status": "COMPLETED", "report_date": "2026-10-04",
                          "opinion": "UNMODIFIED", "fee_amount": "19,275",
                          "payment_ref": "PYR-MLE-401"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["opinion_label"], "Unmodified (clean)")
        self.assertEqual(str(r.data["fee_amount"]), "19275.00")

    def test_the_report_is_uploaded_and_can_be_removed(self):
        ref = self.audit().data["ref"]
        f = SimpleUploadedFile("FS 2025.pdf", b"%PDF-1.4 x",
                               content_type="application/pdf")
        r = self.c.post(f"/api/v1/audits/{ref}/files",
                        {"file": f, "kind": "REPORT", "label": "signed"},
                        format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["files"]), 1)
        self.assertEqual(r.data["files"][0]["name"], "FS 2025.pdf")
        self.assertTrue(r.data["report_url"])
        listed = self.c.get("/api/v1/audits").data["audits"][0]
        self.assertEqual(listed["file_count"], 1)
        fid = r.data["files"][0]["id"]
        r = self.c.delete(f"/api/v1/audits/{ref}/files/{fid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["files"], [])
        r = self.c.post(f"/api/v1/audits/{ref}/files", {"kind": "REPORT"},
                        format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_the_director_reads_and_a_pm_does_not(self):
        ref = self.audit().data["ref"]
        self.c.force_authenticate(self.director)
        self.assertEqual(self.c.get(f"/api/v1/audits/{ref}").status_code, 200)
        self.assertEqual(self.audit().status_code, 403)
        self.c.force_authenticate(self.pm)
        self.assertEqual(self.c.get("/api/v1/audits").status_code, 403)
        self.assertEqual(ExternalAudit.objects.count(), 1)
