"""Project commercial (QS) — BOQ (slice 1)."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Boq, Project, Site, User
from .tests import make_user


class BoqTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="VKR", name="Vakkaru", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=90))
        self.project = Project.objects.create(
            site=self.site, code="POOLS17", title="17 Swimming Pools",
            contract_value="500000")
        self.qs = make_user("qs1", User.Role.QS)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()

    def _url(self, tail=""):
        return f"/api/v1/projects/{self.project.id}/boq{tail}"

    ROWS = [
        {"section": "Bill 1 — Substructure", "description":
         "Bill 1 — Substructure", "is_heading": True},
        {"section": "Bill 1 — Substructure", "item_code": "1.1",
         "description": "Excavate for foundations", "unit": "m3",
         "qty": "120", "rate": "8.50"},
        {"section": "Bill 1 — Substructure", "item_code": "1.2",
         "description": "Mass concrete blinding", "unit": "m3",
         "qty": "35", "rate": "95.00"},
    ]

    def test_qs_saves_boq_and_total_excludes_headings(self):
        self.client.force_authenticate(self.qs)
        r = self.client.post(self._url("/items"), {"rows": self.ROWS},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["exists"])
        self.assertEqual(len(r.data["items"]), 3)
        # 120*8.50 + 35*95.00 = 1020 + 3325 = 4345; heading contributes 0
        self.assertEqual(float(r.data["total"]), 4345.0)
        heading = next(i for i in r.data["items"] if i["is_heading"])
        self.assertEqual(float(heading["amount"]), 0.0)

    def test_save_replaces_previous_lines(self):
        self.client.force_authenticate(self.qs)
        self.client.post(self._url("/items"), {"rows": self.ROWS},
                         format="json")
        r = self.client.post(self._url("/items"), {"rows": [self.ROWS[1]]},
                             format="json")
        self.assertEqual(len(r.data["items"]), 1)
        self.assertEqual(float(r.data["total"]), 1020.0)

    def test_locked_boq_rejects_edits(self):
        self.client.force_authenticate(self.qs)
        self.client.post(self._url("/items"), {"rows": self.ROWS},
                         format="json")
        lk = self.client.post(self._url("/lock"), {"locked": True},
                              format="json")
        self.assertTrue(lk.data["is_locked"])
        r = self.client.post(self._url("/items"), {"rows": self.ROWS},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("locked", r.data["detail"].lower())

    def test_site_staff_cannot_see_or_edit_boq(self):
        self.client.force_authenticate(self.se)
        self.assertEqual(self.client.get(self._url()).status_code, 403)
        self.assertEqual(
            self.client.post(self._url("/items"), {"rows": self.ROWS},
                             format="json").status_code, 403)

    def test_empty_boq_reads_cleanly(self):
        self.client.force_authenticate(self.qs)
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["exists"])
        self.assertEqual(r.data["items"], [])
        self.assertFalse(Boq.objects.filter(project=self.project).exists())
