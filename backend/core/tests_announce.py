"""Announcing a release.

Two failures on the first real use (owner 2026-08-30): a 950-character body
overflowed Notification.body's varchar(300), so Postgres refused every insert
and notify_user's defensive except turned 39 failures into a quiet "0 of 39";
and running the command twice left a duplicate in "what's new".
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .models import Notification, ReleaseNote, User
from .notify import notify_user
from .tests import make_user


class NotifyTrimTests(TestCase):
    def setUp(self):
        self.u = make_user("trim_user", User.Role.PM)

    def test_a_long_body_is_trimmed_not_dropped(self):
        """An alert is not a record of truth: a long body should cost the
        tail of a sentence, not the whole message."""
        n = notify_user(self.u, "t", "x" * 950)
        self.assertIsNotNone(n)
        self.assertEqual(len(n.body), 300)

    def test_a_long_title_is_trimmed_too(self):
        n = notify_user(self.u, "y" * 400, "b")
        self.assertIsNotNone(n)
        self.assertEqual(len(n.title), 140)


class AnnounceReleaseTests(TestCase):
    def setUp(self):
        self.a = make_user("ann_a", User.Role.PM)
        self.b = make_user("ann_b", User.Role.FINANCE)

    def _run(self, title="Something shipped", **kw):
        out, err = StringIO(), StringIO()
        call_command("announce_release", title, stdout=out, stderr=err, **kw)
        return out.getvalue(), err.getvalue()

    def test_it_records_a_note_and_tells_everyone(self):
        out, err = self._run(body="Short and useful.")
        self.assertEqual(ReleaseNote.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertIn("Announced to 2", out)
        self.assertEqual(err, "")

    def test_a_long_body_still_reaches_everyone(self):
        """The exact failure: the note keeps the full text, the alert
        carries a short version, and nobody is silently missed."""
        long_body = "This release does a great many things. " * 40
        out, err = self._run(body=long_body)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertIn("Announced to 2", out)
        self.assertEqual(ReleaseNote.objects.get().body, long_body)
        self.assertLessEqual(len(Notification.objects.first().body), 300)

    def test_the_same_title_twice_in_a_day_is_refused(self):
        self._run(body="One.")
        out, err = self._run(body="One.")
        self.assertIn("already announced today", err)
        self.assertEqual(ReleaseNote.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 2)   # not doubled

    def test_force_sends_it_again(self):
        self._run(body="One.")
        self._run(body="One.", force=True)
        self.assertEqual(ReleaseNote.objects.count(), 2)

    def test_a_dry_run_writes_nothing(self):
        out, _ = self._run(body="One.", dry_run=True)
        self.assertIn("Would tell 2 people", out)
        self.assertEqual(ReleaseNote.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)
