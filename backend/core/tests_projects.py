from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import (
    AuditLog,
    Document,
    ProgrammeActivity,
    Project,
    Site,
    SitePmHistory,
    User,
)
from .tests import make_user
from .tests_documents import TINY_PNG, last_working_days
from .views_projects import parse_programme_paste

# Rows exactly as they paste from the owner's MS Project programme
SAMPLE_PASTE = (
    "1\tPROPOSED CONSTRUCTION OF 17 NOS SWIMMING POOLS\t233 days\t"
    "Fri 4/17/26\tSat 12/5/26\n"
    "3\t  CONTRACT MILESTONES\t228 days\tWed 4/22/26\tSat 12/5/26\n"
    "4\t    Start Date in Local Island\t0 days\tWed 4/22/26\tWed 4/22/26\n"
    "108\t    Form work Preparation\t4 days\tThu 4/23/26\tSun 4/26/26\n"
    "110\t    Footing Concreting\t1 day\tWed 4/29/26\tWed 4/29/26\n"
)


class PasteParserTests(TestCase):
    def test_parses_ms_project_rows(self):
        rows = parse_programme_paste(SAMPLE_PASTE)
        self.assertEqual(len(rows), 5)
        top = rows[0]
        self.assertEqual(top["indent"], 0)
        self.assertEqual(top["duration_days"], 233)
        self.assertEqual(top["start"], date(2026, 4, 17))
        self.assertEqual(top["finish"], date(2026, 12, 5))
        milestone = rows[2]
        self.assertTrue(milestone["is_milestone"])
        self.assertEqual(milestone["indent"], 2)
        self.assertEqual(milestone["name"], "Start Date in Local Island")
        oneday = rows[4]
        self.assertEqual(oneday["duration_days"], 1)
        self.assertFalse(oneday["is_milestone"])


class ProjectBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="VKR", name="Vakkaru", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=90),
        )
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.pools = self.make_project("POOLS17", "17 Swimming Pools")
        self.spa = self.make_project("SPA", "Spa Renovation")
        self.client.force_authenticate(self.se)

    def make_project(self, code, title):
        r = self.client.post(f"/api/v1/sites/{self.site.id}/projects", {
            "code": code, "title": title,
            "start_date": (date.today() - timedelta(days=30)).isoformat(),
        }, format="json")
        assert r.status_code == 201, r.data
        return Project.objects.get(pk=r.data["id"])

    def make_dpr(self, project, doc_date=None, work_done=None):
        r = self.client.post("/api/v1/documents", {
            "doc_type": "DPR", "site_id": self.site.id,
            "project_id": project.id if project else None,
            "doc_date": (doc_date or date.today()).isoformat(),
            "payload": {"weather_am": "Sunny",
                        "work_done": work_done or []},
        }, format="json")
        return r


