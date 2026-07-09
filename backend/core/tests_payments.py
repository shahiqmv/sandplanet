"""M6b — PYR workflow + cost postings (§5.9, §7.5, §4A)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (CompanyParameter, CostHead, CostPosting, Document,
                     Site, SitePmHistory, User)
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

        r = self.act(ref, "authorise", self.signatory, comment="ok")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "AUTHORISED")
        # COMMITTED posted at authorisation
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
        self.act(ref, "authorise", self.signatory)
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
        self.act(ref, "authorise", self.signatory)
        r = self.act(ref, "pay", self.finance, amount_paid=2500)
        self.assertEqual(r.status_code, 400)
        r = self.act(ref, "pay", self.finance, amount_paid=2500,
                     variance_reason="agreed rebate")
        self.assertEqual(r.status_code, 200, r.data)


class PyrSegregationTests(PyrBase):
    def _to_director_approved(self, amount):
        ref = self.raise_pyr(amount=amount).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        return ref

    def test_finance_cannot_authorise_when_threshold_disabled(self):
        ref = self._to_director_approved(3000)
        r = self.act(ref, "authorise", self.finance)
        self.assertEqual(r.status_code, 403)

    def test_finance_authorises_below_threshold_only(self):
        CompanyParameter.objects.create(key="signatory_threshold", value=2000)
        below = self._to_director_approved(1500)
        self.assertEqual(self.act(below, "authorise",
                                  self.finance).status_code, 200)
        above = self._to_director_approved(5000)
        self.assertEqual(self.act(above, "authorise",
                                  self.finance).status_code, 403)
        # a signatory still authorises the large one
        self.assertEqual(self.act(above, "authorise",
                                  self.signatory).status_code, 200)


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
        self.act(ref, "authorise", self.signatory)
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
        self.act(ref, "authorise", self.signatory)
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
