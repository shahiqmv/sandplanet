"""Withdraw the authorisation of a wrong IPR (owner 2026-07-27) — fix an order
authorised against the wrong supplier: reverse the commitment, void the PO,
back to Draft to edit and re-authorise."""
from .models import (CostPosting, Document, DocumentLink,
                     ImportPaymentMilestone, ImportShipment, Supplier)
from .tests_imports import IprBase


class IprWithdrawTests(IprBase):
    def test_withdraw_reverses_commitment_and_voids_po(self):
        ref = self.create_and_authorise()
        doc = Document.objects.get(ref=ref)
        self.assertEqual(doc.status, "AUTHORISED")
        self.assertTrue(CostPosting.objects.filter(
            document=doc, state="COMMITTED", reversal_of__isnull=True).exists())
        po = Document.objects.filter(
            doc_type="PO", links_to__from_document=doc,
            links_to__link_type="IPR_PO").first()
        self.assertIsNotNone(po)

        self.client.force_authenticate(self.signatory)
        r = self.client.post(
            f"/api/v1/documents/{ref}/actions/withdraw-authorisation",
            {"comment": "authorised against the wrong supplier"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

        doc.refresh_from_db()
        self.assertEqual(doc.status, "DRAFT")
        self.assertFalse(CostPosting.objects.filter(   # commitment cleared
            document=doc, state="COMMITTED").exists())
        po.refresh_from_db()
        self.assertTrue(po.is_void)
        self.assertFalse(DocumentLink.objects.filter(
            from_document=doc, link_type="IPR_PO").exists())

    def test_fix_supplier_and_reauthorise_after_withdraw(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.signatory)
        self.client.post(
            f"/api/v1/documents/{ref}/actions/withdraw-authorisation",
            {"comment": "wrong supplier"}, format="json")
        other = Supplier.objects.create(
            name="Correct Supplier Co", category="INTERNATIONAL",
            country="India", default_currency="USD")
        self.client.force_authenticate(self.ho)
        r = self.client.patch(f"/api/v1/ipr/{ref}",
                              {**self.order_body(), "supplier_id": other.id},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(
            Document.objects.get(ref=ref).import_order.supplier_id, other.id)
        # re-run the approval chain → a fresh PO to the right supplier
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {},
                         format="json")
        doc = Document.objects.get(ref=ref)
        self.assertEqual(doc.status, "AUTHORISED")
        po = Document.objects.filter(
            doc_type="PO", links_to__from_document=doc, is_void=False).first()
        self.assertIsNotNone(po)                 # regenerated
        self.assertEqual(po.supplier_id, other.id)

    def test_withdraw_blocked_by_shipment(self):
        ref = self.create_and_authorise()
        doc = Document.objects.get(ref=ref)
        ImportShipment.objects.create(order=doc.import_order, seq=1)
        self.client.force_authenticate(self.signatory)
        r = self.client.post(
            f"/api/v1/documents/{ref}/actions/withdraw-authorisation",
            {"comment": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Document.objects.get(ref=ref).status, "AUTHORISED")

    def _due_advance(self, ref):
        """An advance milestone whose trigger has been met — DUE means it
        still NEEDS a voucher, not that one exists."""
        order = Document.objects.get(ref=ref).import_order
        return ImportPaymentMilestone.objects.create(
            order=order, seq=1, label="Advance", trigger="ADVANCE",
            status="DUE", percent="100")

    def _withdraw(self, ref, comment="x"):
        self.client.force_authenticate(self.signatory)
        return self.client.post(
            f"/api/v1/documents/{ref}/actions/withdraw-authorisation",
            {"comment": comment}, format="json")

    def test_withdraw_blocked_by_raised_voucher_milestone(self):
        """A milestone actually batched onto a voucher blocks the withdrawal —
        the voucher line PROTECT-references it."""
        from .vouchers import create_voucher
        ref = self.create_and_authorise()
        m = self._due_advance(ref)
        pv, err = create_voucher([], self.finance, milestone_ids=[m.id])
        self.assertIsNone(err, err)
        r = self._withdraw(ref)
        self.assertEqual(r.status_code, 400)     # clean refusal, not a 500
        self.assertIn(pv.ref, r.data["detail"])  # says WHICH voucher
        self.assertEqual(Document.objects.get(ref=ref).status, "AUTHORISED")

    def test_marking_a_milestone_due_does_not_block_the_withdrawal(self):
        """DUE is the state BEFORE a voucher: the trigger has been met and it
        still needs one. The guard read "past PENDING" as "vouchered" and
        refused, naming a payment voucher that had never been raised — the
        real IPR-004, where the only thing done was Mark due (owner
        2026-09-01)."""
        ref = self.create_and_authorise()
        m = self._due_advance(ref)
        self.assertEqual(m.voucher_lines.count(), 0)
        r = self._withdraw(ref, "wrong supplier")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Document.objects.get(ref=ref).status, "DRAFT")
        # the unvouchered row goes with the rest of the schedule
        self.assertFalse(ImportPaymentMilestone.objects.filter(
            id=m.id).exists())

    def test_an_authorised_milestone_still_blocks(self):
        """Money committed on a signatory-approved voucher, even if the
        voucher line itself has since been released."""
        ref = self.create_and_authorise()
        m = self._due_advance(ref)
        ImportPaymentMilestone.objects.filter(id=m.id).update(
            status="AUTHORISED")
        r = self._withdraw(ref)
        self.assertEqual(r.status_code, 400)
        self.assertIn("authorised or paid", r.data["detail"])

    def test_withdraw_clears_pending_schedule(self):
        ref = self.create_and_authorise()
        order = Document.objects.get(ref=ref).import_order
        ImportPaymentMilestone.objects.create(
            order=order, seq=1, label="Advance", trigger="ADVANCE",
            status="PENDING")
        self.client.force_authenticate(self.signatory)
        r = self.client.post(
            f"/api/v1/documents/{ref}/actions/withdraw-authorisation",
            {"comment": "wrong supplier"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(order.milestones.exists())   # pending rows removed

    def test_only_signatory_or_admin_can_withdraw(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)   # HO Purchasing may not
        r = self.client.post(
            f"/api/v1/documents/{ref}/actions/withdraw-authorisation",
            {"comment": "x"}, format="json")
        self.assertEqual(r.status_code, 403)
