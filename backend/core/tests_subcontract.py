"""Subcontractor module Phase 2 — site team management, attendance/DPR
inclusion, and the client-facing render guard (acceptance #1, #3, #8)."""
import json
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Document, Employee, EmployeeSiteAllocation,
                     ManpowerCategory, Site, SitePmHistory, Subcontractor, User)
from .tests import make_user
from .views_hr import site_manpower_data


class SubcontractorTeamTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="HDH", name="Other",
                                         status=Site.Status.ACTIVE)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm", User.Role.PM, site=self.site)
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.client = APIClient()

    def _auth(self, u):
        self.client.force_authenticate(u)

    def _approved_sub(self):
        sub = Subcontractor.objects.create(
            site=self.site, name="Alif Gang",
            status=Subcontractor.Status.APPROVED)
        return sub

    def _roster_total(self, site):
        return site_manpower_data(site, date.today())["roster_total"]

    # ---- acceptance #3: approval gates -------------------------------------

    def test_lifecycle_pm_then_director(self):
        self._auth(self.sa)
        r = self.client.post("/api/v1/subcontractors",
                             {"site_id": self.site.id, "name": "Alif Gang"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        sid = r.data["id"]
        self.assertEqual(r.data["status"], "DRAFT")
        self.assertFalse(r.data["can_raise_sca"])

        # unusable until approved — no workers yet
        r = self.client.post(f"/api/v1/subcontractors/{sid}/workers",
                             {"full_name": "Worker A"}, format="json")
        self.assertEqual(r.status_code, 400)

        # SA cannot self-approve
        r = self.client.post(f"/api/v1/subcontractors/{sid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)

        self._auth(self.pm)
        r = self.client.post(f"/api/v1/subcontractors/{sid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "PM_APPROVED")

        # PM cannot also do the Director step
        r = self.client.post(f"/api/v1/subcontractors/{sid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)

        self._auth(self.director)
        r = self.client.post(f"/api/v1/subcontractors/{sid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        self.assertTrue(r.data["can_raise_sca"])

    def test_worker_pending_until_pm_approval(self):
        sub = self._approved_sub()
        self.assertEqual(self._roster_total(self.site), 0)

        self._auth(self.sa)
        r = self.client.post(f"/api/v1/subcontractors/{sub.id}/workers",
                             {"full_name": "Worker A",
                              "job_category_id": self.mason.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        wid = r.data["id"]
        self.assertEqual(r.data["state"], "PENDING")
        # pending worker is inactive → out of every roster / manpower count
        self.assertFalse(Employee.objects.get(pk=wid).is_active)
        self.assertEqual(self._roster_total(self.site), 0)

        # PM approval activates → now counted (acceptance #1 inclusion)
        self._auth(self.pm)
        r = self.client.post(f"/api/v1/subcontract-workers/{wid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["state"], "ACTIVE")
        self.assertEqual(self._roster_total(self.site), 1)

        # removal is immediate
        self._auth(self.sa)
        r = self.client.post(f"/api/v1/subcontract-workers/{wid}/action",
                             {"action": "remove"}, format="json")
        self.assertEqual(r.data["state"], "REMOVED")
        self.assertEqual(self._roster_total(self.site), 0)

    def test_sa_cannot_approve_worker(self):
        sub = self._approved_sub()
        emp = Employee.objects.create(
            emp_no="EMP-9001", full_name="W", job_category=self.mason,
            engagement_type="SUBCONTRACT", subcontractor=sub,
            is_active=False, sub_pending=True)
        self._auth(self.sa)
        r = self.client.post(f"/api/v1/subcontract-workers/{emp.id}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 403)

    # ---- scoping ------------------------------------------------------------

    def test_sa_scoped_to_own_site(self):
        # a subcontractor at another site
        other_sub = Subcontractor.objects.create(
            site=self.other, name="Other Gang",
            status=Subcontractor.Status.APPROVED)
        self._auth(self.sa)
        # not in the SA's visible register
        r = self.client.get("/api/v1/subcontractors")
        self.assertNotIn(other_sub.id, [s["id"] for s in r.data])
        # cannot create for a site they aren't on
        r = self.client.post("/api/v1/subcontractors",
                             {"site_id": self.other.id, "name": "X"},
                             format="json")
        self.assertEqual(r.status_code, 403)
        # cannot open the other site's subcontractor
        r = self.client.get(f"/api/v1/subcontractors/{other_sub.id}")
        self.assertEqual(r.status_code, 404)

    # ---- acceptance #8: client-facing render guard --------------------------

    def test_client_facing_manpower_hides_engagement(self):
        """A mixed site's manpower payload is byte-identical in shape to an
        all-direct site's, and never carries an engagement/subcontractor key."""
        sub = self._approved_sub()
        # mixed site: 1 direct + 1 (approved) subcontract mason
        direct = Employee.objects.create(
            emp_no="EMP-1001", full_name="Direct", job_category=self.mason,
            is_active=True)
        subw = Employee.objects.create(
            emp_no="EMP-1002", full_name="Sub", job_category=self.mason,
            engagement_type="SUBCONTRACT", subcontractor=sub, is_active=True)
        for e in (direct, subw):
            EmployeeSiteAllocation.objects.create(
                employee=e, site=self.site, from_date=date(2026, 1, 1))
        # all-direct control site: 2 direct masons
        for i, n in enumerate(("A", "B")):
            e = Employee.objects.create(
                emp_no=f"EMP-200{i}", full_name=n, job_category=self.mason,
                is_active=True)
            EmployeeSiteAllocation.objects.create(
                employee=e, site=self.other, from_date=date(2026, 1, 1))

        mixed = site_manpower_data(self.site, date.today())
        control = site_manpower_data(self.other, date.today())

        # both count 2 in the workforce, undifferentiated
        self.assertEqual(mixed["roster_total"], 2)
        self.assertEqual(control["roster_total"], 2)
        # identical structure
        self.assertEqual(set(mixed), set(control))
        self.assertEqual(set(mixed["categories"][0]),
                         set(control["categories"][0]))
        # no classification leaks into the client-facing payload
        blob = json.dumps(mixed).lower()
        self.assertNotIn("engagement", blob)
        self.assertNotIn("subcontract", blob)

    def test_team_worker_stays_out_of_payroll(self):
        """A worker added through the team flow is a payroll stranger."""
        sub = self._approved_sub()
        self._auth(self.sa)
        r = self.client.post(f"/api/v1/subcontractors/{sub.id}/workers",
                             {"full_name": "Worker A"}, format="json")
        emp = Employee.objects.get(pk=r.data["id"])
        self.assertEqual(emp.engagement_type, "SUBCONTRACT")
        self.assertNotIn(emp.id, Employee.objects.payroll_eligible()
                         .values_list("id", flat=True))


class SubcontractAgreementTests(TestCase):
    """SCA lifecycle (subcontractor module Phase 3): create → submit → PM →
    Director, scope math, role gates, and doc-type visibility."""

    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.hr = make_user("hr", User.Role.HO_HR)
        self.sub = Subcontractor.objects.create(
            site=self.site, name="Alif Gang",
            status=Subcontractor.Status.APPROVED)
        self.client = APIClient()

    def _auth(self, u):
        self.client.force_authenticate(u)

    ROWS = [
        {"section": "Blockwork", "is_heading": True},
        {"description": "200mm block wall", "unit": "m2",
         "qty": "100", "rate": "150"},
        {"description": "Plaster", "unit": "m2", "qty": "100", "rate": "50"},
    ]

    def _create(self):
        self._auth(self.sa)
        r = self.client.post(f"/api/v1/subcontractors/{self.sub.id}/agreements",
                             {"title": "Blockwork package", "rows": self.ROWS},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["ref"]

    def test_create_computes_value_and_excludes_heading(self):
        ref = self._create()
        doc = Document.objects.get(ref=ref)
        # 100*150 + 100*50 = 20000; the heading row carries no money
        self.assertEqual(doc.subcontract_agreement.value, Decimal("20000"))
        self.assertEqual(doc.subcontract_agreement.items.count(), 3)

    def test_cannot_create_under_unapproved_subcontractor(self):
        self.sub.status = Subcontractor.Status.DRAFT
        self.sub.save()
        self._auth(self.sa)
        r = self.client.post(f"/api/v1/subcontractors/{self.sub.id}/agreements",
                             {"title": "X", "rows": self.ROWS}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_lifecycle_submit_pm_director(self):
        ref = self._create()
        # submit (SA)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")

        # the Director cannot do the PM step (SUBMITTED needs the site PM)
        self._auth(self.director)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                             format="json")
        self.assertEqual(r.status_code, 403)

        # site PM approves → PM_APPROVED
        self._auth(self.pm)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                             format="json")
        self.assertEqual(r.data["status"], "PM_APPROVED")

        # Director activates → APPROVED
        self._auth(self.director)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                             format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        self.assertEqual(Decimal(r.data["subcontract_agreement"]["value"]), Decimal("20000"))

    def test_submit_requires_scope(self):
        self._auth(self.sa)
        r = self.client.post(f"/api/v1/subcontractors/{self.sub.id}/agreements",
                             {"title": "Empty"}, format="json")
        ref = r.data["ref"]
        r = self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_edit_only_in_draft(self):
        ref = self._create()
        # edit scope while draft
        r = self.client.patch(f"/api/v1/subcontract-agreements/{ref}",
                              {"rows": [{"description": "One", "unit": "no",
                                         "qty": "1", "rate": "10"}]},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(r.data["subcontract_agreement"]["value"]), Decimal("10"))
        # submit, then editing is blocked
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        r = self.client.patch(f"/api/v1/subcontract-agreements/{ref}",
                              {"title": "Nope"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_hr_cannot_view_sca(self):
        ref = self._create()
        self._auth(self.hr)
        r = self.client.get(f"/api/v1/documents/{ref}")
        self.assertEqual(r.status_code, 404)
