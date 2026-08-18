"""Site worker-management tool: SA/SE add/remove/transfer DIRECT workers in
approval BATCHES; PM (and, for new hires, Director) approve the whole batch."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Employee, EmployeeSiteAllocation, ManpowerCategory, Site,
                     SitePmHistory, User)
from .tests import make_user


class WorkerBatchTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.dest = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    def _auth(self, u):
        self.client.force_authenticate(u)

    def _worker(self, name, **kw):
        return {"full_name": name, "passport_no": f"P-{name}",
                "nationality": "IND", "basic_pay": "6000",
                "job_category_id": self.mason.id, **kw}

    def _add_batch(self, workers):
        return self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                                {"kind": "ADD", "workers": workers},
                                format="json")

    def _direct(self, site, n=1):
        out = []
        for _ in range(n):
            e = Employee.objects.create(
                emp_no=f"EMP-{Employee.objects.count()+1:04d}",
                full_name=f"W{Employee.objects.count()}",
                job_category=self.mason, basic_pay=Decimal("6000"),
                is_active=True)
            EmployeeSiteAllocation.objects.create(
                employee=e, site=site, from_date=date(2026, 1, 1))
            out.append(e)
        return out

    # ---- ADD -----------------------------------------------------------------

    def test_add_batch_lifecycle(self):
        r = self._add_batch([self._worker("Aay"), self._worker("Bee")])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["worker_count"], 2)
        bid = r.data["id"]
        emp_ids = [w["id"] for w in r.data["workers"]]
        # both pending + inactive → out of payroll
        for eid in emp_ids:
            e = Employee.objects.get(pk=eid)
            self.assertFalse(e.is_active)
            self.assertTrue(e.hire_pending)
            self.assertNotIn(eid, Employee.objects.payroll_eligible()
                             .filter(is_active=True).values_list("id",
                                                                 flat=True))
        # SA can't approve
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)
        # PM → PM_APPROVED (still inactive)
        self._auth(self.pm)
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "PM_APPROVED")
        self.assertFalse(Employee.objects.get(pk=emp_ids[0]).is_active)
        # PM can't do the Director step
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)
        # Director activates the whole batch
        self._auth(self.director)
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        for eid in emp_ids:
            e = Employee.objects.get(pk=eid)
            self.assertTrue(e.is_active)
            self.assertFalse(e.hire_pending)
            self.assertEqual(e.current_site_id(), self.site.id)

    def test_add_validates_each_worker(self):
        r = self._add_batch([self._worker("Ok"),
                            self._worker("Bad", passport_no="")])
        self.assertEqual(r.status_code, 400)
        self.assertIn("Worker 2", r.data["detail"])

    def test_edit_pending_hire_then_resubmit(self):
        r = self._add_batch([self._worker("Cee")])
        bid, eid = r.data["id"], r.data["workers"][0]["id"]
        self._auth(self.pm)
        self.client.post(f"/api/v1/worker-batches/{bid}/action",
                         {"action": "return", "note": "fix pay"},
                         format="json")
        self._auth(self.sa)
        r = self.client.patch(f"/api/v1/worker-hires/{eid}",
                              {"basic_pay": "9000"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(r.data["basic_pay"]), Decimal("9000"))
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "resubmit"}, format="json")
        self.assertEqual(r.data["status"], "SUBMITTED")

    # ---- REMOVE / TRANSFER ---------------------------------------------------

    def test_remove_batch(self):
        emps = self._direct(self.site, 2)
        r = self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                             {"kind": "REMOVE",
                              "employee_ids": [e.id for e in emps],
                              "reason": "done"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        bid = r.data["id"]
        self._auth(self.pm)
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        for e in emps:
            e.refresh_from_db()
            self.assertFalse(e.is_active)

    def test_transfer_batch(self):
        emps = self._direct(self.site, 2)
        r = self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                             {"kind": "TRANSFER",
                              "employee_ids": [e.id for e in emps],
                              "to_site_id": self.dest.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        bid = r.data["id"]
        self._auth(self.pm)
        self.client.post(f"/api/v1/worker-batches/{bid}/action",
                         {"action": "approve"}, format="json")
        for e in emps:
            e.refresh_from_db()
            self.assertEqual(e.current_site_id(), self.dest.id)

    def test_worker_cannot_be_in_two_open_batches(self):
        emp = self._direct(self.site, 1)[0]
        self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                         {"kind": "REMOVE", "employee_ids": [emp.id]},
                         format="json")
        r = self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                             {"kind": "TRANSFER", "employee_ids": [emp.id],
                              "to_site_id": self.dest.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_other_site_pm_cannot_approve(self):
        bid = self._add_batch([self._worker("Dee")]).data["id"]
        other = make_user("pm2", User.Role.PM, site=self.dest)
        SitePmHistory.objects.create(site=self.dest, pm_user=other,
                                     from_date=date(2026, 1, 1))
        self._auth(other)
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)


class RosterSalaryVisibilityTests(TestCase):
    """The workforce roster shows salary, but a Site Admin can't see the pay of
    STAFF-grade (senior) workers (owner 2026-07-23)."""

    def setUp(self):
        from decimal import Decimal
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        labour = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        staff = ManpowerCategory.objects.create(
            list_type="DPR", grp="STAFF", name="Site Engineer", sort_order=1)
        for cat, pay, no in ((labour, "6000", "EMP-0001"),
                             (staff, "20000", "EMP-0002")):
            e = Employee.objects.create(emp_no=no, full_name=cat.name,
                                        job_category=cat,
                                        basic_pay=Decimal(pay), is_active=True)
            EmployeeSiteAllocation.objects.create(
                employee=e, site=self.site, from_date=date(2026, 1, 1))
        self.client = APIClient()

    def _roster(self, user):
        self.client.force_authenticate(user)
        return {r["job_title"]: r for r in self.client.get(
            f"/api/v1/sites/{self.site.id}/direct-workers").data}

    def test_site_admin_cannot_see_staff_pay(self):
        r = self._roster(make_user("sa", User.Role.SITE_ADMIN, site=self.site))
        self.assertIsNotNone(r["Mason"]["basic_pay"])        # labour visible
        self.assertIsNone(r["Site Engineer"]["basic_pay"])   # staff hidden
        self.assertTrue(r["Site Engineer"]["pay_hidden"])

    def test_engineer_and_pm_cannot_see_staff_pay_either(self):
        """Widened from the Site Admin to the whole site team: a PM reading the
        site engineer's salary, and a fellow PM's staff, was "causing some
        trouble" (owner 2026-08-16). Their WORKERS' pay is untouched."""
        for role in (User.Role.SITE_ENGINEER, User.Role.PM):
            with self.subTest(role=role):
                r = self._roster(make_user(f"u{role}", role, site=self.site))
                self.assertIsNone(r["Site Engineer"]["basic_pay"])
                self.assertTrue(r["Site Engineer"]["pay_hidden"])
                self.assertIsNotNone(r["Mason"]["basic_pay"])

    def test_hr_sees_staff_pay(self):
        r = self._roster(make_user("hrx", User.Role.HO_HR))
        self.assertIsNotNone(r["Site Engineer"]["basic_pay"])
        self.assertFalse(r["Site Engineer"]["pay_hidden"])


