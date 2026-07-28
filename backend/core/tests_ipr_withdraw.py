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

    def test_withdraw_blocked_by_raised_voucher_milestone(self):
        ref = self.create_and_authorise()
        order = Document.objects.get(ref=ref).import_order
        ImportPaymentMilestone.objects.create(
            order=order, seq=1, label="Advance", trigger="ADVANCE",
            status="DUE")                        # a voucher was raised
        self.client.force_authenticate(self.signatory)
        r = self.client.post(
            f"/api/v1/documents/{ref}/actions/withdraw-authorisation",
            {"comment": "x"}, format="json")
        self.assertEqual(r.status_code, 400)     # clean refusal, not a 500
        self.assertEqual(Document.objects.get(ref=ref).status, "AUTHORISED")

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
