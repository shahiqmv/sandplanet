"""Meetings — record, visibility, action-item follow-up, recurring series."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Meeting, MeetingActionItem, Project, Site, User
from .tests import make_user


class MeetingTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(site=self.site, code="POOLS17",
                                              title="17 Pools")
        self.director = make_user("dir1", User.Role.DIRECTOR)   # custodian
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        self.qs = make_user("qs1", User.Role.QS)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()

    def _create(self, user=None, **over):
        self.client.force_authenticate(user or self.director)
        body = {"title": "Weekly progress review", "meeting_type": "PROJECT",
                "project_id": self.project.id,
                "scheduled_at": "2026-08-05T10:00:00Z", "cadence": "WEEKLY"}
        body.update(over)
        return self.client.post("/api/v1/meetings", body, format="json")

    # ---- creation + access ----------------------------------------------
    def test_create_project_meeting(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["meeting_type"], "PROJECT")
        self.assertEqual(r.data["project_code"], "POOLS17")
        # the project's site is inferred
        self.assertEqual(r.data["site_code"], "VKR")

    def test_prospect_meeting_uses_free_text_org(self):
        r = self._create(meeting_type="PROSPECT", project_id=None,
                         org_name="Blue Lagoon Resort",
                         title="Intro — new resort")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["org_name"], "Blue Lagoon Resort")

    def test_finance_role_cannot_schedule(self):
        fin = make_user("fin1", User.Role.FINANCE)
        self.assertEqual(self._create(user=fin).status_code, 403)

    def test_custodian_sees_all_others_see_only_theirs(self):
        # QS organises one; the PM (not attending, other site none) shouldn't
        # see it, but the Director (custodian) should.
        mid = self._create(user=self.qs).data["id"]
        self.client.force_authenticate(self.director)
        self.assertIn(mid, [m["id"] for m in
                      self.client.get("/api/v1/meetings").data["meetings"]])
        self.client.force_authenticate(self.pm)
        # PM is not organiser/attendee; the meeting's site is VKR (PM's site) —
        # so a site match makes it visible. Use a non-site prospect to test the
        # exclusion cleanly.
        pid = self._create(user=self.qs, meeting_type="PROSPECT",
                           project_id=None, org_name="X").data["id"]
        self.client.force_authenticate(self.pm)
        self.assertNotIn(pid, [m["id"] for m in
                         self.client.get("/api/v1/meetings").data["meetings"]])

    def test_site_engineer_sees_their_site_meeting(self):
        mid = self._create(meeting_type="SITE", project_id=None,
                           site_id=self.site.id, title="Toolbox").data["id"]
        self.client.force_authenticate(self.se)
        self.assertIn(mid, [m["id"] for m in
                      self.client.get("/api/v1/meetings").data["meetings"]])

    def test_marketing_sees_prospect_meetings(self):
        mkt = make_user("mkt1", User.Role.MARKETING)
        mid = self._create(meeting_type="PROSPECT", project_id=None,
                           org_name="New Resort").data["id"]
        self.client.force_authenticate(mkt)
        self.assertIn(mid, [m["id"] for m in
                      self.client.get("/api/v1/meetings").data["meetings"]])

    def test_inviting_a_user_notifies_them(self):
        from .models import Notification
        mid = self._create().data["id"]          # organiser = director
        r = self.client.patch(f"/api/v1/meetings/{mid}",
                              {"attendees": [{"user_id": self.pm.id}]},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(Notification.objects.filter(
            recipient=self.pm, title__icontains="Meeting invite").exists())
        # re-saving the same attendee doesn't re-notify (no duplicate invite)
        Notification.objects.all().delete()
        self.client.patch(f"/api/v1/meetings/{mid}",
                          {"attendees": [{"user_id": self.pm.id}]},
                          format="json")
        self.assertEqual(Notification.objects.filter(recipient=self.pm)
                         .count(), 0)

    def test_scheduling_notifies_participants(self):
        from .models import Notification
        # director schedules with the PM as attendee → PM gets a push/in-app ping
        r = self._create(attendees=[{"user_id": self.pm.id}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Notification.objects.filter(
            recipient=self.pm, title__icontains="Meeting scheduled").exists())
        # the creator isn't pinged about their own meeting
        self.assertFalse(
            Notification.objects.filter(recipient=self.director).exists())

    def test_scheduling_notifies_organiser_on_their_behalf(self):
        from .models import Notification
        # a custodian schedules on behalf of the QS as organiser → QS is pinged
        r = self._create(organiser_id=self.qs.id)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Notification.objects.filter(
            recipient=self.qs, title__icontains="Meeting scheduled").exists())

    # ---- cancel / delete ------------------------------------------------
    def test_cancel_keeps_record(self):
        mid = self._create().data["id"]
        r = self.client.delete(f"/api/v1/meetings/{mid}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "CANCELLED")
        self.assertTrue(Meeting.objects.filter(pk=mid).exists())

    def test_hard_delete_removes_meeting(self):
        mid = self._create().data["id"]
        r = self.client.delete(f"/api/v1/meetings/{mid}?hard=1")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Meeting.objects.filter(pk=mid).exists())

    def test_non_manager_cannot_delete(self):
        mid = self._create(user=self.qs).data["id"]     # QS organises
        self.client.force_authenticate(self.pm)          # sees it via site, not manager
        r = self.client.delete(f"/api/v1/meetings/{mid}?hard=1")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Meeting.objects.filter(pk=mid).exists())

    def test_meeting_link_set_on_create_and_edit(self):
        r = self._create(location_kind="ONLINE",
                         meeting_link="https://meet.example.com/abc")
        self.assertEqual(r.status_code, 201, r.data)
        mid = r.data["id"]
        self.assertEqual(r.data["meeting_link"], "https://meet.example.com/abc")
        r2 = self.client.patch(f"/api/v1/meetings/{mid}",
                               {"meeting_link": "https://zoom.example.com/xyz"},
                               format="json")
        self.assertEqual(r2.data["meeting_link"], "https://zoom.example.com/xyz")

    # ---- reschedule + audio ---------------------------------------------
    def test_reschedule_moves_time_and_notifies(self):
        from .models import Notification
        mid = self._create(attendees=[{"user_id": self.pm.id}]).data["id"]
        Notification.objects.all().delete()          # clear the scheduling ping
        r = self.client.post(f"/api/v1/meetings/{mid}/reschedule",
                             {"scheduled_at": "2026-08-20T14:00:00Z"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(str(r.data["scheduled_at"]).startswith("2026-08-20"))
        self.assertTrue(Notification.objects.filter(
            recipient=self.pm, title__icontains="rescheduled").exists())

    def test_non_manager_cannot_reschedule(self):
        mid = self._create(user=self.qs).data["id"]  # QS organises
        self.client.force_authenticate(self.pm)       # sees via site, not manager
        r = self.client.post(f"/api/v1/meetings/{mid}/reschedule",
                             {"scheduled_at": "2026-08-20T14:00:00Z"},
                             format="json")
        self.assertEqual(r.status_code, 400)          # blocked at the service
        self.assertIn("custodian", r.data["detail"])

    @override_settings(MEDIA_ROOT="test-media")
    def test_audio_upload_download_delete(self):
        mid = self._create().data["id"]
        f = SimpleUploadedFile("rec.m4a", b"ID3fakeaudiobytes", "audio/mp4")
        r = self.client.post(f"/api/v1/meetings/{mid}/audio",
                             {"file": f, "note": "session 1"}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["recordings"]), 1)
        rec = r.data["recordings"][0]
        self.assertEqual(rec["note"], "session 1")
        d = self.client.get(f"/api/v1/meetings/{mid}/audio/{rec['id']}")
        self.assertEqual(d.status_code, 200)
        d.close()          # release the streamed file handle (Windows lock)
        x = self.client.delete(f"/api/v1/meetings/{mid}/audio/{rec['id']}")
        self.assertEqual(x.status_code, 204)

    # ---- action items + my queue ----------------------------------------
    def test_action_items_and_my_queue(self):
        mid = self._create().data["id"]
        r = self.client.post(f"/api/v1/meetings/{mid}/actions", {"rows": [
            {"description": "Send revised programme", "owner_id": self.pm.id,
             "due_date": "2026-08-08"},
            {"description": "Client to confirm tile colour",
             "owner_name": "Client rep"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["action_items"]), 2)
        # the PM sees the item assigned to them in their queue
        self.client.force_authenticate(self.pm)
        q = self.client.get("/api/v1/meetings/my-actions").data["items"]
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["description"], "Send revised programme")

    # ---- minutes ---------------------------------------------------------
    def test_recording_minutes_sets_draft(self):
        mid = self._create().data["id"]
        r = self.client.patch(f"/api/v1/meetings/{mid}",
                              {"minutes": "Discussed slab progress…"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["minutes_status"], "DRAFT")

    # ---- recurring series ------------------------------------------------
    def test_closing_recurring_spawns_next_and_rolls_open_actions(self):
        mid = self._create().data["id"]
        self.client.post(f"/api/v1/meetings/{mid}/actions", {"rows": [
            {"description": "Open item", "owner_id": self.pm.id},
            {"description": "Done item", "owner_id": self.pm.id,
             "status": "DONE"}]}, format="json")
        r = self.client.post(f"/api/v1/meetings/{mid}/close", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["meeting"]["status"], "HELD")
        nxt = r.data["next"]
        self.assertIsNotNone(nxt)
        # +7 days for a weekly cadence
        self.assertTrue(str(nxt["scheduled_at"]).startswith("2026-08-12"))
        # only the still-open action rolled forward
        detail = self.client.get(f"/api/v1/meetings/{nxt['id']}").data
        descs = [a["description"] for a in detail["action_items"]]
        self.assertEqual(descs, ["Open item"])
        self.assertTrue(detail["action_items"][0]["carried"])

    def test_one_off_does_not_spawn(self):
        mid = self._create(cadence="ONE_OFF").data["id"]
        r = self.client.post(f"/api/v1/meetings/{mid}/close", {}, format="json")
        self.assertIsNone(r.data["next"])

    # ---- Phase 2: Claude-drafted minutes --------------------------------
    def test_draft_minutes_from_notes(self):
        from . import meeting_minutes
        mid = self._create().data["id"]
        orig = meeting_minutes._call_claude
        meeting_minutes._call_claude = lambda content, model: {
            "minutes": "Discussion: slab on track.\nDecisions: proceed.",
            "action_items": [
                {"description": "Send revised programme", "owner": "Ahmed",
                 "due_date": "2026-08-08"},
                {"description": "Confirm tile colour"}]}
        try:
            r = self.client.post(
                f"/api/v1/meetings/{mid}/draft-minutes",
                {"notes": "slab done; Ahmed to send programme by Fri"},
                format="json")
        finally:
            meeting_minutes._call_claude = orig
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("Decisions", r.data["minutes"])
        self.assertEqual(len(r.data["action_items"]), 2)
        self.assertEqual(r.data["action_items"][0]["owner_name"], "Ahmed")
        self.assertEqual(str(r.data["action_items"][0]["due_date"]),
                         "2026-08-08")
        # raw notes are kept on the meeting for re-drafting
        self.assertIn("slab",
                      self.client.get(f"/api/v1/meetings/{mid}").data["notes"])

    def test_draft_minutes_needs_notes(self):
        mid = self._create().data["id"]
        r = self.client.post(f"/api/v1/meetings/{mid}/draft-minutes",
                             {"notes": ""}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_minutes_pdf_renders(self):
        mid = self._create().data["id"]
        self.client.patch(f"/api/v1/meetings/{mid}",
                          {"minutes": "Discussed slab. Decision: proceed."},
                          format="json")
        self.client.post(f"/api/v1/meetings/{mid}/actions", {"rows": [
            {"description": "Send programme", "owner_id": self.pm.id,
             "due_date": "2026-08-08"}]}, format="json")
        r = self.client.get(f"/api/v1/meetings/{mid}/minutes.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