class ProjectTests(ProjectBase):
    def test_site_engineer_cannot_create_project(self):
        r = self.client.post(f"/api/v1/sites/{self.site.id}/projects",
                             {"code": "X", "title": "X"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_dpr_is_site_wide_no_project_needed(self):
        """R8: the DPR is one per SITE per day even when the site runs
        active projects — work rows carry the project tags instead."""
        r = self.make_dpr(None)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(r.data["project"])

    def test_one_dpr_per_site_per_day(self):
        day = last_working_days(self.site, 1)[0]
        r1 = self.make_dpr(self.pools, doc_date=day)
        self.assertEqual(r1.status_code, 201, r1.data)
        self.assertEqual(r1.data["ref"], "DPR-VKR-001")
        # a second DPR the same day is blocked — even quoting another
        # project (R8 site-wide daily report; supersedes R4)
        r2 = self.make_dpr(self.spa, doc_date=day)
        self.assertEqual(r2.status_code, 400)
        self.assertIn("DPR-VKR-001", r2.data["detail"])

    def test_closed_project_blocks_project_documents(self):
        self.pools.status = "CLOSED"
        self.pools.save()
        r = self.client.post("/api/v1/documents", {
            "doc_type": "IR", "site_id": self.site.id,
            "project_id": self.pools.id,
            "payload": {"discipline": "Civil", "work_description": "x"},
        }, format="json")
        self.assertEqual(r.status_code, 400)


class ProgrammeTests(ProjectBase):
    def import_programme(self):
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/projects/{self.pools.id}/programme",
                             {"paste": SAMPLE_PASTE}, format="json")
        assert r.status_code == 201, r.data
        self.client.force_authenticate(self.se)
        return list(self.pools.activities.all())

    def test_paste_import(self):
        activities = self.import_programme()
        self.assertEqual(len(activities), 5)
        self.assertTrue(activities[2].is_milestone)

    @override_settings(MEDIA_ROOT="test-media")
    def test_dpr_issue_updates_programme_progress(self):
        activities = self.import_programme()
        formwork = next(a for a in activities
                        if a.name == "Form work Preparation")
        day = last_working_days(self.site, 1)[0]
        r = self.make_dpr(self.pools, doc_date=day, work_done=[
            {"activity_id": formwork.id, "activity": formwork.name,
             "location": "Casting yard", "progress_today": 25,
             "progress_todate": 60, "remarks": ""},
        ])
        ref = r.data["ref"]
        for i in range(4):
            f = SimpleUploadedFile(f"p{i}.png", TINY_PNG,
                                   content_type="image/png")
            self.client.post(f"/api/v1/documents/{ref}/attachments",
                             {"file": f, "kind": "PHOTO",
                              "caption": f"photo {i}"}, format="multipart")
        r = self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        self.assertEqual(r.status_code, 200, r.data)
        formwork.refresh_from_db()
        self.assertEqual(float(formwork.progress), 60.0)
        self.assertEqual(formwork.progress_updated_from.ref, ref)
        self.assertTrue(AuditLog.objects.filter(
            event="PROGRESS_UPDATED",
            entity_id=formwork.id).exists())
        # weighted overall progress reflects the update
        r = self.client.get(f"/api/v1/projects/{self.pools.id}")
        self.assertGreater(r.data["overall_progress"], 0)

    def test_register_is_site_wide(self):
        """R8: one register row per working day per SITE; the day is
        satisfied by the single site-wide DPR."""
        day = last_working_days(self.site, 1)[0]
        r = self.make_dpr(self.pools, doc_date=day)
        self.assertEqual(r.status_code, 201)
        reg = self.client.get(
            f"/api/v1/registers/dpr-tws?site={self.site.id}"
            f"&from={day.isoformat()}&to={day.isoformat()}").data
        self.assertEqual(reg["rows"][0]["dpr_ref"], r.data["ref"])
        self.assertFalse(reg["rows"][0]["gap"])


class ProjectPmRoutingTests(ProjectBase):
    def test_project_pm_approves_project_documents(self):
        # a second PM handles POOLS17 specifically (not the site PM)
        project_pm = make_user("pm2", User.Role.PM, site=self.site)
        stranger_pm = make_user("pm3", User.Role.PM, site=self.site)
        self.client.force_authenticate(self.pm)
        r = self.client.patch(f"/api/v1/projects/{self.pools.id}",
                              {"pm": project_pm.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["pm_name"], project_pm.full_name)

        # an IR under the project
        self.client.force_authenticate(self.se)
        ir = self.client.post("/api/v1/documents", {
            "doc_type": "IR", "site_id": self.site.id,
            "project_id": self.pools.id,
            "payload": {"discipline": "Civil",
                        "work_description": "Footing rebar"},
        }, format="json").data
        self.client.post(f"/api/v1/documents/{ir['ref']}/actions/submit")

        # unrelated PM: refused; project PM: approves
        self.client.force_authenticate(stranger_pm)
        r = self.client.post(f"/api/v1/documents/{ir['ref']}/actions/approve")
        self.assertEqual(r.status_code, 403)
        self.client.force_authenticate(project_pm)
        r = self.client.post(f"/api/v1/documents/{ir['ref']}/actions/approve")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "PM_APPROVED")

    def test_site_pm_remains_fallback(self):
        self.client.force_authenticate(self.se)
        ir = self.client.post("/api/v1/documents", {
            "doc_type": "IR", "site_id": self.site.id,
            "project_id": self.pools.id,
            "payload": {"discipline": "Civil", "work_description": "x"},
        }, format="json").data
        self.client.post(f"/api/v1/documents/{ir['ref']}/actions/submit")
        self.client.force_authenticate(self.pm)  # site PM, no project PM set
        r = self.client.post(f"/api/v1/documents/{ir['ref']}/actions/approve")
        self.assertEqual(r.status_code, 200)


class ProjectWorkspaceTests(ProjectBase):
    """Phase A — the project page's Documents tab."""

    def test_project_documents_split(self):
        # an IR belongs to the project directly
        ir = self.client.post("/api/v1/documents", {
            "doc_type": "IR", "site_id": self.site.id,
            "project_id": self.pools.id,
            "payload": {"discipline": "Civil", "work_description": "x"},
        }, format="json").data
        # a site-wide DPR carries one row tagged to POOLS17, one General
        day = last_working_days(self.site, 1)[0]
        dpr = self.make_dpr(None, doc_date=day, work_done=[
            {"activity": "Footing", "project": "POOLS17",
             "progress_today": 10},
            {"activity": "Cleanup", "project": ""},
        ]).data
        r = self.client.get(f"/api/v1/projects/{self.pools.id}/documents")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([d["ref"] for d in r.data["project_docs"]],
                         [ir["ref"]])
        self.assertEqual([d["ref"] for d in r.data["daily_docs"]],
                         [dpr["ref"]])
        self.assertIn("1 row(s) for POOLS17",
                      r.data["daily_docs"][0]["detail"])
        # the OTHER project sees no daily rows
        r = self.client.get(f"/api/v1/projects/{self.spa.id}/documents")
        self.assertEqual(r.data["daily_docs"], [])

    def test_activity_predecessors_roundtrip(self):
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/projects/{self.pools.id}/programme", {
            "activities": [{"name": "Excavation", "duration_days": 3},
                           {"name": "Blinding", "duration_days": 1}],
        }, format="json")
        a, b = list(self.pools.activities.all())
        r = self.client.patch(f"/api/v1/programme-activities/{b.id}",
                              {"predecessors": str(a.id)}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["predecessors"], str(a.id))
