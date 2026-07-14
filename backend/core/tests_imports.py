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

    def test_pmr_register_and_dashboard_flag_pending_order(self):
        """A sized-and-released PMR shows as pending-order in the register and
        the HO dashboard (owner 2026-07-14)."""
        pmr = self.create_pmr()
        ref = pmr["ref"]

        def act(user, action, **body):
            self.client.force_authenticate(user)
            return self.client.post(
                f"/api/v1/documents/{ref}/actions/{action}", body,
                format="json")
        act(self.sa, "submit")
        act(self.pm, "approve")
        act(self.ho, "ho-review")
        act(self.director, "size-release", comment="Order 10")

        self.client.force_authenticate(self.ho)
        reg = self.client.get("/api/v1/pmr/register?filter=pending_order").data
        row = next(r for r in reg if r["ref"] == ref)
        self.assertTrue(row["pending_order"])
        self.assertIn("order", row["next_action"].lower())
        dash = self.client.get("/api/v1/dashboards/ho").data
        self.assertEqual(dash["pmrs_pending_order"], 1)
        # site staff cannot see the register
        self.client.force_authenticate(self.sa)
        self.assertEqual(
            self.client.get("/api/v1/pmr/register").status_code, 403)

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
        """Create the order, award it (Director), and authorise it directly
        (Signatory) — no voucher: placing the order is a commitment, not a
        payment."""
        self.client.force_authenticate(self.ho)
        ref = self.client.post("/api/v1/ipr", self.order_body(),
                               format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {},
                         format="json")
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

        # a signatory authorises the order directly (no voucher — placing the
        # order is a commitment, not a payment) → COMMITTED split posts
        self.client.force_authenticate(self.signatory)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)

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

        # mark the advance due → Finance queue (awaiting a voucher)
        self.client.post(
            f"/api/v1/ipr/{ref}/milestones/{advance['id']}/due", {},
            format="json")
        self.client.force_authenticate(self.finance)
        due = self.client.get("/api/v1/ipr/payments-due").data
        self.assertEqual(len(due), 1)
        self.assertEqual(float(due[0]["expected_mvr"]), 4500.0)  # 300*15
        self.assertEqual(due[0]["stage"], "AWAITING_VOUCHER")

        # a due (un-vouchered) TT cannot be paid yet
        r = self.client.post(
            f"/api/v1/ipr/{ref}/milestones/{advance['id']}/pay",
            {"mvr_paid": "4626", "tt_ref": "TT-88"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("authorised on a Payment Voucher", r.data["detail"])

        # Finance batches the TT onto a voucher; a signatory approves it
        from .vouchers import (approve_voucher, create_voucher,
                               submit_voucher)
        pv, err = create_voucher([], self.finance,
                                 milestone_ids=[advance["id"]])
        self.assertIsNone(err, err)
        # the voucher authorises the TT in the order currency (USD 300)
        line = pv.voucher_lines.get()
        self.assertEqual(float(line.amount), 300.0)
        self.assertEqual(line.currency, "USD")
        submit_voucher(pv, self.finance)
        approve_voucher(pv, self.signatory)

        # the milestone now carries its authorising voucher and is ready to pay
        due = self.client.get("/api/v1/ipr/payments-due").data
        self.assertEqual(due[0]["stage"], "READY")
        self.assertEqual(due[0]["voucher_ref"], pv.ref)

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

    def test_milestone_voucher_does_not_hide_other_awaiting(self):
        """Regression: a milestone voucher line has a null source_document —
        it must not poison awaiting_voucher()'s exclude() (which wiped every
        PR/PYR on SQLite when None leaked into the id list)."""
        from .vouchers import (_on_live_voucher, awaiting_voucher,
                               create_voucher)
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        m = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Full", "trigger": "ADVANCE", "percent": "100"}]},
            format="json").data["milestones"][0]
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due", {},
                         format="json")
        pv, err = create_voucher([], self.finance, milestone_ids=[m["id"]])
        self.assertIsNone(err, err)
        self.assertNotIn(None, list(_on_live_voucher()))
        self.assertIsInstance(awaiting_voucher(), list)

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


