"""Editing a user, and linking the login to the person.

The users page could create an account but never open one: email and phone
were settable at creation and invisible afterwards, while "resend invite"
went to whatever address was typed that day. And a User (the account) and an
Employee (the man on the payroll) were the same human held twice with no
thread between them (owner 2026-08-30).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Employee, ManpowerCategory, User
from .tests import make_user


class UserEditTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin_u", User.Role.ADMIN)
        self.other = make_user("plain_u", User.Role.PM)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_an_admin_can_correct_an_email_and_phone(self):
        r = self.client.patch(f"/api/v1/users/{self.other.id}",
                              {"email": "fixed@sandplanet.mv",
                               "phone": "+9607777777"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.other.refresh_from_db()
        self.assertEqual(self.other.email, "fixed@sandplanet.mv")
        self.assertEqual(self.other.phone, "+9607777777")

    def test_the_edit_is_audited(self):
        from .models import AuditLog

        self.client.patch(f"/api/v1/users/{self.other.id}",
                          {"email": "x@y.mv"}, format="json")
        self.assertTrue(AuditLog.objects.filter(event="USER_UPDATED").exists())

    def test_a_non_admin_cannot_edit_anyone(self):
        self.client.force_authenticate(self.other)
        r = self.client.patch(f"/api/v1/users/{self.admin.id}",
                              {"email": "hack@x.mv"}, format="json")
        self.assertEqual(r.status_code, 403)


class UserEmployeeLinkTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin_l", User.Role.ADMIN)
        self.cat = ManpowerCategory.objects.create(name="Engineer",
                                                   list_type="DPR",
                                                   sort_order=1)
        self.emp = Employee.objects.create(
            emp_no="EMP-L01", full_name="Manoj Harshika", currency="MVR",
            job_category=self.cat, employment_type="PERMANENT",
            engagement_type="DIRECT")
        self.other_emp = Employee.objects.create(
            emp_no="EMP-L02", full_name="Someone Else", currency="MVR",
            employment_type="PERMANENT", engagement_type="DIRECT")
        self.user = make_user("manojh", User.Role.SITE_ENGINEER)
        self.user.full_name = "Manoj Harshika"
        self.user.save(update_fields=["full_name"])
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_a_login_can_be_linked_to_its_employee_record(self):
        r = self.client.patch(f"/api/v1/users/{self.user.id}",
                              {"employee": self.emp.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["employee_detail"]["emp_no"], "EMP-L01")
        self.user.refresh_from_db()
        self.assertEqual(self.user.employee, self.emp)

    def test_one_employee_cannot_hold_two_logins(self):
        """Two accounts on one person is a duplicate account, which is the
        thing worth refusing."""
        self.client.patch(f"/api/v1/users/{self.user.id}",
                          {"employee": self.emp.id}, format="json")
        second = make_user("manojh2", User.Role.SITE_ENGINEER)
        r = self.client.patch(f"/api/v1/users/{second.id}",
                              {"employee": self.emp.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("manojh", str(r.data))

    def test_the_link_can_be_cleared(self):
        self.client.patch(f"/api/v1/users/{self.user.id}",
                          {"employee": self.emp.id}, format="json")
        r = self.client.patch(f"/api/v1/users/{self.user.id}",
                              {"employee": None}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.employee)

    def test_options_put_the_name_match_first(self):
        r = self.client.get(
            f"/api/v1/users/{self.user.id}/employee-options")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]["emp_no"], "EMP-L01")
        self.assertTrue(r.data[0]["suggested"])
        self.assertFalse(
            [x for x in r.data if x["emp_no"] == "EMP-L02"][0]["suggested"])

    def test_options_drop_employees_another_login_already_holds(self):
        second = make_user("holder", User.Role.PM)
        second.employee = self.other_emp
        second.save(update_fields=["employee"])
        r = self.client.get(
            f"/api/v1/users/{self.user.id}/employee-options")
        self.assertNotIn("EMP-L02", [x["emp_no"] for x in r.data])

    def test_options_can_be_searched(self):
        r = self.client.get(
            f"/api/v1/users/{self.user.id}/employee-options?q=someone")
        self.assertEqual([x["emp_no"] for x in r.data], ["EMP-L02"])

    def test_deleting_an_employee_leaves_the_login_alone(self):
        """An account must survive its HR record being removed — losing a
        login because somebody tidied up an employee row would lock a person
        out of the system."""
        self.client.patch(f"/api/v1/users/{self.user.id}",
                          {"employee": self.emp.id}, format="json")
        self.emp.delete()
        self.user.refresh_from_db()
        self.assertIsNone(self.user.employee)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_linking_then_saving_the_rest_keeps_the_link(self):
        """The screen saves the link the moment it is picked, then saves the
        form again when the admin presses Save. The second PATCH must not
        carry a stale employee and unlink what was just linked — it did, and
        the link vanished with no error (found 2026-08-30)."""
        self.client.patch(f"/api/v1/users/{self.user.id}",
                          {"employee": self.emp.id}, format="json")
        # ...the form then submits everything it holds, including employee.
        r = self.client.patch(
            f"/api/v1/users/{self.user.id}",
            {"email": "m@sandplanet.mv", "employee": self.emp.id},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.employee, self.emp)
        self.assertEqual(self.user.email, "m@sandplanet.mv")

    def test_an_omitted_employee_field_does_not_clear_the_link(self):
        """A PATCH that says nothing about the employee must leave it alone —
        the field is optional, and absent is not the same as null."""
        self.client.patch(f"/api/v1/users/{self.user.id}",
                          {"employee": self.emp.id}, format="json")
        self.client.patch(f"/api/v1/users/{self.user.id}",
                          {"phone": "+9601234567"}, format="json")
        self.user.refresh_from_db()
        self.assertEqual(self.user.employee, self.emp)
