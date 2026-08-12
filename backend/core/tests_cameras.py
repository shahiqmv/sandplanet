"""Site cameras — the relay's auth hook and the two viewing realms.

The hook is the only thing standing between a public relay port and a live
view of a client's site, so most of this file is about what it REFUSES.
"""
from django.core import signing
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import cameras as cam_svc
from .models import Camera, Site, User
from .tests import make_user

RELAY = "https://cams.example.mv"


@override_settings(CAMERA_RELAY_URL=RELAY)
class RelayAuthHookTests(TestCase):
    """MediaMTX asks us on every connection; these are the answers."""

    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.cam = Camera.objects.create(site=self.site, name="Main gate",
                                         path="vkr-gate", stream_key="s3cret")
        self.api = APIClient()

    def hook(self, **payload):
        return self.api.post("/api/relay/auth", payload, format="json",
                             REMOTE_ADDR="127.0.0.1")

    # ---- publishing (the site box) --------------------------------------
    def test_publish_with_correct_key_allowed(self):
        r = self.hook(action="publish", path="vkr-gate", user="vkr-gate",
                      password="s3cret")
        self.assertEqual(r.status_code, 200)
        self.cam.refresh_from_db()
        self.assertIsNotNone(self.cam.last_seen_at)

    def test_publish_with_wrong_key_denied(self):
        r = self.hook(action="publish", path="vkr-gate", user="vkr-gate",
                      password="guess")
        self.assertEqual(r.status_code, 401)

    def test_publish_with_blank_key_denied(self):
        """A camera row saved with an empty key must not become open season."""
        Camera.objects.filter(pk=self.cam.pk).update(stream_key="")
        r = self.hook(action="publish", path="vkr-gate", user="vkr-gate",
                      password="")
        self.assertEqual(r.status_code, 401)

    def test_publish_to_unknown_path_denied(self):
        r = self.hook(action="publish", path="nope", user="nope",
                      password="s3cret")
        self.assertEqual(r.status_code, 401)

    def test_publish_to_inactive_camera_denied(self):
        Camera.objects.filter(pk=self.cam.pk).update(is_active=False)
        r = self.hook(action="publish", path="vkr-gate", user="vkr-gate",
                      password="s3cret")
        self.assertEqual(r.status_code, 401)

    # ---- reading (a viewer's ticket) ------------------------------------
    def test_read_with_valid_ticket_allowed(self):
        t = cam_svc.issue_ticket(self.cam, "staff", 1)
        r = self.hook(action="read", path="vkr-gate", user="ticket",
                      password=t)
        self.assertEqual(r.status_code, 200)

    def test_read_with_ticket_for_another_camera_denied(self):
        other = Camera.objects.create(site=self.site, name="Jetty",
                                      path="vkr-jetty", stream_key="k")
        t = cam_svc.issue_ticket(other, "staff", 1)
        r = self.hook(action="read", path="vkr-gate", user="ticket",
                      password=t)
        self.assertEqual(r.status_code, 401)

    def test_read_with_expired_ticket_denied(self):
        t = cam_svc.issue_ticket(self.cam, "staff", 1)
        old = signing.loads
        try:
            def expired(*a, **kw):
                raise signing.SignatureExpired("too old")
            signing.loads = expired
            r = self.hook(action="read", path="vkr-gate", password=t)
        finally:
            signing.loads = old
        self.assertEqual(r.status_code, 401)

    def test_read_with_garbage_ticket_denied(self):
        r = self.hook(action="read", path="vkr-gate", password="nonsense")
        self.assertEqual(r.status_code, 401)

    def test_read_with_the_stream_key_denied(self):
        """The publish secret must not double as a viewing credential."""
        r = self.hook(action="read", path="vkr-gate", password="s3cret")
        self.assertEqual(r.status_code, 401)

    # ---- the hook is loopback-only --------------------------------------
    def test_hook_refuses_remote_callers(self):
        t = cam_svc.issue_ticket(self.cam, "staff", 1)
        r = self.api.post("/api/relay/auth",
                          {"action": "read", "path": "vkr-gate",
                           "password": t},
                          format="json", REMOTE_ADDR="203.0.113.9")
        self.assertEqual(r.status_code, 404)


