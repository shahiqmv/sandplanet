"""Procurement hears when a PR supplier is paid, and the PR register says how
far each PR is paid (owner 2026-11-17)."""
from datetime import date

from django.test import TestCase

from .models import Approval, Document, DocumentLine, DocumentRevision, \
    Notification, Site, User
from .notify import notify_pr_paid
from .tests import make_user
from .views_documents import _pr_payment_summary


class PrPaidNotifyTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.buyer = make_user("buy1", User.Role.HO_PURCHASING)
        self.buyer2 = make_user("buy2", User.Role.HO_PURCHASING)
        self.finance = make_user("fin", User.Role.FINANCE)
        self.pr = Document.objects.create(
            doc_type="PR", ref="PR-900", site=self.site,
            doc_date=date.today(), status="AUTHORISED",
            created_by=self.buyer)
        rev = DocumentRevision.objects.create(
            document=self.pr, rev_label="R0", payload={},
            created_by=self.buyer, is_current=True)
        self.pr.current_revision = rev
        self.pr.save(update_fields=["current_revision"])
        self.a = DocumentLine.objects.create(
            revision=rev, line_no=1, vendor="Alpha Hardware", free_text_desc="Cement",
            amount_cash=1000)
        self.b = DocumentLine.objects.create(
            revision=rev, line_no=2, vendor="Beta Timber", amount_cash=500,
            free_text_desc="Plywood")

    def test_procurement_hears_and_is_told_what_is_still_unpaid(self):
        self.a.action_taken = "TT-1"
        self.a.save()
        notify_pr_paid(self.pr, "Alpha Hardware", "TT-1", self.finance,
                       slip=True, amount=1000, currency="MVR")
        got = Notification.objects.filter(doc_ref="PR-900")
        self.assertEqual({n.recipient_id for n in got},
                         {self.buyer.id, self.buyer2.id})
        n = got.first()
        self.assertIn("PR-900 paid", n.title)
        self.assertIn("Alpha Hardware", n.title)
        self.assertIn("slip attached", n.body)
        self.assertIn("still to pay: Beta Timber", n.body)

    def test_the_last_payment_says_the_pr_is_fully_paid(self):
        for ln in (self.a, self.b):
            ln.action_taken = "TT"
            ln.save()
        notify_pr_paid(self.pr, "Beta Timber", "TT-2", self.finance)
        n = Notification.objects.filter(recipient=self.buyer).first()
        self.assertIn("every supplier on this PR is paid", n.body)

    def test_register_summary_counts_cash_rows_paid(self):
        rev = self.pr.current_revision
        self.assertEqual(_pr_payment_summary(rev, None),
                         {"pay_cash_rows": 2, "pay_paid_rows": 0,
                          "pay_last_at": None})
        self.a.action_taken = "TT-1"
        self.a.save()
        Approval.objects.create(document=self.pr, revision=rev,
                                action="PAYMENT_RECORDED", actor=self.finance,
                                actor_role="FINANCE")
        self.assertEqual(_pr_payment_summary(rev, None)["pay_paid_rows"], 1)
