"""Part payment (owner 2026-10-27): Finance puts part of a PR, PYR, payable
or overseas TT on a voucher and leaves the balance for a later one; each
part is approved, paid and reversible on its own; a balance can be closed
with a reason."""
from datetime import date
from decimal import Decimal

from . import costing
from . import vouchers
from .models import (Document, ImportOrder, ImportOrderLine,
                     ImportPaymentMilestone, Payable, PaymentVoucherLine,
                     Supplier)
from .tests_pr_costing import PrCostingBase
from .tests_vouchers import VoucherBase


class PyrPartPaymentTests(VoucherBase):
    def _pv(self, ref, amount):
        self.client.force_authenticate(self.finance)
        r = self.client.post("/api/v1/payment-vouchers", {
            "source_refs": [ref], "amounts": {f"DOC:{ref}": str(amount)}},
            format="json")
        assert r.status_code == 201, r.data
        pv = r.data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        return pv

    def test_paid_in_two_parts_and_one_part_voided(self):
        a = self.director_approved_pyr(amount=1000)
        doc = Document.objects.get(ref=a)
        pv1 = self._pv(a, 400)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "AUTHORISED")
        self.assertEqual(costing.document_net(doc, "COMMITTED"),
                         Decimal("1000"))      # the whole is committed once
        # the pay form defaults to the part, not the whole
        r = self.act(a, "pay", self.finance, payment_ref="TT-1")
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "PART_PAID")
        self.assertEqual(costing.document_net(doc, "PAID"), Decimal("400"))
        self.assertEqual(doc.payment_request.amount_paid, Decimal("400"))
        # it is back in the queue with its balance
        self.client.force_authenticate(self.finance)
        row = next(x for x in self.client.get(
            "/api/v1/finance/awaiting-voucher").data if x.get("ref") == a)
        self.assertEqual((row["amount"], row["paid_so_far"]),
                         (Decimal("600"), Decimal("400")))
        # more than is left is refused
        r = self.client.post("/api/v1/payment-vouchers", {
            "source_refs": [a], "amounts": {f"DOC:{a}": "700"}},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("more than", r.data["detail"])
        pv2 = self._pv(a, 600)          # the balance: no second commitment
        self.assertEqual(costing.document_net(doc, "COMMITTED"),
                         Decimal("1000"))
        self.act(a, "pay", self.finance, payment_ref="TT-2")
        doc.refresh_from_db()
        self.assertEqual(doc.status, "PAID")
        self.assertEqual(costing.document_net(doc, "PAID"), Decimal("1000"))
        # voiding the second voucher takes back only its 600
        self.voucher_action(pv2, "request-void", self.finance, reason="dup")
        r = self.voucher_action(pv2, "void", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "PART_PAID")
        self.assertEqual(costing.document_net(doc, "PAID"), Decimal("400"))
        self.assertEqual(costing.document_net(doc, "COMMITTED"),
                         Decimal("1000"))
        self.assertEqual(vouchers.balance(doc=doc)["balance"], Decimal("600"))
        self.assertFalse(Document.objects.get(ref=pv1).is_void)

    def test_a_payment_that_does_more_than_move_money_is_paid_whole(self):
        a = self.director_approved_pyr(amount=1000)
        pr = Document.objects.get(ref=a).payment_request
        pr.payment_type = "PERMIT_RENEWAL"
        pr.save(update_fields=["payment_type"])
        self.client.force_authenticate(self.finance)
        r = self.client.post("/api/v1/payment-vouchers", {
            "source_refs": [a], "amounts": {f"DOC:{a}": "300"}},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("paid whole", r.data["detail"])

    def test_a_balance_closed_with_a_reason(self):
        a = self.director_approved_pyr(amount=1000)
        doc = Document.objects.get(ref=a)
        self._pv(a, 400)
        self.act(a, "pay", self.finance, payment_ref="TT-1")
        self.client.force_authenticate(self.finance)
        url = "/api/v1/payment-vouchers/close-balance"
        self.assertEqual(self.client.post(url, {"kind": "DOC", "ref": a},
                                          format="json").status_code, 400)
        r = self.client.post(url, {"kind": "DOC", "ref": a,
                                   "reason": "Supplier discount"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "PAID")
        self.assertEqual(doc.payment_request.closed_amount, Decimal("600"))
        self.assertEqual(costing.document_net(doc, "COMMITTED"),
                         Decimal("400"))
        self.assertNotIn(doc, vouchers.awaiting_voucher())


class PayablePartPaymentTests(VoucherBase):
    def test_a_payable_settles_with_its_last_part(self):
        svc = Document.objects.create(
            doc_type="SVC", ref="SVC-PP-001", status="AUTHORISED",
            site=self.site, doc_date=date.today(), created_by=self.finance)
        p = Payable.objects.create(document=svc, site=self.site,
                                   vendor="Atoll Civil", amount=Decimal("800"))
        refs = []
        for amount in ("300", "500"):
            self.client.force_authenticate(self.finance)
            r = self.client.post("/api/v1/payment-vouchers", {
                "payable_ids": [p.id], "amounts": {f"P:{p.id}": amount}},
                format="json")
            self.assertEqual(r.status_code, 201, r.data)
            pv = r.data["ref"]
            refs.append(pv)
            self.voucher_action(pv, "submit", self.finance)
            self.voucher_action(pv, "approve", self.signatory)
            r = self.voucher_action(pv, "settle-payable", self.finance,
                                    payable_id=p.id, payment_ref=f"T{amount}")
            self.assertEqual(r.status_code, 200, r.data)
            p.refresh_from_db()
            if amount == "300":
                self.assertEqual(p.status, "OUTSTANDING")
                self.assertEqual(costing.document_net(svc, "PAID"),
                                 Decimal("300"))
                self.assertIn(p, list(vouchers.awaiting_payables()))
        svc.refresh_from_db()
        self.assertEqual((p.status, svc.status), ("SETTLED", "PAID"))
        self.assertEqual(costing.document_net(svc, "PAID"), Decimal("800"))


class PrPartPaymentTests(PrCostingBase):
    def _two_cash_suppliers(self):
        pr = self.make_pr()
        b = pr.current_revision.lines.get(vendor="Vendor B")
        b.amount_cash, b.amount_credit = Decimal("7000"), None
        b.save(update_fields=["amount_cash", "amount_credit"])
        return pr

    def _voucher(self, pr, rows):
        self.client.force_authenticate(self.finance)
        r = self.client.post("/api/v1/payment-vouchers", {
            "source_refs": [pr.ref], "pr_rows": {pr.ref: rows}},
            format="json")
        assert r.status_code == 201, r.data
        pv = r.data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pv}/actions/submit",
                         {}, format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/payment-vouchers/{pv}/actions/approve",
                         {}, format="json")
        return pv

    def test_paid_supplier_by_supplier(self):
        pr = self._two_cash_suppliers()
        a = pr.current_revision.lines.get(vendor="Vendor A")
        b = pr.current_revision.lines.get(vendor="Vendor B")
        self._voucher(pr, [a.id])
        pr.refresh_from_db()
        self.assertEqual(pr.status, "AUTHORISED")
        self.client.force_authenticate(self.finance)
        # B is not on an approved voucher yet
        r = self.client.post(f"/api/v1/pr/{pr.ref}/vendor-payment",
                             {"line_id": b.id, "payment_ref": "X"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/pr/{pr.ref}/vendor-payment",
                             {"line_id": a.id, "payment_ref": "SLIP-A"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(costing.document_net(pr, "PAID"), Decimal("5000"))
        self.assertIn(pr, vouchers.awaiting_voucher())
        self.assertEqual([r.id for r in vouchers.pr_open_rows(pr)], [b.id])
        self._voucher(pr, [b.id])      # no second authorisation
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/pr/{pr.ref}/vendor-payment",
                             {"line_id": b.id, "payment_ref": "SLIP-B"})
        self.assertEqual(r.status_code, 200, r.data)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "PAID_PO_ISSUED")
        self.assertEqual(costing.document_net(pr, "PAID"), Decimal("12000"))
        self.assertEqual(costing.document_net(pr, "COMMITTED"),
                         Decimal("12000"))
        self.assertNotIn(pr, vouchers.awaiting_voucher())


class PrCreditOrderFirstTests(PrCostingBase):
    def test_cash_suppliers_vouchered_after_the_credit_order_is_signed(self):
        """The credit order was signed first, so the PR was already PAYMENT_
        PROCESSING and the voucher builder refused it: 22 PRs in production
        whose cash could never be paid (owner 2026-10-27)."""
        pr = self.make_pr()                    # cash A 5000 + credit B 7000
        self.sign_orders(pr)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "PAYMENT_PROCESSING")
        self.assertIn(pr, vouchers.awaiting_voucher())
        r = self.authorise(pr.ref)             # voucher + signatory
        self.assertEqual(r.status_code, 200, r.data)
        a = pr.current_revision.lines.get(vendor="Vendor A")
        self.assertEqual(costing.document_net(pr, "COMMITTED"),
                         Decimal("12000"))     # cash 5000 + the order 7000
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/pr/{pr.ref}/vendor-payment",
                             {"line_id": a.id, "payment_ref": "SLIP-A"})
        self.assertEqual(r.status_code, 200, r.data)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "PAID_PO_ISSUED")
        self.assertNotIn(pr, vouchers.awaiting_voucher())


