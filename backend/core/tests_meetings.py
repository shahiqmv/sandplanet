"""Meetings — record, visibility, action-item follow-up, recurring series."""
from django.test import TestCase
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
