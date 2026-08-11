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


class SubcontractAttendanceTests(TestCase):
    """Subcontract workers attend like the crew but take extra hours, not OT
    (subcontractor module — attendance form update)."""

    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        self.sub = Subcontractor.objects.create(
            site=self.site, name="Alif Gang",
            status=Subcontractor.Status.APPROVED)
        self.direct = Employee.objects.create(
            emp_no="EMP-0001", full_name="Direct", job_category=self.mason,
            is_active=True)
        self.subw = Employee.objects.create(
            emp_no="EMP-0002", full_name="SubW", job_category=self.mason,
            engagement_type="SUBCONTRACT", subcontractor=self.sub,
            is_active=True)
        for e in (self.direct, self.subw):
            EmployeeSiteAllocation.objects.create(
                employee=e, site=self.site, from_date=date(2026, 1, 1))
        self.client = APIClient()
        self.client.force_authenticate(self.sa)
        self.today = date.today().isoformat()

    def test_grid_flags_subcontract_rows(self):
        r = self.client.get(f"/api/v1/attendance?site={self.site.id}"
                            f"&date={self.today}")
        rows = {row["emp_no"]: row for row in r.data["rows"]}
        self.assertFalse(rows["EMP-0001"]["is_subcontract"])
        self.assertTrue(rows["EMP-0002"]["is_subcontract"])
        self.assertEqual(rows["EMP-0002"]["subcontractor"], "Alif Gang")
        self.assertIn("sub_extra_hours", rows["EMP-0002"])

    def test_bulk_routes_extra_hours_and_bypasses_ot(self):
        from .models import Attendance
        payload = {"site": self.site.id, "date": self.today, "rows": [
            {"employee_id": self.direct.id, "remark": "PRESENT",
             "check_in": "07:00", "check_out": "17:00", "ot_requested": "3"},
            {"employee_id": self.subw.id, "remark": "PRESENT",
             "check_in": "07:00", "check_out": "17:00",
             "ot_requested": "3", "sub_extra_hours": "2.5"},
        ]}
        r = self.client.put("/api/v1/attendance/bulk", payload, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        d = Attendance.objects.get(employee=self.direct, day=date.today())
        s = Attendance.objects.get(employee=self.subw, day=date.today())
        # direct: OT recorded, awaiting approval; no extra hours
        self.assertEqual(d.ot_requested, Decimal("3"))
        self.assertEqual(d.sub_extra_hours, Decimal("0"))
        # subcontract: extra hours recorded, OT forced clear (even though the
        # client sent ot_requested)
        self.assertEqual(s.sub_extra_hours, Decimal("2.5"))
        self.assertEqual(s.ot_requested, Decimal("0"))
        self.assertIsNone(s.ot_approved)


class SubcontractAgreementTermsTests(TestCase):
    """SCA commercial terms + the Subcontract Agreement PDF (owner template)."""

    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm", User.Role.PM, site=self.site)
        self.client = APIClient()

    def _approved_sub(self):
        return Subcontractor.objects.create(
            site=self.site, name="Alif Gang", address="Hulhumale",
            signatory_name="Ali Rasheed", signatory_title="Managing Director",
            status=Subcontractor.Status.APPROVED)

    def _make_sca(self, **terms):
        sub = self._approved_sub()
        self.client.force_authenticate(self.sa)
        body = {"title": "Blockwork package",
                "rows": [{"description": "Blockwork", "unit": "m2",
                          "qty": "100", "rate": "150"}]}
        body.update(terms)
        r = self.client.post(f"/api/v1/subcontractors/{sub.id}/agreements",
                             body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r

    def test_terms_persist_and_serialize(self):
        r = self._make_sca(
            currency="MVR", advance_percent="10", retention_percent="5",
            payment_days="14", ld_amount="500", ld_cap_percent="10",
            scope_of_work="Blockwork to all villas.",
            contractor_signatory_name="S. Perera",
            contractor_signatory_title="Project Director")
        a = Document.objects.get(ref=r.data["ref"]).subcontract_agreement
        self.assertEqual(a.advance_percent, Decimal("10"))
        self.assertEqual(a.retention_percent, Decimal("5"))
        self.assertEqual(a.payment_days, 14)
        self.assertEqual(a.value, Decimal("15000"))
        self.assertEqual(a.scope_of_work, "Blockwork to all villas.")
        # the document payload (detail) carries the terms
        self.client.force_authenticate(self.pm)
        pl = self.client.get(
            f"/api/v1/documents/{r.data['ref']}").data["subcontract_agreement"]
        self.assertEqual(Decimal(str(pl["advance_percent"])), Decimal("10"))
        self.assertEqual(pl["contractor_signatory_name"], "S. Perera")

    def test_pdf_context_render_retention_conditional(self):
        from django.template.loader import render_to_string

        from . import subcontract
        # with retention → clause present
        r = self._make_sca(retention_percent="5", advance_percent="10",
                           scope_of_work="Blockwork narrative.")
        doc = Document.objects.get(ref=r.data["ref"])
        ctx = subcontract.sca_pdf_context(doc)
        self.assertTrue(ctx["show_retention"])
        html = render_to_string("pdf/subcontract_agreement.html", ctx)
        self.assertIn("Blockwork narrative.", html)
        self.assertIn("Retention.", html)
        # without retention → clause omitted
        r2 = self._make_sca(retention_percent="0")
        ctx2 = subcontract.sca_pdf_context(Document.objects.get(ref=r2.data["ref"]))
        self.assertFalse(ctx2["show_retention"])
        html2 = render_to_string("pdf/subcontract_agreement.html", ctx2)
        self.assertNotIn("Retention.", html2)

    def test_pdf_endpoint_gated_to_pm_plus(self):
        ref = self._make_sca().data["ref"]
        self.client.force_authenticate(self.sa)        # rate-bearing → blocked
        self.assertEqual(self.client.get(
            f"/api/v1/subcontract-agreements/{ref}/pdf").status_code, 403)
        self.client.force_authenticate(self.pm)         # PM may download
        self.assertEqual(self.client.get(
            f"/api/v1/subcontract-agreements/{ref}/pdf").status_code, 200)


class SubcontractValuationTests(TestCase):
    """SVC valuation engine — math, chaining, guards (Phase 4)."""

    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)

    def _approved_sca(self, advance="10", retention="5"):
        from . import subcontract
        sub = Subcontractor.objects.create(
            site=self.site, name="Alif Gang",
            status=Subcontractor.Status.APPROVED)
        doc, err = subcontract.create_sca(sub, {
            "title": "Blockwork", "advance_percent": advance,
            "retention_percent": retention, "rows": [
                {"item_code": "1", "description": "Blockwork", "unit": "m2",
                 "qty": "100", "rate": "150"},
                {"item_code": "2", "description": "Plaster", "unit": "m2",
                 "qty": "200", "rate": "50"}]}, self.sa)
        assert err is None, err
        doc.status = "APPROVED"
        doc.save(update_fields=["status"])
        return doc.subcontract_agreement

    def _set(self, v, code, qty):
        from . import subcontract
        it = v.items.get(scope_item__item_code=code)
        return subcontract.value_svc(
            v, {"rows": [{"id": it.id, "cumulative_qty": qty}]}, self.sa)

    def test_valuation_math(self):
        from . import subcontract
        a = self._approved_sca()
        doc, err = subcontract.create_svc(a, self.sa)
        self.assertIsNone(err, err)
        v = doc.subcontract_valuation
        rows = [{"id": it.id,
                 "cumulative_qty": "40" if it.scope_item.item_code == "1"
                 else "100"} for it in v.items.all()]
        subcontract.value_svc(v, {"rows": rows}, self.sa)
        val = subcontract.svc_valuation(v)
        # gross = 40×150 + 100×50 = 11,000
        self.assertEqual(val["gross_cumulative"], Decimal("11000"))
        # advance 10% of gross = 1,100 (cap = 10% of contract 25,000 = 2,500)
        self.assertEqual(val["advance_recovered"], Decimal("1100"))
        self.assertEqual(val["retention_held"], Decimal("550"))   # 5% of gross
        self.assertEqual(val["net_cumulative"], Decimal("9350"))
        self.assertEqual(val["now_due"], Decimal("9350"))         # first SVC

    def test_second_valuation_chains_and_floors(self):
        from . import subcontract
        a = self._approved_sca()
        v1 = subcontract.create_svc(a, self.sa)[0].subcontract_valuation
        self._set(v1, "1", "40")
        v1.document.status = "AUTHORISED"
        v1.document.save(update_fields=["status"])
        doc2, err = subcontract.create_svc(a, self.sa)
        self.assertIsNone(err, err)
        v2 = doc2.subcontract_valuation
        it1 = v2.items.get(scope_item__item_code="1")
        self.assertEqual(it1.cumulative_qty, Decimal("40"))       # carried
        # this-period only pays the delta
        self._set(v2, "1", "70")
        val = subcontract.svc_valuation(v2)
        self.assertEqual(val["this_gross"], Decimal("30") * Decimal("150"))
        # can't fall below the previously certified
        _, e = self._set(v2, "1", "20")
        self.assertIsNotNone(e)

    def test_one_in_flight_per_sca(self):
        from . import subcontract
        a = self._approved_sca()
        subcontract.create_svc(a, self.sa)
        d2, err = subcontract.create_svc(a, self.sa)
        self.assertIsNone(d2)
        self.assertIn("in progress", err)

    def test_svc_requires_approved_agreement(self):
        from . import subcontract
        sub = Subcontractor.objects.create(
            site=self.site, name="G", status=Subcontractor.Status.APPROVED)
        doc, _ = subcontract.create_sca(sub, {"title": "X", "rows": [
            {"description": "a", "qty": "1", "rate": "1"}]}, self.sa)
        d2, err = subcontract.create_svc(doc.subcontract_agreement, self.sa)
        self.assertIsNone(d2)
        self.assertIn("approved", err.lower())

    def test_workflow_and_cost_commit(self):
        from . import subcontract
        from .models import CostPosting
        pm = make_user("pm_svc", User.Role.PM, site=self.site)
        director = make_user("dir_svc", User.Role.DIRECTOR)
        signatory = make_user("sig_svc", User.Role.SIGNATORY)
        a = self._approved_sca()
        v = subcontract.create_svc(a, self.sa)[0].subcontract_valuation
        self._set(v, "1", "40")
        self._set(v, "2", "100")           # gross = 40×150 + 100×50 = 11,000
        self.assertIsNone(subcontract.svc_action(v, "submit", self.sa))
        # wrong stage / wrong role are blocked
        self.assertIsNotNone(subcontract.svc_action(v, "authorise", signatory))
        self.assertIsNone(subcontract.svc_action(v, "verify", pm))
        self.assertIsNotNone(subcontract.svc_action(v, "approve", self.sa))
        self.assertIsNone(subcontract.svc_action(v, "approve", director))
        self.assertIsNone(subcontract.svc_action(v, "authorise", signatory))
        v.document.refresh_from_db()
        self.assertEqual(v.document.status, "AUTHORISED")
        # this-period gross committed under the Subcontract head
        posts = CostPosting.objects.filter(
            document=v.document, state="COMMITTED", source="SUBCONTRACT")
        self.assertEqual(posts.count(), 1)
        self.assertEqual(posts.first().amount, Decimal("11000.00"))
        self.assertEqual(posts.first().cost_head.name, "Subcontract")

    def test_authorise_creates_payable_then_settle_pays(self):
        from . import subcontract, vouchers
        from .models import CostPosting, Payable
        pm = make_user("pm_p", User.Role.PM, site=self.site)
        director = make_user("dir_p", User.Role.DIRECTOR)
        signatory = make_user("sig_p", User.Role.SIGNATORY)
        finance = make_user("fin_p", User.Role.FINANCE)
        a = self._approved_sca()
        v = subcontract.create_svc(a, self.sa)[0].subcontract_valuation
        self._set(v, "1", "40")
        self._set(v, "2", "100")     # gross 11,000 → now_due 9,350
        for step, who in (("submit", self.sa), ("verify", pm),
                          ("approve", director), ("authorise", signatory)):
            self.assertIsNone(subcontract.svc_action(v, step, who), step)
        p = Payable.objects.get(document=v.document)
        self.assertEqual(p.amount, Decimal("9350.00"))
        self.assertEqual(p.status, "OUTSTANDING")
        self.assertEqual(p.vendor, "Alif Gang")
        self.assertIn(p.id, [x.id for x in vouchers.awaiting_payables()])
        # INCURRED cost = work value (gross); PAID = cash (net)
        self.assertEqual(
            CostPosting.objects.filter(document=v.document, state="INCURRED",
                                       source="SUBCONTRACT").first().amount,
            Decimal("11000.00"))
        # Finance settles it → SVC paid + PAID leg
        self.assertIsNone(vouchers.settle_payable(p, finance, "PV-1"))
        p.refresh_from_db()
        v.document.refresh_from_db()
        self.assertEqual(p.status, "SETTLED")
        self.assertEqual(v.document.status, "PAID")
        paid = CostPosting.objects.filter(document=v.document, state="PAID",
                                          source="SUBCONTRACT")
        self.assertEqual(paid.count(), 1)
        self.assertEqual(paid.first().amount, Decimal("9350.00"))

    def test_svc_in_approval_queues(self):
        from . import subcontract
        from .views_documents import pending_groups
        from .views_mobile import APPROVABLE
        pm = make_user("pm_q", User.Role.PM, site=self.site)
        director = make_user("dir_q", User.Role.DIRECTOR)
        signatory = make_user("sig_q", User.Role.SIGNATORY)
        a = self._approved_sca()
        v = subcontract.create_svc(a, self.sa)[0].subcontract_valuation
        self._set(v, "1", "40")
        ref = v.document.ref

        def refs(u):
            return [it["ref"] for g in pending_groups(u) for it in g["items"]]

        subcontract.svc_action(v, "submit", self.sa)
        self.assertIn(ref, refs(pm))                       # PM verifies
        self.assertIn(("SVC", "SUBMITTED"), APPROVABLE)
        subcontract.svc_action(v, "verify", pm)
        self.assertIn(ref, refs(director))                  # Director approves
        subcontract.svc_action(v, "approve", director)
        self.assertIn(ref, refs(signatory))                 # Signatory authorises
        self.assertIn(("SVC", "DIRECTOR_APPROVED"), APPROVABLE)

    def test_certificate_pdf_context_and_template(self):
        """The certificate renders the measured works, the certification
        waterfall and the digital approval trail; PROVISIONAL is stamped
        until the signatory authorises."""
        from django.template.loader import render_to_string

        from . import subcontract
        pm = make_user("pm_pdf", User.Role.PM, site=self.site)
        director = make_user("dir_pdf", User.Role.DIRECTOR)
        signatory = make_user("sig_pdf", User.Role.SIGNATORY)
        a = self._approved_sca()
        v = subcontract.create_svc(a, self.sa)[0].subcontract_valuation
        self._set(v, "1", "40")
        self._set(v, "2", "100")           # gross 11,000 / net 9,350
        subcontract.svc_action(v, "submit", self.sa)
        html = render_to_string("pdf/svc_certificate.html",
                                subcontract.svc_pdf_context(v.document))
        self.assertIn("PROVISIONAL", html)          # not yet authorised
        self.assertIn(v.document.ref, html)
        self.assertIn("11,000.00", html)            # gross, currency-formatted
        subcontract.svc_action(v, "verify", pm)
        subcontract.svc_action(v, "approve", director)
        subcontract.svc_action(v, "authorise", signatory)
        html = render_to_string("pdf/svc_certificate.html",
                                subcontract.svc_pdf_context(v.document))
        self.assertNotIn("PROVISIONAL", html)
        self.assertIn("9,350.00", html)             # amount now payable
        for u in (self.sa, pm, director, signatory):
            self.assertIn(u.full_name, html)        # digital signature blocks

    def test_certificate_endpoint_blocks_draft_and_site_roles(self):
        from . import subcontract
        a = self._approved_sca()
        v = subcontract.create_svc(a, self.sa)[0].subcontract_valuation
        self._set(v, "1", "40")
        url = f"/api/v1/subcontract-valuations/{v.document.ref}/certificate.pdf"
        pm = make_user("pm_cert", User.Role.PM, site=self.site)
        self.client.force_login(pm)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 400)         # draft — not printable
        subcontract.svc_action(v, "submit", self.sa)
        self.client.force_login(self.sa)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 403)         # rates: PM and above


