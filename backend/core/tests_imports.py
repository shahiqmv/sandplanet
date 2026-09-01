"""Phase 1B — International procurement. P1B-a: Supplier categories + the PMR
(Project Material Requisition) requirement raised and tracked project→PM→HO→
Director."""
from datetime import date

from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from .models import (CostHead, CostPosting, Document, DocumentRevision,
                     ImportPaymentMilestone, Project, SitePmHistory, Site,
                     Supplier, User)
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

    def _order(self, ref):
        from .models import ImportOrder
        return ImportOrder.objects.get(document__ref=ref)

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

    def test_discount_freight_misc_fold_into_total_commitment_and_po(self):
        """Order-level discount / supplier freight / misc fee adjust the order
        total, apportion across the committed legs, and appear on the PO
        (owner 2026-07-21 / -08-06)."""
        self.client.force_authenticate(self.ho)
        body = self.order_body()
        body["discount"] = "100"
        body["freight_handling"] = "50"
        body["misc_fee"] = "25"
        r = self.client.post("/api/v1/ipr", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ref = r.data["ref"]
        self.assertEqual(float(r.data["line_subtotal"]), 1000.0)
        self.assertEqual(float(r.data["order_total"]), 975.0)   # 1000-100+50+25
        self.assertEqual(float(r.data["mvr_total"]), 14625.0)   # 975 * 15

        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {},
                         format="json")
        posts = CostPosting.objects.filter(source="IPR", state="COMMITTED")
        # net_factor 0.975: project 9000*0.975=8775, pool 6000*0.975=5850
        self.assertAlmostEqual(
            float(posts.get(is_stock_pool=False).amount), 8775.0, places=1)
        self.assertAlmostEqual(
            float(posts.get(is_stock_pool=True).amount), 5850.0, places=1)

        # the generated PO carries the order-level charges + the right total
        from core.models import Document
        from core.pdf import _po_context
        po = Document.objects.filter(doc_type="PO").latest("id")
        totals = _po_context(po, po.current_revision)["totals"]
        self.assertTrue(totals["has_discount"] and totals["has_freight"]
                        and totals["has_misc"])
        self.assertEqual(totals["total"], "975.00")
        self.assertAlmostEqual(
            float(sum(p.amount for p in posts)), 14625.0, places=1)

    def test_authorising_generates_supplier_po(self):
        # Owner 2026-07-16: authorising an IPR raises the supplier PO, like a
        # domestic PR — one PO for the whole order, in the order currency.
        ref = self.create_and_authorise()
        ipr = Document.objects.get(ref=ref)
        links = ipr.links_from.filter(link_type="IPR_PO")
        self.assertEqual(links.count(), 1)
        po = links.first().to_document
        self.assertEqual(po.doc_type, "PO")
        self.assertEqual(po.status, "DRAFT")
        self.assertEqual(po.supplier_id, self.supplier.id)
        rev = po.current_revision
        self.assertEqual(rev.payload["currency"], "USD")
        self.assertEqual(rev.payload["tax_rate"], 0)      # no domestic GST
        line = rev.lines.first()
        self.assertEqual(float(line.qty_required), 10.0)
        self.assertEqual(float(line.rate), 100.0)         # order ccy, not MVR

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
        reg = self.client.get("/api/v1/ipr/payments-due").data
        # The register carries the pending balance too now (owner
        # 2026-08-23) — the advance is the one payable.
        due = [r for r in reg if r["band"] == "PAYABLE"]
        self.assertEqual(len(due), 1)
        self.assertEqual(float(due[0]["expected_mvr"]), 4500.0)  # 300*15
        self.assertEqual(due[0]["stage"], "AWAITING_VOUCHER")
        coming = [r for r in reg if r["band"] == "COMING"]
        self.assertEqual([c["label"] for c in coming], ["Balance"])

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
        due = [r for r in self.client.get("/api/v1/ipr/payments-due").data
               if r["label"] == "Advance"]
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

    def test_charge_correction_full_chain_on_part_paid_order(self):
        """The PI included freight but the order was authorised without it and
        the advance is already paid (owner 2026-08-10). Purchasing proposes the
        corrected freight, the Director approves, a Signatory authorises —
        the order total, committed ledger and PO all move to the real value
        while the paid milestone stays untouched."""
        from .vouchers import approve_voucher, create_voucher, submit_voucher
        ref = self.create_and_authorise()   # 1000 USD @ 15 = 15000 MVR
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "trigger": "ADVANCE", "percent": "30"},
            {"label": "Balance", "trigger": "BALANCE", "percent": "70"},
        ]}, format="json")
        advance = next(m for m in r.data["milestones"]
                       if m["label"] == "Advance")
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{advance['id']}/due",
                         {}, format="json")
        pv, err = create_voucher([], self.finance,
                                 milestone_ids=[advance["id"]])
        self.assertIsNone(err, err)
        submit_voucher(pv, self.finance)
        approve_voucher(pv, self.signatory)
        self.client.force_authenticate(self.finance)
        r = self.client.post(
            f"/api/v1/ipr/{ref}/milestones/{advance['id']}/pay",
            {"mvr_paid": "4500", "tt_ref": "TT-1"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.client.force_authenticate(self.ho)

        # a reason is required
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges",
                             {"freight_handling": "80"}, format="json")
        self.assertEqual(r.status_code, 400)
        # purchasing proposes: the PI includes USD 80 freight
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges",
                             {"freight_handling": "80",
                              "reason": "PI includes freight"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["charge_correction"]["status"],
                         "PENDING_DIRECTOR")
        self.assertEqual(float(r.data["order_total"]), 1000.0)  # not yet

        # a second proposal is refused while one is pending
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges",
                             {"freight_handling": "90", "reason": "again"},
                             format="json")
        self.assertEqual(r.status_code, 400)

        # the signatory can't jump the Director's approval
        self.client.force_authenticate(self.signatory)
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges/decide",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges/decide",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["charge_correction"]["status"],
                         "PENDING_SIGNATORY")

        self.client.force_authenticate(self.signatory)
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges/decide",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(r.data["charge_correction"])
        self.assertEqual(float(r.data["order_total"]), 1080.0)
        self.assertEqual(float(r.data["mvr_total"]), 16200.0)
        # supplier_charges_freight now suppresses the forwarder-freight charge
        self.assertTrue(r.data["supplier_charges_freight"])
        # the balance milestone rescales to the corrected total (70% of 1080)
        balance = next(m for m in r.data["milestones"]
                       if m["label"] == "Balance")
        self.assertEqual(float(balance["due_amount"]), 756.0)
        # committed ledger now carries the real order value
        posts = CostPosting.objects.filter(source="IPR", state="COMMITTED")
        self.assertAlmostEqual(float(sum(p.amount for p in posts)),
                               16200.0, places=1)
        # the PO is revised with the corrected charges
        po = Document.objects.filter(doc_type="PO").latest("id")
        self.assertEqual(po.current_revision.rev_label, "R1")
        self.assertEqual(float(po.current_revision.payload["freight"]), 80.0)
        self.assertEqual(po.current_revision.lines.count(), 1)
        # the paid advance is untouched
        adv = ImportPaymentMilestone.objects.get(pk=advance["id"])
        self.assertEqual(adv.status, "PAID")
        self.assertEqual(float(adv.mvr_paid), 4500.0)

    def test_charge_correction_guards(self):
        """Only HO proposes; a correction below the settled amount, or one
        that changes nothing, is refused; a rejection needs an approver."""
        ref = self.create_and_authorise()   # total 1000, nothing paid yet
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges",
                             {"freight_handling": "80", "reason": "x"},
                             format="json")
        self.assertEqual(r.status_code, 403)
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges",
                             {"reason": "no change"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Nothing changed", r.data["detail"])
        # milestone vouchered → the corrected total must still cover it
        self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Full", "trigger": "ADVANCE", "percent": "100"}]},
            format="json")
        m = self.client.get(f"/api/v1/ipr/{ref}").data["milestones"][0]
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due", {},
                         format="json")
        # Merely DUE (no voucher) no longer blocks — only committed money
        # does (owner 2026-08-27). Authorise it to arm the guard.
        ImportPaymentMilestone.objects.filter(pk=m["id"]).update(
            status="AUTHORISED")
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges",
                             {"discount": "900", "reason": "wrong"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("below what is already", r.data["detail"])
        ImportPaymentMilestone.objects.filter(pk=m["id"]).update(status="DUE")
        # a valid proposal can be rejected by the Director with a reason
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges",
                             {"freight_handling": "80", "reason": "PI freight"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges/decide",
                             {"action": "reject", "reason": "not agreed"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(r.data["charge_correction"])
        order = Document.objects.get(ref=ref).import_order
        self.assertIsNone(order.freight_handling)   # untouched
        self.assertEqual(order.charge_corrections.get().status, "REJECTED")

    def test_fold_freight_line_into_supplier_freight(self):
        """The user typed the PI's freight as an order LINE (owner 2026-08-10:
        the real stuck order). Folding it via a charge correction zeroes the
        line, pulls it off the shipment manifest, moves its value into
        freight_handling and reconciles the committed ledger — total unchanged,
        paid advance untouched."""
        from .models import ImportShipmentLine
        self.client.force_authenticate(self.ho)
        body = self.order_body()          # goods 10 × 100 = 1000
        body["lines"].append({
            "free_text_desc": "Sea Freight", "unit": "item", "order_qty": 1,
            "unit_price": "80", "cost_head_id": self.head.id,
            "allocations": [{"qty": 1}]})   # general stock
        ref = self.client.post("/api/v1/ipr", body,
                               format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {},
                         format="json")
        self.client.force_authenticate(self.ho)
        doc = self.client.get(f"/api/v1/ipr/{ref}").data
        self.assertEqual(float(doc["order_total"]), 1080.0)
        goods, freight = doc["order"]["lines"]
        # a whole-order shipment carries both lines
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                             format="json")
        sid = r.data["shipments"][0]["id"]
        self.assertEqual(ImportShipmentLine.objects.filter(
            shipment_id=sid).count(), 2)

        r = self.client.post(
            f"/api/v1/ipr/{ref}/correct-charges",
            {"freight_handling": "80", "fold_line_ids": [freight["id"]],
             "reason": "PI freight was typed as a line item"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([l["description"] for l in
                          r.data["charge_correction"]["fold_lines"]],
                         ["Sea Freight"])
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/ipr/{ref}/correct-charges/decide",
                         {"action": "approve"}, format="json")
        self.client.force_authenticate(self.signatory)
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges/decide",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # total unchanged, but freight now rides the charge field
        self.assertEqual(float(r.data["line_subtotal"]), 1000.0)
        self.assertEqual(float(r.data["order_total"]), 1080.0)
        self.assertTrue(r.data["supplier_charges_freight"])
        folded = next(l for l in r.data["order"]["lines"]
                      if l["description"] == "Sea Freight")
        self.assertEqual(float(folded["order_qty"]), 0.0)
        # off the manifest; the goods line still ships
        self.assertEqual(ImportShipmentLine.objects.filter(
            shipment_id=sid).count(), 1)
        # ledger reconciles to the corrected MVR total (1080 * 15)
        posts = CostPosting.objects.filter(document__ref=ref,
                                           state="COMMITTED")
        self.assertAlmostEqual(float(sum(p.amount for p in posts)),
                               16200.0, places=1)
        # the folded line's committed value was mirrored, never deleted
        self.assertTrue(posts.filter(amount__lt=0,
                                     reversal_of__isnull=False).exists())

    def test_fold_blocked_after_receipt(self):
        """Once an IRN has counted the line into stock the fold is refused."""
        self.client.force_authenticate(self.ho)
        body = self.order_body()
        body["lines"].append({
            "free_text_desc": "Sea Freight", "unit": "item", "order_qty": 1,
            "unit_price": "80", "cost_head_id": self.head.id,
            "allocations": [{"qty": 1}]})
        ref = self.client.post("/api/v1/ipr", body,
                               format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {},
                         format="json")
        self.client.force_authenticate(self.ho)
        doc = self.client.get(f"/api/v1/ipr/{ref}").data
        freight = doc["order"]["lines"][1]
        sid = self.client.post(f"/api/v1/ipr/{ref}/shipments",
                               {"mode": "SEA"},
                               format="json").data["shipments"][0]["id"]
        irn = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/receive",
                               {"location": ""}, format="json").data["ref"]
        self.client.post(f"/api/v1/irn/{irn}/post", {}, format="json")
        r = self.client.post(
            f"/api/v1/ipr/{ref}/correct-charges",
            {"freight_handling": "80", "fold_line_ids": [freight["id"]],
             "reason": "typed as line"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("received on an IRN", r.data["detail"])

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

    def test_mobile_pv_detail_renders_milestone_line(self):
        """Regression: opening a PV that batches an overseas-TT milestone on
        Planet Mobile must not 500 (was reading a non-existent .stage attr)."""
        from .views_mobile import _document_payload
        from .vouchers import create_voucher
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        m = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "percent": "100"}]}, format="json") \
            .data["milestones"][0]
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due", {},
                         format="json")
        pv, err = create_voucher([], self.finance, milestone_ids=[m["id"]])
        self.assertIsNone(err, err)
        payload = _document_payload(pv, None)      # must not raise
        self.assertEqual(payload["doc_type"], "PV")
        self.assertEqual(len(payload["lines"]), 1)
        self.assertIn("Advance", payload["lines"][0]["ref"])

    def test_voiding_releases_the_milestone_and_the_register_still_loads(self):
        """The whole IPR-047 sequence, end to end.

        A voucher is raised against an import milestone and voided while
        still submitted. Voiding lets go of the milestone — it has to, or the
        PROTECT FK freezes that order's payment schedule for good. That
        leaves a line with no source behind it, and the vouchers register
        used to 500 on the page that line fell on (owner 2026-09-01)."""
        from .models import PaymentVoucherLine
        from .vouchers import create_voucher
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        m = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance  30%", "trigger": "ADVANCE", "percent": "30"},
            {"label": "Balance", "trigger": "BL", "percent": "70"}]},
            format="json").data["milestones"][0]
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due", {},
                         format="json")
        pv, err = create_voucher([], self.finance, milestone_ids=[m["id"]])
        self.assertIsNone(err, err)
        self.client.force_authenticate(self.finance)
        self.client.post(f"/api/v1/payment-vouchers/{pv.ref}/actions/submit",
                         {}, format="json")
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv.ref}/actions/void",
            {"reason": "amount wrong"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

        # the milestone is let go, but the line still says what it was for
        line = PaymentVoucherLine.objects.get(voucher=pv)
        self.assertIsNone(line.source_milestone_id)
        self.assertIsNone(line.source_document_id)
        self.assertIn("Advance", line.source_note)

        # ...and the register renders it instead of falling over
        self.client.force_authenticate(self.finance)
        r = self.client.get("/api/v1/payment-vouchers?limit=25&offset=0")
        self.assertEqual(r.status_code, 200)
        row = next(v for v in r.data["vouchers"] if v["ref"] == pv.ref)
        self.assertEqual(row["status"], "VOID")
        shown = row["lines"][0]
        self.assertEqual(shown["doc_type"], "RELEASED")
        self.assertEqual(shown["ref"], ref)
        self.assertIn("Advance", shown["purpose"])
        self.assertFalse(shown["paid"])

    def test_a_voided_voucher_cannot_be_approved(self):
        """Voiding leaves `status` at SUBMITTED and raises is_void, so the
        voucher still looked approvable to everything reading status alone."""
        from .vouchers import approve_voucher, create_voucher
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        m = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "percent": "100"}]}, format="json") \
            .data["milestones"][0]
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due", {},
                         format="json")
        pv, _ = create_voucher([], self.finance, milestone_ids=[m["id"]])
        self.client.force_authenticate(self.finance)
        self.client.post(f"/api/v1/payment-vouchers/{pv.ref}/actions/submit",
                         {}, format="json")
        self.client.post(f"/api/v1/payment-vouchers/{pv.ref}/actions/void",
                         {"reason": "amount wrong"}, format="json")
        pv.refresh_from_db()
        self.assertEqual(pv.status, "SUBMITTED")   # the drift itself
        self.assertTrue(pv.is_void)
        self.assertEqual(approve_voucher(pv, self.signatory),
                         "This voucher has been voided.")

    def test_credit_days_live_in_the_schedule_and_set_pay_by(self):
        """Credit terms are written into the milestone schedule itself: the
        row's own figure, else the supplier's agreed period. When a milestone
        falls due, pay-by = that day + its credit days (owner 2026-08-23)."""
        from datetime import date, timedelta

        from .models import ImportPaymentMilestone, Supplier
        ref = self.create_and_authorise()
        order = self._order(ref)
        Supplier.objects.filter(pk=order.supplier_id).update(credit_days=45)
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "trigger": "ADVANCE", "percent": "30",
             "credit_days": "0"},                      # pay on the trigger
            {"label": "Balance", "trigger": "ARRIVAL", "percent": "70"},
        ]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        ms = {m["label"]: m for m in r.data["milestones"]}
        self.assertEqual(ms["Advance"]["credit_days"], 0)     # explicit wins
        self.assertEqual(ms["Balance"]["credit_days"], 45)    # supplier default
        # Falls due today → pay-by follows the credit.
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{ms['Balance']['id']}"
                         f"/due", {}, format="json")
        m = ImportPaymentMilestone.objects.get(pk=ms["Balance"]["id"])
        self.assertEqual(m.fell_due_on, date.today())
        self.assertEqual(m.pay_by, date.today() + timedelta(days=45))
        self.client.force_authenticate(self.finance)
        row = next(x for x in self.client.get("/api/v1/ipr/payments-due").data
                   if x["label"] == "Balance")
        self.assertEqual(row["band"], "PAYABLE")
        self.assertEqual(str(row["pay_by"]),
                         str(date.today() + timedelta(days=45)))
        self.assertFalse(row["overdue"])

    def test_finance_moves_pay_by_with_a_reason(self):
        from datetime import date, timedelta

        from .models import AuditLog, ImportPaymentMilestone
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        m = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Full", "trigger": "ADVANCE", "percent": "100"}]},
            format="json").data["milestones"][0]
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due", {},
                         format="json")
        self.client.force_authenticate(self.finance)
        later = str(date.today() + timedelta(days=60))
        r = self.client.post(f"/api/v1/ipr/milestones/{m['id']}/pay-by",
                             {"pay_by": later}, format="json")
        self.assertEqual(r.status_code, 400)               # reason required
        r = self.client.post(f"/api/v1/ipr/milestones/{m['id']}/pay-by",
                             {"pay_by": later,
                              "reason": "related party — agreed 60 days"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(str(ImportPaymentMilestone.objects.get(
            pk=m["id"]).pay_by), later)
        self.assertTrue(AuditLog.objects.filter(
            event="IPR_MILESTONE_PAY_BY_MOVED").exists())

    def test_one_voucher_pays_one_supplier(self):
        from .models import Supplier
        from .vouchers import create_voucher
        ref1 = self.create_and_authorise()
        # A second order for a DIFFERENT supplier (the fixture's PMR is spent
        # on the first, so this one carries none).
        other = Supplier.objects.create(name="Other Overseas Co",
                                        default_currency="USD")
        body = self.order_body()
        body.update({"supplier_id": other.id, "pmr_refs": []})
        self.client.force_authenticate(self.ho)
        r = self.client.post("/api/v1/ipr", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ref2 = r.data["ref"]
        self.client.post(f"/api/v1/documents/{ref2}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref2}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/documents/{ref2}/actions/authorise", {},
                         format="json")
        self.client.force_authenticate(self.ho)
        ids = []
        for ref in (ref1, ref2):
            m = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
                {"label": "Full", "trigger": "ADVANCE", "percent": "100"}]},
                format="json").data["milestones"][0]
            self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due",
                             {}, format="json")
            ids.append(m["id"])
        pv, err = create_voucher([], self.finance, milestone_ids=ids)
        self.assertIsNone(pv)
        self.assertIn("one supplier", err)

    def test_due_milestones_are_not_offered_in_the_generic_voucher_builder(self):
        """They are picked on the International Payables register, one
        supplier at a time (owner 2026-08-23)."""
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        m = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Full", "trigger": "ADVANCE", "percent": "100"}]},
            format="json").data["milestones"][0]
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due", {},
                         format="json")
        self.client.force_authenticate(self.finance)
        aw = self.client.get("/api/v1/finance/awaiting-voucher").data
        self.assertFalse(any(r.get("kind") == "MILESTONE" for r in aw))
        # ...but the register has it, and can voucher it.
        reg = self.client.get("/api/v1/ipr/payments-due").data
        self.assertEqual([r["band"] for r in reg], ["PAYABLE"])
        r = self.client.post("/api/v1/payment-vouchers",
                             {"milestone_ids": [m["id"]]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_historical_payment_marks_paid_without_a_voucher_or_fx(self):
        """Payments made before the app: marked paid through the normal TT
        posting path, at the committed rate, no voucher, no FX (owner
        2026-08-23)."""
        from io import StringIO

        from django.core.management import call_command

        from .models import ImportPaymentMilestone
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        ms = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "trigger": "ADVANCE", "percent": "30"},
            {"label": "Balance", "trigger": "ARRIVAL", "percent": "70"},
        ]}, format="json").data["milestones"]
        adv = next(m for m in ms if m["label"] == "Advance")
        out = StringIO()
        call_command("mark_milestone_paid_historical", ids=str(adv["id"]),
                     date="2026-06-01", stdout=out)          # dry run
        self.assertEqual(ImportPaymentMilestone.objects.get(
            pk=adv["id"]).status, "PENDING")
        call_command("mark_milestone_paid_historical", ids=str(adv["id"]),
                     date="2026-06-01", apply=True, stdout=out)
        m = ImportPaymentMilestone.objects.get(pk=adv["id"])
        self.assertEqual(m.status, "PAID")
        self.assertIsNone(m.voucher_id)
        self.assertIn("historical", m.tt_ref.lower())
        self.assertEqual(float(m.mvr_paid), 4500.0)          # 300 USD @ 15
        self.assertEqual(str(m.paid_at.date()), "2026-06-01")
        # PAID legs posted to the project/stock; no FX posting.
        self.assertTrue(CostPosting.objects.filter(
            state="PAID", document__ref=ref, ipr_milestone=m).exists())
        self.assertFalse(CostPosting.objects.filter(
            source="FX", document__ref=ref).exists())
        # Off the register, and a second run skips it.
        self.client.force_authenticate(self.finance)
        labels = [r["label"] for r in
                  self.client.get("/api/v1/ipr/payments-due").data]
        self.assertNotIn("Advance", labels)
        out2 = StringIO()
        call_command("mark_milestone_paid_historical", ids=str(adv["id"]),
                     apply=True, stdout=out2)
        self.assertIn("already PAID", out2.getvalue())

    def test_schedule_must_sum_to_order_total(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "percent": "30"},
            {"label": "Balance", "percent": "50"},   # only 80%
        ]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("sum to the order total", r.data["detail"])

    def test_mixed_fixed_and_percent_schedule(self):
        """A milestone can be a fixed amount in the order currency, mixed with
        percentage milestones, as long as the schedule sums to the order
        total (10 × $100 = $1000)."""
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "trigger": "ADVANCE", "fixed_amount": "250"},
            {"label": "Balance", "trigger": "BALANCE", "percent": "75"},
        ]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        amounts = sorted(float(m["due_amount"]) for m in r.data["milestones"])
        self.assertEqual(amounts, [250.0, 750.0])

    def test_fixed_schedule_must_still_balance(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance", "fixed_amount": "250"},
            {"label": "Balance", "fixed_amount": "600"},   # 850 ≠ 1000
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
                              "container_awb": "MSCU1234566"}, format="json")
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

    def test_split_shipment_allocation_receipt_and_limit(self):
        """A 10-unit order ships in two parts. Each shipment draws from the
        line's remaining balance; over-allocation is refused; the IRN for a
        part seeds only that part's quantity; and once fully shipped a further
        whole-order shipment has nothing left."""
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        lid = self.client.get(f"/api/v1/ipr/{ref}").data[
            "order"]["lines"][0]["id"]

        # ship 4 of 10
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments",
            {"mode": "SEA", "lines": [{"ipr_line_id": lid, "qty": "4"}]},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        line = self.client.get(f"/api/v1/ipr/{ref}").data["order"]["lines"][0]
        self.assertEqual(float(line["shipped_qty"]), 4.0)
        self.assertEqual(float(line["remaining_qty"]), 6.0)

        # over-allocation refused (only 6 left)
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments",
            {"mode": "SEA", "lines": [{"ipr_line_id": lid, "qty": "7"}]},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("left to ship", r.data["detail"])

        # the IRN for shipment 1 expects only its 4 units
        sid = self.client.get(f"/api/v1/ipr/{ref}").data["shipments"][0]["id"]
        irn = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/receive",
                               {}, format="json").data
        self.assertEqual(len(irn["lines"]), 1)
        self.assertEqual(float(irn["lines"][0]["expected_qty"]), 4.0)

        # ship the remaining 6; then no whole-order shipment is possible
        self.client.post(f"/api/v1/ipr/{ref}/shipments",
            {"mode": "SEA", "lines": [{"ipr_line_id": lid, "qty": "6"}]},
            format="json")
        self.assertEqual(float(self.client.get(f"/api/v1/ipr/{ref}").data[
            "order"]["lines"][0]["remaining_qty"]), 0.0)
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already on shipments", r.data["detail"])

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

    def test_update_can_remove_forwarder(self):
        """Blank forwarder on the edit form clears it (the supplier ships on
        their own PI) — it must not 500 on the empty-string id."""
        fwd = Supplier.objects.create(name="SeaTranz Maldives")
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments",
                             {"mode": "SEA", "forwarder_id": fwd.id,
                              "container_awb": "MSCU1234566"}, format="json")
        sid = r.data["shipments"][0]["id"]
        self.assertEqual(r.data["shipments"][0]["forwarder"], fwd.id)
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/update",
                             {"forwarder_id": ""}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(r.data["shipments"][0]["forwarder"])

    def test_charge_payment_accepts_blank_payee(self):
        """Saving a shipment charge with no payee chosen yet keeps the row
        payee-less instead of crashing on the empty-string id."""
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                             format="json")
        sid = r.data["shipments"][0]["id"]
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/payments/DO",
                             {"payee_id": "", "amount": "500"},
                             format="multipart")
        self.assertEqual(r.status_code, 200, r.data)

    def test_only_ho_manages_shipments(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.sa)   # site admin
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                             format="json")
        self.assertEqual(r.status_code, 404)   # site staff can't see IPRs


