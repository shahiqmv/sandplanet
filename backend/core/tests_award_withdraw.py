"""Withdrawing awarded items from one vendor of an approved PR.

PR-259 (owner 2026-10-01): a fault found in one line of a vendor's quotation
after the Director had awarded it and the other orders had gone out. The
vendor's order was returned and cancelled, and there the request stuck — it
could not be edited, the award stood with no order, the request could never
settle, and every item stayed locked to it.
"""
from decimal import Decimal

from .models import (Approval, AuditLog, CostPosting, Document, DocumentLine,
                     QuotationLine)
from .tests_quotes import QuoteBase


class AwardWithdrawTests(QuoteBase):
    def setUp(self):
        super().setUp()
        mr = self.sent_mr()
        self.mr_ref = mr["ref"]
        self.cement_line, self.rebar_line = (mr["lines"][0]["id"],
                                             mr["lines"][1]["id"])
        pr = self.draft_pr(mr)
        self.pr_ref = pr["ref"]
        # one credit vendor awarded both items — the second is the faulty one
        self.add_quote(self.pr_ref, self.steel, [
            {"supplier_desc": "Cement", "unit": "bag", "qty": 150, "rate": 100,
             "mr_line": self.cement_line, "awarded": True},
            {"supplier_desc": "GI pipe (wrong spec)", "unit": "kg", "qty": 500,
             "rate": 35, "mr_line": self.rebar_line, "awarded": True},
        ], terms="30 days credit")
        self.client.post(f"/api/v1/pr/{self.pr_ref}/sync-vendor-rows")
        self.act(self.pr_ref, "submit")
        self.as_user(self.director)
        assert self.act(self.pr_ref, "approve").status_code == 200
        self.pr = Document.objects.get(ref=self.pr_ref)
        self.row = self.pr.current_revision.lines.get()
        self.po = Document.objects.get(doc_type="PO",
                                       links_from__to_document=self.pr)
        self.q_cement, self.q_pipe = list(QuotationLine.objects.filter(
            quotation__document=self.pr).order_by("line_no"))

    def _cancel_order(self):
        self.as_user(self.signatory)
        assert self.act(self.po.ref, "return",
                        {"comment": "GI pipe wrong"}).status_code == 200
        self.as_user(self.purchasing)
        assert self.act(self.po.ref, "cancel",
                        {"comment": "GI pipe remove"}).status_code == 200

    def _withdraw(self, ids, reason="Wrong spec on the quote", user=None):
        self.as_user(user or self.purchasing)
        return self.client.post(
            f"/api/v1/pr/{self.pr_ref}/withdraw-award",
            {"line_id": self.row.id, "quote_line_ids": ids, "reason": reason},
            format="json")

    def test_while_the_order_stands_it_is_refused(self):
        r = self._withdraw([self.q_pipe.id])
        self.assertEqual(r.status_code, 400)
        self.assertIn(self.po.ref, r.data["detail"])
        self.as_user(self.purchasing)
        info = self.client.get(f"/api/v1/pr/{self.pr_ref}/withdraw-award"
                               f"?line_id={self.row.id}").data
        self.assertIn("cancel that order first", info["block"])

    def test_one_item_withdrawn_the_rest_re_ordered(self):
        self._cancel_order()
        self.as_user(self.purchasing)
        info = self.client.get(f"/api/v1/pr/{self.pr_ref}/withdraw-award"
                               f"?line_id={self.row.id}").data
        self.assertIsNone(info["block"])
        self.assertEqual(len(info["lines"]), 2)

        r = self._withdraw([self.q_pipe.id])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["withdrawn"], r.data["amount"], r.data["left"],
                          r.data["released_items"]),
                         (1, Decimal("17500.00"), Decimal("15000.00"), 1))
        # the vendor row is what is left, with its tax
        self.row.refresh_from_db()
        self.assertEqual(self.row.amount_credit, Decimal("15000.00"))
        self.assertEqual(self.row.gst_amount, Decimal("1200.00"))
        self.assertIn("1 withdrawn", self.row.remarks)
        # a clean order for the remaining item, already with the signatory
        new = Document.objects.get(ref=r.data["new_orders"][0])
        self.assertEqual((new.status, self.row.po_ref), ("SUBMITTED", new.ref))
        lines = list(new.current_revision.lines.all())
        self.assertEqual([(ln.item_id, ln.amount) for ln in lines],
                         [(self.cement.id, Decimal("15000.00"))])
        # the pipe is free for a new request; the cement stays on this one
        pipe, cement = (DocumentLine.objects.get(pk=self.rebar_line),
                        DocumentLine.objects.get(pk=self.cement_line))
        self.assertIsNone(pipe.ordered_pr_id)
        self.assertEqual(cement.ordered_pr_id, self.pr.id)
        self.assertEqual(Document.objects.get(ref=self.mr_ref).status,
                         "PARTIALLY_ORDERED")
        # nothing was ever committed for the withdrawn value
        self.assertFalse(CostPosting.objects.filter(document=self.pr).exists())
        # on the record, and the Director is told
        self.assertTrue(Approval.objects.filter(
            document=self.pr, action="AWARD_WITHDRAWN").exists())
        log = AuditLog.objects.get(event="PR_AWARD_WITHDRAWN")
        self.assertEqual(log.detail["amount"], "17500.00")
        # the released item can go on a new request
        self.as_user(self.purchasing)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id,
            "mr_refs": [self.mr_ref], "line_ids": [self.rebar_line],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_signing_the_new_order_settles_the_request(self):
        self._cancel_order()
        r = self._withdraw([self.q_pipe.id])
        self.as_user(self.signatory)
        self.assertEqual(self.act(r.data["new_orders"][0],
                                  "authorise").status_code, 200)
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, "PAID_PO_ISSUED")
        # only the remaining value is committed
        net = sum(c.amount for c in CostPosting.objects.filter(
            document=self.pr, state="COMMITTED", is_stock_pool=False))
        self.assertEqual(net, Decimal("15000.00"))

    def test_everything_withdrawn_leaves_no_order_and_settles_the_row(self):
        self._cancel_order()
        r = self._withdraw([self.q_pipe.id, self.q_cement.id])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["left"], r.data["new_orders"],
                          r.data["released_items"]), (Decimal("0"), [], 2))
        self.row.refresh_from_db()
        self.assertIsNone(self.row.amount_credit)
        self.assertEqual(self.row.gst_amount, Decimal("0"))
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, "PAID_PO_ISSUED")   # nothing left open
        self.assertEqual(Document.objects.filter(
            doc_type="PO", links_from__to_document=self.pr)
            .exclude(status="CANCELLED").count(), 0)

    def test_reason_items_and_role_are_required(self):
        self._cancel_order()
        self.assertEqual(self._withdraw([self.q_pipe.id], reason="")
                         .status_code, 400)
        self.assertEqual(self._withdraw([]).status_code, 400)
        for who in (self.sa, self.finance, self.signatory):
            self.assertEqual(self._withdraw([self.q_pipe.id], user=who)
                             .status_code, 403, who.role)
        self.assertTrue(QuotationLine.objects.get(pk=self.q_pipe.id).awarded)

    def test_an_issued_order_is_amended_not_withdrawn(self):
        self.as_user(self.signatory)
        assert self.act(self.po.ref, "authorise").status_code == 200
        r = self._withdraw([self.q_pipe.id])
        self.assertEqual(r.status_code, 400)
        self.assertIn("amend the order", r.data["detail"])
