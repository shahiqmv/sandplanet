"""What currency a receivable is reported in.

Site.currency defaults to MVR and was never set on any site, while every
contract BOQ is USD — so every certified claim was reported as MVR and the
aging totalled USD money under an MVR heading (owner 2026-09-01).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from . import receivables
from .models import Boq, ProgressClaim, Project, Site, User
from .tests import make_user


class ContractCurrencyTests(TestCase):
    def setUp(self):
        self.qs = make_user("qs_ccy", User.Role.QS)
        # As every real site is: the MVR default, never changed.
        self.site = Site.objects.create(code="CCY", name="Ccy site",
                                        status=Site.Status.ACTIVE,
                                        currency="MVR")

    def _project(self, code, boq_ccy="USD"):
        p = Project.objects.create(site=self.site, code=code, title=code,
                                   status="ACTIVE",
                                   contract_value=Decimal("100000"))
        if boq_ccy:
            Boq.objects.create(project=p, currency=boq_ccy)
        return p

    def _claim(self, project, no):
        return ProgressClaim.objects.create(
            project=project, seq=1, ref="IPA-01", claim_type="ADVANCE",
            basis="PERCENT", status="CERTIFIED", invoice_no=no,
            certified_at="2026-09-01T00:00:00Z", created_by=self.qs)

    def test_the_contract_decides_not_the_site(self):
        p = self._project("USDP", "USD")
        self.assertEqual(receivables.contract_currency(p), "USD")

    def test_a_genuinely_mvr_contract_is_still_mvr(self):
        """The MRA case the aging split was built for."""
        p = self._project("MVRP", "MVR")
        self.assertEqual(receivables.contract_currency(p), "MVR")

    def test_without_a_boq_the_site_is_the_fallback(self):
        """Nothing records a contract currency, so the field it stood in for
        is what is left."""
        p = self._project("NOBOQ", None)
        self.assertEqual(receivables.contract_currency(p), "MVR")

    def test_a_claim_is_aged_in_the_contract_currency(self):
        p = self._project("USDP", "USD")
        self._claim(p, "INV-T-0001")
        rows = receivables.invoice_rows(site_id=self.site.id)
        self.assertEqual([r["currency"] for r in rows], ["USD"])

    def test_two_contracts_on_one_site_are_reported_separately(self):
        """One client can hold contracts in both — the ledger must not
        blend them, which is what the per-currency split is for."""
        self._claim(self._project("USDP", "USD"), "INV-T-0001")
        self._claim(self._project("MVRP", "MVR"), "INV-T-0002")
        rows = receivables.invoice_rows(site_id=self.site.id)
        by_no = {r["invoice_no"]: r["currency"] for r in rows}
        self.assertEqual(by_no["INV-T-0001"], "USD")
        self.assertEqual(by_no["INV-T-0002"], "MVR")

    def test_the_statement_follows_the_contracts(self):
        self._project("USDP", "USD")
        self._project("USDQ", "USD")
        self.assertEqual(
            receivables.client_statement(self.site)["currency"], "USD")

    def test_a_site_with_no_projects_falls_back_to_its_own_field(self):
        empty = Site.objects.create(code="EMP", name="Empty",
                                    status=Site.Status.ACTIVE, currency="MVR")
        self.assertEqual(
            receivables.client_statement(empty)["currency"], "MVR")
