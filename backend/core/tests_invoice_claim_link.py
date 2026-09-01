"""An invoice raised ahead of the claim that covers it.

Work is often billed before the claim covering it can be raised — an advance
against a signed LOA, where the bonds and the advance claim take weeks, so the
QS invoices it directly. When that claim is eventually certified it bills the
same money, and receivables reads certified claims AND manual invoices: the
client would owe it twice (owner 2026-09-01, SFR CASUAL / INV-2026-0026).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from . import manual_invoices as mi_svc
from . import receivables
from .commercial import set_claim_status
from .models import (Boq, ClientReceipt, ManualInvoice, ProgressClaim, Project,
                     Site, User)
from .tests import make_user


class InvoiceSupersededByClaimTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="LNK", name="Link site",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(
            site=self.site, code="CASUAL", title="Casual Accommodation",
            status="ACTIVE", contract_value=Decimal("830844.83"))
        Boq.objects.create(project=self.project, currency="USD")
        self.qs = make_user("qs_lnk", User.Role.QS)
        self.pd = make_user("pd_lnk", User.Role.DIRECTOR)
        self.mi = ManualInvoice.objects.create(
            project=self.project, origin="ISSUED",
            invoice_no="INV-2026-0026", invoice_date=date(2026, 9, 1),
            currency="USD", gst_pct=Decimal("0"),
            net_amount=Decimal("166168.97"), gst_amount=Decimal("0"),
            amount=Decimal("166168.97"),
            description="20% advance against LOA", created_by=self.qs)
        self.claim = ProgressClaim.objects.create(
            project=self.project, seq=1, ref="IPA-01", claim_type="ADVANCE",
            basis="PERCENT", gst_pct=Decimal("0"), status="DRAFT",
            created_by=self.qs)

    def _outstanding_refs(self):
        return {r["invoice_no"] for r in receivables.invoice_rows(
            site_id=self.site.id)}

    # ---- linking ---------------------------------------------------------

    def test_an_invoice_can_be_linked_to_the_claim_that_covers_it(self):
        self.assertIsNone(
            mi_svc.link_to_claim(self.mi, self.claim, self.qs))
        self.mi.refresh_from_db()
        self.assertEqual(self.mi.superseded_by, self.claim)
        # Not closed yet — the claim has not billed anything.
        self.assertIsNone(self.mi.superseded_at)
        self.assertIn("INV-2026-0026", self._outstanding_refs())

    def test_certifying_the_claim_closes_the_invoice(self):
        """The moment the same money is billed a second time."""
        mi_svc.link_to_claim(self.mi, self.claim, self.qs)
        set_claim_status(self.claim, "SUBMITTED", self.qs)
        set_claim_status(self.claim, "CERTIFIED", self.pd)
        self.mi.refresh_from_db()
        self.assertIsNotNone(self.mi.superseded_at)
        self.assertNotIn("INV-2026-0026", self._outstanding_refs())

    def test_linking_an_already_certified_claim_closes_it_at_once(self):
        """There is no later moment to wait for — the second bill exists."""
        set_claim_status(self.claim, "SUBMITTED", self.qs)
        set_claim_status(self.claim, "CERTIFIED", self.pd)
        mi_svc.link_to_claim(self.mi, self.claim, self.qs)
        self.mi.refresh_from_db()
        self.assertIsNotNone(self.mi.superseded_at)

    def test_reopening_the_claim_reopens_the_invoice(self):
        """An invoice must not sit closed against a certificate that no
        longer stands."""
        mi_svc.link_to_claim(self.mi, self.claim, self.qs)
        set_claim_status(self.claim, "SUBMITTED", self.qs)
        set_claim_status(self.claim, "CERTIFIED", self.pd)
        admin = make_user("adm_lnk", User.Role.ADMIN)
        set_claim_status(self.claim, "DRAFT", admin)
        self.mi.refresh_from_db()
        self.assertIsNone(self.mi.superseded_at)
        self.assertIn("INV-2026-0026", self._outstanding_refs())

    def test_it_can_be_unlinked(self):
        mi_svc.link_to_claim(self.mi, self.claim, self.qs)
        self.assertIsNone(mi_svc.unlink_from_claim(self.mi, self.qs))
        self.mi.refresh_from_db()
        self.assertIsNone(self.mi.superseded_by_id)

    # ---- the guards ------------------------------------------------------

    def test_a_claim_on_another_project_is_refused(self):
        other = Project.objects.create(site=self.site, code="OTHER",
                                       title="Other", status="ACTIVE")
        theirs = ProgressClaim.objects.create(
            project=other, seq=1, ref="IPA-01", claim_type="ADVANCE",
            basis="PERCENT", status="DRAFT", created_by=self.qs)
        msg = mi_svc.link_to_claim(self.mi, theirs, self.qs)
        self.assertIn("OTHER", msg)

    def test_an_invoice_with_a_receipt_is_refused(self):
        """Closing it would leave the client's cash pointing at something no
        longer owed, and the claim showing unpaid."""
        ClientReceipt.objects.create(
            project=self.project, manual_invoice=self.mi,
            amount=Decimal("50000"), currency="USD",
            received_on=date(2026, 9, 5), recorded_by=self.qs)
        msg = mi_svc.link_to_claim(self.mi, self.claim, self.qs)
        self.assertIn("move them", msg)

    def test_a_second_claim_cannot_take_an_already_linked_invoice(self):
        mi_svc.link_to_claim(self.mi, self.claim, self.qs)
        second = ProgressClaim.objects.create(
            project=self.project, seq=2, ref="IPA-02", claim_type="INTERIM",
            basis="PERCENT", status="DRAFT", created_by=self.qs)
        self.assertIn("already linked",
                      mi_svc.link_to_claim(self.mi, second, self.qs))

    def test_a_void_invoice_cannot_be_linked(self):
        self.mi.is_void = True
        self.mi.save(update_fields=["is_void"])
        self.assertIn("void", mi_svc.link_to_claim(self.mi, self.claim,
                                                   self.qs))

    def test_only_the_billing_roles_may_link(self):
        outsider = make_user("se_lnk", User.Role.SITE_ENGINEER,
                             site=self.site)
        self.assertIn("can't change",
                      mi_svc.link_to_claim(self.mi, self.claim, outsider))
