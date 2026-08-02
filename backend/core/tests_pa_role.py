"""Personal Assistant — Director's Office (PA) role (owner 2026-08-01).

She runs the meeting module (custodian), does onboarding data entry and keeps
the company profile current, and reads across projects/commercials to support
the PD — but is NOT a purchasing, finance, site-ops or user-admin operator.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from . import meetings as msvc
from . import onboarding as osvc
from . import profile as psvc
from .models import Project, Site, User
from .tests import make_user
from .views_cost import COST_ROLES
from .views_receivables import RECEIPT_ROLES, RECEIVABLE_ROLES


class PARoleTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="PAX", name="Pax",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(site=self.site, code="PAX-01",
                                              title="Test")
        self.pa = make_user("pa1", User.Role.PA)
        self.client = APIClient()
        self.client.force_authenticate(self.pa)

    def test_pa_has_all_site_read_scope(self):
        self.assertTrue(self.pa.is_ho)          # reads across every site/project

    def test_pa_is_meeting_custodian_and_can_schedule(self):
        self.assertTrue(msvc.is_custodian(self.pa))
        r = self.client.post("/api/v1/meetings", {
            "title": "PD weekly sync", "meeting_type": "PROJECT",
            "project_id": self.project.id,
            "scheduled_at": "2026-08-10T09:00:00Z"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_pa_does_onboarding_entry_but_not_approval(self):
        self.assertIn("PA", osvc.RAISE_ROLES)       # enters candidate/joining data
        self.assertNotIn("PA", osvc.APPROVE_ROLES)  # Director still approves
        self.assertNotIn("PA", osvc.PROCESS_ROLES)  # HR still processes visas

    def test_pa_maintains_company_profile(self):
        self.assertIn("PA", psvc.PROFILE_ROLES)

    def test_pa_reads_money_screens_but_not_finance_ops(self):
        self.assertIn("PA", RECEIVABLE_ROLES)   # sees receivables/aging/statements
        self.assertNotIn("PA", RECEIPT_ROLES)   # can't issue/void receipts
        self.assertIn("PA", COST_ROLES)         # sees project cost/portfolio

    def test_pa_cannot_raise_site_documents(self):
        r = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id, "doc_date": "2026-08-02",
            "payload": {"lines": [{"description": "Cement", "qty": "1",
                                   "unit": "bag"}]}}, format="json")
        self.assertEqual(r.status_code, 403, getattr(r, "data", None))