class SiteHiresContractOnlyTests(WorkerBatchTests):
    """Sites hire CONTRACT workers only (owner 2026-08-11): a PERMANENT
    worker (company work permit) is created by HR / onboarding, never via a
    site batch — whatever the payload claims. The employee DB was getting
    messy with site-added 'permanent' workers."""

    def test_site_add_forces_contract(self):
        # even an explicit PERMANENT in the payload is overridden
        r = self._add_batch([
            self._worker("Cee", employment_type="PERMANENT"),
            self._worker("Dee")])
        self.assertEqual(r.status_code, 201, r.data)
        for w in r.data["workers"]:
            emp = Employee.objects.get(pk=w["id"])
            self.assertEqual(emp.employment_type,
                             Employee.EmploymentType.CONTRACT)

    def test_hire_edit_cannot_flip_to_permanent(self):
        r = self._add_batch([self._worker("Eee")])
        emp_id = r.data["workers"][0]["id"]
        r = self.client.patch(f"/api/v1/worker-hires/{emp_id}",
                              {"employment_type": "PERMANENT"},
                              format="json")
        self.assertIn(r.status_code, (200, 204), getattr(r, "data", None))
        self.assertEqual(Employee.objects.get(pk=emp_id).employment_type,
                         Employee.EmploymentType.CONTRACT)


