"""Work-permit tracking: status, renewal (months → expiry), and HR alerts."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from . import permits
from .models import Employee, User
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


class PermitScheduleApplyTests(TestCase):
    def setUp(self):
        self.hr = make_user("hr", User.Role.HO_HR)

    def test_schedule_does_not_change_expiry(self):
        e = emp("R", work_permit_expiry=date(2026, 8, 1))
        row = permits.schedule(e, 12, 350, "PYR-x", self.hr)
        e.refresh_from_db()
        self.assertEqual(e.work_permit_expiry, date(2026, 8, 1))  # unchanged
        self.assertFalse(row.applied)
        self.assertIsNone(row.new_expiry)

    def test_apply_extends_from_current_expiry(self):
        e = emp("R", work_permit_expiry=date(2026, 8, 1))
        row = permits.schedule(e, 12, 350, "", self.hr)
        permits.apply(row, self.hr, today=date(2026, 7, 12))
        e.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(e.work_permit_expiry, date(2027, 8, 1))
        self.assertTrue(row.applied)
        self.assertEqual(row.new_expiry, date(2027, 8, 1))

    def test_apply_is_idempotent(self):
        e = emp("R", work_permit_expiry=date(2026, 8, 1))
        row = permits.schedule(e, 12, 350, "", self.hr)
        permits.apply(row, self.hr)
        permits.apply(row, self.hr)   # second call is a no-op
        e.refresh_from_db()
        self.assertEqual(e.work_permit_expiry, date(2027, 8, 1))

    def test_schedule_flips_contract_to_permanent(self):
        e = emp("F", employment_type=Employee.EmploymentType.CONTRACT)
        permits.schedule(e, 3, 350, "", self.hr)
        e.refresh_from_db()
        self.assertEqual(e.employment_type, "PERMANENT")

    def test_zero_months_rejected(self):
        e = emp("Z", work_permit_expiry=date(2026, 8, 1))
        with self.assertRaises(ValueError):
            permits.schedule(e, 0, 350, "", self.hr)


class PermitApiTests(TestCase):
    def setUp(self):
        self.hr = make_user("hr", User.Role.HO_HR)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

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


class PermitBatchRenewTests(TestCase):
    def setUp(self):
        from datetime import date as _date

        from .models import CostHead, Site
        self.hr = make_user("hr", User.Role.HO_HR)
        Site.objects.get_or_create(
            code="MLE", defaults={"name": "Head Office", "is_head_office": True,
                                  "status": Site.Status.ACTIVE,
                                  "start_date": _date(2026, 1, 1)})
        CostHead.objects.get_or_create(name="Permits & Fees")
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_batch_renew_raises_pyr_pending_until_paid(self):
        from decimal import Decimal

        from . import permits
        from .models import Document, WorkPermitRenewal
        e1 = emp("B1", work_permit_expiry=date(2026, 8, 1))
        e2 = emp("B2", work_permit_expiry=date(2026, 8, 15))
        r = self.client.post("/api/v1/permits/batch-renew", {
            "payee": "Immigration Maldives",
            "lines": [
                {"employee_id": e1.id, "months": 12, "fee": 350},
                {"employee_id": e2.id, "months": 6, "fee": 350},
            ]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["count"], 2)
        self.assertEqual(Decimal(r.data["amount"]), Decimal("700"))
        doc = Document.objects.get(ref=r.data["ref"])
        self.assertEqual(doc.doc_type, "PYR")
        self.assertEqual(doc.payment_request.payment_type, "PERMIT_RENEWAL")
        # Renewals are recorded but PENDING — expiries unchanged until paid
        linked = WorkPermitRenewal.objects.filter(document=doc)
        self.assertEqual(linked.count(), 2)
        self.assertFalse(linked.filter(applied=True).exists())
        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertEqual(e1.work_permit_expiry, date(2026, 8, 1))   # unchanged
        self.assertEqual(e2.work_permit_expiry, date(2026, 8, 15))  # unchanged
        # Simulate Finance paying the PYR → expiries now extend
        permits.apply_for_document(doc, self.hr)
        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertEqual(e1.work_permit_expiry, date(2027, 8, 1))
        self.assertEqual(e2.work_permit_expiry, date(2027, 2, 15))
        self.assertEqual(linked.filter(applied=True).count(), 2)

    def test_batch_renew_needs_lines(self):
        r = self.client.post("/api/v1/permits/batch-renew", {"lines": []},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_batch_renew_hr_only(self):
        se = make_user("se", User.Role.SITE_ENGINEER)
        self.client.force_authenticate(se)
        e = emp("X", work_permit_expiry=date(2026, 8, 1))
        r = self.client.post("/api/v1/permits/batch-renew", {
            "lines": [{"employee_id": e.id, "months": 12, "fee": 350}]},
            format="json")
        self.assertEqual(r.status_code, 403)
