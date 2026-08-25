"""Biometric terminals: what arrives from the gate, and what we do with it.

Phase 1 is listen-only, so the load-bearing tests here are about not losing and
not double-counting punches — and about attendance being untouched.
"""
from datetime import date, datetime, timedelta

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import biometric as svc
from .models import (Attendance, AttendanceDevice, BiometricEnrolment,
                     DevicePunch, Employee, ManpowerCategory, Site,
                     EmployeeSiteAllocation, User)
from .tests import make_user

SECRET = "test-adms-secret"
PUSH = f"/adms/{SECRET}/iclock/cdata"


@override_settings(ADMS_SECRET=SECRET)
class AdmsIngestTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="BVR", name="Bvlgari",
                                        status=Site.Status.ACTIVE)
        self.hr = make_user("bio_hr", User.Role.HO_HR)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.emp = Employee.objects.create(
            emp_no="EMP-0603", full_name="Rakib Hossain",
            job_category=self.cat, is_active=True)
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 1, 1))
        self.device = AttendanceDevice.objects.create(
            site=self.site, name="Camp gate", serial="CJTM214860055",
            model="SenseFace M2F-LR")
        self.client = APIClient()

    def _push(self, body, serial=None, secret=SECRET):
        return self.client.post(
            f"/adms/{secret}/iclock/cdata"
            f"?SN={serial or self.device.serial}&table=ATTLOG",
            body, content_type="text/plain")

    # ---- identity ----

    def test_the_employee_number_is_the_device_id(self):
        self.assertEqual(svc.device_id_for(self.emp), "603")

    def test_a_punch_is_matched_to_the_worker_by_that_id(self):
        r = self._push("603\t2026-08-23 07:12:04\t0\t15\t0\t0\t0\n")
        self.assertEqual(r.status_code, 200)
        p = DevicePunch.objects.get()
        self.assertEqual(p.employee, self.emp)
        self.assertEqual(p.status, "MATCHED")
        self.assertEqual(p.direction, "IN")
        self.assertEqual(p.verify_mode, "face")

    def test_a_terminals_local_time_is_stored_as_the_right_instant(self):
        """The gate is set to Maldives time; the app stores UTC. A five-hour
        error would move every punch into the previous evening."""
        self._push("603\t2026-08-23 07:12:04\t0\t1\n")
        p = DevicePunch.objects.get()
        self.assertEqual(p.punched_at.astimezone(
            svc.timezone(svc.SITE_OFFSET)).strftime("%Y-%m-%d %H:%M"),
            "2026-08-23 07:12")
        self.assertEqual(p.punched_at.utctimetuple()[:5],
                         (2026, 8, 23, 2, 12))          # 07:12 − 5h

    def test_an_unknown_id_is_kept_not_discarded(self):
        self._push("999\t2026-08-23 07:15:00\t0\t1\n")
        p = DevicePunch.objects.get()
        self.assertEqual(p.status, "UNKNOWN_ID")
        self.assertIsNone(p.employee_id)
        self.assertIn("999", p.raw)

    def test_a_line_we_cannot_read_is_still_stored(self):
        self._push("this is not a punch\n")
        p = DevicePunch.objects.get()
        self.assertEqual(p.status, "UNPARSED")
        self.assertEqual(p.raw, "this is not a punch")

    # ---- the outage case (requirement D-02) ----

    def test_a_resend_after_an_outage_does_not_double_count(self):
        batch = ("603\t2026-08-23 07:12:04\t0\t1\n"
                 "603\t2026-08-23 17:40:11\t1\t1\n")
        first = self._push(batch)
        self.assertEqual(DevicePunch.objects.count(), 2)
        # The device did not see our reply and sends the whole batch again.
        self._push(batch)
        self.assertEqual(DevicePunch.objects.count(), 2)
        self.assertIn("OK", first.content.decode())

    def test_a_resend_that_also_carries_new_punches_keeps_the_new_ones(self):
        self._push("603\t2026-08-23 07:12:04\t0\t1\n")
        self._push("603\t2026-08-23 07:12:04\t0\t1\n"
                   "603\t2026-08-23 12:02:00\t1\t1\n")
        self.assertEqual(DevicePunch.objects.count(), 2)

    def test_in_and_out_are_read_from_the_status_column(self):
        self._push("603\t2026-08-23 07:12:04\t0\t1\n"
                   "603\t2026-08-23 17:40:11\t1\t1\n"
                   "603\t2026-08-24 07:05:00\t9\t1\n")
        local = svc.timezone(svc.SITE_OFFSET)
        got = {p.punched_at.astimezone(local).strftime("%d %H:%M"): p.direction
               for p in DevicePunch.objects.all()}
        self.assertEqual(got["23 07:12"], "IN")
        self.assertEqual(got["23 17:40"], "OUT")
        self.assertEqual(got["24 07:05"], "UNKNOWN")   # never guessed

    # ---- who we accept from ----

    def test_an_unregistered_serial_is_never_stored(self):
        r = self._push("603\t2026-08-23 07:12:04\t0\t1\n", serial="NOPE-1")
        self.assertEqual(r.status_code, 200)     # acknowledged, not revealing
        self.assertEqual(DevicePunch.objects.count(), 0)

    def test_a_wrong_secret_is_refused(self):
        r = self._push("603\t2026-08-23 07:12:04\t0\t1\n", secret="guess")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(DevicePunch.objects.count(), 0)

    @override_settings(ADMS_SECRET="")
    def test_with_no_secret_configured_nothing_is_accepted(self):
        """A machine with no terminals must not have an open endpoint."""
        r = self.client.post(f"/adms//iclock/cdata?SN={self.device.serial}",
                             "603\t2026-08-23 07:12:04\t0\t1\n",
                             content_type="text/plain")
        self.assertIn(r.status_code, (403, 404))
        self.assertEqual(DevicePunch.objects.count(), 0)

    def test_a_deactivated_terminal_stops_being_accepted(self):
        self.device.is_active = False
        self.device.save(update_fields=["is_active"])
        self._push("603\t2026-08-23 07:12:04\t0\t1\n")
        self.assertEqual(DevicePunch.objects.count(), 0)

    def test_the_doubled_iclock_path_is_accepted(self):
        """The firmware appends /iclock/cdata to the configured address, so an
        address ending in /iclock produces /iclock/iclock/ — the first real
        unit did exactly this (2026-08-24)."""
        r = self.client.post(
            f"/adms/{SECRET}/iclock/iclock/cdata"
            f"?SN={self.device.serial}&table=ATTLOG",
            "603\t2026-08-23 07:12:04\t0\t1\n",
            content_type="text/plain")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(DevicePunch.objects.count(), 1)
        r = self.client.get(f"/adms/{SECRET}/iclock/iclock/cdata"
                            f"?SN={self.device.serial}&options=all")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Realtime=1", r.content.decode())

    # ---- the handshake ----

    def test_the_handshake_answers_and_marks_the_device_seen(self):
        r = self.client.get(f"{PUSH}?SN={self.device.serial}&options=all")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("TimeZone=5", body)        # Maldives, not UTC
        self.assertIn("Realtime=1", body)
        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_seen_at)

    def test_health_counters_move_with_the_punches(self):
        self._push("603\t2026-08-23 07:12:04\t0\t1\n")
        self.device.refresh_from_db()
        self.assertEqual(self.device.punches_received, 1)
        self.assertIsNotNone(self.device.last_punch_at)

    # ---- the whole point of Phase 1 ----

    def test_a_punch_does_not_touch_attendance(self):
        """Listen only: the device runs alongside manual marking for a month
        before it is trusted with anyone's pay (owner 2026-08-23)."""
        self._push("603\t2026-08-23 07:12:04\t0\t1\n"
                   "603\t2026-08-23 17:40:11\t1\t1\n")
        self.assertEqual(DevicePunch.objects.count(), 2)
        self.assertEqual(Attendance.objects.count(), 0)