class EmployeeDeleteTests(TestCase):
    """Admin-only delete of an employee record — for the duplicate / wrongly
    created rows the expat-portal reconciliation surfaced (owner 2026-08-12).
    A record carrying real history can never be deleted."""

    def setUp(self):
        self.site = Site.objects.create(code="DEL", name="Del Isle",
                                        status=Site.Status.ACTIVE)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.admin = make_user("del_adm", User.Role.ADMIN)
        self.hr = make_user("del_hr", User.Role.HO_HR)
        self.client = APIClient()

    def _emp(self, name="Dup Worker"):
        e = Employee.objects.create(
            emp_no=f"EMP-{Employee.objects.count() + 900:04d}",
            full_name=name, job_category=self.mason,
            basic_pay=Decimal("6000"), is_active=True)
        EmployeeSiteAllocation.objects.create(
            employee=e, site=self.site, from_date=date(2026, 1, 1))
        return e

    def test_admin_deletes_a_clean_duplicate(self):
        e = self._emp()
        self.client.force_authenticate(self.admin)
        r = self.client.get(f"/api/v1/employees/{e.id}/deletable")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["can_delete"])
        self.assertEqual(r.data["allocations"], 1)
        r = self.client.delete(f"/api/v1/employees/{e.id}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Employee.objects.filter(pk=e.id).exists())
        self.assertFalse(EmployeeSiteAllocation.objects
                         .filter(employee_id=e.id).exists())

    def test_hr_cannot_delete(self):
        e = self._emp()
        self.client.force_authenticate(self.hr)
        r = self.client.delete(f"/api/v1/employees/{e.id}")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Employee.objects.filter(pk=e.id).exists())

    def test_record_with_history_is_refused(self):
        from .models import Attendance
        e = self._emp()
        Attendance.objects.create(employee=e, site=self.site,
                                  day=date(2026, 2, 1), normal_hours=8)
        self.client.force_authenticate(self.admin)
        r = self.client.get(f"/api/v1/employees/{e.id}/deletable")
        self.assertFalse(r.data["can_delete"])
        self.assertIn("1 attendance days", r.data["blockers"])
        r = self.client.delete(f"/api/v1/employees/{e.id}")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Deactivate", r.data["detail"])
        self.assertTrue(Employee.objects.filter(pk=e.id).exists())


