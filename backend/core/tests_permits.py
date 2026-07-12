"""Work-permit tracking: status, renewal (months → expiry), and HR alerts."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from . import permits
from .models import Employee, User, WorkPermitRenewal
from .tests import make_user


def emp(name, **kw):
    kw.setdefault("employment_type", Employee.EmploymentType.PERMANENT)
    return Employee.objects.create(emp_no=f"EMP-{name}", full_name=name, **kw)


class PermitStatusTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 12)

    def test_contract_worker_is_not_tracked(self):
        e = emp("C", employment_type=Employee.EmploymentType.CONTRACT,
                work_permit_expiry=self.today)
        state, days = permits.permit_status(e, self.today)
        self.assertEqual(state, "NA")
        self.assertIsNone(days)

    def test_permanent_without_expiry_is_na(self):
        e = emp("P")
        self.assertEqual(permits.permit_status(e, self.today)[0], "NA")

    def test_ok_expiring_expired_thresholds(self):
        ok = emp("OK", work_permit_expiry=self.today + timedelta(days=90))
        soon = emp("SOON", work_permit_expiry=self.today + timedelta(days=20))
        gone = emp("GONE", work_permit_expiry=self.today - timedelta(days=1))
        self.assertEqual(permits.permit_status(ok, self.today)[0], "OK")
        self.assertEqual(permits.permit_status(soon, self.today)[0], "EXPIRING")
        self.assertEqual(permits.permit_status(gone, self.today)[0], "EXPIRED")

    def test_add_months_clamps_day(self):
        self.assertEqual(permits.add_months(date(2026, 1, 31), 1),
                         date(2026, 2, 28))
        self.assertEqual(permits.add_months(date(2026, 12, 15), 2),
                         date(2027, 2, 15))


class PermitRenewTests(TestCase):
    def setUp(self):
        self.hr = make_user("hr", User.Role.HO_HR)

    def test_renew_extends_from_current_expiry(self):
        e = emp("R", work_permit_expiry=date(2026, 8, 1))
        permits.renew(e, 12, "WP-999", "PYR-HO-014", self.hr,
                      today=date(2026, 7, 12))
        e.refresh_from_db()
        self.assertEqual(e.work_permit_expiry, date(2027, 8, 1))
        self.assertEqual(e.work_permit_no, "WP-999")
        row = WorkPermitRenewal.objects.get(employee=e)
        self.assertEqual(row.months, 12)
        self.assertEqual(row.previous_expiry, date(2026, 8, 1))

    def test_renew_without_prior_expiry_uses_today(self):
        e = emp("N")
        permits.renew(e, 6, "", "", self.hr, today=date(2026, 7, 12))
        e.refresh_from_db()
        self.assertEqual(e.work_permit_expiry, date(2027, 1, 12))

    def test_renew_flips_contract_to_permanent(self):
        e = emp("F", employment_type=Employee.EmploymentType.CONTRACT)
        permits.renew(e, 3, "", "", self.hr, today=date(2026, 7, 12))
        e.refresh_from_db()
        self.assertEqual(e.employment_type, "PERMANENT")

    def test_zero_months_rejected(self):
        e = emp("Z", work_permit_expiry=date(2026, 8, 1))
        with self.assertRaises(ValueError):
            permits.renew(e, 0, "", "", self.hr)


class PermitApiTests(TestCase):
    def setUp(self):
        self.hr = make_user("hr", User.Role.HO_HR)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_renew_endpoint(self):
        e = emp("A", work_permit_expiry=date(2026, 8, 1))
        r = self.client.post(f"/api/v1/employees/{e.id}/renew-permit",
                             {"months": 12, "permit_no": "WP-1"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["permit_state"] in ("OK", "EXPIRING"), True)
        hist = self.client.get(f"/api/v1/employees/{e.id}/permit-renewals")
        self.assertEqual(len(hist.data), 1)

    def test_alerts_lists_permanent_only(self):
        emp("P1", work_permit_expiry=date.today() + timedelta(days=10))
        emp("C1", employment_type=Employee.EmploymentType.CONTRACT,
            work_permit_expiry=date.today() + timedelta(days=10))
        emp("OK1", work_permit_expiry=date.today() + timedelta(days=200))
        r = self.client.get("/api/v1/permits/alerts")
        self.assertEqual(r.status_code, 200)
        names = [x["full_name"] for x in r.data["expiring"]]
        self.assertIn("P1", names)
        self.assertNotIn("C1", names)      # contract excluded
        self.assertNotIn("OK1", names)     # not within 30 days

    def test_site_user_cannot_renew(self):
        e = emp("S", work_permit_expiry=date(2026, 8, 1))
        se = make_user("se", User.Role.SITE_ENGINEER)
        self.client.force_authenticate(se)
        r = self.client.post(f"/api/v1/employees/{e.id}/renew-permit",
                             {"months": 12}, format="json")
        self.assertEqual(r.status_code, 403)
