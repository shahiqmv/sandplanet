"""QA / QC — inspection & test plans, non-conformance, supplier evaluation.

The audit found real submittal workflows but no NCR register and no supplier
evaluation: a quality failure had nowhere to live, and a supplier who kept
causing them was never rated (conformance audit 2026-08-28)."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Document, NonConformance, Site, Supplier, User)
from .tests import make_user


class ItpTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="QA1", name="Quality site",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("se_qa1", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def _itp(self, **extra):
        body = {"site_id": self.site.id, "title": "Concrete works",
                "discipline": "Civil",
                "items": [
                    {"activity": "Rebar before pour", "point_type": "HOLD",
                     "reference": "SPEC 03200 cl.3.4",
                     "acceptance_criteria": "Cover 40mm, laps 40d",
                     "responsible": "CONSULTANT"},
                    {"activity": "Slump test", "point_type": "WITNESS",
                     "frequency": "Every truck"}]}
        body.update(extra)
        return self.client.post("/api/v1/quality/itps", body, format="json")

    def test_a_plan_records_its_hold_points(self):
        r = self._itp()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("ITP-"))
        self.assertEqual(r.data["progress"]["items"], 2)
        self.assertEqual(r.data["progress"]["holds_outstanding"], 1)

    def test_a_plan_with_no_points_is_refused(self):
        self.assertEqual(self._itp(items=[]).status_code, 400)

    def test_signing_off_a_hold_point_clears_it(self):
        plan = self._itp().data
        hold = next(i for i in plan["items"] if i["point_type"] == "HOLD")
        r = self.client.post(
            f"/api/v1/quality/itp-items/{hold['id']}/record",
            {"result": "PASS", "location": "Villa 3 slab",
             "inspected_on": str(date.today())}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        fresh = self.client.get("/api/v1/quality/itps").data[0]
        self.assertEqual(fresh["progress"]["holds_outstanding"], 0)

    def test_a_failed_point_does_not_count_as_signed_off(self):
        plan = self._itp().data
        hold = next(i for i in plan["items"] if i["point_type"] == "HOLD")
        self.client.post(f"/api/v1/quality/itp-items/{hold['id']}/record",
                         {"result": "FAIL", "note": "Cover short"},
                         format="json")
        fresh = self.client.get("/api/v1/quality/itps").data[0]
        self.assertEqual(fresh["progress"]["holds_outstanding"], 1)
        self.assertEqual(fresh["progress"]["failed"], 1)

    def test_a_revision_supersedes_its_predecessor(self):
        first = self._itp().data
        second = self._itp(supersedes_id=first["id"]).data
        self.assertEqual(second["supersedes_ref"], first["ref"])
        self.assertEqual(Document.objects.get(ref=first["ref"]).status,
                         "SUPERSEDED")


class NcrTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="QA2", name="NCR site",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("se_qa2", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("pm_qa2", User.Role.PM, site=self.site)
        self.supplier = Supplier.objects.create(name="Reef Aggregates")
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def _ncr(self, **extra):
        body = {"site_id": self.site.id, "category": "WORKMANSHIP",
                "severity": "MAJOR",
                "description": "Blockwork out of plumb by 25mm.",
                "requirement": "SPEC 04200 cl.3.2 — max 5mm in 2.4m",
                "location": "Villa 3, west wall"}
        body.update(extra)
        return self.client.post("/api/v1/quality/ncrs", body, format="json")

    def test_raising_an_ncr_numbers_and_opens_it(self):
        r = self._ncr()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("NCR-"))
        self.assertEqual(r.data["status"], "OPEN")

    def test_an_ncr_must_say_what_it_breaches(self):
        """Without a requirement it is an opinion, not a finding."""
        r = self._ncr(requirement="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("fails to meet", r.data["detail"])

    def test_a_site_engineer_cannot_decide_the_disposition(self):
        """Anyone can say this is wrong; 'use it anyway' is an engineering
        decision."""
        ref = self._ncr().data["ref"]
        r = self.client.post(f"/api/v1/quality/ncrs/{ref}/disposition",
                             {"disposition": "USE_AS_IS",
                              "disposition_note": "Acceptable"},
                             format="json")
        self.assertEqual(r.status_code, 403)

    def test_use_as_is_needs_a_reason_on_the_record(self):
        ref = self._ncr().data["ref"]
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/quality/ncrs/{ref}/disposition",
                             {"disposition": "USE_AS_IS"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("reason", r.data["detail"])

    def test_it_cannot_close_before_the_work_is_decided(self):
        ref = self._ncr().data["ref"]
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/quality/ncrs/{ref}/close")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Decide what happens", r.data["detail"])

    def test_it_cannot_close_with_an_open_corrective_action(self):
        ref = self._ncr().data["ref"]
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/quality/ncrs/{ref}/disposition",
                         {"disposition": "REWORK"}, format="json")
        self.client.post(f"/api/v1/quality/ncrs/{ref}/actions",
                         {"description": "Take down and rebuild",
                          "owner_id": self.se.id,
                          "due_date": str(date.today() + timedelta(days=3))},
                         format="json")
        r = self.client.post(f"/api/v1/quality/ncrs/{ref}/close")
        self.assertEqual(r.status_code, 400)
        self.assertIn("still open", r.data["detail"])

    def test_ncr_actions_land_in_the_same_register_as_safety(self):
        """One open-actions list, whatever raised the item."""
        ref = self._ncr().data["ref"]
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/quality/ncrs/{ref}/actions",
                         {"description": "Rebuild the wall",
                          "owner_id": self.se.id,
                          "due_date": str(date.today() + timedelta(days=3))},
                         format="json")
        rows = self.client.get("/api/v1/hse/actions?status=open").data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_ref"], ref)

    def test_it_closes_once_decided_and_the_action_is_verified(self):
        ref = self._ncr().data["ref"]
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/quality/ncrs/{ref}/disposition",
                         {"disposition": "REWORK"}, format="json")
        r = self.client.post(f"/api/v1/quality/ncrs/{ref}/close",
                             {"note": "Rebuilt and re-inspected."},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "CLOSED")

    def test_another_site_cannot_see_it(self):
        ref = self._ncr().data["ref"]
        other = Site.objects.create(code="QA9", name="Other",
                                    status=Site.Status.ACTIVE)
        outsider = make_user("se_qa9", User.Role.SITE_ENGINEER, site=other)
        self.client.force_authenticate(outsider)
        self.assertEqual(
            self.client.get(f"/api/v1/quality/ncrs/{ref}").status_code, 404)


class SupplierEvaluationTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="QA3", name="Eval site",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("qs_qa3", User.Role.QS)
        self.supplier = Supplier.objects.create(name="Island Steel")
        self.client = APIClient()
        self.client.force_authenticate(self.qs)

    def _evaluate(self, **extra):
        body = {"supplier_id": self.supplier.id,
                "period_start": str(date.today() - timedelta(days=90)),
                "period_end": str(date.today()),
                "quality": 4, "delivery": 3, "price": 4,
                "responsiveness": 5, "documentation": 4}
        body.update(extra)
        return self.client.post("/api/v1/quality/supplier-evaluations", body,
                                format="json")

    def test_a_rating_averages_and_bands(self):
        r = self._evaluate()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(str(r.data["score"]), "4.00")
        self.assertEqual(r.data["band"], "APPROVED")

    def test_out_of_range_scores_are_clamped(self):
        r = self._evaluate(quality=9, delivery=0)
        self.assertEqual(r.data["quality"], 5)
        self.assertEqual(r.data["delivery"], 1)

    def test_the_ncr_count_is_evidence_beside_the_opinion(self):
        """A supplier rated highly while carrying non-conformances is a
        conversation worth having."""
        doc = Document.objects.create(
            doc_type="NCR", ref="NCR-QA3-001", site=self.site,
            doc_date=date.today(), status="OPEN", created_by=self.qs)
        NonConformance.objects.create(
            document=doc, category="MATERIAL", severity="MAJOR",
            raised_by=self.qs, raised_on=date.today(),
            description="Bar diameter under size", requirement="BS 4449",
            supplier=self.supplier)
        r = self._evaluate()
        self.assertEqual(r.data["ncr_count"], 1)

    def test_re_rating_the_same_period_replaces_it(self):
        self._evaluate()
        self._evaluate(quality=1, delivery=1, price=1, responsiveness=1,
                       documentation=1)
        rows = self.client.get(
            f"/api/v1/quality/supplier-evaluations?supplier="
            f"{self.supplier.id}").data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["band"], "UNACCEPTABLE")

    def test_the_scorecard_shows_performance_beside_the_name(self):
        self._evaluate()
        rows = self.client.get(
            "/api/v1/quality/supplier-scorecards?rated=1").data
        row = next(r for r in rows if r["supplier_id"] == self.supplier.id)
        self.assertEqual(row["band"], "APPROVED")
        self.assertEqual(row["ncrs_12m"], 0)

    def test_a_period_must_end_after_it_starts(self):
        r = self._evaluate(period_start=str(date.today()),
                           period_end=str(date.today() - timedelta(days=5)))
        self.assertEqual(r.status_code, 400)
