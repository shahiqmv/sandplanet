"""Bill of Materials — the per-project quantity budget, its variance report
(ordered / issued / off-BOM), the MR project gate and the planner seeding
(owner 2026-08-11)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import bom as bom_svc
from .models import (Boq, BoqCategory, BoqItem, Document,
                     DocumentLine, DocumentRevision, ImportAllocation,
                     ImportOrder, ImportOrderLine, Item, Project, Quotation,
                     QuotationLine, Site, SitePmHistory, StockMovement,
                     Supplier, User)
from .tests import make_user


class BomBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="MXB", name="Bom Isle",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(site=self.site, code="MXB-01",
                                              title="Pools", status="ACTIVE")
        self.qs = make_user("bom_qs", User.Role.QS)
        self.sa = make_user("bom_sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("bom_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.pipe = Item.objects.create(code="ITM-0001",
                                        description="Ø63 HDPE Pipe PE100",
                                        unit="mt")
        self.elbow = Item.objects.create(code="ITM-0002",
                                         description="Ø63 PVC 90° Elbow",
                                         unit="pcs")
        self.cement = Item.objects.create(code="ITM-0003",
                                          description="Cement OPC 50kg",
                                          unit="bag")
        self.client = APIClient()

    def _mr(self, project, lines, status="SUBMITTED"):
        doc = Document.objects.create(
            doc_type="MR", ref=f"MR-MXB-{Document.objects.count():03d}",
            site=self.site, project=project, doc_date=date.today(),
            status=status, created_by=self.sa)
        rev = DocumentRevision.objects.create(document=doc, rev_label="R0",
                                              payload={}, created_by=self.sa)
        doc.current_revision = rev
        doc.save(update_fields=["current_revision"])
        out = []
        for i, (item, qty) in enumerate(lines, 1):
            out.append(DocumentLine.objects.create(
                revision=rev, line_no=i, item=item, unit=item.unit,
                qty_required=qty, qty_to_order=qty))
        return doc, out


class BomVarianceTests(BomBase):
    def test_save_requires_mapped_items(self):
        n, err = bom_svc.save_bom(self.project,
                                  [{"item_id": None, "qty": "5"}], self.qs)
        self.assertIn("mapped", err)
        n, err = bom_svc.save_bom(self.project, [
            {"item_id": self.pipe.id, "qty": "100"},
            {"item_id": self.pipe.id, "qty": "50"}], self.qs)
        self.assertIn("twice", err)
        n, err = bom_svc.save_bom(self.project, [
            {"item_id": self.pipe.id, "qty": "100", "source": "BOQ"},
            {"item_id": self.elbow.id, "qty": "40"}], self.qs)
        self.assertIsNone(err)
        self.assertEqual(n, 2)

    def test_variance_orders_issues_and_off_bom(self):
        bom_svc.save_bom(self.project, [
            {"item_id": self.pipe.id, "qty": "100"},
            {"item_id": self.elbow.id, "qty": "40"}], self.qs)
        # MR demand: 60 pipe for the project (a draft MR must NOT count)
        mr, mr_lines = self._mr(self.project, [(self.pipe, Decimal("60"))])
        self._mr(self.project, [(self.pipe, Decimal("999"))], status="DRAFT")
        # domestic award: 55 of the 60 awarded on an approved PR
        pr = Document.objects.create(
            doc_type="PR", ref="PR-901", site=self.site,
            doc_date=date.today(), status="APPROVED", created_by=self.qs)
        supp = Supplier.objects.create(name="Local Vendor")
        q = Quotation.objects.create(document=pr, supplier=supp,
                                     created_by=self.qs)
        QuotationLine.objects.create(quotation=q, line_no=1,
                                     supplier_desc="63mm pipe",
                                     qty=Decimal("55"), awarded=True,
                                     mr_line=mr_lines[0])
        # import order: 30 elbows allocated to this project, authorised
        ipr = Document.objects.create(
            doc_type="IPR", ref="IPR-901", site=self.site,
            doc_date=date.today(), status="AUTHORISED", created_by=self.qs)
        order = ImportOrder.objects.create(
            document=ipr, supplier=Supplier.objects.create(
                name="Guangzhou", category="INTERNATIONAL"),
            order_currency="USD", exchange_rate=Decimal("15.42"))
        from .models import CostHead
        head = CostHead.objects.get_or_create(
            name="Materials", defaults={"sort_order": 1})[0]
        line = ImportOrderLine.objects.create(
            order=order, line_no=1, item=self.elbow, unit="pcs",
            order_qty=Decimal("30"), unit_price=Decimal("1"),
            cost_head=head)
        ImportAllocation.objects.create(line=line, project=self.project,
                                        qty=Decimal("30"))
        # issues: 20 pipe to the project, 5 cement OFF-BOM, 7 pipe general
        StockMovement.objects.create(
            site=self.site, item=self.pipe, kind="ISSUE", qty=Decimal("-20"),
            project=self.project, movement_date=date.today())
        StockMovement.objects.create(
            site=self.site, item=self.cement, kind="ISSUE", qty=Decimal("-5"),
            project=self.project, movement_date=date.today())
        StockMovement.objects.create(
            site=self.site, item=self.pipe, kind="ISSUE", qty=Decimal("-7"),
            project=None, movement_date=date.today())

        v = bom_svc.variance(self.project)
        rows = {r["code"]: r for r in v["rows"]}
        pipe = rows["ITM-0001"]
        self.assertEqual(pipe["bom_qty"], Decimal("100"))
        self.assertEqual(pipe["requested"], Decimal("60"))
        self.assertEqual(pipe["ordered"], Decimal("55"))
        self.assertEqual(pipe["issued"], Decimal("20"))   # general 7 excluded
        self.assertEqual(pipe["variance"], Decimal("45"))
        self.assertFalse(pipe["over"])
        elbow = rows["ITM-0002"]
        self.assertEqual(elbow["ordered"], Decimal("30"))
        self.assertEqual(elbow["variance"], Decimal("10"))
        # the cement was never budgeted — it must surface as OFF-BOM
        off = {r["code"]: r for r in v["off_bom"]}
        self.assertIn("ITM-0003", off)
        self.assertEqual(off["ITM-0003"]["issued"], Decimal("5"))
        self.assertEqual(v["totals"]["off_bom_items"], 1)

    def test_over_bom_flags(self):
        bom_svc.save_bom(self.project,
                         [{"item_id": self.pipe.id, "qty": "10"}], self.qs)
        mr, mr_lines = self._mr(self.project, [(self.pipe, Decimal("50"))])
        pr = Document.objects.create(
            doc_type="PR", ref="PR-902", site=self.site,
            doc_date=date.today(), status="APPROVED", created_by=self.qs)
        q = Quotation.objects.create(
            document=pr, supplier=Supplier.objects.create(name="V2"),
            created_by=self.qs)
        QuotationLine.objects.create(quotation=q, line_no=1,
                                     supplier_desc="pipe", qty=Decimal("50"),
                                     awarded=True, mr_line=mr_lines[0])
        v = bom_svc.variance(self.project)
        row = v["rows"][0]
        self.assertTrue(row["over"])
        self.assertEqual(row["variance"], Decimal("-40"))
        self.assertEqual(bom_svc.bom_balance(self.project, self.pipe),
                         Decimal("-40"))
        self.assertIsNone(bom_svc.bom_balance(self.project, self.cement))

    def test_seed_from_unit_boq_aggregates_and_matches(self):
        boq = Boq.objects.create(project=self.project, mode=Boq.Mode.UNIT)
        c1 = BoqCategory.objects.create(boq=boq, name="Model A", qty=8,
                                        unit_amount=Decimal("100"))
        c2 = BoqCategory.objects.create(boq=boq, name="Model B", qty=3,
                                        unit_amount=Decimal("100"))
        BoqItem.objects.create(boq=boq, category=c1, sort_order=1,
                               description="[PIPES] Ø63 HDPE Pipe PE100",
                               unit="mt", qty=Decimal("30"),
                               rate_supply=Decimal("4"))
        BoqItem.objects.create(boq=boq, category=c2, sort_order=1,
                               description="Ø63 HDPE Pipe PE100", unit="mt",
                               qty=Decimal("10"), rate_supply=Decimal("4"))
        BoqItem.objects.create(boq=boq, category=c1, sort_order=2,
                               description="Something unmatched", unit="no",
                               qty=Decimal("1"), rate_supply=Decimal("1"))
        rows = bom_svc.seed_from_boq(self.project)
        pipe = next(r for r in rows
                    if r["description"] == "Ø63 HDPE Pipe PE100")
        # 30×8 + 10×3, section prefix stripped, catalogue match suggested
        self.assertEqual(Decimal(pipe["qty"]), Decimal("270"))
        self.assertEqual(pipe["item_id"], self.pipe.id)
        other = next(r for r in rows
                     if r["description"] == "Something unmatched")
        self.assertIsNone(other["item_id"])


class MrProjectGateTests(BomBase):
    def _post_mr(self, body_extra):
        self.client.force_authenticate(self.sa)
        body = {"doc_type": "MR", "site_id": self.site.id,
                "doc_date": date.today().isoformat(),
                "payload": {}, "lines": [
                    {"item_id": self.pipe.id, "qty_required": "5",
                     "qty_to_order": "5", "unit": "mt"}]}
        body.update(body_extra)
        return self.client.post("/api/v1/documents", body, format="json")

    def test_mr_requires_project_or_general(self):
        r = self._post_mr({})
        self.assertEqual(r.status_code, 400)
        self.assertIn("General", r.data["detail"])
        r = self._post_mr({"general_works": True})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(Document.objects.get(ref=r.data["ref"]).project)
        r = self._post_mr({"project_id": self.project.id})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Document.objects.get(ref=r.data["ref"]).project_id,
                         self.project.id)

    def test_bom_balance_endpoint(self):
        bom_svc.save_bom(self.project,
                         [{"item_id": self.pipe.id, "qty": "100"}], self.qs)
        self.client.force_authenticate(self.sa)
        r = self.client.get(f"/api/v1/projects/{self.project.id}/bom/balance"
                            f"?item_id={self.pipe.id}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["on_bom"])
        self.assertEqual(Decimal(r.data["balance"]), Decimal("100"))
        r = self.client.get(f"/api/v1/projects/{self.project.id}/bom/balance"
                            f"?item_id={self.cement.id}")
        self.assertFalse(r.data["on_bom"])


class StockIssueGateTests(BomBase):
    def setUp(self):
        super().setUp()
        StockMovement.objects.create(
            site=self.site, item=self.pipe, kind="RECEIPT", qty=Decimal("50"),
            movement_date=date.today())

    def _issue(self, extra):
        self.client.force_authenticate(self.sa)
        body = {"lines": [{"item_id": self.pipe.id, "qty": 5}]}
        body.update(extra)
        return self.client.post(f"/api/v1/stock/{self.site.id}/issue", body,
                                format="json")

    def test_issue_requires_project_or_general(self):
        r = self._issue({})
        self.assertEqual(r.status_code, 400)
        self.assertIn("General", r.data["detail"])
        r = self._issue({"general_works": True})
        self.assertEqual(r.status_code, 201, r.data)
        r = self._issue({"project_id": self.project.id})
        self.assertEqual(r.status_code, 201, r.data)
        tagged = StockMovement.objects.filter(kind="ISSUE",
                                              project=self.project)
        self.assertEqual(tagged.count(), 1)


class PlannerSeedTests(BomBase):
    def test_schedule_seeds_from_bom(self):
        bom_svc.save_bom(self.project, [
            {"item_id": self.pipe.id, "qty": "100"},
            {"item_id": self.elbow.id, "qty": "40"}], self.qs)
        self.client.force_authenticate(self.pm)
        pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule"
        ).data["id"]
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/seed-bom")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["seeded"], 2)
        self.assertEqual(len(r.data["lines"]), 2)
        self.assertEqual({l["description"] for l in r.data["lines"]},
                         {self.pipe.description, self.elbow.description})
        # re-seeding adds nothing (items already on the plan)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/seed-bom")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["seeded"], 0)
