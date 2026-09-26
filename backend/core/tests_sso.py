"""The bridge between the two instances (core/peer_auth.py)."""
import json
from unittest import mock

from django.core import signing
from django.test import override_settings

from . import peer_auth
from .models import User
from .tests import BaseCase, make_user

SECRET = "test-peer-secret-0123456789"


@override_settings(PEER_AUTH_SECRET=SECRET, PEER_URL="http://peer/api/v1")
class HandoffTests(BaseCase):
    def test_a_handoff_token_signs_the_user_in_on_the_other_instance(self):
        pm = make_user("nalin", User.Role.PM)
        pm.email = "nalin@sandplanet.mv"
        pm.save()
        self.login(pm)
        token = self.client.post("/api/v1/auth/handoff", {}, format="json").data["token"]
        # the same token is redeemed by the OTHER instance — simulate by
        # stamping a different source into the profile
        profile = signing.loads(token, key=SECRET, salt=peer_auth.SALT)
        self.assertEqual((profile["u"], profile["src"]), ("nalin", "planet"))
        foreign = signing.dumps({**profile, "src": "marine", "u": "hussain", "n": "Hussain M",
                                 "e": "h@marine.mv", "p": "7770001", "r": "RENTAL"},
                                key=SECRET, salt=peer_auth.SALT)
        self.client.logout()
        self.client.force_authenticate(None)
        r = self.client.post("/api/v1/auth/sso", {"token": foreign}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["username"], r.data["role"]), ("hussain", "RENTAL"))
        u = User.objects.get(username="hussain")
        self.assertEqual((u.home_instance, u.full_name, u.email), ("marine", "Hussain M", "h@marine.mv"))
        self.assertFalse(u.has_usable_password())
        # a token from THIS instance is refused here; a tampered one too
        self.assertEqual(self.client.post("/api/v1/auth/sso", {"token": token}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/auth/sso", {"token": foreign + "x"}, format="json").status_code, 400)
        # deactivated here → the bridge does not bring them back
        u.is_active = False
        u.save()
        self.assertEqual(self.client.post("/api/v1/auth/sso", {"token": foreign}, format="json").status_code, 403)

    def test_switching_back_reuses_the_existing_account_and_refreshes_details(self):
        u = make_user("gayan", User.Role.SITE_ENGINEER)
        foreign = signing.dumps({"u": "gayan", "n": "Gayan Perera", "e": "g@x.mv", "p": "", "r": "PM",
                                 "src": "marine"}, key=SECRET, salt=peer_auth.SALT)
        r = self.client.post("/api/v1/auth/sso", {"token": foreign}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        u.refresh_from_db()
        self.assertEqual((u.role, u.full_name, u.home_instance), ("SITE_ENGINEER", "Gayan Perera", ""))
        self.assertTrue(u.has_usable_password())             # a local account stays local


@override_settings(PEER_AUTH_SECRET=SECRET, PEER_URL="http://peer/api/v1")
class PeerVerifyTests(BaseCase):
    def test_the_sister_instance_verifies_our_credentials_only_with_the_shared_secret(self):
        make_user("asanka", User.Role.SITE_ADMIN)
        body = json.dumps({"username": "asanka", "password": "pw-test-123"}).encode()
        r = self.client.generic("POST", "/api/v1/auth/peer-verify", body, content_type="application/json")
        self.assertEqual(r.status_code, 403)                  # unsigned
        r = self.client.generic("POST", "/api/v1/auth/peer-verify", body, content_type="application/json",
                                HTTP_X_PEER_SIGNATURE=peer_auth.sign_body(body))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["u"], r.data["r"], r.data["src"]), ("asanka", "SITE_ADMIN", "planet"))
        bad = json.dumps({"username": "asanka", "password": "wrong"}).encode()
        r = self.client.generic("POST", "/api/v1/auth/peer-verify", bad, content_type="application/json",
                                HTTP_X_PEER_SIGNATURE=peer_auth.sign_body(bad))
        self.assertEqual(r.status_code, 403)
        # a mirrored account never answers for the other side (no chaining)
        m = User(username="mirror1", role="PM", home_instance="marine")
        m.set_unusable_password()
        m.save()
        b2 = json.dumps({"username": "mirror1", "password": "x"}).encode()
        r = self.client.generic("POST", "/api/v1/auth/peer-verify", b2, content_type="application/json",
                                HTTP_X_PEER_SIGNATURE=peer_auth.sign_body(b2))
        self.assertEqual(r.status_code, 403)

    def test_a_cold_sign_in_falls_back_to_the_sister_instance(self):
        profile = {"u": "nalin", "n": "Nalin S", "e": "n@sp.mv", "p": "", "r": "FINANCE", "src": "marine"}
        with mock.patch.object(peer_auth, "verify_at_peer", return_value=profile) as v:
            r = self.client.post("/api/v1/auth/login", {"username": "nalin", "password": "their-pw"}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
            v.assert_called_once_with("nalin", "their-pw")
        u = User.objects.get(username="nalin")
        self.assertEqual((u.home_instance, u.role), ("marine", "FINANCE"))
        # next time the mirrored account asks the sister again (no local password)
        with mock.patch.object(peer_auth, "verify_at_peer", return_value=None):
            r = self.client.post("/api/v1/auth/login", {"username": "nalin", "password": "their-pw"}, format="json")
            self.assertEqual(r.status_code, 400)
        # a local account with a real password never goes to the peer
        make_user("local1", User.Role.PM)
        with mock.patch.object(peer_auth, "verify_at_peer") as v:
            r = self.client.post("/api/v1/auth/login", {"username": "local1", "password": "pw-test-123"}, format="json")
            self.assertEqual(r.status_code, 200)
            v.assert_not_called()

    def test_off_when_no_secret(self):
        with override_settings(PEER_AUTH_SECRET=""):
            self.assertEqual(self.client.post("/api/v1/auth/sso", {"token": "x"}, format="json").status_code, 404)
            self.assertEqual(self.client.get("/api/v1/brand").data["sso"], False)