class EmployeeMergeTests(TestCase):
    """Merging a duplicate record moves its history onto the survivor so
    payroll sees the work (owner 2026-08-12: HR re-created workers instead of
    reactivating them, stranding July attendance on inactive records)."""

    def setUp(self):
        from core import employee_merge as em
        self.em = em
        self.site = Site.objects.create(code="MRG", name="Merge Isle",
                                        status=Site.Status.ACTIVE)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.admin = make_user("mrg_adm", User.Role.ADMIN)

    def _emp(self, name, active=True, pp="P1"):
        # These fixtures build the duplicate pair the merge tool exists to
        # clean up, so they say so explicitly — a passport already on file is
        # refused everywhere else now (owner 2026-08-16).
        e = Employee(
            emp_no=f"EMP-{Employee.objects.count() + 700:04d}", full_name=name,
            job_category=self.mason, basic_pay=Decimal("6000"),
            passport_no=pp, is_active=active)
        e._allow_duplicate_passport = True
        e.save()
        EmployeeSiteAllocation.objects.create(
            employee=e, site=self.site, from_date=date(2026, 1, 1))
        return e

    def _att(self, e, *days):
        from .models import Attendance
        for d in days:
            Attendance.objects.create(employee=e, site=self.site,
                                      day=date(2026, 7, d), normal_hours=8)

    def test_merge_moves_attendance_and_deletes_duplicate(self):
        old = self._emp("Worker Old", active=False)
        new = self._emp("Worker New")
        self._att(old, 1, 2, 3)
        self._att(new, 10)
        detail, err = self.em.merge(old, new, self.admin)
        self.assertIsNone(err)
        self.assertFalse(Employee.objects.filter(pk=old.pk).exists())
        from .models import Attendance
        self.assertEqual(Attendance.objects.filter(employee=new).count(), 4)
        self.assertEqual(detail["moved"]["attendance"], 3)
        self.assertEqual(detail["into"], new.emp_no)

    def test_clashing_day_keeps_target_by_default(self):
        from .models import Attendance
        old = self._emp("Dup", active=False)
        new = self._emp("Live")
        self._att(old, 1, 5)
        self._att(new, 5)
        Attendance.objects.filter(employee=new, day=date(2026, 7, 5)).update(
            normal_hours=Decimal("4"))
        detail, err = self.em.merge(old, new, self.admin)
        self.assertIsNone(err)
        rows = Attendance.objects.filter(employee=new).order_by("day")
        self.assertEqual([r.day.day for r in rows], [1, 5])
        # the survivor's own row for the clashing day is the one kept
        self.assertEqual(rows.get(day=date(2026, 7, 5)).normal_hours,
                         Decimal("4.00"))
        self.assertEqual(detail["clashing_days_resolved"], ["2026-07-05"])

    def test_keep_source_rule_replaces_the_clashing_day(self):
        from .models import Attendance
        old = self._emp("Dup", active=False)
        new = self._emp("Live")
        self._att(old, 5)
        self._att(new, 5)
        Attendance.objects.filter(employee=new).update(normal_hours=Decimal("4"))
        self.em.merge(old, new, self.admin, clash="keep_source")
        self.assertEqual(
            Attendance.objects.get(employee=new).normal_hours, Decimal("8.00"))

    def test_merge_into_self_refused(self):
        e = self._emp("Solo")
        detail, err = self.em.merge(e, e, self.admin)
        self.assertIsNotNone(err)
        self.assertTrue(Employee.objects.filter(pk=e.pk).exists())

    def test_preview_reports_clashes_and_warnings(self):
        old = self._emp("Dup", active=False, pp="AAA")
        new = self._emp("Live", pp="BBB")
        self._att(old, 1, 2)
        self._att(new, 2)
        pv = self.em.preview(old, new)
        self.assertEqual(pv["moves"]["attendance"], 2)
        self.assertEqual(len(pv["attendance_clashes"]), 1)
        self.assertIn("passport numbers differ", pv["warnings"])


    def test_keep_higher_rescues_the_real_hours(self):
        """The default that nearly cost FAYSAL AHAMMED 154 hours: the
        surviving record held 0-hour placeholder days while the duplicate
        carried the real 11-hour markings (owner 2026-08-12)."""
        from .models import Attendance
        old = self._emp("Real hours", active=False)
        new = self._emp("Placeholder")
        self._att(old, 1, 2, 3)                       # 8h each
        self._att(new, 1, 2, 3)
        Attendance.objects.filter(employee=new).update(normal_hours=Decimal("0"))
        detail, err = self.em.merge(old, new, self.admin, clash="keep_higher")
        self.assertIsNone(err)
        rows = Attendance.objects.filter(employee=new)
        self.assertEqual(rows.count(), 3)
        self.assertEqual(sum(r.normal_hours for r in rows), Decimal("24.00"))
        self.assertEqual(detail["hours_rescued"], 24.0)

    def test_keep_higher_leaves_the_fuller_target_alone(self):
        from .models import Attendance
        old = self._emp("Thin", active=False)
        new = self._emp("Full")
        self._att(old, 1)
        self._att(new, 1)
        Attendance.objects.filter(employee=old).update(normal_hours=Decimal("4"))
        detail, err = self.em.merge(old, new, self.admin, clash="keep_higher")
        self.assertIsNone(err)
        self.assertEqual(Attendance.objects.get(employee=new).normal_hours,
                         Decimal("8.00"))
        self.assertEqual(detail["hours_rescued"], 0)


class JoinDateTests(TestCase):
    """Sites maintain start dates themselves — payroll pro-rates from them
    (owner 2026-08-13)."""

    def setUp(self):
        from datetime import date

        from .models import EmployeeSiteAllocation
        self.site = Site.objects.create(code="JDT", name="Join Isle",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="JDO", name="Other Isle",
                                         status=Site.Status.ACTIVE)
        self.sa = make_user("jd_sa", User.Role.SITE_ADMIN, site=self.site)
        self.other_sa = make_user("jd_sa2", User.Role.SITE_ADMIN,
                                  site=self.other)
        self.hr = make_user("jd_hr", User.Role.HO_HR)
        self.emp = Employee.objects.create(emp_no="JD-0001", full_name="Ali",
                                           is_active=True)
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 7, 1))
        self.client = APIClient()

    def _patch(self, user, value):
        self.client.force_authenticate(user)
        return self.client.patch(f"/api/v1/workers/{self.emp.id}/join-date",
                                 {"join_date": value}, format="json")

    def test_site_admin_sets_the_date(self):
        from datetime import date
        r = self._patch(self.sa, "2026-07-16")
        self.assertEqual(r.status_code, 200, r.data)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.join_date, date(2026, 7, 16))

    def test_hr_may_set_it_too(self):
        self.assertEqual(self._patch(self.hr, "2026-07-16").status_code, 200)

    def test_another_sites_admin_cannot(self):
        self.assertEqual(self._patch(self.other_sa, "2026-07-16").status_code,
                         403)

    def test_future_date_refused(self):
        from datetime import date, timedelta
        soon = (date.today() + timedelta(days=3)).isoformat()
        r = self._patch(self.sa, soon)
        self.assertEqual(r.status_code, 400)
        self.assertIn("future", r.data["detail"].lower())

    def test_rubbish_date_refused(self):
        r = self._patch(self.sa, "16/07/2026")
        self.assertEqual(r.status_code, 400)

    def test_blank_refused(self):
        self.assertEqual(self._patch(self.sa, "").status_code, 400)

    def test_change_is_audited(self):
        from .models import AuditLog
        self._patch(self.sa, "2026-07-16")
        self.assertTrue(AuditLog.objects.filter(
            event="WORKER_JOIN_DATE_SET", entity_id=self.emp.id).exists())


