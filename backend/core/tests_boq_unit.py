"""Unit-based BOQ — normalise, commit, capture endpoint, and that the
conventional path is left untouched."""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from . import boq_unit_extract as ue
from .models import Boq, BoqItem, Project, Site, User
from .tests import make_user


class BoqUnitTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SFR", name="Fushi",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("bu_qs", User.Role.QS)
        self.project = Project.objects.create(
            site=self.site, code="SFR-01", title="Villa Refurb")
        self.client = APIClient()

    def _cats(self):
        return ue.normalise([
            {"name": "Preliminaries", "amount_per_unit": 132512.18,
             "is_lump": True},
            {"name": "Category D Villas", "quantity": 11, "unit": "no",
             "amount_per_unit": 26491.41},
        ])

    def test_normalise_lump_and_priced(self):
        cats = self._cats()
        self.assertEqual(len(cats), 2)
        self.assertTrue(cats[0]["is_lump"])
        self.assertEqual(Decimal(cats[0]["line_total"]), Decimal("132512.18"))
        self.assertEqual(cats[1]["quantity"], "11")
        self.assertEqual(Decimal(cats[1]["line_total"]),
                         Decimal("26491.41") * 11)

    def test_commit_builds_unit_boq_and_value(self):
        boq, msg = ue.commit(self.project, self._cats(), self.qs)
        self.assertIsNone(msg)
        self.assertEqual(boq.mode, Boq.Mode.UNIT)
        self.assertEqual(boq.categories.count(), 2)
        # 132512.18 (lump) + 11 × 26491.41
        self.assertEqual(boq.contract_value,
                         Decimal("132512.18") + Decimal("26491.41") * 11)
        # priced category carries one per-unit line; lump carries none
        priced = boq.categories.get(is_lump=False)
        self.assertEqual(priced.items.count(), 1)
        self.assertEqual(priced.per_unit_total, Decimal("26491.410"))

    def test_capture_endpoint_returns_categories(self):
        orig = ue.run_capture
        ue.run_capture = lambda upload, model=None: (self._cats(), 8, None)
        try:
            self.client.force_authenticate(self.qs)
            f = SimpleUploadedFile("boq.pdf", b"%PDF-1.4 x", "application/pdf")
            r = self.client.post(
                f"/api/v1/projects/{self.project.id}/boq/capture-unit",
                {"file": f}, format="multipart")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.data["count"], 2)
            self.assertEqual(r.data["gst_percent"], 8)
        finally:
            ue.run_capture = orig

    def test_conventional_boq_unaffected(self):
        boq = Boq.objects.create(project=self.project)
        BoqItem.objects.create(boq=boq, description="Concrete", qty=Decimal(10),
                               rate_supply=Decimal("100"))
        self.assertEqual(boq.mode, Boq.Mode.CONVENTIONAL)   # default
        self.assertEqual(boq.contract_value, boq.total)     # == item total
        self.assertEqual(boq.contract_value, Decimal("1000.000"))

    def test_lump_only_unit_boq_can_be_claimed(self):
        # A unit BOQ of only lump bills has NO BoqItem rows; claiming must still
        # seed one line per category and value each by % (owner 2026-07-30).
        cats = ue.normalise([
            {"name": "Preliminaries", "amount_per_unit": 100000,
             "is_lump": True},
            {"name": "Provisional sum", "amount_per_unit": 50000,
             "is_lump": True}])
        ue.commit(self.project, cats, self.qs)
        self.assertFalse(
            BoqItem.objects.filter(boq__project=self.project).exists())
        self.client.force_authenticate(self.qs)
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/claims/create", {},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        cid = r.data["claims"][-1]["id"]
        d = self.client.get(f"/api/v1/claims/{cid}").data
        self.assertEqual(len(d["lines"]), 2)          # one per lump category
        self.assertTrue(all(ln["is_percent_only"] for ln in d["lines"]))

    def test_saving_flat_items_reverts_unit_boq_to_conventional(self):
        from . import commercial
        ue.commit(self.project, self._cats(), self.qs)
        boq = Boq.objects.get(project=self.project)
        self.assertEqual(boq.mode, Boq.Mode.UNIT)
        self.assertTrue(boq.categories.exists())
        # Importing / entering flat priced items cleanly converts back and drops
        # the orphan unit categories (so contract_value stops summing them).
        commercial.set_boq_items(self.project, [
            {"item_code": "1", "description": "Concrete", "unit": "m3",
             "qty": "10", "rate_combined": "100"}], self.qs)
        boq.refresh_from_db()
        self.assertEqual(boq.mode, Boq.Mode.CONVENTIONAL)
        self.assertFalse(boq.categories.exists())
        self.assertEqual(boq.contract_value, Decimal("1000.000"))