@override_settings(ADMS_SECRET=SECRET)
class EnrolmentTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.hr = make_user("en_hr", User.Role.HO_HR)
        self.pm = make_user("en_pm", User.Role.PM, site=self.site)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.a = self._worker("EMP-0100", "Direct Man")
        self.b = self._worker("EMP-0101", "Sub Man",
                              engagement=Employee.Engagement.SUBCONTRACT)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _worker(self, emp_no, name, engagement=None):
        e = Employee.objects.create(
            emp_no=emp_no, full_name=name, job_category=self.cat,
            is_active=True,
            engagement_type=engagement or Employee.Engagement.DIRECT)
        EmployeeSiteAllocation.objects.create(employee=e, site=self.site,
                                              from_date=date(2026, 1, 1))
        return e

    def test_enrolling_defaults_to_the_employee_number(self):
        r = self.client.post(f"/api/v1/employees/{self.a.id}/biometric",
                             {"finger_count": 2, "face_enrolled": True},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["device_user_id"], "100")
        self.assertEqual(r.data["finger_count"], 2)

    def test_a_device_id_cannot_belong_to_two_workers(self):
        self.client.post(f"/api/v1/employees/{self.a.id}/biometric",
                         {"device_user_id": "777"}, format="json")
        r = self.client.post(f"/api/v1/employees/{self.b.id}/biometric",
                             {"device_user_id": "777"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already enrolled", r.data["detail"])

    def test_subcontract_workers_enrol_the_same_way(self):
        r = self.client.post(f"/api/v1/employees/{self.b.id}/biometric",
                             {"finger_count": 1, "face_enrolled": True},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["device_user_id"], "101")

    def test_the_gap_list_is_who_is_on_site_and_not_enrolled(self):
        r = self.client.get(f"/api/v1/attendance-devices/enrolment"
                            f"?site={self.site.id}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual({m["emp_no"] for m in r.data["missing"]},
                         {"EMP-0100", "EMP-0101"})
        self.assertEqual([m["suggested_id"] for m in r.data["missing"]
                          if m["emp_no"] == "EMP-0100"], ["100"])
        self.client.post(f"/api/v1/employees/{self.a.id}/biometric", {},
                         format="json")
        r = self.client.get(f"/api/v1/attendance-devices/enrolment"
                            f"?site={self.site.id}")
        self.assertEqual({m["emp_no"] for m in r.data["missing"]},
                         {"EMP-0101"})
        self.assertEqual([e["emp_no"] for e in r.data["enrolled"]],
                         ["EMP-0100"])

    def test_removing_an_enrolment_frees_the_id(self):
        self.client.post(f"/api/v1/employees/{self.a.id}/biometric",
                         {"device_user_id": "500"}, format="json")
        r = self.client.delete(f"/api/v1/employees/{self.a.id}/biometric",
                               {"reason": "demobilised"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(BiometricEnrolment.objects.filter(
            employee=self.a, is_active=True).exists())
        # ...and the next worker may take it.
        r2 = self.client.post(f"/api/v1/employees/{self.b.id}/biometric",
                              {"device_user_id": "500"}, format="json")
        self.assertEqual(r2.status_code, 201, r2.data)

    def test_only_hr_records_enrolment(self):
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/employees/{self.a.id}/biometric", {},
                             format="json")
        self.assertEqual(r.status_code, 403)


@override_settings(ADMS_SECRET=SECRET)
class DeviceRegistryTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="MXR", name="Max Royal",
                                        status=Site.Status.ACTIVE)
        self.hr = make_user("rg_hr", User.Role.HO_HR)
        self.pm = make_user("rg_pm", User.Role.PM, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_registering_a_terminal(self):
        r = self.client.post("/api/v1/attendance-devices", {
            "site_id": self.site.id, "name": "Camp gate",
            "serial": "CJTM214860055", "model": "SenseFace M2F-LR",
            "location_note": "Under the mess canopy"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["healthy"])      # never heard from yet
        self.assertEqual(r.data["punches_today"], 0)

    def test_a_serial_is_registered_once(self):
        body = {"site_id": self.site.id, "name": "A", "serial": "SN-1"}
        self.client.post("/api/v1/attendance-devices", body, format="json")
        r = self.client.post("/api/v1/attendance-devices",
                             {**body, "name": "B"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already registered", r.data["detail"])

    def test_a_pm_can_read_the_registry_but_not_add_to_it(self):
        self.client.post("/api/v1/attendance-devices", {
            "site_id": self.site.id, "name": "Gate", "serial": "SN-9"},
            format="json")
        self.client.force_authenticate(self.pm)
        self.assertEqual(self.client.get("/api/v1/attendance-devices")
                         .status_code, 200)
        r = self.client.post("/api/v1/attendance-devices", {
            "site_id": self.site.id, "name": "X", "serial": "SN-8"},
            format="json")
        self.assertEqual(r.status_code, 403)

    def test_the_punch_log_can_be_read_and_filtered(self):
        d = AttendanceDevice.objects.create(site=self.site, name="Gate",
                                            serial="SN-7")
        DevicePunch.objects.create(
            device=d, device_user_id="42",
            punched_at=svc._aware(datetime(2026, 8, 23, 7, 30)),
            direction="IN", status="UNKNOWN_ID", raw="42\t...")
        r = self.client.get("/api/v1/attendance-devices/punches"
                            "?status=UNKNOWN_ID")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["punches"][0]["device_user_id"], "42")
        self.assertIsNone(r.data["punches"][0]["emp_no"])


@override_settings(ADMS_SECRET=SECRET)
class DayProposalTests(TestCase):
    """Phase 2: punches PROPOSE the day on the clerk's grid, by the owner's
    rules (2026-08-24). Nothing is stored; the clerk's save is still the only
    write path into attendance."""

    def setUp(self):
        from datetime import time
        self.site = Site.objects.create(
            code="MLE", name="Head Office", status=Site.Status.ACTIVE,
            working_hours_from=time(8, 0), working_hours_to=time(17, 0))
        self.hr = make_user("dp_hr", User.Role.HO_HR)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.emp = Employee.objects.create(
            emp_no="EMP-0700", full_name="Grid Man", job_category=self.cat,
            is_active=True, join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 1, 1))
        self.device = AttendanceDevice.objects.create(
            site=self.site, name="Office", serial="DP-1")
        self.client = APIClient()
        self.client.force_authenticate(self.hr)
        # A Monday — inside the default working week.
        self.day = date(2026, 8, 24)

    def _push(self, *lines):
        body = "".join(f"{l}\n" for l in lines)
        return self.client.post(
            f"/adms/{SECRET}/iclock/cdata?SN=DP-1&table=ATTLOG",
            body, content_type="text/plain")

    def _grid_row(self):
        r = self.client.get(f"/api/v1/attendance?site={self.site.id}"
                            f"&date={self.day}")
        assert r.status_code == 200, r.data
        self.grid = r.data
        return next(x for x in r.data["rows"]
                    if x["employee_id"] == self.emp.id)

    def test_a_full_day_with_overtime_is_proposed_for_the_clerk(self):
        self._push("700\t2026-08-24 07:58:00\t255\t1",
                   "700\t2026-08-24 19:47:00\t255\t1")
        row = self._grid_row()
        d = row["device"]
        self.assertEqual(d["punch_count"], 2)
        self.assertEqual(d["proposal"]["check_in"], "07:58")
        self.assertEqual(d["proposal"]["check_out"], "19:47")
        self.assertEqual(d["proposal"]["remark"], "PRESENT")
        # 17:00 -> 19:47 is 2h47m; floored to the half hour = 2.5, for the
        # clerk to adjust and the PM to approve as always.
        self.assertEqual(d["proposal"]["ot_requested"], "2.5")
        self.assertIn("OT", d["flags"])
        self.assertNotIn("LATE", d["flags"])

    def test_no_punch_out_proposes_the_normal_finish_flagged(self):
        self._push("700\t2026-08-24 07:55:00\t255\t15")
        d = self._grid_row()["device"]
        self.assertIn("NO_OUT", d["flags"])
        self.assertEqual(d["proposal"]["check_out"], "17:00")
        self.assertEqual(d["proposal"]["remark"], "PRESENT")
        self.assertEqual(d["proposal"]["ot_requested"], "0")

    def test_a_short_span_proposes_a_half_day(self):
        self._push("700\t2026-08-24 08:02:00\t255\t1",
                   "700\t2026-08-24 12:30:00\t255\t1")
        d = self._grid_row()["device"]
        self.assertEqual(d["proposal"]["remark"], "HALF_DAY")
        self.assertIn("SHORT", d["flags"])

    def test_more_than_fifteen_minutes_late_is_flagged_not_priced(self):
        self._push("700\t2026-08-24 08:20:00\t255\t1",
                   "700\t2026-08-24 17:05:00\t255\t1")
        d = self._grid_row()["device"]
        self.assertIn("LATE", d["flags"])
        self.assertEqual(d["proposal"]["remark"], "PRESENT")  # pay untouched

    def test_ot_counts_from_the_sites_own_threshold_when_set(self):
        from datetime import time
        # Site says OT only counts after 18:00, though work finishes 17:00.
        self.site.ot_counts_from = time(18, 0)
        self.site.save(update_fields=["ot_counts_from"])
        self._push("700\t2026-08-24 07:58:00\t255\t1",
                   "700\t2026-08-24 19:47:00\t255\t1")
        d = self._grid_row()["device"]
        # 18:00 -> 19:47 is 1h47m, floored = 1.5 (was 2.5 from the finish).
        self.assertEqual(d["proposal"]["ot_requested"], "1.5")

    def test_the_late_grace_is_the_sites_own_setting(self):
        self.site.late_after_min = 45
        self.site.save(update_fields=["late_after_min"])
        self._push("700\t2026-08-24 08:40:00\t255\t1",
                   "700\t2026-08-24 17:05:00\t255\t1")
        d = self._grid_row()["device"]
        self.assertNotIn("LATE", d["flags"])   # 40 min late, 45 allowed

    def test_a_rest_day_punch_is_flagged_and_proposes_nothing(self):
        self.day = date(2026, 8, 28)                     # a Friday
        self._push("700\t2026-08-28 09:10:00\t255\t1")
        d = self._grid_row()["device"]
        self.assertIn("REST_DAY", d["flags"])
        self.assertIsNone(d["proposal"])

    def test_a_stranger_at_the_gate_is_listed_not_rostered(self):
        other = Employee.objects.create(
            emp_no="EMP-0800", full_name="Other Site Man",
            job_category=self.cat, is_active=True)
        self._push("800\t2026-08-24 08:05:00\t255\t1",
                   "999\t2026-08-24 08:06:00\t255\t1")
        self._grid_row()
        um = self.grid["device_unmatched"]
        self.assertEqual(len(um), 2)
        whys = {u["device_user_id"]: u["why"] for u in um}
        self.assertEqual(whys["800"], "not on this site's register")
        self.assertEqual(whys["999"], "no worker for this ID")

    def test_a_site_with_no_terminal_pays_no_cost(self):
        self.device.is_active = False
        self.device.save(update_fields=["is_active"])
        row = self._grid_row()
        self.assertIsNone(row["device"])
        self.assertFalse(self.grid["has_devices"])

    def test_proposals_store_nothing_until_the_clerk_saves(self):
        self._push("700\t2026-08-24 07:58:00\t255\t1",
                   "700\t2026-08-24 19:47:00\t255\t1")
        self._grid_row()
        self.assertEqual(Attendance.objects.count(), 0)
        # The clerk accepts the proposal — through the SAME endpoint as a
        # hand-marked day, so every guard applies.
        r = self.client.put("/api/v1/attendance/bulk", {
            "site": self.site.id, "date": str(self.day),
            "rows": [{"employee_id": self.emp.id, "check_in": "07:58",
                      "check_out": "19:47", "ot_requested": "2.5",
                      "remark": "PRESENT"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        a = Attendance.objects.get()
        self.assertEqual(str(a.ot_requested), "2.50")
        self.assertIsNone(a.ot_approved)          # the PM still approves