class ReopenClosedSubcontractorTests(TestCase):
    """Re-opening a CLOSED subcontractor group is an admin-level correction
    (owner 2026-08-11); a PM can still reactivate a SUSPENDED one."""

    def setUp(self):
        from .tests import make_user
        self.site = Site.objects.create(code="RSC", name="Reopen Isle",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("rsc_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.admin = make_user("rsc_adm", User.Role.ADMIN)
        self.sub = Subcontractor.objects.create(
            site=self.site, name="Mistakenly Closed Team",
            status=Subcontractor.Status.CLOSED, created_by=self.pm)
        self.client = APIClient()

    def _act(self, user, action):
        self.client.force_authenticate(user)
        return self.client.post(f"/api/v1/subcontractors/{self.sub.id}/action",
                                {"action": action}, format="json")

    def test_pm_cannot_reopen_closed(self):
        r = self._act(self.pm, "reactivate")
        self.assertEqual(r.status_code, 400)
        self.assertIn("administrator", r.data["detail"])

    def test_admin_reopens_closed_to_approved(self):
        r = self._act(self.admin, "reactivate")
        self.assertEqual(r.status_code, 200, r.data)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subcontractor.Status.APPROVED)

    def test_pm_still_reactivates_suspended(self):
        self.sub.status = Subcontractor.Status.SUSPENDED
        self.sub.save(update_fields=["status"])
        r = self._act(self.pm, "reactivate")
        self.assertEqual(r.status_code, 200, r.data)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subcontractor.Status.APPROVED)
