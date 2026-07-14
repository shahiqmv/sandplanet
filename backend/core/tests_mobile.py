"""Planet Mobile (R6) — device-token auth."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import MobileDevice, User
from .tests import make_user


class MobileAuthTests(TestCase):
    def setUp(self):
        self.user = make_user("pm_m", User.Role.PM)
        self.user.set_password("verify-123")
        self.user.save()
        self.client = APIClient()

    def _login(self, pw="verify-123"):
        return self.client.post("/api/mobile/v1/auth/login",
                                {"username": "pm_m", "password": pw},
                                format="json")

    def test_login_returns_token_then_me_works(self):
        r = self._login()
        self.assertEqual(r.status_code, 201, r.data)
        token = r.data["token"]
        self.assertEqual(r.data["user"]["role"], "PM")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        me = self.client.get("/api/mobile/v1/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["username"], "pm_m")

    def test_wrong_password_rejected(self):
        self.assertEqual(self._login("nope").status_code, 401)

    def test_no_token_is_unauthorised(self):
        self.assertEqual(self.client.get("/api/mobile/v1/me").status_code, 401)

    def test_logout_revokes_the_device(self):
        token = self._login().data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(
            self.client.post("/api/mobile/v1/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/mobile/v1/me").status_code, 401)

    def test_idle_token_expires(self):
        token = self._login().data["token"]
        MobileDevice.objects.filter(token=token).update(
            last_seen=timezone.now() - timedelta(days=31))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get("/api/mobile/v1/me").status_code, 401)

    def test_desktop_session_api_still_session_auth(self):
        # the mobile token must NOT authenticate the desktop API
        token = self._login().data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertIn(self.client.get("/api/v1/auth/me").status_code,
                      (200, 403))  # session endpoint ignores the bearer token
        self.assertFalse(self.client.get("/api/v1/auth/me")
                         .data.get("authenticated", False))
