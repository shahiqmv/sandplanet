"""The discussion on a document (owner 2026-10-07): notes for the record,
follow-ups that sit on My Tasks until answered, visible only to those who
can see the document, never a gate."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Comment, CommentRecipient, Document, Notification, Site,
                     SitePmHistory, User)
from .tests import make_user


class DiscussionTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="VKR", name="Vakkaru",
                                         status=Site.Status.ACTIVE)
        self.sa = make_user("d_sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("d_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.pd = make_user("d_pd", User.Role.DIRECTOR)
        self.sig = make_user("d_sig", User.Role.SIGNATORY)
        self.far = make_user("d_far", User.Role.SITE_ADMIN, site=self.other)
        self.doc = Document.objects.create(
            doc_type="MR", ref="MR-SJR-900", site=self.site,
            doc_date=date(2026, 10, 1), status="SUBMITTED", created_by=self.sa)
        self.key = f"doc:{self.doc.id}"
        self.c = APIClient()

    def post(self, user, body, to=None):
        self.c.force_authenticate(user)
        return self.c.post(f"/api/v1/discussion/{self.key}",
                           {"body": body, "to": to or []}, format="json")

    def tasks(self, user):
        self.c.force_authenticate(user)
        groups = self.c.get("/api/v1/approvals/pending").data["groups"]
        g = next((g for g in groups if g["title"].startswith("To answer")),
                 None)
        return [i["ref"] for i in g["items"]] if g else []

    def test_a_note_is_for_the_record_and_chases_nobody(self):
        r = self.post(self.sa, "Ordered against the June BOM.")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["comments"][0]["kind"], "NOTE")
        self.assertEqual(r.data["comments"][0]["status_at"], "SUBMITTED")
        self.assertEqual(self.tasks(self.pm), [])
        self.assertEqual(Notification.objects.count(), 0)

    def test_a_follow_up_sits_on_my_tasks_until_answered(self):
        r = self.post(self.sa, "PM, can this go today?", to=[self.pm.id])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["comments"][0]["kind"], "FOLLOWUP")
        self.assertTrue(r.data["comments"][0]["open"])
        self.assertEqual(self.tasks(self.pm), ["MR-SJR-900"])
        self.assertTrue(Notification.objects.filter(
            recipient=self.pm, title__contains="asked on MR-SJR-900").exists())
        # the PM's reply answers it, and the asker is told
        r = self.post(self.pm, "Yes, approved this morning.")
        self.assertFalse(r.data["comments"][0]["open"])
        self.assertEqual(r.data["comments"][0]["to"][0]["answered_by"],
                         self.pm.full_name)
        self.assertEqual(self.tasks(self.pm), [])
        self.assertTrue(Notification.objects.filter(
            recipient=self.sa, title__contains="replied").exists())

    def test_anyone_else_may_answer_and_the_asker_may_not_answer_themself(self):
        self.post(self.sa, "Signatory, is the PV signed?", to=[self.sig.id])
        # the asker's own further note leaves the question open
        r = self.post(self.sa, "Still waiting on this.")
        self.assertTrue(r.data["comments"][0]["open"])
        self.assertEqual(self.tasks(self.sig), ["MR-SJR-900"])
        # the Director answers what was put to the Signatory
        r = self.post(self.pd, "Signed yesterday.")
        self.assertFalse(r.data["comments"][0]["open"])
        self.assertEqual(self.tasks(self.sig), [])

    def test_the_person_asked_can_mark_it_answered_without_replying(self):
        r = self.post(self.sa, "Seen?", to=[self.pm.id])
        rid = r.data["comments"][0]["to"][0]["recipient_id"]
        self.c.force_authenticate(self.pd)
        self.assertEqual(self.c.post(
            f"/api/v1/discussion/recipients/{rid}/answered").status_code, 400)
        self.c.force_authenticate(self.pm)
        r = self.c.post(f"/api/v1/discussion/recipients/{rid}/answered")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["comments"][0]["open"])

    def test_only_people_who_can_see_the_document(self):
        # a site admin of another site can neither read it nor be asked
        self.c.force_authenticate(self.far)
        self.assertEqual(self.c.get(f"/api/v1/discussion/{self.key}")
                         .status_code, 404)
        r = self.post(self.sa, "Can you check?", to=[self.far.id])
        self.assertEqual(r.status_code, 400)
        self.assertIn("cannot see", r.data["detail"])
        # the picker offers the document's own people first
        self.c.force_authenticate(self.sa)
        names = [p["name"] for p in self.c.get(
            f"/api/v1/discussion/{self.key}/people").data["people"]]
        self.assertIn(self.pm.full_name, names)
        self.assertIn(self.pd.full_name, names)
        self.assertNotIn(self.far.full_name, names)
        self.assertNotIn(self.sa.full_name, names)       # not oneself

    def test_a_thread_never_blocks_the_workflow(self):
        self.post(self.sa, "Question?", to=[self.pm.id])
        self.c.force_authenticate(self.pm)
        r = self.c.post(f"/api/v1/documents/{self.doc.ref}/actions/approve",
                        {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(CommentRecipient.objects.filter(
            answered_at__isnull=True).count(), 1)
        self.assertEqual(Comment.objects.count(), 1)

    def test_a_payroll_run_has_a_thread_too(self):
        from .models import PayrollRun
        hr = make_user("d_hr", User.Role.HO_HR)
        run = PayrollRun.objects.create(site=self.site, currency="MVR",
                                        year=2026, month=9, working_days=30,
                                        created_by=hr, ref="PRL-SJR-900")
        self.c.force_authenticate(hr)
        r = self.c.post(f"/api/v1/discussion/payroll:{run.id}",
                        {"body": "PM, please verify by Friday.",
                         "to": [self.pm.id]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.c.force_authenticate(self.pm)
        items = self.c.get("/api/v1/discussion/mine").data["items"]
        self.assertEqual([(i["doc_type"], i["run_id"]) for i in items],
                         [("PAY", run.id)])
        # a site admin cannot see a payroll run, so cannot be asked on it
        self.c.force_authenticate(hr)
        r = self.c.post(f"/api/v1/discussion/payroll:{run.id}",
                        {"body": "x", "to": [self.sa.id]}, format="json")
        self.assertEqual(r.status_code, 400)
