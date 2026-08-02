"""Client Portal — the security boundary (Phase 3). The realm must be
structurally isolated: a client token can't reach staff APIs and a staff
session can't reach client APIs."""
from django.test import TestCase
from rest_framework.test import APIClient

from .models import ClientUser, Site, User
from .tests import make_user


class ClientPortalAuthTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="HDH", name="Other",
                                         status=Site.Status.ACTIVE)
        self.admin = make_user("admin1", User.Role.ADMIN)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        self.client = APIClient()

    def _make_client_user(self, sites=None):
        self.client.force_authenticate(self.admin)
        r = self.client.post("/api/v1/client-users", {
            "org_name": "Blue Lagoon Resort", "full_name": "Aisha Client",
            "email": "aisha@bluelagoon.mv",
            "site_ids": [s.id for s in (sites or [self.site])],
        }, format="json")
        assert r.status_code == 201, r.data
        self.client.force_authenticate(None)
        return r.data["temp_password"], r.data

    def _login(self, email, password):
        return self.client.post("/api/client/auth/login",
                                {"email": email, "password": password},
                                format="json")

    # ---- account creation is admin-only --------------------------------
    def test_only_admin_creates_client_users(self):
        self.client.force_authenticate(self.pm)
        r = self.client.post("/api/v1/client-users",
                             {"email": "x@y.mv"}, format="json")
        self.assertEqual(r.status_code, 403)

    # ---- login ----------------------------------------------------------
    def test_login_and_me(self):
        temp, _ = self._make_client_user()
        r = self._login("aisha@bluelagoon.mv", temp)
        self.assertEqual(r.status_code, 200, r.data)
        token = r.data["token"]
        self.assertTrue(r.data["must_change_password"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        me = self.client.get("/api/client/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["org_name"], "Blue Lagoon Resort")
        self.assertEqual([s["code"] for s in me.data["sites"]], ["VKR"])

    def test_wrong_password_rejected(self):
        self._make_client_user()
        self.assertEqual(
            self._login("aisha@bluelagoon.mv", "nope").status_code, 401)

    # ---- THE BOUNDARY ---------------------------------------------------
    def test_client_token_rejected_on_staff_api(self):
        temp, _ = self._make_client_user()
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        # a staff endpoint must NOT accept a client token
        for url in ("/api/v1/directory", "/api/v1/sites",
                    "/api/v1/client-users"):
            r = self.client.get(url)
            self.assertIn(r.status_code, (401, 403), f"{url} -> {r.status_code}")

    def test_staff_session_rejected_on_client_api(self):
        self.client.force_authenticate(self.admin)   # staff session
        for url in ("/api/client/me", "/api/client/sites"):
            r = self.client.get(url)
            self.assertIn(r.status_code, (401, 403), f"{url} -> {r.status_code}")

    # ---- site scoping ---------------------------------------------------
    def test_sites_scoped_to_assigned(self):
        temp, _ = self._make_client_user(sites=[self.site])
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        r = self.client.get("/api/client/sites")
        self.assertEqual([s["code"] for s in r.data], ["VKR"])   # not HDH

    def test_change_password_clears_flag_and_revoke_on_deactivate(self):
        temp, created = self._make_client_user()
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        r = self.client.post("/api/client/auth/change-password", {
            "current_password": temp, "new_password": "brand-new-pass"},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # deactivating the account kills the live session
        self.client.credentials()
        self.client.force_authenticate(self.admin)
        self.client.delete(f"/api/v1/client-users/{created['id']}")
        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get("/api/client/me").status_code, 401)

    def test_site_dashboard_scoped_and_allowlisted(self):
        import json
        temp, _ = self._make_client_user(sites=[self.site])
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        r = self.client.get(f"/api/client/sites/{self.site.id}")
        self.assertEqual(r.status_code, 200, r.data)
        for key in ("site", "projects", "manpower", "dma", "recent_dprs",
                    "materials_on_the_way"):
            self.assertIn(key, r.data)
        self.assertIn("grand_total", r.data["manpower"])
        # no commercial / internal fields leak through
        blob = json.dumps(r.data, default=str).lower()
        for bad in ("rate", "cost", "contract_value", "engagement",
                    "subcontract", "basic_pay", "client_name"):
            self.assertNotIn(bad, blob)
        # a site they aren't assigned to → 404, never 403
        self.assertEqual(
            self.client.get(f"/api/client/sites/{self.other.id}").status_code,
            404)

    def test_document_viewer_gated(self):
        from datetime import date
        from .models import Document
        temp, _ = self._make_client_user(sites=[self.site])
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        # an internal (non-viewable) doc type on their own site → 404
        po = Document.objects.create(
            doc_type="PO", ref="PO-VKR-001", site=self.site,
            doc_date=date.today(), status="ISSUED", created_by=self.admin)
        self.assertEqual(
            self.client.get(f"/api/client/documents/{po.ref}").status_code, 404)
        # a viewable type but on a site they aren't assigned to → 404
        dpr = Document.objects.create(
            doc_type="DPR", ref="DPR-HDH-001", site=self.other,
            doc_date=date.today(), status="ISSUED", created_by=self.admin)
        self.assertEqual(
            self.client.get(f"/api/client/documents/{dpr.ref}").status_code, 404)

    def test_project_procurement_gated(self):
        from .models import Project
        temp, _ = self._make_client_user(sites=[self.site])
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        mine = Project.objects.create(site=self.site, code="VKR-A",
                                      title="Pools")
        theirs = Project.objects.create(site=self.other, code="HDH-A",
                                        title="Villas")
        # own project, no schedule yet → available:false (200)
        r = self.client.get(f"/api/client/projects/{mine.id}/procurement")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["available"])
        # a project on another site → 404
        self.assertEqual(
            self.client.get(
                f"/api/client/projects/{theirs.id}/procurement").status_code,
            404)