class ShipmentTests(IprBase):
    def _file(self, name="doc.pdf"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, b"%PDF-1.4 test",
                                  content_type="application/pdf")

    def test_shipment_lifecycle_fires_milestones_and_gates_clearing(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        # 40% on B/L + 60% on arrival
        self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "On BL", "trigger": "BL", "percent": "40"},
            {"label": "On arrival", "trigger": "ARRIVAL", "percent": "60"},
        ]}, format="json")

        r = self.client.post(f"/api/v1/ipr/{ref}/shipments",
                             {"mode": "SEA", "vessel_flight": "MV Test",
                              "container_awb": "CONT-1"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ship = r.data["shipments"][0]
        sid = ship["id"]

        def milestone(label):
            doc = self.client.get(f"/api/v1/ipr/{ref}").data
            return next(m for m in doc["milestones"] if m["label"] == label)

        # upload the B/L → BL milestone becomes due
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/documents",
                             {"doc_type": "BL_AWB", "file": self._file()},
                             format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(milestone("On BL")["status"], "DUE")
        self.assertEqual(milestone("On arrival")["status"], "PENDING")

        # ship → arrived fires the arrival milestone
        self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/status",
                         {"status": "SHIPPED"}, format="json")
        self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/status",
                         {"status": "ARRIVED"}, format="json")
        self.assertEqual(milestone("On arrival")["status"], "DUE")

        # can't go under clearing without packing list + commercial invoice
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/status",
                             {"status": "UNDER_CLEARING"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("PACKING_LIST", r.data["detail"])
        for t in ("PACKING_LIST", "COMMERCIAL_INVOICE"):
            self.client.post(
                f"/api/v1/ipr/{ref}/shipments/{sid}/documents",
                {"doc_type": t, "file": self._file()}, format="multipart")
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/status",
                             {"status": "UNDER_CLEARING"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["shipments"][0]["status"], "UNDER_CLEARING")

    def test_clearing_charges_total(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        sid = self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                               format="json").data["shipments"][0]["id"]
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/charges",
                             {"customs_duty": "1200", "import_gst": "800",
                              "port_handling": "300", "agent_charges": "500",
                              "local_transport": "200"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(float(r.data["shipments"][0]["clearing_total"]), 3000.0)

    def test_only_ho_manages_shipments(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.sa)   # site admin
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                             format="json")
        self.assertEqual(r.status_code, 404)   # site staff can't see IPRs


class StoreReceiptTests(IprBase):
    def _shipment(self, ref):
        return self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                                format="json").data["shipments"][0]["id"]

    def test_landed_cost_receipt_creates_valued_lots(self):
        ref = self.create_and_authorise()   # 1000 USD @ 15 = 15000 goods
        self.client.force_authenticate(self.ho)
        sid = self._shipment(ref)
        self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/charges",
                         {"freight": "1000", "customs_duty": "500"},
                         format="json")   # +1500 charges
        d = self.client.get(f"/api/v1/ipr/{ref}").data
        self.assertEqual(float(d["landed"]["total_landed"]), 16500.0)
        self.assertEqual(float(d["landed"]["uplift_pct"]), 10.0)

        irn = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/receive",
                               {"location": "Bay 3"}, format="json").data
        r = self.client.post(f"/api/v1/irn/{irn['ref']}/post", {},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)

        from .models import StockLot
        lots = StockLot.objects.all()
        self.assertEqual(lots.count(), 2)                 # project + general
        proj = lots.get(project__isnull=False)
        self.assertEqual(float(proj.qty_on_hand), 6.0)
        self.assertEqual(float(proj.unit_landed_cost), 1650.0)  # 16500/10
        gen = lots.get(project__isnull=True)
        self.assertEqual(float(gen.qty_on_hand), 4.0)
        # store view sums to the full landed value
        sv = self.client.get("/api/v1/store/lots").data
        self.assertEqual(float(sv["total_value"]), 16500.0)

    def test_shortage_notifies_director_and_splits_pro_rata(self):
        from .models import Notification, StockLot
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        sid = self._shipment(ref)
        irn = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/receive",
                               {}, format="json").data
        lid = irn["lines"][0]["id"]
        r = self.client.post(f"/api/v1/irn/{irn['ref']}/post",
                             {"rows": [{"id": lid, "received_qty": "8"}]},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(Notification.objects.filter(
            recipient=self.director, doc_ref=irn["ref"]).exists())
        # 8 split 6:4 → 4.8 to the project, 3.2 to general stock
        self.assertEqual(float(StockLot.objects.get(
            project__isnull=False).qty_on_hand), 4.8)
        self.assertEqual(float(StockLot.objects.get(
            project__isnull=True).qty_on_hand), 3.2)


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

    def test_reclassify_local_supplier_to_international(self):
        """A supplier created Local can be switched to International so it
        appears when raising an import order (owner 2026-07-14)."""
        s = Supplier.objects.create(name="Male' Trading",
                                    category=Supplier.Category.LOCAL)
        self.client.force_authenticate(self.ho)
        ctx = self.client.get("/api/v1/ipr/context").data
        self.assertNotIn("Male' Trading",
                         [x["name"] for x in ctx["suppliers"]])
        r = self.client.patch(f"/api/v1/suppliers/{s.id}",
                              {"category": "INTERNATIONAL", "country": "China",
                               "default_currency": "USD"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        ctx = self.client.get("/api/v1/ipr/context").data
        row = next(x for x in ctx["suppliers"] if x["name"] == "Male' Trading")
        self.assertEqual(row["default_currency"], "USD")


class QsOverseasAuthTests(IprBase):
    """QS shares the Director's overseas-procurement authority: size-release
    PMRs and award/return IPRs (owner 2026-07-14)."""

    def setUp(self):
        super().setUp()
        self.qs = make_user("qs", User.Role.QS)

    def _pmr_to_ho_reviewed(self):
        pmr = self.create_pmr()
        ref = pmr["ref"]

        def act(user, action):
            self.client.force_authenticate(user)
            return self.client.post(
                f"/api/v1/documents/{ref}/actions/{action}", {}, format="json")
        act(self.sa, "submit")
        act(self.pm, "approve")
        act(self.ho, "ho-review")
        return ref

    def test_qs_can_size_release_pmr(self):
        ref = self._pmr_to_ho_reviewed()
        self.client.force_authenticate(self.qs)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/size-release",
                             {"comment": "Order 10 (MOQ)"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SIZED_RELEASED")

    def test_qs_can_award_and_view_ipr(self):
        self.client.force_authenticate(self.ho)
        ref = self.client.post("/api/v1/ipr", self.order_body(),
                               format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        # QS can list and open overseas orders…
        self.client.force_authenticate(self.qs)
        self.assertEqual(self.client.get("/api/v1/ipr").status_code, 200)
        # …and award (approve) one, exactly like the Director
        r = self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "APPROVED")

    def test_site_role_still_cannot_award_ipr(self):
        self.client.force_authenticate(self.ho)
        ref = self.client.post("/api/v1/ipr", self.order_body(),
                               format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.sa)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                             format="json")
        self.assertIn(r.status_code, (403, 404))   # denied (can't see/award)
        self.assertEqual(Document.objects.get(ref=ref).status, "SUBMITTED")


class OpeningStockTests(PmrBase):
    """Seed the HO store with opening / manual stock without an import
    (owner 2026-07-14)."""

    def test_receive_opening_stock_into_ho_store(self):
        from .models import Item, StockLot
        item = Item.objects.create(code="ITM-70001", description="Cement",
                                   unit="bag")
        self.client.force_authenticate(self.ho)
        r = self.client.post("/api/v1/store/opening-stock", {
            "lines": [{"item_id": item.id, "qty": 40, "unit_cost": 150,
                       "location": "Rack A"}],
            "note": "Year-end count"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["lots"], 1)
        self.assertEqual(float(r.data["total_value"]), 6000.0)   # 40 × 150
        lot = StockLot.objects.get(item=item)
        self.assertIsNone(lot.source_receipt_id)
        self.assertEqual(float(lot.qty_on_hand), 40.0)
        self.assertEqual(float(lot.unit_landed_cost), 150.0)
        self.assertIn("Opening stock", lot.origin_note)
        # surfaces in the HO store list with a friendly source label
        row = next(x for x in self.client.get("/api/v1/store/lots").data["lots"]
                   if x["id"] == lot.id)
        self.assertIn("Opening stock", row["source_irn"])

    def test_opening_stock_can_fulfil_a_later_mr(self):
        from .models import Item
        item = Item.objects.create(code="ITM-70003", description="Rebar",
                                   unit="kg")
        self.client.force_authenticate(self.ho)
        self.client.post("/api/v1/store/opening-stock", {
            "lines": [{"item_id": item.id, "qty": 100, "unit_cost": 20}]},
            format="json")
        # a site MR for the same item, sent to HO
        self.client.force_authenticate(self.sa)
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id,
            "lines": [{"item_id": item.id, "qty_required": 30, "qty_stock": 0,
                       "qty_to_order": 30}]}, format="json").data
        self.client.post(f"/api/v1/documents/{mr['ref']}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/documents/{mr['ref']}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.sa)
        self.client.post(f"/api/v1/documents/{mr['ref']}/actions/send", {},
                         format="json")
        # HO sees the opening stock as available to fulfil from store
        self.client.force_authenticate(self.ho)
        avail = self.client.get(
            f"/api/v1/mr/{mr['ref']}/store-availability").data["availability"]
        self.assertEqual(float(list(avail.values())[0]), 100.0)

    def test_site_role_cannot_receive_opening_stock(self):
        from .models import Item
        item = Item.objects.create(code="ITM-70002", description="Sand",
                                   unit="bag")
        self.client.force_authenticate(self.sa)
        r = self.client.post("/api/v1/store/opening-stock", {
            "lines": [{"item_id": item.id, "qty": 5, "unit_cost": 10}]},
            format="json")
        self.assertEqual(r.status_code, 403)

    def test_validation_rejects_bad_lines(self):
        from .models import Item
        item = Item.objects.create(code="ITM-70004", description="Ply",
                                   unit="sheet")
        self.client.force_authenticate(self.ho)
        r = self.client.post("/api/v1/store/opening-stock", {
            "lines": [{"item_id": item.id, "qty": 0, "unit_cost": 10}]},
            format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/store/opening-stock",
                             {"lines": []}, format="json")
        self.assertEqual(r.status_code, 400)


class ImportsCatalogTests(IprBase):
    """Catalog-driven IPR lines, proforma-invoice upload, import tracker
    (owner 2026-07-13)."""

    def _item(self):
        self.client.force_authenticate(self.ho)
        return self.client.post("/api/v1/items", {
            "description": "Chilled-water pump", "unit": "nos",
            "category": "MEP"}, format="json").data

    def test_context_includes_catalog_items(self):
        self._item()
        self.client.force_authenticate(self.ho)
        ctx = self.client.get("/api/v1/ipr/context").data
        self.assertIn("items", ctx)
        self.assertTrue(any(i["description"] == "Chilled-water pump"
                            for i in ctx["items"]))

    def test_ipr_line_from_catalog_item_without_pmr(self):
        it = self._item()
        body = self.order_body()
        body["pmr_refs"] = []
        body["lines"][0] = {
            "item_id": it["id"], "unit": "nos", "order_qty": 5,
            "unit_price": "100", "cost_head_id": self.head.id,
            "allocations": [{"project_id": None, "qty": 5}]}
        self.client.force_authenticate(self.ho)
        r = self.client.post("/api/v1/ipr", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["order"]["lines"][0]["item"], it["id"])

    def test_proforma_upload_and_view_by_signatory(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        ref = self.create_and_authorise()
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            self.client.force_authenticate(self.ho)
            pdf = SimpleUploadedFile("pi.pdf", b"%PDF-1.4 test",
                                     content_type="application/pdf")
            r = self.client.post(f"/api/v1/ipr/{ref}/proforma", {"file": pdf},
                                 format="multipart")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertTrue(r.data["order"]["proforma_invoice_url"])
            self.client.force_authenticate(self.signatory)
            d = self.client.get(f"/api/v1/ipr/{ref}").data
            self.assertTrue(d["order"]["proforma_invoice_url"])
        # site staff cannot upload (order is HO-only)
        self.client.force_authenticate(self.sa)
        r = self.client.post(
            f"/api/v1/ipr/{ref}/proforma",
            {"file": SimpleUploadedFile("x.pdf", b"x")}, format="multipart")
        self.assertIn(r.status_code, (403, 404))

    def test_tracker_lists_orders_and_awaiting(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        t = self.client.get("/api/v1/imports/tracker").data
        self.assertIn(ref, [o["ref"] for o in t["orders"]])
        self.assertIn("awaiting_order", t)


class StoreIssueTests(IprBase):
    """SIN — issue landed stock from the HO store to a site (P1B-f1)."""

    def _stock_lots(self):
        """Authorise an order, ship, receive + post an IRN → HO stock lots."""
        ref = self.create_and_authorise()
        order = Document.objects.get(ref=ref).import_order
        self.client.force_authenticate(self.ho)
        self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                         format="json")
        ship = order.shipments.first()
        irn = self.client.post(
            f"/api/v1/ipr/{ref}/shipments/{ship.id}/receive",
            {"location": "HO"}, format="json").data
        self.client.post(f"/api/v1/irn/{irn['ref']}/post", {}, format="json")
        return order

    def test_issue_moves_on_hand_to_in_transit(self):
        from .models import StockLot
        self._stock_lots()
        general = StockLot.objects.get(project__isnull=True)  # 4 @ 1500
        self.assertEqual(float(general.qty_on_hand), 4.0)
        self.client.force_authenticate(self.ho)
        r = self.client.post("/api/v1/store/issues", {
            "to_site_id": self.site.id, "to_project_id": self.project.id,
            "rows": [{"lot_id": general.id, "qty": 2}]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ref = r.data["ref"]
        self.assertTrue(ref.startswith("SIN-"))
        self.assertEqual(float(r.data["total_value"]), 3000.0)   # 2 @ 1500
        # posting the SIN moves 2 from on-hand to in-transit
        p = self.client.post(f"/api/v1/sin/{ref}/issue", {}, format="json")
        self.assertEqual(p.status_code, 200, p.data)
        self.assertEqual(p.data["status"], "ISSUED")
        general.refresh_from_db()
        self.assertEqual(float(general.qty_on_hand), 2.0)
        self.assertEqual(float(general.qty_in_transit), 2.0)

    def test_cannot_issue_more_than_on_hand(self):
        from .models import StockLot
        self._stock_lots()
        general = StockLot.objects.get(project__isnull=True)
        self.client.force_authenticate(self.ho)
        r = self.client.post("/api/v1/store/issues", {
            "to_site_id": self.site.id,
            "rows": [{"lot_id": general.id, "qty": 99}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("on hand", r.data["detail"])

    def test_site_staff_cannot_issue_store(self):
        from .models import StockLot
        self._stock_lots()
        general = StockLot.objects.get(project__isnull=True)
        self.client.force_authenticate(self.sa)
        r = self.client.post("/api/v1/store/issues", {
            "to_site_id": self.site.id,
            "rows": [{"lot_id": general.id, "qty": 1}]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_fifo_picks_reserved_then_general(self):
        from .imports import pick_lots_fifo
        from .models import Item, StockLot
        order = self._stock_lots()
        line = order.lines.first()
        item = line.item
        if item is None:      # order line is free-text — attach a catalog item
            item = Item.objects.create(description="Chilled-water pump",
                                       unit="nos", code="ITM-T1")
            StockLot.objects.filter(source_ipr_line=line).update(item=item)
        picks, err = pick_lots_fifo(item, self.project, 8)  # 6 reserved + 2 gen
        self.assertIsNone(err, err)
        self.assertEqual(len(picks), 2)
        self.assertEqual(picks[0][0].project_id, self.project.id)
        self.assertIsNone(picks[1][0].project_id)


class MrFromStoreTests(IprBase):
    """MR fulfilled from the HO store via a SIN; INCURRED at the site on
    receipt at landed cost (P1B-f2, owner 2026-07-13)."""

    def setUp(self):
        super().setUp()
        from .models import Item
        self.item = Item.objects.create(code="ITM-P1", unit="nos",
                                        description="Chilled-water pump")

    def _stock(self):
        body = self.order_body()
        body["lines"][0]["free_text_desc"] = ""
        body["lines"][0]["item_id"] = self.item.id
        self.client.force_authenticate(self.ho)
        ref = self.client.post("/api/v1/ipr", body, format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {},
                         format="json")
        order = Document.objects.get(ref=ref).import_order
        self.client.force_authenticate(self.ho)
        self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                         format="json")
        ship = order.shipments.first()
        irn = self.client.post(
            f"/api/v1/ipr/{ref}/shipments/{ship.id}/receive",
            {"location": "HO"}, format="json").data
        self.client.post(f"/api/v1/irn/{irn['ref']}/post", {}, format="json")

    def _mr(self, qty_to_order=3):
        self.client.force_authenticate(self.sa)
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id,
            "lines": [{"item_id": self.item.id, "qty_required": qty_to_order,
                       "qty_stock": 0, "qty_to_order": qty_to_order}],
        }, format="json").data
        self.client.post(f"/api/v1/documents/{mr['ref']}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/documents/{mr['ref']}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.sa)
        self.client.post(f"/api/v1/documents/{mr['ref']}/actions/send", {},
                         format="json")
        return self.client.get(f"/api/v1/documents/{mr['ref']}").data

    def test_store_availability_reports_general_stock(self):
        self._stock()
        mr = self._mr()
        line_id = mr["lines"][0]["id"]
        self.client.force_authenticate(self.ho)
        r = self.client.get(f"/api/v1/mr/{mr['ref']}/store-availability")
        self.assertEqual(r.status_code, 200, r.data)
        # site MR (no project) → only general stock (4 units) is available
        self.assertEqual(float(r.data["availability"][str(line_id)]), 4.0)

    def test_fulfil_from_store_then_receive_posts_incurred(self):
        from .models import CostPosting, StockLot
        self._stock()
        mr = self._mr(qty_to_order=3)
        line_id = mr["lines"][0]["id"]
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/mr/{mr['ref']}/store-fulfil",
                             {"line_ids": [line_id]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        sin_ref = r.data["ref"]
        self.assertEqual(r.data["status"], "ISSUED")
        general = StockLot.objects.get(item=self.item, project__isnull=True)
        self.assertEqual(float(general.qty_on_hand), 1.0)      # 4 - 3
        self.assertEqual(float(general.qty_in_transit), 3.0)
        # site receives → INCURRED at landed cost (3 @ 1500 = 4500)
        self.client.force_authenticate(self.sa)
        p = self.client.post(f"/api/v1/sin/{sin_ref}/receive", {},
                             format="json")
        self.assertEqual(p.status_code, 200, p.data)
        self.assertEqual(p.data["status"], "RECEIVED")
        general.refresh_from_db()
        self.assertEqual(float(general.qty_in_transit), 0.0)
        inc = CostPosting.objects.filter(site=self.site, state="INCURRED",
                                         source="STORE_ISSUE")
        self.assertEqual(float(sum(x.amount for x in inc)), 4500.0)


class StoreOnManifestTests(MrFromStoreTests):
    """Store items ride the LM and are received on ONE combined GRN, posting
    INCURRED at landed cost (owner 2026-07-14, P1B-f3)."""

    def test_lm_prefill_excludes_store_fulfilled_lines(self):
        """The MR→LM prefill must skip store-fulfilled lines — they load via
        "Load store items", so prefilling them too would double the line
        (owner 2026-07-14)."""
        self._stock()
        mr = self._mr(qty_to_order=3)
        line_id = mr["lines"][0]["id"]
        self.client.force_authenticate(self.ho)
        self.client.post(f"/api/v1/mr/{mr['ref']}/store-fulfil",
                         {"line_ids": [line_id]}, format="json")
        pre = self.client.get(f"/api/v1/mr/{mr['ref']}/lm-prefill").data
        self.assertEqual(pre["lines"], [])   # store line is not a purchase line

    def test_store_line_on_lm_incurred_at_grn_no_double_count(self):
        from .models import CostPosting, StockLot, StoreIssueLine, User as U
        from .tests import make_user
        se = make_user("se_store", U.Role.SITE_ENGINEER, site=self.site)
        self._stock()
        mr = self._mr(qty_to_order=3)
        line_id = mr["lines"][0]["id"]
        self.client.force_authenticate(self.ho)
        sin = self.client.post(f"/api/v1/mr/{mr['ref']}/store-fulfil",
                               {"line_ids": [line_id]}, format="json").data
        lm = self.client.post("/api/v1/documents", {
            "doc_type": "LM", "site_id": self.site.id,
            "mr_refs": [mr["ref"]], "lines": []}, format="json").data
        loaded = self.client.post(f"/api/v1/documents/{lm['ref']}/load-store",
                                  {}, format="json")
        self.assertEqual(loaded.status_code, 200, loaded.data)
        self.assertEqual(loaded.data["loaded_store_lines"], 1)
        self.client.post(f"/api/v1/documents/{lm['ref']}/actions/depart", {},
                         format="json")

        self.client.force_authenticate(self.sa)
        grn = self.client.post("/api/v1/documents", {
            "doc_type": "GRN", "site_id": self.site.id,
            "lm_ref": lm["ref"]}, format="json").data
        gline = grn["lines"][0]
        self.assertEqual(gline["fulfil_source"], "STORE")
        # count received in full — echo the store link, as the UI does
        self.client.patch(f"/api/v1/documents/{grn['ref']}", {"lines": [{
            "item_id": self.item.id, "qty_manifest": gline["qty_manifest"],
            "qty_received": 3, "fulfil_source": "STORE",
            "store_issue_line": gline["store_issue_line"]}]}, format="json")
        self.client.post(f"/api/v1/documents/{grn['ref']}/actions/count", {},
                         format="json")
        self.client.force_authenticate(se)
        v = self.client.post(f"/api/v1/documents/{grn['ref']}/actions/verify",
                             {}, format="json")
        self.assertEqual(v.data["status"], "COMPLETE", v.data)

        inc = CostPosting.objects.filter(site=self.site, state="INCURRED",
                                         source="STORE_ISSUE")
        self.assertEqual(float(sum(x.amount for x in inc)), 4500.0)   # 3 @ 1500
        general = StockLot.objects.get(item=self.item, project__isnull=True)
        self.assertEqual(float(general.qty_in_transit), 0.0)
        self.assertEqual(Document.objects.get(ref=sin["ref"]).status,
                         "RECEIVED")
        self.assertEqual(float(StoreIssueLine.objects.get(
            issue__document__ref=sin["ref"]).received_qty), 3.0)

        # a direct SIN receipt afterwards must not double-post
        self.client.force_authenticate(self.sa)
        self.client.post(f"/api/v1/sin/{sin['ref']}/receive", {},
                         format="json")
        again = CostPosting.objects.filter(site=self.site, state="INCURRED",
                                           source="STORE_ISSUE")
        self.assertEqual(float(sum(x.amount for x in again)), 4500.0)