class ShipmentDeleteTests(IprBase):
    """Admin can delete a mis-booked shipment; blocked once received (an IRN
    exists) so inventory stays intact (owner 2026-07-20)."""

    def setUp(self):
        super().setUp()
        self.admin = make_user("adm", User.Role.ADMIN)

    def _book(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                             format="json")
        return ref, r.data["shipments"][0]["id"]

    def _del(self, ref, sid):
        return self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/delete")

    def test_admin_deletes_and_frees_allocation(self):
        ref, sid = self._book()
        # whole order is on the shipment → nothing left to ship
        ipr = self.client.get(f"/api/v1/ipr/{ref}").data
        self.assertTrue(all(float(l["remaining_qty"]) == 0
                            for l in ipr["order"]["lines"]))
        self.client.force_authenticate(self.admin)
        r = self._del(ref, sid)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["shipments"]), 0)
        # the quantity is shippable again
        ipr = self.client.get(f"/api/v1/ipr/{ref}").data
        self.assertTrue(any(float(l["remaining_qty"]) > 0
                            for l in ipr["order"]["lines"]))

    def test_non_admin_cannot_delete(self):
        ref, sid = self._book()
        self.client.force_authenticate(self.ho)
        self.assertEqual(self._del(ref, sid).status_code, 403)
        self.client.force_authenticate(self.director)
        self.assertEqual(self._del(ref, sid).status_code, 403)

    def test_cannot_delete_received_shipment(self):
        ref, sid = self._book()
        self.client.force_authenticate(self.ho)
        self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/receive",
                         {"location": ""}, format="json")
        self.client.force_authenticate(self.admin)
        r = self._del(ref, sid)
        self.assertEqual(r.status_code, 400)
        self.assertIn("received", r.data["detail"].lower())


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


