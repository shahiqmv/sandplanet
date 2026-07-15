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

    # A supply (material) + install (labour) split BOQ.
    ROWS = [
        {"section": "Bill 1 — Substructure", "description":
         "Bill 1 — Substructure", "is_heading": True},
        {"section": "Bill 1 — Substructure", "item_code": "1.1",
         "description": "Excavate for foundations", "unit": "m3",
         "qty": "120", "rate_supply": "5.00", "rate_install": "3.50"},
        {"section": "Bill 1 — Substructure", "item_code": "1.2",
         "description": "Mass concrete blinding", "unit": "m3",
         "qty": "35", "rate_supply": "80.00", "rate_install": "15.00"},
    ]

    def test_qs_saves_split_boq_totals(self):
        self.client.force_authenticate(self.qs)
        r = self.client.post(self._url("/items"), {"rows": self.ROWS},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["exists"])
        self.assertTrue(r.data["split_rates"])
        self.assertEqual(len(r.data["items"]), 3)
        # supply: 120*5 + 35*80 = 600 + 2800 = 3400
        # labour: 120*3.5 + 35*15 = 420 + 525 = 945 ; total 4345
        self.assertEqual(float(r.data["total_supply"]), 3400.0)
        self.assertEqual(float(r.data["total_install"]), 945.0)
        self.assertEqual(float(r.data["total"]), 4345.0)
        heading = next(i for i in r.data["items"] if i["is_heading"])
        self.assertEqual(float(heading["amount"]), 0.0)

    def test_combined_rate_boq_is_not_split(self):
        self.client.force_authenticate(self.qs)
        rows = [{"item_code": "1.1", "description": "Blockwork", "unit": "m2",
                 "qty": "50", "rate_combined": "20.00"}]
        r = self.client.post(self._url("/items"), {"rows": rows},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["split_rates"])
        self.assertEqual(float(r.data["total"]), 1000.0)

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


class VariationTests(TestCase):
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
        self.client.force_authenticate(self.qs)

    def _create(self, kind="ADDITION"):
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/variations/create",
            {"title": "Extra pool coping", "kind": kind, "rows": [
                {"item_code": "V1", "description": "Coping stone", "unit": "m",
                 "qty": "40", "rate_supply": "25", "rate_install": "10"}]},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["variations"][-1]

    def test_addition_adjusts_revised_only_when_approved(self):
        v = self._create("ADDITION")
        self.assertEqual(v["ref"], "VO-01")
        self.assertEqual(float(v["gross"]), 1400.0)   # 40 * (25+10)
        self.assertEqual(float(v["signed_total"]), 1400.0)
        vid = v["id"]
        # submitted → shows as a pending provision, revised unchanged
        r = self.client.post(f"/api/v1/variations/{vid}/status",
                             {"status": "SUBMITTED"}, format="json")
        c = r.data["contract"]
        self.assertEqual(float(c["revised"]), 500000.0)
        self.assertEqual(float(c["pending_net"]), 1400.0)
        self.assertEqual(float(c["forecast"]), 501400.0)
        # approved → folds into the revised contract sum
        r = self.client.post(f"/api/v1/variations/{vid}/status",
                             {"status": "APPROVED"}, format="json")
        c = r.data["contract"]
        self.assertEqual(float(c["revised"]), 501400.0)
        self.assertEqual(float(c["pending_net"]), 0.0)

    def test_omission_subtracts(self):
        v = self._create("OMISSION")
        self.assertEqual(float(v["signed_total"]), -1400.0)
        self.client.post(f"/api/v1/variations/{v['id']}/status",
                         {"status": "SUBMITTED"}, format="json")
        r = self.client.post(f"/api/v1/variations/{v['id']}/status",
                             {"status": "APPROVED"}, format="json")
        self.assertEqual(float(r.data["contract"]["revised"]), 498600.0)

    def test_approved_variation_is_locked_for_edit(self):
        v = self._create()
        self.client.post(f"/api/v1/variations/{v['id']}/status",
                         {"status": "SUBMITTED"}, format="json")
        self.client.post(f"/api/v1/variations/{v['id']}/status",
                         {"status": "APPROVED"}, format="json")
        r = self.client.post(f"/api/v1/variations/{v['id']}/items",
                             {"rows": []}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_site_staff_cannot_see_variations(self):
        self.client.force_authenticate(self.se)
        r = self.client.get(f"/api/v1/projects/{self.project.id}/variations")
        self.assertEqual(r.status_code, 403)
