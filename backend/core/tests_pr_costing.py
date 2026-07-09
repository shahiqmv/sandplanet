"""M6c — PR signatory gate + cost postings (§6C.2, §4A, §7.5)."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import costing
from .models import (CompanyParameter, CostPosting, Document, Payable,
                     Site, SitePmHistory, User)
from .tests import make_user


class PrCostingBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE,
                                        start_date=date.today() -
                                        timedelta(days=30))
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.purchasing = make_user("hop", User.Role.HO_PURCHASING)
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.signatory = make_user("sig", User.Role.SIGNATORY)
        self.finance = make_user("fin", User.Role.FINANCE)
        self.client = APIClient()

    def act(self, ref, action, user, **body):
        self.client.force_authenticate(user)
        return self.client.post(f"/api/v1/documents/{ref}/actions/{action}",
                                body, format="json")

    def make_pr(self):
        # MR first (a PR answers an MR)
        self.client.force_authenticate(self.sa)
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id, "payload": {},
            "lines": [{"free_text_desc": "Cement", "unit": "bag",
                       "qty_required": 100, "qty_to_order": 100}],
        }, format="json").data
        self.act(mr["ref"], "submit", self.sa)
        self.act(mr["ref"], "approve", self.pm)
        self.act(mr["ref"], "send", self.sa)
        self.client.force_authenticate(self.purchasing)
        pr = self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "mr_refs": [mr["ref"]],
            "lines": [
                {"free_text_desc": "Vendor A", "vendor": "Vendor A",
                 "amount_cash": 5000},
                {"free_text_desc": "Vendor B", "vendor": "Vendor B",
                 "amount_credit": 7000},
            ],
        }, format="json").data
        self.act(pr["ref"], "submit", self.purchasing)
        self.act(pr["ref"], "approve", self.director)
        return Document.objects.get(ref=pr["ref"])


class PrAuthorisationTests(PrCostingBase):
    def test_commit_posts_at_authorisation_not_approval(self):
        pr = self.make_pr()
        # Director-approved: nothing committed yet
        self.assertEqual(CostPosting.objects.filter(document=pr).count(), 0)
        r = self.act(pr.ref, "authorise", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "AUTHORISED")
        # COMMITTED per vendor line, netting to the grand total
        committed = costing.document_net(pr, state="COMMITTED")
        self.assertEqual(committed, Decimal("12000"))
        # a payable was created for the credit vendor only
        self.assertEqual(Payable.objects.filter(document=pr).count(), 1)
        self.assertEqual(Payable.objects.get(document=pr).amount,
                         Decimal("7000"))
        # POs generated at authorisation (none here — free-text vendors,
        # no quotes) but the flow ran without error

    def test_finance_cannot_authorise_when_threshold_disabled(self):
        pr = self.make_pr()
        r = self.act(pr.ref, "authorise", self.finance)
        self.assertEqual(r.status_code, 403)

    def test_finance_authorises_below_threshold(self):
        CompanyParameter.objects.create(key="signatory_threshold",
                                        value=20000)
        pr = self.make_pr()  # total 12000 < 20000
        r = self.act(pr.ref, "authorise", self.finance)
        self.assertEqual(r.status_code, 200, r.data)

    def test_withdrawal_reverses_commitment(self):
        pr = self.make_pr()
        self.act(pr.ref, "authorise", self.signatory)
        self.assertEqual(costing.document_net(pr), Decimal("12000"))
        r = self.act(pr.ref, "withdraw-authorisation", self.finance,
                     comment="wrong vendor account")
        self.assertEqual(r.status_code, 200, r.data)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "DRAFT")
        self.assertEqual(costing.document_net(pr), Decimal("0"))
        self.assertEqual(Payable.objects.get(document=pr).status, "CANCELLED")

    def test_payment_posts_paid_and_settles_payable(self):
        pr = self.make_pr()
        self.act(pr.ref, "authorise", self.signatory)
        lines = list(pr.current_revision.lines.all())
        credit_line = next(l for l in lines if (l.amount_credit or 0) > 0)
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/pr/{pr.ref}/vendor-payment",
                             {"line_id": credit_line.id,
                              "payment_ref": "VCH-9"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(costing.document_net(pr, state="PAID"),
                         Decimal("7000"))
        self.assertEqual(Payable.objects.get(document=pr).status, "SETTLED")
