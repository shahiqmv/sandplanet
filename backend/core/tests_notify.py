"""Approval notifications — the in-app bell."""
from .models import Notification
from .tests_procurement import ProcBase


class NotificationTests(ProcBase):
    def test_mr_submit_notifies_pm(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")   # sa submits → PM must approve
        n = Notification.objects.filter(recipient=self.pm, doc_ref=mr["ref"])
        self.assertTrue(n.exists())
        self.assertIn("needs your approval", n.first().title)
        # the submitter is not notified about their own action
        self.assertFalse(Notification.objects.filter(
            recipient=self.sa, doc_ref=mr["ref"]).exists())

    def test_bell_lists_and_marks_read(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")
        self.as_user(self.pm)
        r = self.client.get("/api/v1/notifications")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.data["unread"], 1)
        self.assertTrue(any(mr["ref"] in i["title"] for i in r.data["items"]))
        r = self.client.post("/api/v1/notifications/read", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/notifications").data["unread"],
                         0)

    def test_not_duplicated_on_repeat(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")
        # returning then resubmitting is a fresh block, but a second submit of
        # the same state must not stack duplicates while still unread
        before = Notification.objects.filter(recipient=self.pm).count()
        from .notify import notify_document
        from .models import Document
        notify_document(Document.objects.get(ref=mr["ref"]), self.sa)
        self.assertEqual(Notification.objects.filter(recipient=self.pm).count(),
                         before)

    def test_pr_submit_notifies_director(self):
        mr_ref = self.mr_to_sent()
        pr = self.make_pr(mr_ref)
        self.act(pr["ref"], "submit")
        self.assertTrue(Notification.objects.filter(
            recipient=self.director, doc_ref=pr["ref"]).exists())


class OriginatorNotifyTests(ProcBase):
    """Milestone notifications to the person who raised the document (R6 §6.2)."""

    def test_originator_notified_on_approval(self):
        mr = self.make_mr()                 # raised by sa
        self.act(mr["ref"], "submit")
        self.as_user(self.pm)
        self.act(mr["ref"], "approve")
        self.assertTrue(Notification.objects.filter(
            recipient=self.sa, doc_ref=mr["ref"],
            title__icontains="approved").exists())

    def test_originator_notified_on_return_with_reason(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")
        self.as_user(self.pm)
        self.act(mr["ref"], "return", {"comment": "spec unclear"})
        n = Notification.objects.filter(
            recipient=self.sa, doc_ref=mr["ref"],
            title__icontains="returned").first()
        self.assertIsNotNone(n)
        self.assertIn("spec unclear", n.title)
