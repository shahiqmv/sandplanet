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
SECRET = "relay-shared-secret"


@override_settings(CAMERA_RELAY_URL=RELAY, CAMERA_RELAY_SECRET=SECRET)
class RelayAuthHookTests(TestCase):
    """MediaMTX asks us on every connection; these are the answers."""

    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.cam = Camera.objects.create(site=self.site, name="Main gate",
                                         path="vkr-gate", stream_key="s3cret")
        self.api = APIClient()

    def hook(self, secret=SECRET, **payload):
        return self.api.post(f"/api/relay/auth/{secret}", payload,
                             format="json")

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

    # ---- the relay must prove it is the relay ---------------------------
    def test_hook_refuses_a_wrong_secret(self):
        t = cam_svc.issue_ticket(self.cam, "staff", 1)
        r = self.hook(secret="not-the-secret", action="read",
                      path="vkr-gate", password=t)
        self.assertEqual(r.status_code, 404)

    @override_settings(CAMERA_RELAY_SECRET="")
    def test_unset_secret_disables_the_hook_rather_than_opening_it(self):
        """A missing secret must never be read as 'no check required'."""
        t = cam_svc.issue_ticket(self.cam, "staff", 1)
        self.assertEqual(self.hook(secret="", action="read", path="vkr-gate",
                                   password=t).status_code, 404)
        self.assertEqual(self.hook(action="read", path="vkr-gate",
                                   password=t).status_code, 404)
        # and a publisher with a perfectly good key is refused too
        self.assertEqual(self.hook(action="publish", path="vkr-gate",
                                   user="vkr-gate",
                                   password="s3cret").status_code, 404)

    def test_the_old_secretless_url_is_gone(self):
        r = self.api.post("/api/relay/auth", {"action": "read",
                                              "path": "vkr-gate"},
                          format="json")
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


class RelayHookHostTests(TestCase):
    """The relay reaches Django as http://web:8000/… , so the Host header is
    the compose service name. If ALLOWED_HOSTS rejects it Django answers 400,
    and MediaMTX reports only 'failed to authenticate' — which sends you
    hunting a credential bug that does not exist (cost an hour, 2026-08-13).
    """

    @override_settings(CAMERA_RELAY_URL=RELAY, CAMERA_RELAY_SECRET=SECRET,
                       ALLOWED_HOSTS=["app.sandplanet.mv",
                                      "client.sandplanet.mv", "web"])
    def test_hook_accepts_the_internal_service_host(self):
        site = Site.objects.create(code="HST", name="Host Isle",
                                   status=Site.Status.ACTIVE)
        cam = Camera.objects.create(site=site, name="Gate", path="hst-gate",
                                    stream_key="k3y")
        r = APIClient().post(f"/api/relay/auth/{SECRET}",
                             {"action": "publish", "path": cam.path,
                              "user": cam.path, "password": "k3y"},
                             format="json", HTTP_HOST="web")
        self.assertNotEqual(r.status_code, 400,
                            "ALLOWED_HOSTS is rejecting the relay's Host")
        self.assertEqual(r.status_code, 200)

    @override_settings(CAMERA_RELAY_URL=RELAY, CAMERA_RELAY_SECRET=SECRET,
                       ALLOWED_HOSTS=["app.sandplanet.mv", "web"],
                       SECURE_SSL_REDIRECT=True,
                       SECURE_REDIRECT_EXEMPT=[r"^api/relay/"])
    def test_hook_is_not_bounced_by_the_https_redirect(self):
        """The relay talks plain HTTP inside the container network and does
        not follow redirects — a 301 reads to it as an auth failure."""
        site = Site.objects.create(code="SSL1", name="Redirect Isle",
                                   status=Site.Status.ACTIVE)
        Camera.objects.create(site=site, name="Gate", path="ssl-gate",
                              stream_key="k3y")
        r = APIClient().post(f"/api/relay/auth/{SECRET}",
                             {"action": "publish", "path": "ssl-gate",
                              "user": "ssl-gate", "password": "k3y"},
                             format="json", HTTP_HOST="web")
        self.assertNotEqual(r.status_code, 301,
                            "the HTTPS redirect is swallowing the hook")
        self.assertEqual(r.status_code, 200)