class MilestonePartPaymentTests(VoucherBase):
    def test_an_overseas_tt_paid_in_parts(self):
        from . import imports as ipr_svc
        ipr = Document.objects.create(
            doc_type="IPR", ref="IPR-PP-001", status="AUTHORISED",
            site=self.site, doc_date=date.today(), created_by=self.finance)
        order = ImportOrder.objects.create(
            document=ipr, supplier=Supplier.objects.create(name="Overseas"),
            exchange_rate=Decimal("15.42"))
        ImportOrderLine.objects.create(order=order, line_no=1,
                                       free_text_desc="Tiles",
                                       order_qty=Decimal("10"),
                                       unit_price=Decimal("10"),
                                       cost_head=self.head)
        m = ImportPaymentMilestone.objects.create(
            order=order, seq=1, label="Balance", trigger="ADVANCE",
            fixed_amount=Decimal("100"), status="DUE")
        self.client.force_authenticate(self.finance)
        r = self.client.post("/api/v1/payment-vouchers", {
            "milestone_ids": [m.id], "amounts": {f"M:{m.id}": "40"}},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        pv = r.data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        m.refresh_from_db()
        self.assertEqual(m.status, "AUTHORISED")
        self.assertIsNone(ipr_svc.pay_milestone(m, "620", "TT-40",
                                                self.finance))
        m.refresh_from_db()
        self.assertEqual(m.status, "DUE")
        self.assertEqual(m.mvr_paid, Decimal("620"))
        line = PaymentVoucherLine.objects.get(voucher__ref=pv)
        self.assertEqual((line.paid_amount, line.paid_local),
                         (Decimal("40"), Decimal("620")))
        self.assertEqual(vouchers.balance(milestone=m)["balance"],
                         Decimal("60"))
        self.assertIn(m, list(vouchers.awaiting_milestones()))
