"""Phase 1B — International procurement. P1B-a: Supplier categories + the PMR
(Project Material Requisition) requirement raised and tracked project→PM→HO→
Director."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (CostHead, CostPosting, Document, DocumentRevision,
                     Project, SitePmHistory, Site, Supplier, User)
from .tests import make_user


class PmrBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.ho = make_user("ho", User.Role.HO_PURCHASING)
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.project = Project.objects.create(site=self.site, code="P1",
                                              title="Overwater villas",
                                              pm=self.pm)
        self.client = APIClient()

    def create_pmr(self):
        self.client.force_authenticate(self.sa)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "PMR", "site_id": self.site.id,
            "project_id": self.project.id,
            "payload": {"discipline": "MEP", "justification": "long lead"},
            "lines": [{"free_text_desc": "Chilled-water pump", "qty_required": 4,
                       "unit": "nos", "spec": "50 m3/h, 4 bar",
                       "mar_ref": "MAR-SJR-002"}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data


class PmrWorkflowTests(PmrBase):
    def test_pmr_is_per_site_and_project_scoped(self):
        pmr = self.create_pmr()
        self.assertTrue(pmr["ref"].startswith("PMR-SJR-"))
        doc = Document.objects.get(ref=pmr["ref"])
        self.assertEqual(doc.project_id, self.project.id)
        line = doc.current_revision.lines.first()
        self.assertEqual(line.spec, "50 m3/h, 4 bar")
        self.assertEqual(line.mar_ref, "MAR-SJR-002")

    def test_full_thread_site_to_director(self):
        pmr = self.create_pmr()
        ref = pmr["ref"]

        def act(user, action, **body):
            self.client.force_authenticate(user)
            return self.client.post(
                f"/api/v1/documents/{ref}/actions/{action}", body,
                format="json")

        self.assertEqual(act(self.sa, "submit").data["status"], "SUBMITTED")
        self.assertEqual(act(self.pm, "approve").data["status"], "PM_APPROVED")
        self.assertEqual(act(self.ho, "ho-review").data["status"],
                         "HO_REVIEWED")
        r = act(self.director, "size-release", comment="Order 10 (MOQ)")
        self.assertEqual(r.data["status"], "SIZED_RELEASED")
        doc = Document.objects.get(ref=ref)
        self.assertEqual((doc.current_revision.payload or {})
                         .get("sizing", {}).get("note"), "Order 10 (MOQ)")

    def test_wrong_role_cannot_advance(self):
        pmr = self.create_pmr()
        ref = pmr["ref"]
        self.client.force_authenticate(self.sa)
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        # HO cannot PM-approve; Director cannot ho-review
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                             format="json")
        self.assertEqual(r.status_code, 403)

    def test_return_to_draft_from_ho(self):
        pmr = self.create_pmr()
        ref = pmr["ref"]
        self.client.force_authenticate(self.sa)
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/return",
                             {"comment": "spec unclear"}, format="json")
        self.assertEqual(r.data["status"], "DRAFT")


class IprBase(PmrBase):
    def setUp(self):
        super().setUp()
        self.finance = make_user("fin", User.Role.FINANCE)
        self.signatory = make_user("sig", User.Role.SIGNATORY)
        self.supplier = Supplier.objects.create(
            name="Guangzhou Pumps Co", category="INTERNATIONAL",
            country="China", default_currency="USD")
        self.head = CostHead.objects.get_or_create(
            name="Materials", defaults={"sort_order": 1})[0]
        CostHead.objects.get_or_create(
            name="General Stock", defaults={"is_pool": True})
        # a sized-and-released PMR ready to be ordered
        self.pmr = Document.objects.create(
            doc_type="PMR", ref="PMR-SJR-050", site=self.site,
            project=self.project, doc_date=date.today(),
            status="SIZED_RELEASED", created_by=self.pm)
        rev = DocumentRevision.objects.create(document=self.pmr, rev_label="R0",
                                              payload={}, created_by=self.pm)
        self.pmr.current_revision = rev
        self.pmr.save(update_fields=["current_revision"])

    def create_and_authorise(self):
        """Create the order, award it, and authorise it on a voucher."""
        from .vouchers import approve_voucher, create_voucher, submit_voucher
        self.client.force_authenticate(self.ho)
        ref = self.client.post("/api/v1/ipr", self.order_body(),
                               format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        pv, _ = create_voucher([ref], self.finance)
        submit_voucher(pv, self.finance)
        approve_voucher(pv, self.signatory)
        return ref

    def order_body(self, proj_qty=6, stock_qty=4):
        return {
            "supplier_id": self.supplier.id, "order_currency": "USD",
            "exchange_rate": "15", "incoterm": "FOB",
            "pmr_refs": [self.pmr.ref],
            "lines": [{
                "free_text_desc": "Chilled-water pump", "unit": "nos",
                "order_qty": proj_qty + stock_qty, "unit_price": "100",
                "cost_head_id": self.head.id,
                "allocations": [
                    {"project_id": self.project.id, "qty": proj_qty},
                    {"project_id": None, "qty": stock_qty},
                ],
            }],
        }


class IprFlowTests(IprBase):
    def test_create_award_authorise_commits_split(self):
        self.client.force_authenticate(self.ho)
        r = self.client.post("/api/v1/ipr", self.order_body(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ref = r.data["ref"]
        self.assertTrue(ref.startswith("IPR-"))          # global numbering
        self.assertEqual(r.data["mvr_total"], 15000)     # 1000 USD * 15
        # creating the order moved the PMR into sourcing
        self.pmr.refresh_from_db()
        self.assertEqual(self.pmr.status, "SOURCING")

        # HO submits, Director awards → PMR advances to ORDERED
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                             format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        self.pmr.refresh_from_db()
        self.assertEqual(self.pmr.status, "ORDERED")
        # nothing committed yet — award is not the commitment point
        self.assertFalse(CostPosting.objects.filter(source="IPR").exists())

        # Finance vouchers it, signatory approves → COMMITTED split posts
        from .vouchers import approve_voucher, create_voucher, submit_voucher
        pv, err = create_voucher([ref], self.finance)
        self.assertIsNone(err, err)
        submit_voucher(pv, self.finance)
        approve_voucher(pv, self.signatory)

        doc = Document.objects.get(ref=ref)
        self.assertEqual(doc.status, "AUTHORISED")
        posts = CostPosting.objects.filter(source="IPR", state="COMMITTED")
        # project leg: 6 * 100 * 15 = 9000 to the project's site
        proj_leg = posts.get(is_stock_pool=False)
        self.assertEqual(proj_leg.site_id, self.site.id)
        self.assertEqual(float(proj_leg.amount), 9000.0)
        # general-stock leg: 4 * 100 * 15 = 6000 to the pool, not a project
        pool_leg = posts.get(is_stock_pool=True)
        self.assertEqual(float(pool_leg.amount), 6000.0)
        self.assertEqual(float(sum(p.amount for p in posts)), 15000.0)

    def test_allocations_must_sum_to_order_qty(self):
        self.client.force_authenticate(self.ho)
        body = self.order_body(proj_qty=6, stock_qty=1)  # sums to 7, qty 10
        body["lines"][0]["order_qty"] = 10
        r = self.client.post("/api/v1/ipr", body, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("sum to the order", r.data["detail"])

    def test_site_staff_cannot_view_import_prices(self):
        self.client.force_authenticate(self.ho)
        ref = self.client.post("/api/v1/ipr", self.order_body(),
                               format="json").data["ref"]
        self.client.force_authenticate(self.sa)   # site admin
        r = self.client.get(f"/api/v1/ipr/{ref}")
        self.assertEqual(r.status_code, 404)       # invisible to site staff


class MilestonePaymentTests(IprBase):
    def test_schedule_pay_splits_and_posts_fx(self):
        ref = self.create_and_authorise()   # order 1000 USD @ 15 = 15000 MVR
        # 30% advance + 70% balance
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "trigger": "ADVANCE", "percent": "30"},
            {"label": "Balance", "trigger": "BALANCE", "percent": "70"},
        ]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        advance = next(m for m in r.data["milestones"] if m["label"] == "Advance")
        self.assertEqual(float(advance["due_amount"]), 300.0)   # 30% of 1000

        # mark the advance due → Finance queue
        self.client.post(
            f"/api/v1/ipr/{ref}/milestones/{advance['id']}/due", {},
            format="json")
        self.client.force_authenticate(self.finance)
        due = self.client.get("/api/v1/ipr/payments-due").data
        self.assertEqual(len(due), 1)
        self.assertEqual(float(due[0]["expected_mvr"]), 4500.0)  # 300*15

        # pay it — actual rate 15.42 → MVR 4626 (committed value 4500, FX +126)
        r = self.client.post(
            f"/api/v1/ipr/{ref}/milestones/{advance['id']}/pay",
            {"mvr_paid": "4626", "tt_ref": "TT-88"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

        paid = CostPosting.objects.filter(state="PAID", document__ref=ref)
        # project leg 0.3*9000=2700, general-stock leg 0.3*6000=1800
        proj = paid.filter(source="IPR", is_stock_pool=False)
        self.assertEqual(float(sum(p.amount for p in proj)), 2700.0)
        stock = paid.filter(source="IPR", is_stock_pool=True)
        self.assertEqual(float(sum(p.amount for p in stock)), 1800.0)
        # realised FX to the Foreign Exchange pool, never a project
        fx = paid.get(source="FX")
        self.assertEqual(float(fx.amount), 126.0)
        self.assertTrue(fx.is_stock_pool)
        self.assertEqual(fx.cost_head.name, "Foreign Exchange")
        # total cash out reconciles to what Finance paid
        self.assertEqual(float(sum(p.amount for p in paid)), 4626.0)

    def test_schedule_must_sum_to_order_total(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "percent": "30"},
            {"label": "Balance", "percent": "50"},   # only 80%
        ]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("sum to the order total", r.data["detail"])

    def test_only_finance_pays(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        m = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Full", "percent": "100"}]}, format="json") \
            .data["milestones"][0]
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due", {},
                         format="json")
        # HO cannot pay
        r = self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/pay",
                             {"mvr_paid": "15420"}, format="json")
        self.assertEqual(r.status_code, 403)


class SupplierCategoryTests(PmrBase):
    def test_category_filter_and_bank_visibility(self):
        Supplier.objects.create(name="Local Hardware",
                                category=Supplier.Category.LOCAL)
        Supplier.objects.create(name="Guangzhou Pumps Co",
                                category=Supplier.Category.INTERNATIONAL,
                                country="China", default_currency="USD",
                                bank_details="ICBC ...acct 123")
        # category filter
        self.client.force_authenticate(self.ho)
        r = self.client.get("/api/v1/suppliers?category=INTERNATIONAL")
        names = [s["name"] for s in r.data]
        self.assertEqual(names, ["Guangzhou Pumps Co"])
        self.assertIn("bank_details", r.data[0])   # HO sees bank details
        # site staff never see bank details
        self.client.force_authenticate(self.sa)
        r = self.client.get("/api/v1/suppliers?category=INTERNATIONAL")
        self.assertNotIn("bank_details", r.data[0])