@override_settings(CAMERA_RELAY_URL=RELAY)
class StaffCameraTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="HDH", name="Other",
                                         status=Site.Status.ACTIVE)
        self.admin = make_user("admin1", User.Role.ADMIN)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        self.cam = Camera.objects.create(site=self.site, name="Gate",
                                         path="vkr-gate", stream_key="s3cret")
        self.hidden = Camera.objects.create(site=self.other, name="Elsewhere",
                                            path="hdh-gate", stream_key="k2")
        self.api = APIClient()

    def test_admin_sees_all_sites_and_the_stream_key(self):
        self.api.force_authenticate(self.admin)
        r = self.api.get("/api/v1/cameras")
        self.assertEqual(r.status_code, 200)
        paths = sorted(c["path"] for c in r.data["cameras"])
        self.assertEqual(paths, ["hdh-gate", "vkr-gate"])
        self.assertTrue(r.data["can_manage"])
        self.assertIn("stream_key", r.data["cameras"][0])

    def test_pm_is_scoped_and_never_sees_the_stream_key(self):
        self.api.force_authenticate(self.pm)
        r = self.api.get("/api/v1/cameras")
        self.assertEqual([c["path"] for c in r.data["cameras"]], ["vkr-gate"])
        self.assertFalse(r.data["can_manage"])
        self.assertNotIn("stream_key", r.data["cameras"][0])

    def test_pm_cannot_register_or_edit(self):
        self.api.force_authenticate(self.pm)
        self.assertEqual(self.api.post("/api/v1/cameras", {
            "site": self.site.id, "name": "X", "path": "vkr-x"},
            format="json").status_code, 403)
        self.assertEqual(self.api.patch(
            f"/api/v1/cameras/{self.cam.id}", {"name": "Renamed"},
            format="json").status_code, 403)

    def test_registering_generates_a_key_and_stays_internal(self):
        self.api.force_authenticate(self.admin)
        r = self.api.post("/api/v1/cameras", {
            "site": self.site.id, "name": "Jetty", "path": "vkr-jetty"},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(len(r.data["stream_key"]) >= 20)
        # a new camera is never client-visible by default
        self.assertFalse(r.data["client_visible"])

    def test_duplicate_path_refused(self):
        self.api.force_authenticate(self.admin)
        r = self.api.post("/api/v1/cameras", {
            "site": self.site.id, "name": "Dup", "path": "vkr-gate"},
            format="json")
        self.assertEqual(r.status_code, 400)

    def test_ticket_for_a_camera_outside_the_users_sites_is_404(self):
        self.api.force_authenticate(self.pm)
        r = self.api.post(f"/api/v1/cameras/{self.hidden.id}/ticket")
        self.assertEqual(r.status_code, 404)

    def test_ticket_is_scoped_to_that_camera(self):
        self.api.force_authenticate(self.pm)
        r = self.api.post(f"/api/v1/cameras/{self.cam.id}/ticket")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["whep"], f"{RELAY}/vkr-gate/whep")
        self.assertIsNotNone(cam_svc.read_ticket(r.data["ticket"], "vkr-gate"))
        self.assertIsNone(cam_svc.read_ticket(r.data["ticket"], "hdh-gate"))

    @override_settings(CAMERA_RELAY_URL="")
    def test_no_relay_configured_is_503_not_a_broken_url(self):
        self.api.force_authenticate(self.admin)
        r = self.api.post(f"/api/v1/cameras/{self.cam.id}/ticket")
        self.assertEqual(r.status_code, 503)


@override_settings(CAMERA_RELAY_URL=RELAY)
class ClientCameraTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="HDH", name="Other",
                                         status=Site.Status.ACTIVE)
        self.admin = make_user("admin1", User.Role.ADMIN)
        self.shown = Camera.objects.create(
            site=self.site, name="Gate", path="vkr-gate", stream_key="k",
            client_visible=True)
        self.internal = Camera.objects.create(
            site=self.site, name="Store", path="vkr-store", stream_key="k2")
        self.api = APIClient()
        self.token = self._client_login()

    def _client_login(self):
        self.api.force_authenticate(self.admin)
        r = self.api.post("/api/v1/client-users", {
            "org_name": "Blue Lagoon", "full_name": "Aisha",
            "email": "aisha@bl.mv", "site_ids": [self.site.id]},
            format="json")
        temp = r.data["temp_password"]
        self.api.force_authenticate(None)
        lr = self.api.post("/api/client/auth/login",
                           {"email": "aisha@bl.mv", "password": temp},
                           format="json")
        return lr.data["token"]

    def auth(self):
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_only_client_visible_cameras_are_listed(self):
        self.auth()
        r = self.api.get(f"/api/client/sites/{self.site.id}/cameras")
        self.assertEqual(r.status_code, 200)
        names = [c["name"] for c in r.data["cameras"]]
        self.assertEqual(names, ["Gate"])

    def test_client_payload_never_carries_the_stream_key_or_path(self):
        self.auth()
        r = self.api.get(f"/api/client/sites/{self.site.id}/cameras")
        for c in r.data["cameras"]:
            self.assertNotIn("stream_key", c)
            self.assertNotIn("path", c)

    def test_a_site_they_are_not_assigned_to_is_404(self):
        self.auth()
        r = self.api.get(f"/api/client/sites/{self.other.id}/cameras")
        self.assertEqual(r.status_code, 404)

    def test_admin_gate_hides_the_whole_section(self):
        from .models import ClientUser
        ClientUser.objects.filter(email="aisha@bl.mv").update(
            show_cameras=False)
        self.auth()
        self.assertEqual(self.api.get(
            f"/api/client/sites/{self.site.id}/cameras").status_code, 404)
        self.assertEqual(self.api.post(
            f"/api/client/cameras/{self.shown.id}/ticket").status_code, 404)

    def test_ticket_refused_for_an_internal_camera(self):
        self.auth()
        r = self.api.post(f"/api/client/cameras/{self.internal.id}/ticket")
        self.assertEqual(r.status_code, 404)

    def test_ticket_issued_for_a_published_camera(self):
        self.auth()
        r = self.api.post(f"/api/client/cameras/{self.shown.id}/ticket")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNotNone(cam_svc.read_ticket(r.data["ticket"], "vkr-gate"))

    def test_has_cameras_flag_only_counts_published_ones(self):
        self.auth()
        r = self.api.get("/api/client/sites")
        self.assertTrue(r.data[0]["has_cameras"])
        Camera.objects.filter(pk=self.shown.pk).update(client_visible=False)
        r = self.api.get("/api/client/sites")
        self.assertFalse(r.data[0]["has_cameras"])
