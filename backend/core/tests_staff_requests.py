"""Asking for an advance, or for leave.

A request layer in front of machinery that already exists: an advance ends as
the same HR-origin PYR HR raises today, and leave ends in core.leave.grant.
What is new is the ask and the Director's decision (owner 2026-08-30).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Document, Employee, EmployeeSiteAllocation,
                     ManpowerCategory, Site, StaffRequest, User, WorkerLeave)
from .tests import make_user


class StaffRequestTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="REQ", name="Req site",
                                        status=Site.Status.ACTIVE)
        self.ho = Site.objects.create(code="MLE", name="Head Office",
                                      status=Site.Status.ACTIVE,
                                      is_head_office=True)
        self.staff_cat = ManpowerCategory.objects.create(
            name="Supervisor", list_type="DPR", grp="STAFF", sort_order=1)
        self.labour_cat = ManpowerCategory.objects.create(
            name="Mason", list_type="DPR", grp="LABOUR", sort_order=2)

        self.staff = self._emp("EMP-R01", self.staff_cat)
        self.worker = self._emp("EMP-R02", self.labour_cat)

        self.me = make_user("req_staff", User.Role.SITE_ENGINEER,
                            site=self.site)
        self.me.employee = self.staff
        self.me.save(update_fields=["employee"])
        self.labourer = make_user("req_worker", User.Role.SITE_ADMIN,
                                  site=self.site)
        self.labourer.employee = self.worker
        self.labourer.save(update_fields=["employee"])

        self.pd = make_user("req_pd", User.Role.DIRECTOR)
        self.hr = make_user("req_hr", User.Role.HO_HR)
        self.fin = make_user("req_fin", User.Role.FINANCE)
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def _emp(self, no, cat):
        e = Employee.objects.create(
            emp_no=no, full_name=f"Person {no}", basic_pay=Decimal("10000"),
            currency="MVR", job_category=cat, employment_type="PERMANENT",
            engagement_type="DIRECT", join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(employee=e, site=self.site,
                                              from_date=date(2026, 1, 1))
        return e

    def _post(self, body):
        return self.client.post("/api/v1/me/requests", body, format="json")

    def _future(self, days=10):
        return (timezone.localdate() + timedelta(days=days)).isoformat()

    # ---- raising ---------------------------------------------------------

    def test_i_can_ask_for_an_advance(self):
        r = self._post({"kind": "ADVANCE", "amount": "3000",
                        "reason": "Family medical"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")
        self.assertEqual(r.data["amount"], Decimal("3000.00"))

    def test_an_advance_cannot_exceed_a_month_of_pay(self):
        """It is recovered from the next salary in one go, so a bigger
        advance would leave nothing to live on."""
        r = self._post({"kind": "ADVANCE", "amount": "15000",
                        "reason": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("monthly pay", r.data["detail"])

    def test_an_advance_needs_a_reason(self):
        r = self._post({"kind": "ADVANCE", "amount": "500"})
        self.assertEqual(r.status_code, 400)

    def test_staff_can_ask_for_leave(self):
        r = self._post({"kind": "LEAVE_ANNUAL", "from_date": self._future(10),
                        "to_date": self._future(20), "reason": "Home"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["days"], 11)

    def test_a_worker_cannot_ask_for_leave(self):
        """The leave system is for staff — 33 people, not 555
        (owner 2026-08-30)."""
        self.client.force_authenticate(self.labourer)
        r = self._post({"kind": "LEAVE_ANNUAL", "from_date": self._future(10),
                        "to_date": self._future(12)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("staff", r.data["detail"])

    def test_a_worker_can_still_ask_for_an_advance(self):
        """Only leave is restricted."""
        self.client.force_authenticate(self.labourer)
        r = self._post({"kind": "ADVANCE", "amount": "1000", "reason": "x"})
        self.assertEqual(r.status_code, 201, r.data)

    def test_annual_leave_must_be_planned_ahead(self):
        r = self._post({"kind": "LEAVE_ANNUAL",
                        "from_date": timezone.localdate().isoformat(),
                        "to_date": self._future(3)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("emergency", r.data["detail"])

    def test_emergency_leave_can_start_today(self):
        r = self._post({"kind": "LEAVE_EMERGENCY",
                        "from_date": timezone.localdate().isoformat(),
                        "to_date": self._future(3), "reason": "Bereavement"})
        self.assertEqual(r.status_code, 201, r.data)

    def test_overlapping_leave_requests_are_refused(self):
        self._post({"kind": "LEAVE_ANNUAL", "from_date": self._future(10),
                    "to_date": self._future(20)})
        r = self._post({"kind": "LEAVE_ANNUAL", "from_date": self._future(15),
                        "to_date": self._future(25)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("already have a leave request", r.data["detail"])

    def test_an_unlinked_login_cannot_ask(self):
        stranger = make_user("nolink", User.Role.SITE_ENGINEER,
                             site=self.site)
        self.client.force_authenticate(stranger)
        r = self._post({"kind": "ADVANCE", "amount": "100", "reason": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("linked", r.data["detail"])

    # ---- the Director ----------------------------------------------------

    def _raise_advance(self):
        return StaffRequest.objects.get(
            pk=self._post({"kind": "ADVANCE", "amount": "3000",
                           "reason": "Medical"}).data["id"])

    def test_only_the_director_decides(self):
        req = self._raise_advance()
        for who in (self.hr, self.fin, self.me):
            self.client.force_authenticate(who)
            r = self.client.post(
                f"/api/v1/staff-requests/{req.id}/decide",
                {"approve": True}, format="json")
            self.assertEqual(r.status_code, 400, who.role)

    def test_the_director_approves(self):
        req = self._raise_advance()
        self.client.force_authenticate(self.pd)
        r = self.client.post(f"/api/v1/staff-requests/{req.id}/decide",
                             {"approve": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "APPROVED")

    def test_declining_needs_a_reason(self):
        req = self._raise_advance()
        self.client.force_authenticate(self.pd)
        r = self.client.post(f"/api/v1/staff-requests/{req.id}/decide",
                             {"approve": False}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/staff-requests/{req.id}/decide",
                             {"approve": False, "note": "Too soon after the "
                                                        "last one"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "DECLINED")

    def test_i_can_withdraw_my_own_request_before_it_is_decided(self):
        req = self._raise_advance()
        r = self.client.post(f"/api/v1/staff-requests/{req.id}/cancel")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "CANCELLED")

    def test_i_cannot_withdraw_it_after_approval(self):
        req = self._raise_advance()
        self.client.force_authenticate(self.pd)
        self.client.post(f"/api/v1/staff-requests/{req.id}/decide",
                         {"approve": True}, format="json")
        self.client.force_authenticate(self.me)
        r = self.client.post(f"/api/v1/staff-requests/{req.id}/cancel")
        self.assertEqual(r.status_code, 400)

    # ---- hand-off --------------------------------------------------------

    def _approved_leave(self):
        rid = self._post({"kind": "LEAVE_ANNUAL",
                          "from_date": self._future(10),
                          "to_date": self._future(14),
                          "reason": "Home"}).data["id"]
        self.client.force_authenticate(self.pd)
        self.client.post(f"/api/v1/staff-requests/{rid}/decide",
                         {"approve": True}, format="json")
        return StaffRequest.objects.get(pk=rid)

    def test_hr_grants_the_approved_leave_and_it_becomes_real_leave(self):
        req = self._approved_leave()
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/staff-requests/{req.id}/grant-leave",
                             {"kind": "PAID"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "DONE")
        req.refresh_from_db()
        lv = WorkerLeave.objects.get(pk=req.worker_leave_id)
        self.assertEqual(lv.employee, self.staff)
        self.assertEqual(lv.kind, "PAID")
        # ...and the existing machinery moved him to Head Office.
        self.assertTrue(EmployeeSiteAllocation.objects.filter(
            employee=self.staff, site=self.ho).exists())

    def test_leave_cannot_be_granted_before_the_director_approves(self):
        rid = self._post({"kind": "LEAVE_ANNUAL",
                          "from_date": self._future(10),
                          "to_date": self._future(14)}).data["id"]
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/staff-requests/{rid}/grant-leave",
                             {"kind": "PAID"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Director", r.data["detail"])

    def test_paid_or_unpaid_is_hrs_call_not_the_requesters(self):
        """The one decision that changes what payroll does."""
        req = self._approved_leave()
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/staff-requests/{req.id}/grant-leave",
                             {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("paid", r.data["detail"].lower())

    def test_finance_ties_the_pyr_back_to_the_advance(self):
        req = self._raise_advance()
        self.client.force_authenticate(self.pd)
        self.client.post(f"/api/v1/staff-requests/{req.id}/decide",
                         {"approve": True}, format="json")
        Document.objects.create(doc_type="PYR", ref="PYR-REQ-001",
                                site=self.site, status="SUBMITTED",
                                doc_date=date.today(), created_by=self.fin)
        self.client.force_authenticate(self.fin)
        r = self.client.post(
            f"/api/v1/staff-requests/{req.id}/link-payment",
            {"ref": "PYR-REQ-001"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "DONE")
        self.assertEqual(r.data["pyr_ref"], "PYR-REQ-001")

    # ---- queues ----------------------------------------------------------

    def test_each_role_sees_only_what_it_must_act_on(self):
        adv = self._raise_advance()
        lv = self._approved_leave()          # leaves PD authenticated
        self.client.force_authenticate(self.pd)
        self.assertEqual(
            [x["id"] for x in
             self.client.get("/api/v1/staff-requests/queue").data],
            [adv.id])
        self.client.force_authenticate(self.hr)
        self.assertEqual(
            [x["id"] for x in
             self.client.get("/api/v1/staff-requests/queue").data],
            [lv.id])
        self.client.force_authenticate(self.fin)
        self.assertEqual(
            self.client.get("/api/v1/staff-requests/queue").data, [])


class HeadOfficeStaffTests(TestCase):
    """Head Office is the app's own marker for staff who are not on a site.

    The STAFF manpower categories are site-shaped — engineer, foreman,
    supervisor — with nothing for a Signatory, HR or Finance. Inventing those
    categories would put head-office roles into the DPR and TWS manpower
    pickers, so being allocated to Head Office is the second way to be staff
    (owner 2026-08-30).
    """

    def setUp(self):
        self.ho = Site.objects.create(code="MLE", name="Head Office",
                                      status=Site.Status.ACTIVE,
                                      is_head_office=True)
        self.site = Site.objects.create(code="SIT", name="A site",
                                        status=Site.Status.ACTIVE)
        self.labour_cat = ManpowerCategory.objects.create(
            name="Skilled Labour", list_type="DPR", grp="LABOUR",
            sort_order=1)
        self.client = APIClient()

    def _person(self, no, site, cat=None):
        e = Employee.objects.create(
            emp_no=no, full_name=f"P {no}", basic_pay=Decimal("9000"),
            currency="MVR", job_category=cat, employment_type="PERMANENT",
            engagement_type="DIRECT", join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(employee=e, site=site,
                                              from_date=date(2026, 1, 1))
        u = make_user(f"u{no.lower().replace('-', '')}", User.Role.HO_HR)
        u.employee = e
        u.save(update_fields=["employee"])
        return u

    def _ask(self, user):
        self.client.force_authenticate(user)
        return self.client.post("/api/v1/me/requests", {
            "kind": "LEAVE_ANNUAL",
            "from_date": (timezone.localdate() + timedelta(days=10))
            .isoformat(),
            "to_date": (timezone.localdate() + timedelta(days=14))
            .isoformat()}, format="json")

    def test_head_office_with_no_category_counts_as_staff(self):
        u = self._person("EMP-H01", self.ho)
        self.assertEqual(self._ask(u).status_code, 201)

    def test_head_office_with_a_labour_category_still_counts(self):
        """Finance and Purchasing carry Skilled Labour on their records."""
        u = self._person("EMP-H02", self.ho, self.labour_cat)
        self.assertEqual(self._ask(u).status_code, 201)

    def test_a_labourer_on_a_site_still_cannot(self):
        u = self._person("EMP-H03", self.site, self.labour_cat)
        r = self._ask(u)
        self.assertEqual(r.status_code, 400)
        self.assertIn("staff", r.data["detail"])

    def test_a_site_person_with_no_category_still_cannot(self):
        """No category and not at Head Office says nothing either way, and
        guessing in favour would open leave to the whole workforce."""
        u = self._person("EMP-H04", self.site)
        self.assertEqual(self._ask(u).status_code, 400)