@override_settings(CAMERA_RELAY_URL=RELAY, CAMERA_RELAY_SECRET=SECRET)
class PullModeTests(TestCase):
    """A site with a routable address forwards its camera port and the relay
    fetches the stream itself — nothing runs at the site, and an unwatched
    camera costs its uplink nothing (owner 2026-08-13)."""

    def setUp(self):
        self.site = Site.objects.create(code="PUL", name="Pull Isle",
                                        status=Site.Status.ACTIVE)
        self.admin = make_user("pull_admin", User.Role.ADMIN)
        self.pm = make_user("pull_pm", User.Role.PM, site=self.site)
        self.api = APIClient()

    def _add(self, **extra):
        self.api.force_authenticate(self.admin)
        body = {"site": self.site.id, "name": "Gate", "path": "pul-gate"}
        body.update(extra)
        return self.api.post("/api/v1/cameras", body, format="json")

    def test_a_pull_camera_is_flagged_as_such(self):
        url = "rtsp://admin:pw@203.0.113.7:8554/Preview_02_main"
        r = self._add(source_url=url)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["mode"], "PULL")

    def test_a_camera_without_a_url_still_expects_the_site_to_publish(self):
        self.assertEqual(self._add().data["mode"], "PUSH")

    def test_the_source_url_never_reaches_a_non_admin(self):
        """It carries the camera's password."""
        self._add(source_url="rtsp://admin:pw@203.0.113.7:8554/x")
        self.api.force_authenticate(self.pm)
        row = self.api.get("/api/v1/cameras").data["cameras"][0]
        self.assertNotIn("source_url", row)
        self.assertNotIn("stream_key", row)
        self.assertEqual(row["mode"], "PULL")   # mode alone is not a secret

    def test_the_source_url_never_reaches_a_client(self):
        from .models import Camera, ClientUser
        self._add(source_url="rtsp://admin:pw@203.0.113.7:8554/x")
        Camera.objects.filter(path="pul-gate").update(client_visible=True)
        self.api.force_authenticate(self.admin)
        temp = self.api.post("/api/v1/client-users", {
            "org_name": "O", "full_name": "C", "email": "c@x.mv",
            "site_ids": [self.site.id]}, format="json").data["temp_password"]
        self.api.force_authenticate(None)
        tok = self.api.post("/api/client/auth/login",
                            {"email": "c@x.mv", "password": temp},
                            format="json").data["token"]
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
        cams = self.api.get(
            f"/api/client/sites/{self.site.id}/cameras").data["cameras"]
        self.assertEqual(len(cams), 1)
        for key in ("source_url", "stream_key", "path", "mode"):
            self.assertNotIn(key, cams[0])
        self.assertTrue(cams[0]["on_demand"])
        self.assertTrue(ClientUser.objects.filter(email="c@x.mv").exists())

    def test_a_pull_camera_still_needs_a_ticket_to_watch(self):
        """Pull mode changes how the stream ARRIVES, never who may see it."""
        from .models import Camera
        self._add(source_url="rtsp://admin:pw@203.0.113.7:8554/x")
        cam = Camera.objects.get(path="pul-gate")
        api = APIClient()
        self.assertEqual(
            api.post(f"/api/relay/auth/{SECRET}",
                     {"action": "read", "path": cam.path,
                      "password": "nope"}, format="json").status_code, 401)
        t = cam_svc.issue_ticket(cam, "staff", 1)
        self.assertEqual(
            api.post(f"/api/relay/auth/{SECRET}",
                     {"action": "read", "path": cam.path,
                      "password": t}, format="json").status_code, 200)
