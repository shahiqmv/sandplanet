"""M6a — the cost-posting ledger foundation (Technical Design §4A).
These are the highest-stakes invariants in the system; per the build
brief they are written first."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from . import costing
from .models import (CompanyParameter, CostHead, CostPosting, Site, User)
from .tests import make_user


class CostHeadSeedTests(TestCase):
    def test_default_heads_and_pools_seeded(self):
        self.assertTrue(CostHead.objects.filter(name="Materials",
                                                is_pool=False).exists())
        # the three HO pools are flagged and never a project head
        for pool in ("General Stock", "Foreign Exchange", "Stock Adjustment"):
            self.assertTrue(CostHead.objects.filter(name=pool,
                                                    is_pool=True).exists())
        self.assertEqual(CostHead.objects.filter(is_pool=False).count(), 8)


class PostingLedgerTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.materials = CostHead.objects.get(name="Materials")
        self.actor = make_user("fin", User.Role.FINANCE)

    def test_posting_is_append_only(self):
        # the service exposes no update/delete; the model has no such method
        p = costing.post(site=self.site, cost_head=self.materials,
                         state="COMMITTED", source="PYR", amount=1000,
                         actor=self.actor)
        self.assertEqual(CostPosting.objects.count(), 1)
        self.assertFalse(hasattr(costing, "update_posting"))
        self.assertFalse(hasattr(costing, "delete_posting"))
        self.assertEqual(p.amount, Decimal("1000"))

    def test_reversal_nets_to_zero(self):
        from .models import Document
        doc = Document.objects.create(
            doc_type="PYR", ref="PYR-VKR-001", site=self.site,
            doc_date=date.today(), status="PAID", created_by=self.actor)
        costing.post(site=self.site, cost_head=self.materials,
                     state="COMMITTED", source="PYR", amount=1000,
                     document=doc, actor=self.actor)
        costing.post(site=self.site, cost_head=self.materials,
                     state="INCURRED", source="PYR", amount=1000,
                     document=doc, actor=self.actor)
        self.assertEqual(costing.document_net(doc), Decimal("2000"))

        reversals = costing.reverse_document(doc, actor=self.actor)
        self.assertEqual(len(reversals), 2)
        # every posting the document produced now nets to zero
        self.assertEqual(costing.document_net(doc), Decimal("0"))
        for r in reversals:
            self.assertIsNotNone(r.reversal_of_id)
            self.assertLess(r.amount, 0)

    def test_reverse_is_idempotent(self):
        from .models import Document
        doc = Document.objects.create(
            doc_type="PYR", ref="PYR-VKR-002", site=self.site,
            doc_date=date.today(), status="PAID", created_by=self.actor)
        costing.post(site=self.site, cost_head=self.materials,
                     state="COMMITTED", source="PYR", amount=500,
                     document=doc, actor=self.actor)
        costing.reverse_document(doc, actor=self.actor)
        # a second withdrawal must not double-reverse
        second = costing.reverse_document(doc, actor=self.actor)
        self.assertEqual(second, [])
        self.assertEqual(costing.document_net(doc), Decimal("0"))


class SegregationOfDutiesTests(TestCase):
    """Build brief non-negotiable: a FINANCE user may never authorise at or
    above signatory_threshold."""

    def setUp(self):
        self.finance = make_user("fin", User.Role.FINANCE)
        self.signatory = make_user("sig", User.Role.SIGNATORY)
        self.director = make_user("dir", User.Role.DIRECTOR)

    def set_threshold(self, value):
        CompanyParameter.objects.update_or_create(
            key="signatory_threshold", defaults={"value": value})

    def test_threshold_disabled_by_default(self):
        # no parameter set → everything needs a signatory
        self.assertIsNone(costing.signatory_threshold())
        self.assertFalse(costing.can_authorise(self.finance, 100))
        self.assertTrue(costing.can_authorise(self.signatory, 10_000_000))

    def test_finance_blocked_at_or_above_threshold(self):
        self.set_threshold(2000)
        self.assertTrue(costing.can_authorise(self.finance, 1999))
        self.assertFalse(costing.can_authorise(self.finance, 2000))
        self.assertFalse(costing.can_authorise(self.finance, 5000))
        # signatory always may; a plain director never authorises (that is
        # commercial approval, not financial authorisation)
        self.assertTrue(costing.can_authorise(self.signatory, 5000))
        self.assertFalse(costing.can_authorise(self.director, 100))
