"""M6b — PYR workflow + cost postings (§5.9, §7.5, §4A)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (CostHead, CostPosting, Document, Site, SitePmHistory,
                     User)
from .tests import make_user


class PyrBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.signatory = make_user("sig", User.Role.SIGNATORY)
        self.finance = make_user("fin", User.Role.FINANCE)
        self.head = CostHead.objects.get(name="Transport & Freight")
        self.client = APIClient()

    def raise_pyr(self, amount=3000, **extra):
        self.client.force_authenticate(self.sa)
        body = {
            "doc_type": "PYR", "site_id": self.site.id, "payload": {},
            "cost_head_id": self.head.id, "payee": "Island Boat Services",
            "payment_type": "DIRECT", "payment_method": "BANK",
            "amount_requested": amount, "purpose": "Boat hire for loading",
            "has_supporting_doc": True,
        }
        body.update(extra)
        return self.client.post("/api/v1/documents", body, format="json")

    def act(self, ref, action, user, **data):
        self.client.force_authenticate(user)
        return self.client.post(f"/api/v1/documents/{ref}/actions/{action}",
                                data, format="json")

    def authorise(self, ref, approver=None):
        """Authorise a Director-approved PYR the M6d way: Finance builds a
        payment voucher, a signatory approves it. Returns the approve
        response."""
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [ref]}, format="json")
        assert pv.status_code == 201, pv.data
        pref = pv.data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pref}/actions/submit",
                         {}, format="json")
        self.client.force_authenticate(approver or self.signatory)
        return self.client.post(
            f"/api/v1/payment-vouchers/{pref}/actions/approve", {},
            format="json")

    def committed(self, doc_id):
        return CostPosting.objects.filter(document_id=doc_id,
                                          state="COMMITTED",
                                          reversal_of__isnull=True)


class PyrHappyPathTests(PyrBase):
    def test_full_chain_posts_committed_then_incurred_paid(self):
        r = self.raise_pyr(amount=3000)
        self.assertEqual(r.status_code, 201, r.data)
        ref = r.data["ref"]
        self.assertEqual(ref, "PYR-VKR-001")

        self.assertEqual(self.act(ref, "submit", self.sa).status_code, 200)
        self.assertEqual(self.act(ref, "approve", self.pm).status_code, 200)
        self.assertEqual(self.act(ref, "approve",
                                  self.director).status_code, 200)
        # nothing posts before authorisation
        doc = Document.objects.get(ref=ref)
        self.assertEqual(CostPosting.objects.filter(document=doc).count(), 0)

        r = self.authorise(ref)
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "AUTHORISED")
        # COMMITTED posted at authorisation (on the voucher)
        c = self.committed(doc.id)
        self.assertEqual(c.count(), 1)
        self.assertEqual(c.first().amount, Decimal("3000"))

        r = self.act(ref, "pay", self.finance, payment_ref="TRF-99",
                     amount_paid=3000)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "PAID")
        self.assertEqual(CostPosting.objects.filter(
            document=doc, state="INCURRED").count(), 1)
        self.assertEqual(CostPosting.objects.filter(
            document=doc, state="PAID").count(), 1)

    def test_finance_attaches_payment_slip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        ref = self.raise_pyr(amount=3000).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        self.authorise(ref)
        self.client.force_authenticate(self.finance)
        with override_settings(MEDIA_ROOT="test-media"):
            slip = SimpleUploadedFile("trf.pdf", b"%PDF slip",
                                      content_type="application/pdf")
            r = self.client.post(
                f"/api/v1/documents/{ref}/actions/pay",
                {"amount_paid": 3000, "payment_ref": "TRF-77", "file": slip},
                format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "PAID")
        self.assertTrue(any(a["kind"] == "PAYMENT_SLIP"
                            for a in r.data["attachments"]))

    def test_pay_variance_requires_reason(self):
        ref = self.raise_pyr(amount=3000).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        self.authorise(ref)
        r = self.act(ref, "pay", self.finance, amount_paid=2500)
        self.assertEqual(r.status_code, 400)
        r = self.act(ref, "pay", self.finance, amount_paid=2500,
                     variance_reason="agreed rebate")
        self.assertEqual(r.status_code, 200, r.data)


class PyrVoucherAuthTests(PyrBase):
    """M6d — authorisation happens only on a payment voucher, and Finance
    cannot approve its own voucher (no self-authorisation)."""

    def _to_director_approved(self, amount):
        ref = self.raise_pyr(amount=amount).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        return ref

    def test_direct_authorise_action_is_retired(self):
        ref = self._to_director_approved(3000)
        r = self.act(ref, "authorise", self.signatory)
        self.assertEqual(r.status_code, 400)
        self.assertIn("payment voucher", r.data["detail"].lower())

    def test_finance_cannot_approve_own_voucher(self):
        ref = self._to_director_approved(3000)
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [ref]}, format="json").data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pv}/actions/submit", {},
                         format="json")
        # Finance cannot approve — that is the signatory's job
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv}/actions/approve", {},
            format="json")
        self.assertEqual(r.status_code, 403)
        # a signatory approves → the PYR commits and becomes payable
        self.client.force_authenticate(self.signatory)
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv}/actions/approve", {},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Document.objects.get(ref=ref).status, "AUTHORISED")


class PyrReturnPathTests(PyrBase):
    def test_return_before_authorisation_posts_nothing(self):
        ref = self.raise_pyr(amount=3000).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        # director returns for review
        r = self.act(ref, "return", self.director,
                     reason_category="INCORRECT_DETAILS",
                     note="Wrong payee account — fix and resubmit.")
        self.assertEqual(r.status_code, 200, r.data)
        doc = Document.objects.get(ref=ref)
        self.assertEqual(doc.status, "DRAFT")
        self.assertEqual(CostPosting.objects.filter(document=doc).count(), 0)
        self.assertEqual(doc.payment_request.returned_reason,
                         "INCORRECT_DETAILS")

    def test_withdraw_authorisation_reverses_to_zero(self):
        from . import costing
        ref = self.raise_pyr(amount=3000).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        self.authorise(ref)
        doc = Document.objects.get(ref=ref)
        self.assertEqual(costing.document_net(doc), Decimal("3000"))
        r = self.act(ref, "withdraw-authorisation", self.finance,
                     note="Duplicate found in the ledger.")
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "DRAFT")
        self.assertEqual(costing.document_net(doc), Decimal("0"))
        # a PM cannot withdraw — Finance only
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        self.authorise(ref)
        self.assertEqual(self.act(ref, "withdraw-authorisation",
                                  self.pm, note="x").status_code, 403)


class PyrSupportingDocTests(PyrBase):
    def test_above_threshold_needs_doc_or_override(self):
        # 8000 > 5000 default, no supporting doc, no override → blocked
        ref = self.raise_pyr(amount=8000, has_supporting_doc=False,
                             no_doc_reason="informal labour").data["ref"]
        r = self.act(ref, "submit", self.sa)
        self.assertEqual(r.status_code, 400)
        self.assertIn("supporting document", r.data["detail"].lower())

    def test_no_doc_needs_reason(self):
        ref = self.raise_pyr(amount=1000, has_supporting_doc=False,
                             no_doc_reason="").data["ref"]
        r = self.act(ref, "submit", self.sa)
        self.assertEqual(r.status_code, 400)
