"""Finance and the signatory read a project's commercials and the tender
register, and write nothing (owner 2026-09-30). The screens hide the edit
controls for them; these tests hold the server to the same promise."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Project, Site, User
from .tests import make_user


class ReadOnlyCommercialsTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="ROC", name="Read Only Isle",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(
            site=self.site, code="ROC1", title="Villas", contract_value="500000")
        self.qs = make_user("ro_qs", User.Role.QS)
        self.readers = [make_user("ro_fin", User.Role.FINANCE),
                        make_user("ro_sig", User.Role.SIGNATORY)]
        self.sa = make_user("ro_sa", User.Role.SITE_ADMIN, site=self.site)
        self.c = APIClient()
        self.c.force_authenticate(self.qs)
        r = self.c.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "Resort",
            "title": "Jetty", "enquiry_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=14))}, format="json")
        assert r.status_code == 201, r.data
        self.tid = r.data["id"]

    def test_they_read_every_commercial_area(self):
        pid = self.project.id
        for u in self.readers:
            self.c.force_authenticate(u)
            for path in (f"/api/v1/projects/{pid}/boq",
                         f"/api/v1/projects/{pid}/variations",
                         f"/api/v1/projects/{pid}/claims",
                         f"/api/v1/projects/{pid}/bonds",
                         f"/api/v1/projects/{pid}/units"):
                r = self.c.get(path)
                self.assertEqual(r.status_code, 200, (u.role, path, r.data))
            self.assertFalse(self.c.get(
                f"/api/v1/projects/{pid}/bonds").data["can_edit"])

    def test_and_every_write_is_refused(self):
        pid = self.project.id
        writes = [
            ("post", f"/api/v1/projects/{pid}/boq/items", {"items": []}),
            ("post", f"/api/v1/projects/{pid}/boq/lock", {}),
            ("delete", f"/api/v1/projects/{pid}/boq/delete", {}),
            ("post", f"/api/v1/projects/{pid}/variations/create",
             {"title": "x"}),
            ("post", f"/api/v1/projects/{pid}/claims/create", {}),
            ("post", f"/api/v1/projects/{pid}/bonds", {"kind": "PB"}),
            ("post", f"/api/v1/projects/{pid}/unit-stages", {"stages": []}),
        ]
        for u in self.readers:
            self.c.force_authenticate(u)
            for method, path, body in writes:
                r = getattr(self.c, method)(path, body, format="json")
                # a refusal — not a missing page, which would prove nothing
                self.assertIn(r.status_code, (400, 403),
                              (u.role, path, r.status_code, r.data))
                self.assertIn(str(r.data.get("detail", "")).split()[0],
                              ("Only", "The", "You", "Not"),
                              (u.role, path, r.data))
        from .models import Variation
        self.assertEqual(Variation.objects.filter(project=self.project).count(), 0)

    def test_finance_reads_tenders_and_changes_none(self):
        fin = self.readers[0]
        self.c.force_authenticate(fin)
        rows = self.c.get("/api/v1/tenders").data
        rows = rows["results"] if isinstance(rows, dict) else rows
        self.assertEqual([t["id"] for t in rows], [self.tid])
        self.assertEqual(self.c.get(f"/api/v1/tenders/{self.tid}").status_code, 200)
        self.assertEqual(self.c.get(f"/api/v1/tenders/{self.tid}/boq").status_code, 200)
        for method, path, body in (
                ("post", "/api/v1/tenders", {"site_id": self.site.id,
                                             "client_name": "X", "title": "Y"}),
                ("patch", f"/api/v1/tenders/{self.tid}", {"title": "Changed"}),
                ("post", f"/api/v1/tenders/{self.tid}/boq/items", {"items": []}),
                ("post", f"/api/v1/tenders/{self.tid}/send-for-approval", {}),
                ("post", f"/api/v1/tenders/{self.tid}/approve", {})):
            r = getattr(self.c, method)(path, body, format="json")
            self.assertEqual(r.status_code, 403, (path, r.status_code, r.data))

    def test_a_site_role_cannot_search_tender_workings(self):
        """It could: the read path never asked who was looking."""
        self.c.force_authenticate(self.sa)
        r = self.c.get(f"/api/v1/tenders/{self.tid}/boq/workings/search?q=a")
        self.assertEqual(r.status_code, 403)
