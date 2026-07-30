"""Procurement Schedule — bundle grouping (collapse same-material, same-supplier
variant lines into one expandable summary row)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import procurement_client, procurement_grouping as g
from .models import ProcurementSchedule, SitePmHistory, Project, Site, User
from .tests import make_user


def _stage(key, state):
    return {"key": key, "label": key.upper(), "state": state}


def _ld(bundle="", supplier="", risk="ON_TRACK", tds="done", order="pending",
        qty="10", uom="nos", req=None, est=None, section_id=1):
    return {
        "section_id": section_id, "bundle": bundle, "bundle_supplier": supplier,
        "risk": {"level": risk, "projected": req, "reason": ""},
        "pipeline": [_stage("tds", tds), _stage("order", order),
                     _stage("production", "pending"), _stage("shipment", "none"),
                     _stage("delivery", "none"), _stage("eta", "none")],
        "required_date": req, "quantity": Decimal(qty), "uom": uom,
        "make_brand": "Kapoor", "source_country": "China",
        "category": "Timber & Joinery", "supply_by": "CONTRACTOR",
        "estimated_value": (Decimal(est) if est else None), "committed": None,
    }


class GroupRowsTests(TestCase):
    """The pure grouping function — the risky rollup logic, no DB."""

    def test_same_bundle_and_supplier_collapse_with_rollup(self):
        rows = g.group_rows([
            _ld("Deck Timber", "Kapoor", risk="ON_TRACK", qty="10",
                req=date(2026, 9, 1), est="100"),
            _ld("Deck Timber", "Kapoor", risk="LATE", qty="15",
                req=date(2026, 8, 1), est="200"),
        ], values=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "bundle")
        s = rows[0]["summary"]
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["risk"]["level"], "LATE")            # worst
        self.assertEqual(s["required_date"], date(2026, 8, 1))  # earliest
        self.assertEqual(s["quantity"], Decimal("25"))          # summed (same uom)
        self.assertEqual(s["estimated_value"], Decimal("300"))
        tds = next(x for x in s["pipeline"] if x["key"] == "tds")
        order = next(x for x in s["pipeline"] if x["key"] == "order")
        self.assertEqual(tds["state"], "done")     # all members done
        self.assertEqual(order["state"], "pending")  # none done yet

    def test_same_bundle_splits_by_supplier(self):
        rows = g.group_rows([
            _ld("Deck Timber", "Supplier A"), _ld("Deck Timber", "Supplier A"),
            _ld("Deck Timber", "Supplier B"), _ld("Deck Timber", "Supplier B"),
        ], values=False)
        bundles = [r for r in rows if r["kind"] == "bundle"]
        self.assertEqual(len(bundles), 2)
        self.assertEqual({b["summary"]["supplier"] for b in bundles},
                         {"Supplier A", "Supplier B"})

    def test_lone_bundled_line_stays_a_line(self):
        rows = g.group_rows([_ld("Solo bundle", "X")], values=False)
        self.assertEqual(rows[0]["kind"], "line")

    def test_unbundled_line_passes_through(self):
        rows = g.group_rows([_ld("", "")], values=False)
        self.assertEqual(rows[0]["kind"], "line")

    def test_mixed_units_are_not_summed(self):
        rows = g.group_rows([
            _ld("Bundle", "S", qty="10", uom="nos"),
            _ld("Bundle", "S", qty="5", uom="m")], values=False)
        self.assertIsNone(rows[0]["summary"]["quantity"])
        self.assertEqual(rows[0]["summary"]["count"], 2)


class GroupingIntegrationTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("gg_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa Upgrades", pm=self.pm)
        self.purch = make_user("gg_buy", User.Role.HO_PURCHASING)
        self.director = make_user("gg_dir", User.Role.DIRECTOR)
        self.client = APIClient()

    def _add(self, pk, **plan):
        # A new line renumbers to s_no=1, so it sorts FIRST in the response.
        return self.client.post(
            f"/api/v1/procurement-schedules/{pk}/lines",
            {"section_code": "A", **plan}, format="json").data["lines"][0]["id"]

    def _open(self):
        self.client.force_authenticate(self.pm)
        return self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]

    def test_two_same_bundle_lines_collapse_in_planner_and_client(self):
        pk = self._open()
        self._add(pk, description="Timber 90x40", bundle="Deck & Fence Timber")
        self._add(pk, description="Timber 50x30", bundle="Deck & Fence Timber")
        self._add(pk, description="Manhole cover")   # standalone
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        rows = d["groups"][str(d["lines"][0]["section_id"])]
        kinds = sorted(r["kind"] for r in rows)
        self.assertEqual(kinds, ["bundle", "line"])
        bundle = next(r for r in rows if r["kind"] == "bundle")
        self.assertEqual(bundle["summary"]["count"], 2)
        self.assertEqual(len(bundle["members"]), 2)
        # client plan collapses the two timber lines to one summary row
        sched = ProcurementSchedule.objects.get(project=self.project)
        plan = procurement_client.client_plan(sched)
        descs = [r["description"] for sec in plan["sections"] for r in sec["rows"]]
        self.assertIn("Deck & Fence Timber", descs)
        self.assertEqual(descs.count("Deck & Fence Timber"), 1)
        self.assertEqual(len([sec for sec in plan["sections"]
                              for r in sec["rows"]]), 2)  # bundle + standalone

    def test_bundle_splits_when_purchasing_sets_two_suppliers(self):
        pk = self._open()
        a1 = self._add(pk, description="Timber 90x40", bundle="Deck Timber")
        a2 = self._add(pk, description="Timber 50x30", bundle="Deck Timber")
        b1 = self._add(pk, description="Timber 125x75", bundle="Deck Timber")
        b2 = self._add(pk, description="Timber 90x30", bundle="Deck Timber")
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        for lid in (a1, a2):
            self.client.patch(f"/api/v1/procurement-schedule-lines/{lid}",
                              {"planned_supplier": "Supplier A"}, format="json")
        for lid in (b1, b2):
            self.client.patch(f"/api/v1/procurement-schedule-lines/{lid}",
                              {"planned_supplier": "Supplier B"}, format="json")
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        rows = d["groups"][str(d["lines"][0]["section_id"])]
        bundles = [r for r in rows if r["kind"] == "bundle"]
        self.assertEqual(len(bundles), 2)   # same bundle, split by supplier
        self.assertEqual({b["summary"]["supplier"] for b in bundles},
                         {"Supplier A", "Supplier B"})
