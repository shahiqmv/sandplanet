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


class ClaimBilledByInvoicesTests(TestCase):
    """The other way round: SFR CASUAL's 40% advance (IPA-01) went to the
    client as two invoices — 20% at the LOA, the balance once the policy
    documents were in. The claim keeps the certificate (the next IPC reads
    its advance from it); the invoices are the receivables (owner
    2026-10-24)."""

    def setUp(self):
        from .commercial import _q2, claim_valuation
        self.site = Site.objects.create(code="BIL", name="Billed site",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(
            site=self.site, code="CASUAL", title="Casual Accommodation",
            status="ACTIVE", contract_value=Decimal("830844.83"),
            advance_payment_pct=Decimal("40"))
        Boq.objects.create(project=self.project, currency="USD")
        self.qs = make_user("qs_bil", User.Role.QS)
        self.pd = make_user("pd_bil", User.Role.DIRECTOR)
        self.fin = make_user("fin_bil", User.Role.FINANCE)
        self.claim = ProgressClaim.objects.create(
            project=self.project, seq=1, ref="IPA-01", claim_type="ADVANCE",
            basis="PERCENT", advance_pct=Decimal("40"), gst_pct=Decimal("8"),
            status="DRAFT", created_by=self.qs)
        set_claim_status(self.claim, "SUBMITTED", self.qs)
        set_claim_status(self.claim, "CERTIFIED", self.pd)
        self.claim.refresh_from_db()
        self.due = _q2(claim_valuation(self.claim)["waterfall"]["net_to_pay"])
        half = _q2(self.due / 2)
        self.first = self._inv("INV-2026-0029", half, date(2026, 9, 1))
        # the split rounds: the two halves come a cent over the claim
        self.balance = self._inv("INV-2026-0055",
                                 self.due - half + Decimal("0.01"),
                                 date(2026, 10, 12))
        ClientReceipt.objects.create(project=self.project,
                                     manual_invoice=self.first, amount=half,
                                     received_on=date(2026, 9, 6))

    def _inv(self, no, amount, on):
        return ManualInvoice.objects.create(
            project=self.project, origin="ISSUED", invoice_no=no,
            invoice_date=on, currency="USD", gst_pct=Decimal("0"),
            net_amount=amount, gst_amount=Decimal("0"), amount=amount,
            description="Advance", created_by=self.qs)

    def _rows(self):
        return {r["invoice_no"]: r for r in
                receivables.invoice_rows(site_id=self.site.id)}

    def test_before_the_link_the_advance_is_billed_twice(self):
        self.assertTrue(self.claim.invoice_no)
        self.assertEqual(len(self._rows()), 3)

    def test_the_invoices_bill_the_claim_and_its_own_invoice_is_dropped(self):
        claim_no = self.claim.invoice_no
        err = mi_svc.bill_claim_by(self.claim, [self.first, self.balance],
                                   self.qs, drop_claim_invoice=True)
        self.assertIsNone(err, err)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.invoice_no, "")
        rows = self._rows()
        self.assertEqual(set(rows), {"INV-2026-0029", "INV-2026-0055"})
        self.assertNotIn(claim_no, rows)
        self.assertEqual(rows["INV-2026-0029"]["outstanding"], 0)
        self.assertEqual(self.claim.status, "CERTIFIED")      # half paid
        # re-certifying never issues it a number again
        set_claim_status(self.claim, "DRAFT", make_user("adm_bil",
                                                         User.Role.ADMIN))
        set_claim_status(self.claim, "SUBMITTED", self.qs)
        set_claim_status(self.claim, "CERTIFIED", self.pd)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.invoice_no, "")
        # paying the balance through an official receipt settles the claim
        from .receipts import create_official_receipt
        rec, err = create_official_receipt({
            "site": self.site.id, "receipt_date": "2026-10-20",
            "method": "TT", "allocations": [
                {"manual_invoice_id": self.balance.id,
                 "amount": str(self.balance.amount)}]}, self.fin)
        self.assertIsNone(err, err)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, "PAID")

    def test_invoices_that_do_not_add_up_are_refused(self):
        err = mi_svc.bill_claim_by(self.claim, [self.first], self.qs)
        self.assertIn("must match", err)
