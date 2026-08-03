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

    def test_site_wide_procurement_gated(self):
        temp, _ = self._make_client_user(sites=[self.site])
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        # own site, no schedules yet → available:false (200), not an error
        r = self.client.get(f"/api/client/sites/{self.site.id}/procurement")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["available"])
        # a site they aren't assigned to → 404
        self.assertEqual(
            self.client.get(
                f"/api/client/sites/{self.other.id}/procurement").status_code,
            404)

    def test_report_json_client_safe(self):
        import json
        from datetime import date
        from .models import Document, DocumentRevision
        temp, _ = self._make_client_user(sites=[self.site])
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        dpr = Document.objects.create(
            doc_type="DPR", ref="DPR-VKR-900", site=self.site,
            doc_date=date.today(), status="ISSUED", created_by=self.admin)
        rev = DocumentRevision.objects.create(
            document=dpr, rev_label="R0", created_by=self.admin,
            payload={"working_hours": "07:00-18:00",
                     "work_done": [{"activity": "Wall", "project": "",
                                    "progress_todate": "25"}]})
        dpr.current_revision = rev
        dpr.save(update_fields=["current_revision"])
        r = self.client.get(f"/api/client/documents/{dpr.ref}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["type"], "DPR")
        self.assertEqual(r.data["work_groups"][0]["rows"][0]["todate"], "25")
        blob = json.dumps(r.data, default=str).lower()
        for bad in ("basic_pay", "passport", "engagement", "subcontract",
                    "cost", "rate", "contract_value"):
            self.assertNotIn(bad, blob)

    def test_admin_can_gate_sections(self):
        """Admin toggling a client's show_* flag hides that section both in the
        payload and at the endpoint (404, never 403)."""
        temp, created = self._make_client_user(sites=[self.site])
        cid = created["id"]
        # default: all sections visible in the admin list
        self.client.force_authenticate(self.admin)
        row = next(u for u in self.client.get("/api/v1/client-users").data
                   if u["id"] == cid)
        self.assertTrue(row["show_procurement"])
        # admin turns procurement off
        p = self.client.patch(f"/api/v1/client-users/{cid}",
                              {"show_procurement": False}, format="json")
        self.assertEqual(p.status_code, 200, p.data)
        self.assertFalse(p.data["show_procurement"])
        self.client.force_authenticate(None)
        # the client now can't reach procurement, and the site payload says so
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get(
            f"/api/client/sites/{self.site.id}/procurement").status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/client/sites/{self.site.id}/procurement.xlsx").status_code,
            404)
        vis = self.client.get(
            f"/api/client/sites/{self.site.id}").data["visibility"]
        self.assertFalse(vis["show_procurement"])
        self.assertTrue(vis["show_programme"])

    def test_reports_gate_empties_dashboard_and_blocks_doc(self):
        from datetime import date
        from .models import Document
        temp, created = self._make_client_user(sites=[self.site])
        self.client.force_authenticate(self.admin)
        self.client.patch(f"/api/v1/client-users/{created['id']}",
                          {"show_reports": False}, format="json")
        self.client.force_authenticate(None)
        dpr = Document.objects.create(
            doc_type="DPR", ref="DPR-VKR-777", site=self.site,
            doc_date=date.today(), status="ISSUED", created_by=self.admin)
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        d = self.client.get(f"/api/client/sites/{self.site.id}").data
        self.assertEqual(d["recent_dprs"], [])
        self.assertEqual(d["dma"], {"today": None, "tomorrow": None})
        self.assertEqual(
            self.client.get(f"/api/client/documents/{dpr.ref}").status_code, 404)

    def test_gallery_groups_photos_by_date(self):
        from datetime import date, timedelta
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import Attachment, Document
        temp, _ = self._make_client_user(sites=[self.site])
        png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        for i, dd in enumerate((date.today(), date.today() - timedelta(days=1))):
            doc = Document.objects.create(
                doc_type="DPR", ref=f"DPR-VKR-G{i}", site=self.site,
                doc_date=dd, status="ISSUED", created_by=self.admin)
            Attachment.objects.create(
                document=doc, kind="PHOTO", caption=f"day {i}",
                file=SimpleUploadedFile(f"p{i}.png", png,
                                        content_type="image/png"))
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        r = self.client.get(f"/api/client/sites/{self.site.id}/gallery")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["total"], 2)
        self.assertEqual(len(r.data["days"]), 2)
        # newest date first, caption carried
        self.assertEqual(r.data["days"][0]["date"], date.today().isoformat())
        self.assertEqual(r.data["days"][0]["photos"][0]["caption"], "day 0")
        # a site they aren't assigned to → 404
        self.assertEqual(self.client.get(
            f"/api/client/sites/{self.other.id}/gallery").status_code, 404)

    def test_gallery_gate_blocks_endpoint(self):
        temp, created = self._make_client_user(sites=[self.site])
        self.client.force_authenticate(self.admin)
        self.client.patch(f"/api/v1/client-users/{created['id']}",
                          {"show_gallery": False}, format="json")
        self.client.force_authenticate(None)
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get(
            f"/api/client/sites/{self.site.id}/gallery").status_code, 404)

    def test_client_progress_programme_and_override(self):
        from datetime import date
        from .models import Project, ProgrammeActivity
        temp, _ = self._make_client_user(sites=[self.site])
        token = self._login("aisha@bluelagoon.mv", temp).data["token"]
        proj = Project.objects.create(
            site=self.site, code="VKR-P", title="Pools",
            start_date=date(2026, 1, 1), planned_completion=date(2026, 12, 1))
        # summary + two leaf tasks → duration-weighted 50%
        ProgrammeActivity.objects.create(project=proj, sort_order=1, indent=0,
                                         name="Works", duration_days=1)
        ProgrammeActivity.objects.create(project=proj, sort_order=2, indent=1,
                                         name="A", duration_days=10, progress=100)
        ProgrammeActivity.objects.create(project=proj, sort_order=3, indent=1,
                                         name="B", duration_days=10, progress=0)
        # client sees the programme-weighted % by default
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        r = self.client.get(f"/api/client/sites/{self.site.id}")
        p = next(x for x in r.data["projects"] if x["code"] == "VKR-P")
        self.assertEqual(p["progress"]["percent"], 50)
        self.assertEqual(p["progress"]["source"], "programme")
        # client programme endpoint returns the Gantt rows
        r = self.client.get(f"/api/client/projects/{proj.id}/programme")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["activities"]), 3)
        self.assertEqual(r.data["overall"], 50)
        # a PM/admin publishes an override + note
        self.client.credentials()
        self.client.force_authenticate(self.admin)
        r = self.client.post(f"/api/v1/projects/{proj.id}/client-progress",
                             {"override": 72, "note": "Tiling underway."},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # client now sees the published figure + note
        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        p = next(x for x in self.client.get(
            f"/api/client/sites/{self.site.id}").data["projects"]
            if x["code"] == "VKR-P")
        self.assertEqual(p["progress"]["percent"], 72)
        self.assertEqual(p["progress"]["source"], "published")
        self.assertEqual(p["progress"]["note"], "Tiling underway.")

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
