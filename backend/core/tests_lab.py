"""Materials & site testing — cube tests and the rest.

They were recorded nowhere: the reports existed as paper and only reached the
app when somebody uploaded them into the handover pack at the end (owner
2026-08-29)."""
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from . import lab
from .models import Document, MaterialTest, Project, Site, User
from .tests import make_user


class TestRequestTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="LB1", name="Lab site",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("se_lb1", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("pm_lb1", User.Role.PM, site=self.site)
        self.site.pm_history.create(pm_user=self.pm, from_date=date.today())
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE")
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def _request(self, **extra):
        body = {"site_id": self.site.id, "project_id": self.project.id,
                "kind": "CUBE", "element": "Villa 3 ground floor slab",
                "pour_ref": "POUR-014", "grade": "C30/20",
                "quantity": "18 m3",
                "sampled_on": str(date.today() - timedelta(days=30)),
                "required_value": "30.00", "unit": "N/mm2",
                "lab_name": "Maldives Testing Lab"}
        body.update(extra)
        return self.client.post("/api/v1/quality/tests", body, format="json")

    def _result(self, ref, **extra):
        body = {"age_days": 28, "value": "34.50",
                "tested_on": str(date.today())}
        body.update(extra)
        return self.client.post(f"/api/v1/quality/tests/{ref}/results", body,
                                format="json")

    def test_a_sample_is_recorded_when_it_is_taken(self):
        r = self._request()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("TR-"))
        self.assertEqual(r.data["status"], "SAMPLED")

    def test_a_cube_knows_its_28_day_result_is_due(self):
        r = self._request()
        self.assertEqual(
            str(r.data["result_due_on"]),
            str(date.today() - timedelta(days=30) + timedelta(days=28)))

    def test_a_sample_cannot_be_taken_in_the_future(self):
        r = self._request(sampled_on=str(date.today() + timedelta(days=1)))
        self.assertEqual(r.status_code, 400)

    def test_the_element_must_be_named(self):
        self.assertEqual(self._request(element="").status_code, 400)

    def test_a_result_is_graded_against_the_specified_figure(self):
        ref = self._request().data["ref"]
        r = self._result(ref)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["results"][0]["outcome"], "PASS")
        self.assertEqual(r.data["status"], "PASSED")

    def test_a_low_break_fails_without_being_told_to(self):
        ref = self._request().data["ref"]
        r = self._result(ref, value="21.00")
        self.assertEqual(r.data["results"][0]["outcome"], "FAIL")
        self.assertEqual(r.data["status"], "FAILED")

    def test_with_no_specified_figure_the_software_invents_no_criterion(self):
        ref = self._request(required_value=None).data["ref"]
        r = self._result(ref, value="12.00")
        self.assertEqual(r.data["results"][0]["outcome"], "PENDING")

    def test_a_seven_day_pass_leaves_the_request_partial(self):
        """The 28-day break is the one that finishes a cube."""
        ref = self._request().data["ref"]
        r = self._result(ref, age_days=7, value="24.00", outcome="PASS")
        self.assertEqual(r.data["status"], "PARTIAL")
        r = self._result(ref, age_days=28, value="33.00")
        self.assertEqual(r.data["status"], "PASSED")

    def test_a_failure_at_any_age_fails_the_sample(self):
        """A cube that broke low at 7 days is not rescued by a good 28-day
        one — it is a question that has to be answered."""
        ref = self._request().data["ref"]
        self._result(ref, age_days=7, value="9.00")
        r = self._result(ref, age_days=28, value="36.00")
        self.assertEqual(r.data["status"], "FAILED")

    def test_a_failure_alerts_the_pm(self):
        from .models import Notification
        ref = self._request().data["ref"]
        self._result(ref, value="18.00")
        self.assertTrue(Notification.objects.filter(recipient=self.pm)
                        .exists())

    def test_a_certificate_can_be_attached_to_the_result(self):
        ref = self._request().data["ref"]
        cert = SimpleUploadedFile("cube-28d.pdf", b"%PDF-1.4",
                                  content_type="application/pdf")
        r = self.client.post(f"/api/v1/quality/tests/{ref}/results",
                             {"age_days": 28, "value": "35.0",
                              "certificate": cert}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNotNone(r.data["results"][0]["certificate_url"])

    def test_a_sample_past_its_age_with_no_result_is_overdue(self):
        """Either a lost certificate or a failure nobody chased."""
        self._request(sampled_on=str(date.today() - timedelta(days=40)))
        rows = self.client.get("/api/v1/quality/tests?overdue=1").data
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_overdue"])
        self.assertEqual(
            self.client.get("/api/v1/quality/tests/stats").data["overdue"], 1)

    def test_a_finished_sample_is_not_overdue(self):
        ref = self._request(
            sampled_on=str(date.today() - timedelta(days=40))).data["ref"]
        self._result(ref, value="35.00")
        self.assertEqual(
            len(self.client.get("/api/v1/quality/tests?overdue=1").data), 0)

    def test_a_failed_test_raises_a_non_conformance(self):
        ref = self._request().data["ref"]
        self._result(ref, value="19.50")
        r = self.client.post(f"/api/v1/quality/tests/{ref}/ncr", {},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ncr_ref"].startswith("NCR-"))
        ncr = self.client.get(f"/api/v1/quality/ncrs/{r.data['ncr_ref']}").data
        self.assertEqual(ncr["category"], "MATERIAL")
        self.assertIn("19.50", ncr["description"])
        self.assertTrue(ncr["requirement"])

    def test_a_passing_test_raises_no_non_conformance(self):
        ref = self._request().data["ref"]
        self._result(ref, value="35.00")
        r = self.client.post(f"/api/v1/quality/tests/{ref}/ncr", {},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_the_same_failure_is_not_raised_twice(self):
        ref = self._request().data["ref"]
        self._result(ref, value="19.50")
        self.client.post(f"/api/v1/quality/tests/{ref}/ncr", {},
                         format="json")
        r = self.client.post(f"/api/v1/quality/tests/{ref}/ncr", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already covers", r.data["detail"])

    def test_another_site_cannot_see_the_test(self):
        ref = self._request().data["ref"]
        other = Site.objects.create(code="LB9", name="Other",
                                    status=Site.Status.ACTIVE)
        outsider = make_user("se_lb9", User.Role.SITE_ENGINEER, site=other)
        self.client.force_authenticate(outsider)
        self.assertEqual(
            self.client.get(f"/api/v1/quality/tests/{ref}").status_code, 404)


class TestsInHandoverTests(TestCase):
    """The point of recording them: handover PULLS them like any other
    document instead of somebody uploading paper at the end."""

    def setUp(self):
        self.site = Site.objects.create(code="LB2", name="Handover lab",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_lb2", User.Role.PM, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE")
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/projects/{self.project.id}/handover")

    def _passed_test(self):
        ref = self.client.post("/api/v1/quality/tests", {
            "site_id": self.site.id, "project_id": self.project.id,
            "kind": "CUBE", "element": "Villa 3 slab",
            "sampled_on": str(date.today() - timedelta(days=30)),
            "required_value": "30.00", "unit": "N/mm2"},
            format="json").data["ref"]
        self.client.post(f"/api/v1/quality/tests/{ref}/results",
                         {"age_days": 28, "value": "35.00"}, format="json")
        return ref

    def test_a_passed_test_is_offered_to_the_handover_pack(self):
        ref = self._passed_test()
        rows = self.client.get(
            f"/api/v1/projects/{self.project.id}/handover/candidates").data
        self.assertEqual([r["ref"] for r in rows], [ref])
        self.assertEqual(rows[0]["suggested_section"], "TEST")

    def test_a_failed_test_is_never_offered_as_handover_evidence(self):
        ref = self.client.post("/api/v1/quality/tests", {
            "site_id": self.site.id, "project_id": self.project.id,
            "kind": "CUBE", "element": "Villa 4 slab",
            "sampled_on": str(date.today() - timedelta(days=30)),
            "required_value": "30.00"}, format="json").data["ref"]
        self.client.post(f"/api/v1/quality/tests/{ref}/results",
                         {"age_days": 28, "value": "12.00"}, format="json")
        rows = self.client.get(
            f"/api/v1/projects/{self.project.id}/handover/candidates").data
        self.assertEqual(rows, [])

    def test_pulling_it_in_links_the_record_rather_than_copying_it(self):
        ref = self._passed_test()
        doc = Document.objects.get(ref=ref)
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/handover/items",
            {"document_id": doc.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["section"], "TEST")
        self.assertEqual(r.data["document_ref"], ref)
        self.assertEqual(r.data["status"], "PROVIDED")

    def test_an_awaited_test_is_not_offered_yet(self):
        self.client.post("/api/v1/quality/tests", {
            "site_id": self.site.id, "project_id": self.project.id,
            "kind": "CUBE", "element": "Villa 5 slab",
            "sampled_on": str(date.today())}, format="json")
        rows = self.client.get(
            f"/api/v1/projects/{self.project.id}/handover/candidates").data
        self.assertEqual(rows, [])