class CancelledHireReleasesPassportTests(WorkerBatchTests):
    """Cancelling an ADD batch must not strand the man it was for.

    A pending hire is an INACTIVE placeholder until the batch is approved.
    Cancelling used to clear `hire_pending` and leave everything else, so the
    record fell off every screen — no roster, not a pending hire — while still
    holding the passport. The site could not re-add him: the guard named a
    record they had no way to see. Reported on AMILA CHINTHANA SUNIL
    KARUNATHILAKALAGE, one of 21 stuck this way (owner 2026-08-18).
    """

    def _cancel(self, batch_id, user=None):
        self._auth(user or self.sa)
        return self.client.post(f"/api/v1/worker-batches/{batch_id}/action",
                                {"action": "cancel"}, format="json")

    def test_the_same_man_can_be_added_again_after_a_cancel(self):
        r = self._add_batch([self._worker("AMILA")])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self._cancel(r.data["id"]).status_code, 200)
        # the point of the whole change: re-adding him now works
        again = self._add_batch([self._worker("AMILA")])
        self.assertEqual(again.status_code, 201, again.data)

    def test_the_placeholder_is_kept_but_marked_and_freed(self):
        r = self._add_batch([self._worker("AMILA")])
        emp_id = r.data["workers"][0]["id"]
        self._cancel(r.data["id"])
        emp = Employee.objects.get(pk=emp_id)          # never deleted
        self.assertEqual(emp.passport_no, "")           # passport released
        self.assertIn("cancelled hire", emp.full_name)  # and says why
        self.assertFalse(emp.is_active)
        self.assertFalse(emp.hire_pending)

    def test_the_batch_still_shows_who_was_asked_for(self):
        r = self._add_batch([self._worker("AMILA")])
        batch_id = r.data["id"]
        self._cancel(batch_id)
        self._auth(self.pm)
        got = self.client.get(f"/api/v1/worker-batches?site_id={self.site.id}")
        row = next(b for b in got.data if b["id"] == batch_id)
        self.assertEqual(row["status"], "CANCELLED")
        self.assertEqual(len(row["workers"]), 1)
        self.assertIn("AMILA", row["workers"][0]["full_name"])

    def test_a_live_worker_is_never_touched(self):
        """The guard that matters: if a placeholder somehow went live, its
        passport stays with it."""
        from core import worker_mgmt as wm
        live = self._direct(self.site, 1)[0]
        live.passport_no = "KEEPME"
        live.save()
        self.assertFalse(wm.release_cancelled_hire(live))
        live.refresh_from_db()
        self.assertEqual(live.passport_no, "KEEPME")
        self.assertTrue(live.is_active)

    def test_an_approved_batch_still_hires_normally(self):
        """Cancel is the only path that releases — approval must be unaffected."""
        r = self._add_batch([self._worker("REALHIRE")])
        self._auth(self.pm)
        self.client.post(f"/api/v1/worker-batches/{r.data['id']}/action",
                         {"action": "approve"}, format="json")
        self._auth(self.director)
        self.client.post(f"/api/v1/worker-batches/{r.data['id']}/action",
                         {"action": "approve"}, format="json")
        emp = Employee.objects.get(pk=r.data["workers"][0]["id"])
        self.assertTrue(emp.is_active)
        self.assertEqual(emp.passport_no, "P-REALHIRE")
        self.assertNotIn("cancelled", emp.full_name.lower())