class EditDraftIprTests(IprBase):
    """A draft overseas order can be edited before submit, and free-text 'new
    item' lines promoted to catalog items (owner 2026-07-14)."""

    def _draft(self):
        self.client.force_authenticate(self.ho)
        return self.client.post("/api/v1/ipr", self.order_body(),
                                format="json").data["ref"]

    def test_edit_draft_line_description_and_rate(self):
        ref = self._draft()
        body = {"supplier_id": self.supplier.id, "order_currency": "USD",
                "exchange_rate": "16", "incoterm": "CIF",
                "lines": [{"free_text_desc": "Chilled-water pump (corrected)",
                           "unit": "nos", "order_qty": 10, "unit_price": "120",
                           "cost_head_id": self.head.id,
                           "allocations": [{"project_id": None, "qty": 10}]}]}
        r = self.client.patch(f"/api/v1/ipr/{ref}", body, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(float(r.data["order"]["exchange_rate"]), 16.0)
        line = r.data["order"]["lines"][0]
        self.assertEqual(line["description"], "Chilled-water pump (corrected)")
        self.assertIsNone(line["item"])
        self.assertEqual(float(line["order_qty"]), 10.0)

    def test_promote_free_text_line_to_catalog_item(self):
        from .models import Item
        ref = self._draft()
        self.client.force_authenticate(self.ho)
        item = self.client.post("/api/v1/items",
                                {"description": "Chilled-water pump 50 m3/h",
                                 "unit": "nos"}, format="json").data
        self.assertTrue(item["code"].startswith("ITM-"))   # now in the catalog
        body = {"supplier_id": self.supplier.id, "order_currency": "USD",
                "exchange_rate": "15",
                "lines": [{"item_id": item["id"], "order_qty": 10,
                           "unit_price": "100", "cost_head_id": self.head.id,
                           "allocations": [{"project_id": None, "qty": 10}]}]}
        r = self.client.patch(f"/api/v1/ipr/{ref}", body, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["order"]["lines"][0]["item"], item["id"])
        self.assertTrue(Item.objects.filter(pk=item["id"]).exists())

    def test_cannot_edit_after_submit(self):
        ref = self._draft()
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        r = self.client.patch(f"/api/v1/ipr/{ref}",
                              {"supplier_id": self.supplier.id,
                               "exchange_rate": "16",
                               "lines": self.order_body()["lines"]},
                              format="json")
        self.assertEqual(r.status_code, 400)

    def test_site_role_cannot_edit(self):
        ref = self._draft()
        self.client.force_authenticate(self.sa)
        r = self.client.patch(f"/api/v1/ipr/{ref}",
                              {"exchange_rate": "16",
                               "lines": self.order_body()["lines"]},
                              format="json")
        self.assertIn(r.status_code, (403, 404))


class ProvisionalBlockTests(IprBase):
    """A provisional (site-added, unreviewed) catalogue item cannot be ordered
    until HO approves it (owner 2026-07-14)."""

    def test_ipr_submit_blocked_until_item_approved(self):
        from .models import Item
        prov = Item.objects.create(code="ITM-P9", description="Site Pump",
                                   unit="nos", is_provisional=True)
        body = self.order_body()
        body["lines"][0] = {"item_id": prov.id, "unit": "nos", "order_qty": 5,
                            "unit_price": "100", "cost_head_id": self.head.id,
                            "allocations": [{"project_id": None, "qty": 5}]}
        self.client.force_authenticate(self.ho)
        ref = self.client.post("/api/v1/ipr", body, format="json").data["ref"]
        r = self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Site Pump", r.data["provisional_items"])
        # HO approves the item, then the order submits fine
        self.client.post(f"/api/v1/items/{prov.id}/approve")
        r = self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")


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


class IprMobileSummaryTests(IprBase):
    """The mobile IPR detail shows supplier, order value and items so the
    Director/Signatory can review the overseas order (owner 2026-07-19)."""

    def test_ipr_mobile_summary_shows_order_and_items(self):
        from .views_mobile import _document_payload
        ref = self.create_and_authorise()
        p = _document_payload(Document.objects.get(ref=ref), None)
        self.assertEqual(p["supplier_name"], "Guangzhou Pumps Co")
        self.assertEqual(p["currency"], "USD")
        facts = {f["k"]: f["v"] for f in p["summary"]}
        self.assertIn("Order value", facts)
        self.assertIn("In MVR", facts)
        self.assertTrue(p["lines"])
        self.assertTrue(p["lines"][0]["title"])


class MobileIprAuthoriseTests(IprBase):
    """The signatory authorises a Director-awarded overseas order from the
    mobile app, raising its PO (owner 2026-07-16)."""

    def setUp(self):
        super().setUp()
        self.signatory.set_password("verify-123")
        self.signatory.save()
        self.m = APIClient()
        tok = self.m.post("/api/mobile/v1/auth/login",
                          {"username": self.signatory.username,
                           "password": "verify-123"}, format="json").data["token"]
        self.m.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")

    def _awarded_order(self):
        self.client.force_authenticate(self.ho)
        ref = self.client.post("/api/v1/ipr", self.order_body(),
                               format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        return ref

    def test_signatory_sees_and_authorises_awarded_ipr_on_mobile(self):
        ref = self._awarded_order()
        self.assertEqual(Document.objects.get(ref=ref).status, "APPROVED")
        # the awarded order reaches the signatory's mobile queue…
        q = self.m.get("/api/mobile/v1/queue")
        self.assertEqual(q.status_code, 200)
        self.assertIn(ref, [i["ref"] for i in q.data["items"]])
        # …and authorising it commits the order and raises the PO
        r = self.m.post(f"/api/mobile/v1/documents/{ref}/approve", {},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Document.objects.get(ref=ref).status, "AUTHORISED")
        self.assertTrue(Document.objects.filter(
            doc_type="PO", links_to__from_document__ref=ref,
            links_to__link_type="IPR_PO").exists())


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
            "project_id": self.project.id,
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
            "general_works": True,   # the no-project path is what's under test
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


class ShipmentChargePyrTests(IprBase):
    """Import-charge payments: raise a payment-only (capitalized) PYR to pay a
    shipment charge to its agent — it pays but posts nothing to the ledger,
    because the charge already rides the material's landed cost."""

    def _file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile("inv.pdf", b"%PDF-1.4",
                                  content_type="application/pdf")

    def _shipment(self):
        from core.models import Document, ImportShipment
        ref = self.create_and_authorise()
        order = Document.objects.get(ref=ref).import_order
        return ImportShipment.objects.create(order=order, seq=1)

    def test_raise_capitalized_pyr_posts_nothing(self):
        from decimal import Decimal

        from core import imports, vouchers
        from core.models import CostPosting, ShipmentPayment
        pay = ShipmentPayment.objects.create(
            shipment=self._shipment(), kind="FREIGHT", payee_name="SeaTranz",
            amount=Decimal("5000"), invoice=self._file())
        doc, err = imports.raise_charge_pyr(pay, self.signatory)
        self.assertIsNone(err, err)
        self.assertEqual(doc.doc_type, "PYR")
        self.assertTrue(doc.payment_request.is_capitalized)
        # auto-submitted AND cleared past the Director straight to a voucher
        self.assertEqual(doc.status, "DIRECTOR_APPROVED")
        pay.refresh_from_db()
        self.assertEqual(pay.pyr_id, doc.id)
        # authorising the capitalized PYR posts NOTHING to the cost ledger
        vouchers.authorise_source(doc, self.signatory)
        self.assertFalse(
            CostPosting.objects.filter(source="PYR", document=doc).exists())

    def test_a_charge_can_be_paid_direct_to_port_or_customs(self):
        """Port dues go to the port and duty to customs — not to the agents,
        who may not even be on file. IPR-020's port charge sat unraisable
        because the payee dropdown offered agents only (owner 2026-08-24)."""

        from core import imports
        sh = self._shipment()          # no forwarder, no agents at all
        pay, err = imports.set_shipment_payment(sh, "PORT", {
            "payee_name": "Maldives Ports Limited",
            "amount": "6246.02", "currency": "MVR"}, self.signatory)
        self.assertIsNone(err, err)
        self.assertEqual(pay.resolved_payee(), "Maldives Ports Limited")
        pay.invoice = self._file()
        pay.save(update_fields=["invoice"])
        doc, err = imports.raise_charge_pyr(pay, self.signatory)
        self.assertIsNone(err, err)
        self.assertEqual(doc.payment_request.payee, "Maldives Ports Limited")
        self.assertEqual(float(doc.payment_request.amount_requested), 6246.02)

    def test_agent_and_typed_payee_are_mutually_exclusive(self):
        """The supplier FK used to silently win over a typed name."""
        from core import imports
        from core.models import Supplier
        sh = self._shipment()
        agent = Supplier.objects.create(name="Clearing Co")
        pay, _ = imports.set_shipment_payment(sh, "DUTY", {
            "payee_id": agent.id, "amount": "100"}, self.signatory)
        self.assertEqual(pay.resolved_payee(), "Clearing Co")
        # Switching to a typed name clears the agent…
        pay, _ = imports.set_shipment_payment(sh, "DUTY", {
            "payee_name": "Maldives Customs Service"}, self.signatory)
        self.assertIsNone(pay.payee_id)
        self.assertEqual(pay.resolved_payee(), "Maldives Customs Service")
        # …and switching back clears the name.
        pay, _ = imports.set_shipment_payment(sh, "DUTY", {
            "payee_id": agent.id}, self.signatory)
        self.assertEqual(pay.payee_name, "")
        self.assertEqual(pay.resolved_payee(), "Clearing Co")

    def test_missing_payee_says_what_the_choices_are(self):
        from core import imports
        sh = self._shipment()
        pay, _ = imports.set_shipment_payment(sh, "PORT", {"amount": "50"},
                                              self.signatory)
        pay.invoice = self._file()
        pay.save(update_fields=["invoice"])
        _, err = imports.raise_charge_pyr(pay, self.signatory)
        self.assertIn("port / customs", err)

    def test_raise_requires_amount_payee_invoice(self):
        from core import imports
        from core.models import ShipmentPayment
        pay = ShipmentPayment.objects.create(shipment=self._shipment(),
                                             kind="DO")
        _, err = imports.raise_charge_pyr(pay, self.signatory)
        self.assertIsNotNone(err)      # no amount / payee / invoice
        self.assertIsNone(pay.pyr_id)


class ClearingAgentShareTests(IprBase):
    """Share-with-agent emails the shipping documents to THE clearing agent
    (one company-wide, flagged on the supplier — owner 2026-08-24)."""

    def _file(self, name="doc.pdf"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, b"%PDF-1.4 test",
                                  content_type="application/pdf")

    def _shipment_with_docs(self, doc_types=("BL_AWB", "PACKING_LIST")):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments",
                             {"mode": "SEA", "vessel_flight": "MV Test",
                              "container_awb": "MSCU1234566"}, format="json")
        sid = r.data["shipments"][0]["id"]
        for t in doc_types:
            self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/documents",
                             {"doc_type": t, "file": self._file(f"{t}.pdf")},
                             format="multipart")
        return ref, sid

    def _agent(self, email="agent@clearco.mv", flag=True):
        return Supplier.objects.create(
            name="ClearCo Maldives", category="CLEARING_AGENT",
            email=email, contact_person="Ali", is_clearing_agent=flag)

    def test_share_emails_all_documents_to_the_agent(self):
        from django.core import mail
        from .models import ImportShipment
        self._agent()
        ref, sid = self._shipment_with_docs()
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/share",
                             {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["agent@clearco.mv"])
        self.assertEqual(msg.cc, ["projects@sandplanet.mv"])
        self.assertIn(ref, msg.subject)
        self.assertEqual(len(msg.attachments), 2)
        self.assertIn("Dear Ali", msg.body)
        self.assertIsNotNone(
            ImportShipment.objects.get(pk=sid).shared_with_agent_at)

    def test_share_refused_without_agent_email_or_documents(self):
        from django.core import mail
        from .models import ImportShipment
        # one shipment, nothing uploaded yet
        ref, sid = self._shipment_with_docs(doc_types=())
        # no agent at all
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/share",
                             {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("No clearing agent", r.data["detail"])
        # agent without an email address
        agent = self._agent(email="")
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/share",
                             {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no email", r.data["detail"])
        # agent fine, but nothing uploaded
        agent.email = "agent@clearco.mv"
        agent.save()
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/share",
                             {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("nothing to send", r.data["detail"])
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(
            ImportShipment.objects.get(pk=sid).shared_with_agent_at)

    def test_clearing_agent_swap_is_atomic_and_unique(self):
        a = self._agent()
        b = Supplier.objects.create(name="Other Agent",
                                    category="CLEARING_AGENT",
                                    email="b@x.mv")
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/suppliers/{b.id}/clearing-agent",
                             {"set": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        a.refresh_from_db(); b.refresh_from_db()
        self.assertFalse(a.is_clearing_agent)
        self.assertTrue(b.is_clearing_agent)
        # clear it
        self.client.post(f"/api/v1/suppliers/{b.id}/clearing-agent",
                         {"set": False}, format="json")
        b.refresh_from_db()
        self.assertFalse(b.is_clearing_agent)
        # a plain PATCH can't sneak the flag on — only the swap action moves it
        self.client.patch(f"/api/v1/suppliers/{b.id}",
                          {"is_clearing_agent": True}, format="json")
        b.refresh_from_db()
        self.assertFalse(b.is_clearing_agent)
        # site roles can't touch it
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/suppliers/{a.id}/clearing-agent",
                             {"set": True}, format="json")
        self.assertEqual(r.status_code, 403)


class VoidedIprTests(IprBase):
    """A voided order stays readable but shows VOID and refuses all moves
    (IPR-035: voided while APPROVED yet the page still offered Authorise)."""

    def _void(self, ref):
        self.admin = make_user("adm2", User.Role.ADMIN)
        self.client.force_authenticate(self.admin)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/void",
                             {"reason": "not needed"}, format="json")
        self.assertIsNone(r.data.get("detail"), r.data)
        return r

    def test_voided_ipr_is_read_only_everywhere(self):
        # award it (Director) but stop before authorisation — IPR-035's state
        self.client.force_authenticate(self.ho)
        ref = self.client.post("/api/v1/ipr", self.order_body(),
                               format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self._void(ref)
        # generic workflow action refused
        self.client.force_authenticate(self.signatory)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        # IPR-specific mutations refused
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments",
                             {"mode": "SEA"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("void", r.data["detail"].lower())
        r = self.client.post(f"/api/v1/ipr/{ref}/milestones",
                             {"rows": []}, format="json")
        self.assertEqual(r.status_code, 400)
        # still readable, but read-only for every role, and flagged void
        r = self.client.get(f"/api/v1/ipr/{ref}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["is_void"])
        self.assertFalse(r.data["can_manage"])
        self.assertFalse(r.data["can_pay"])
        # the list carries the flag too
        row = next(x for x in self.client.get("/api/v1/ipr").data["rows"]
                   if x["ref"] == ref)
        self.assertTrue(row["is_void"])


class ClearanceSetupTests(IprBase):
    """The Cargo Clearance page (owner 2026-08-26): editable CC list drives
    the share email; agent + candidates + share history in one payload."""

    def test_cc_param_drives_the_share_email(self):
        from django.core import mail
        from core.models import CompanyParameter, Supplier
        Supplier.objects.create(name="ClearCo", category="CLEARING_AGENT",
                                email="agent@clearco.mv",
                                is_clearing_agent=True)
        CompanyParameter.objects.create(
            key="clearance_share_cc",
            value="cargoclearance@sandplanet.mv, second@sandplanet.mv")
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments",
                             {"mode": "SEA"}, format="json")
        sid = r.data["shipments"][0]["id"]
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/documents",
                         {"doc_type": "BL_AWB",
                          "file": SimpleUploadedFile("bl.pdf", b"%PDF-1.4",
                              content_type="application/pdf")},
                         format="multipart")
        r = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/share",
                             {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(mail.outbox[0].cc,
                         ["cargoclearance@sandplanet.mv",
                          "second@sandplanet.mv"])

    def test_setup_page_reads_and_purchasing_edits(self):
        from core.models import Supplier
        agent = Supplier.objects.create(
            name="ClearCo", category="CLEARING_AGENT",
            email="agent@clearco.mv", is_clearing_agent=True)
        self.client.force_authenticate(self.ho)
        r = self.client.get("/api/v1/clearance/setup")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["agent"]["id"], agent.id)
        self.assertTrue(r.data["can_edit"])
        # save a CC list
        r = self.client.post("/api/v1/clearance/setup",
                             {"share_cc": "cargoclearance@sandplanet.mv"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["share_cc"], "cargoclearance@sandplanet.mv")
        # a bad address is refused
        r = self.client.post("/api/v1/clearance/setup",
                             {"share_cc": "not-an-email"}, format="json")
        self.assertEqual(r.status_code, 400)
        # finance reads but cannot edit
        self.client.force_authenticate(self.finance)
        r = self.client.get("/api/v1/clearance/setup")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can_edit"])
        r = self.client.post("/api/v1/clearance/setup",
                             {"share_cc": "x@y.mv"}, format="json")
        self.assertEqual(r.status_code, 403)
        # site roles see nothing
        self.client.force_authenticate(self.pm)
        self.assertEqual(
            self.client.get("/api/v1/clearance/setup").status_code, 403)

    def test_pending_clearances_list_the_uncleared_shipments(self):
        from core.models import Supplier
        Supplier.objects.create(name="ClearCo", category="CLEARING_AGENT",
                                email="agent@clearco.mv",
                                is_clearing_agent=True)
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        self.client.post(f"/api/v1/ipr/{ref}/shipments",
                         {"mode": "SEA"}, format="json")
        data = self.client.get("/api/v1/clearance/setup").data
        row = next(x for x in data["incoming"] if x["ipr_ref"] == ref)
        self.assertEqual(row["status"], "BOOKED")
        self.assertIsNone(row["shared_at"])
        self.assertIn("Packing list", row["missing_docs"])
        self.assertEqual(row["charges"],
                         {"paid": 0, "raised": 0, "entered": 0})
        self.assertIn("Upload", row["next_action"])
        self.assertEqual(data["tiles"]["at_sea"], 1)
        self.assertEqual(data["tiles"]["at_port"], 0)
        self.assertEqual(data["at_port"], [])
        self.assertEqual(data["to_receive"], [])


class CorrectionReschedulesFixedMilestoneTests(IprBase):
    """IPR-037 (owner 2026-08-27): a DUE fixed advance dead-locked charge
    corrections — the guard called it settled, and even an approved
    correction left the fixed amount stale so the schedule no longer summed
    to the total. Now DUE-unvouchered milestones rescale with the total."""

    def test_due_fixed_advance_rescales_through_a_correction(self):
        from decimal import Decimal
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        # order 1000 goods + 1150 freight = 2150; fixed advance = full total
        order = self._order(ref)
        order.freight_handling = Decimal("1150")
        order.save(update_fields=["freight_handling"])
        total = str(Decimal("1000") + Decimal("1150"))
        self.client.post(f"/api/v1/ipr/{ref}/milestones", {"rows": [
            {"label": "Advance 100%", "trigger": "ADVANCE",
             "fixed_amount": total}]}, format="json")
        m = self.client.get(f"/api/v1/ipr/{ref}").data["milestones"][0]
        self.client.post(f"/api/v1/ipr/{ref}/milestones/{m['id']}/due", {},
                         format="json")
        # correct: freight removed, misc 350 → total 1350 (below old 2150,
        # above nothing committed) — proposal must be ACCEPTED
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges",
                             {"freight_handling": "0", "misc_fee": "350",
                              "reason": "air freight removed"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # Director then Signatory
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/ipr/{ref}/correct-charges/decide",
                         {"action": "approve"}, format="json")
        self.client.force_authenticate(self.signatory)
        r = self.client.post(f"/api/v1/ipr/{ref}/correct-charges/decide",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        mm = ImportPaymentMilestone.objects.get(pk=m["id"])
        self.assertEqual(mm.fixed_amount, Decimal("1350.00"))
        self.assertEqual(mm.status, "DUE")     # still due, at the new value


class IprBriefTests(IprBase):
    """Site teams track their orders through the sanitised brief (owner
    2026-08-27) — status, payment words, shipping; never a price (§6C.5)."""

    def test_pm_of_the_allocated_site_reads_it_without_money(self):
        ref = self.create_and_authorise()
        pm = make_user("brief_pm", User.Role.PM, site=self.site)
        self.client.force_authenticate(pm)
        r = self.client.get(f"/api/v1/ipr/{ref}/brief")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["ref"], ref)
        self.assertEqual(r.data["supplier"], self.supplier.name)
        blob = str(r.data)
        for forbidden in ("unit_price", "order_total", "mvr", "amount",
                          "exchange_rate", "1500", "100.0"):
            self.assertNotIn(forbidden, blob.lower())

    def test_pm_of_another_site_sees_nothing(self):
        ref = self.create_and_authorise()
        other = Site.objects.create(code="ZZB", name="Elsewhere",
                                    status=Site.Status.ACTIVE)
        pm = make_user("brief_pm2", User.Role.PM, site=other)
        self.client.force_authenticate(pm)
        self.assertEqual(
            self.client.get(f"/api/v1/ipr/{ref}/brief").status_code, 404)


class ConsolidatedShipmentTests(IprBase):
    """Shipments are independent of orders (owner 2026-08-28): one shipment
    can carry cargo from several IPRs; each order still sees it, and the
    clearing charges apportion by goods value aboard."""

    def _second_order(self):
        from .models import Document, DocumentRevision
        pmr2 = Document.objects.create(
            doc_type="PMR", ref="PMR-SJR-051", site=self.site,
            project=self.project, doc_date=date.today(),
            status="SIZED_RELEASED", created_by=self.pm)
        DocumentRevision.objects.create(document=pmr2, rev_label="R0",
                                        payload={}, created_by=self.pm)
        pmr2.current_revision = pmr2.revisions.first()
        pmr2.save(update_fields=["current_revision"])
        self.client.force_authenticate(self.ho)
        body = self.order_body()
        body["pmr_refs"] = [pmr2.ref]
        ref = self.client.post("/api/v1/ipr", body, format="json").data["ref"]
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {},
                         format="json")
        return ref

    def test_one_shipment_carries_two_orders_and_both_see_it(self):
        ref_a = self.create_and_authorise()
        ref_b = self._second_order()
        self.client.force_authenticate(self.ho)
        opts = self.client.get("/api/v1/shipments/cargo-options").data
        rows = []
        for o in opts:
            if o["ipr_ref"] in (ref_a, ref_b):
                rows.append({"ipr_line_id": o["lines"][0]["id"], "qty": "2"})
        self.assertEqual(len(rows), 2)
        r = self.client.post("/api/v1/shipments",
                             {"mode": "SEA", "rows": rows,
                              "container_awb": "CSQU3054383"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("SHP-"))
        self.assertEqual(len(r.data["orders"]), 2)
        # both orders show the consolidated shipment, each naming the other
        for ref in (ref_a, ref_b):
            doc = self.client.get(f"/api/v1/ipr/{ref}").data
            self.assertEqual(len(doc["shipments"]), 1)
            aboard = {o["ref"] for o in doc["shipments"][0]["orders_aboard"]}
            self.assertEqual(aboard, {ref_a, ref_b})

    def test_clearing_charges_apportion_by_goods_value_aboard(self):
        from decimal import Decimal
        from .models import ImportShipment
        ref_a = self.create_and_authorise()
        ref_b = self._second_order()
        self.client.force_authenticate(self.ho)
        opts = {o["ipr_ref"]: o for o in
                self.client.get("/api/v1/shipments/cargo-options").data}
        # 3 units of A and 1 of B, same unit price → 75% / 25%
        rows = [{"ipr_line_id": opts[ref_a]["lines"][0]["id"], "qty": "3"},
                {"ipr_line_id": opts[ref_b]["lines"][0]["id"], "qty": "1"}]
        sid = self.client.post("/api/v1/shipments",
                               {"mode": "SEA", "rows": rows},
                               format="json").data["id"]
        sh = ImportShipment.objects.get(pk=sid)
        sh.freight = Decimal("4000")          # MVR clearing charge
        sh.save(update_fields=["freight"])
        from . import imports as svc
        a = svc.shipment_charge_share(sh, self._order(ref_a))
        b = svc.shipment_charge_share(sh, self._order(ref_b))
        self.assertEqual(a.quantize(Decimal("0.01")), Decimal("3000.00"))
        self.assertEqual(b.quantize(Decimal("0.01")), Decimal("1000.00"))
        self.assertEqual((a + b).quantize(Decimal("0.01")),
                         Decimal("4000.00"))


class BookingNeedsNoAmbientTransactionTests(TransactionTestCase):
    """IPR-016 (2026-08-28): booking 500ed in the real request because
    next_ref locks the counter FOR UPDATE and nothing opened a transaction —
    every test until now ran inside TestCase's implicit atomic block, which
    hid it. TransactionTestCase reproduces production's autocommit."""

    def test_both_booking_paths_work_in_autocommit(self):
        from .models import (CostHead, Document, DocumentRevision,
                             ImportOrder, ImportOrderLine, Site, User)
        from .tests import make_user
        site = Site.objects.create(code="BKG", name="Booking",
                                   status=Site.Status.ACTIVE)
        actor = make_user("bkg_ho", User.Role.HO_PURCHASING)
        supplier = Supplier.objects.create(name="Pumps Co",
                                           category="INTERNATIONAL")
        head = CostHead.objects.get_or_create(
            name="Materials", defaults={"sort_order": 1})[0]
        doc = Document.objects.create(
            doc_type="IPR", ref="IPR-BKG-001", site=site,
            doc_date=date.today(), status="AUTHORISED", created_by=actor)
        DocumentRevision.objects.create(document=doc, rev_label="R0",
                                        payload={}, created_by=actor)
        order = ImportOrder.objects.create(document=doc, supplier=supplier,
                                           order_currency="USD",
                                           exchange_rate=15)
        line = ImportOrderLine.objects.create(
            order=order, line_no=1, free_text_desc="Pump", unit="nos",
            order_qty=10, unit_price=100, cost_head=head)

        from . import imports as svc
        sh, err = svc.create_consolidated_shipment(
            {"mode": "SEA", "rows": [{"ipr_line_id": line.id, "qty": "4"}]},
            actor)
        self.assertIsNone(err)
        self.assertTrue(sh.ref.startswith("SHP-"))

        sh2, err2 = svc.create_shipment(
            order, {"mode": "SEA", "lines": [{"ipr_line_id": line.id,
                                              "qty": "6"}]}, actor)
        self.assertIsNone(err2)
        self.assertTrue(sh2.ref.startswith("SHP-"))
        self.assertNotEqual(sh.ref, sh2.ref)
