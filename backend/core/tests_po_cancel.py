"""Cancelling a returned order releases the award (owner 2026-09-12).

PO-139: two MRs for the same item, one quote, one PR, approved — the
duplicate found at signature. The signatory returned the order, and there
it stuck: its lines cannot be edited, and re-approving the PR does not cut
it again, because generation leaves alone any vendor whose lines already
carry an order. The only way out was to leave a dead draft and start over.
"""
from .models import AuditLog, Document
from .tests_pr_costing import PrCostingBase


class CancelReturnedOrderTests(PrCostingBase):

    def _awarded(self):
        """A PR through approval, with its credit order cut — make_pr already
        submits and approves it."""
        pr = self.make_pr()
        self.assertEqual(pr.status, "APPROVED")
        pos = list(Document.objects.filter(doc_type="PO",
                                           links_from__to_document=pr))
        self.assertEqual(len(pos), 1, pos)
        po = pos[0]
        # The award sends the order for signature itself; it is only in
        # draft once a signatory has handed it back — PO-139's exact state.
        self.assertEqual(po.status, "SUBMITTED")
        r = self.act(po.ref, "return", self.signatory,
                     comment="Duplicate item — same thing on two MRs")
        self.assertEqual(r.status_code, 200, r.data)
        po.refresh_from_db()
        pr.refresh_from_db()
        return pr, po

    def _po_refs(self, pr):
        pr.refresh_from_db()
        return sorted(ln.po_ref for ln in pr.current_revision.lines.all()
                      if (ln.po_ref or "").strip())

    def test_cancelling_releases_the_award_so_a_clean_order_is_cut(self):
        pr, po = self._awarded()
        self.assertEqual(po.status, "DRAFT")
        self.assertEqual(self._po_refs(pr), [po.ref])

        r = self.act(po.ref, "cancel", self.purchasing,
                     comment="Duplicate — same item on two MRs")
        self.assertEqual(r.status_code, 200, r.data)
        po.refresh_from_db()
        self.assertEqual(po.status, "CANCELLED")
        self.assertEqual(self._po_refs(pr), [])            # award released
        self.assertTrue(AuditLog.objects.filter(
            event="PO_AWARD_RELEASED", entity_id=po.id).exists())

        # the PR can now be returned, corrected and approved again — and a
        # fresh order is cut, which is the whole point
        r = self.act(pr.ref, "return", self.director, comment="drop the dup")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.act(pr.ref, "submit", self.purchasing)
                         .status_code, 200)
        r = self.act(pr.ref, "approve", self.director)
        self.assertEqual(r.status_code, 200, r.data)
        fresh = Document.objects.filter(doc_type="PO",
                                        links_from__to_document=pr
                                        ).exclude(pk=po.pk)
        self.assertEqual(fresh.count(), 1)
        # the award sends the new order straight on for signature
        self.assertEqual(fresh.first().status, "SUBMITTED")
        self.assertEqual(self._po_refs(pr), [fresh.first().ref])

    def test_without_cancelling_re_approval_does_not_re_cut(self):
        """The gap this closes, pinned so nobody 'fixes' it back."""
        pr, po = self._awarded()
        self.act(pr.ref, "return", self.director, comment="rework")
        self.act(pr.ref, "submit", self.purchasing)
        self.act(pr.ref, "approve", self.director)
        self.assertEqual(Document.objects.filter(
            doc_type="PO", links_from__to_document=pr).count(), 1)

    def test_only_a_returned_draft_can_be_cancelled(self):
        """An order with the signatory is theirs to return first."""
        pr = self.make_pr()
        po = Document.objects.get(doc_type="PO", links_from__to_document=pr)
        self.assertEqual(po.status, "SUBMITTED")
        r = self.act(po.ref, "cancel", self.purchasing, comment="x")
        self.assertEqual(r.status_code, 400)
        self.assertIn("returned", r.data["detail"])
        self.assertEqual(self._po_refs(pr), [po.ref])      # nothing released

    def test_a_reason_is_required(self):
        _, po = self._awarded()
        r = self.act(po.ref, "cancel", self.purchasing, comment="")
        self.assertEqual(r.status_code, 400)

    def test_purchasing_cancels_not_the_site_or_the_director(self):
        pr, po = self._awarded()
        for who in (self.director, self.sa, self.finance):
            r = self.act(po.ref, "cancel", who, comment="x")
            self.assertEqual(r.status_code, 403, (who.role, r.data))
        self.assertEqual(self._po_refs(pr), [po.ref])
