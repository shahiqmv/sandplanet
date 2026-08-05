"""M6b — PYR workflow + cost postings (§5.9, §7.5, §4A)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (CostHead, CostPosting, Document, Site, SitePmHistory,
                     User)
from .tests import make_user


class PyrBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.signatory = make_user("sig", User.Role.SIGNATORY)
        self.finance = make_user("fin", User.Role.FINANCE)
        self.head = CostHead.objects.get(name="Transport & Freight")
        self.client = APIClient()

    def raise_pyr(self, amount=3000, **extra):
        self.client.force_authenticate(self.sa)
        body = {
            "doc_type": "PYR", "site_id": self.site.id, "payload": {},
            "cost_head_id": self.head.id, "payee": "Island Boat Services",
            "payment_type": "DIRECT", "payment_method": "BANK",
            "amount_requested": amount, "purpose": "Boat hire for loading",
            "has_supporting_doc": True,
        }
        body.update(extra)
        return self.client.post("/api/v1/documents", body, format="json")

    def act(self, ref, action, user, **data):
        self.client.force_authenticate(user)
        return self.client.post(f"/api/v1/documents/{ref}/actions/{action}",
                                data, format="json")

    def authorise(self, ref, approver=None):
        """Authorise a Director-approved PYR the M6d way: Finance builds a
        payment voucher, a signatory approves it. Returns the approve
        response."""
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [ref]}, format="json")
        assert pv.status_code == 201, pv.data
        pref = pv.data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pref}/actions/submit",
                         {}, format="json")
        self.client.force_authenticate(approver or self.signatory)
        return self.client.post(
            f"/api/v1/payment-vouchers/{pref}/actions/approve", {},
            format="json")

    def committed(self, doc_id):
        return CostPosting.objects.filter(document_id=doc_id,
                                          state="COMMITTED",
                                          reversal_of__isnull=True)


class PyrHappyPathTests(PyrBase):
    def test_full_chain_posts_committed_then_incurred_paid(self):
        r = self.raise_pyr(amount=3000)
        self.assertEqual(r.status_code, 201, r.data)
        ref = r.data["ref"]
        self.assertEqual(ref, "PYR-VKR-001")

        self.assertEqual(self.act(ref, "submit", self.sa).status_code, 200)
        self.assertEqual(self.act(ref, "approve", self.pm).status_code, 200)
        self.assertEqual(self.act(ref, "approve",
                                  self.director).status_code, 200)
        # nothing posts before authorisation
        doc = Document.objects.get(ref=ref)
        self.assertEqual(CostPosting.objects.filter(document=doc).count(), 0)

        r = self.authorise(ref)
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "AUTHORISED")
        # COMMITTED posted at authorisation (on the voucher)
        c = self.committed(doc.id)
        self.assertEqual(c.count(), 1)
        self.assertEqual(c.first().amount, Decimal("3000"))

        r = self.act(ref, "pay", self.finance, payment_ref="TRF-99",
                     amount_paid=3000)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "PAID")
        self.assertEqual(CostPosting.objects.filter(
            document=doc, state="INCURRED").count(), 1)
        self.assertEqual(CostPosting.objects.filter(
            document=doc, state="PAID").count(), 1)

    def test_finance_attaches_payment_slip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        ref = self.raise_pyr(amount=3000).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        self.authorise(ref)
        self.client.force_authenticate(self.finance)
        with override_settings(MEDIA_ROOT="test-media"):
            slip = SimpleUploadedFile("trf.pdf", b"%PDF slip",
                                      content_type="application/pdf")
            r = self.client.post(
                f"/api/v1/documents/{ref}/actions/pay",
                {"amount_paid": 3000, "payment_ref": "TRF-77", "file": slip},
                format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "PAID")
        self.assertTrue(any(a["kind"] == "PAYMENT_SLIP"
                            for a in r.data["attachments"]))

    def test_pay_variance_requires_reason(self):
        ref = self.raise_pyr(amount=3000).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        self.authorise(ref)
        r = self.act(ref, "pay", self.finance, amount_paid=2500)
        self.assertEqual(r.status_code, 400)
        r = self.act(ref, "pay", self.finance, amount_paid=2500,
                     variance_reason="agreed rebate")
        self.assertEqual(r.status_code, 200, r.data)


class PyrVoucherAuthTests(PyrBase):
    """M6d — authorisation happens only on a payment voucher, and Finance
    cannot approve its own voucher (no self-authorisation)."""

    def _to_director_approved(self, amount):
        ref = self.raise_pyr(amount=amount).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        return ref

    def test_direct_authorise_action_is_retired(self):
        ref = self._to_director_approved(3000)
        r = self.act(ref, "authorise", self.signatory)
        self.assertEqual(r.status_code, 400)
        self.assertIn("payment voucher", r.data["detail"].lower())

    def test_finance_cannot_approve_own_voucher(self):
        ref = self._to_director_approved(3000)
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [ref]}, format="json").data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pv}/actions/submit", {},
                         format="json")
        # Finance cannot approve — that is the signatory's job
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv}/actions/approve", {},
            format="json")
        self.assertEqual(r.status_code, 403)
        # a signatory approves → the PYR commits and becomes payable
        self.client.force_authenticate(self.signatory)
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv}/actions/approve", {},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Document.objects.get(ref=ref).status, "AUTHORISED")


class PyrReturnPathTests(PyrBase):
    def test_return_before_authorisation_posts_nothing(self):
        ref = self.raise_pyr(amount=3000).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        # director returns for review
        r = self.act(ref, "return", self.director,
                     reason_category="INCORRECT_DETAILS",
                     note="Wrong payee account — fix and resubmit.")
        self.assertEqual(r.status_code, 200, r.data)
        doc = Document.objects.get(ref=ref)
        self.assertEqual(doc.status, "DRAFT")
        self.assertEqual(CostPosting.objects.filter(document=doc).count(), 0)
        self.assertEqual(doc.payment_request.returned_reason,
                         "INCORRECT_DETAILS")

    def test_withdraw_authorisation_reverses_to_zero(self):
        from . import costing
        ref = self.raise_pyr(amount=3000).data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        self.authorise(ref)
        doc = Document.objects.get(ref=ref)
        self.assertEqual(costing.document_net(doc), Decimal("3000"))
        r = self.act(ref, "withdraw-authorisation", self.finance,
                     note="Duplicate found in the ledger.")
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "DRAFT")
        self.assertEqual(costing.document_net(doc), Decimal("0"))
        # a PM cannot withdraw — Finance only
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        self.authorise(ref)
        self.assertEqual(self.act(ref, "withdraw-authorisation",
                                  self.pm, note="x").status_code, 403)


class PyrSupportingDocTests(PyrBase):
    def test_above_threshold_needs_doc_or_override(self):
        # 8000 > 5000 default, no supporting doc, no override → blocked
        ref = self.raise_pyr(amount=8000, has_supporting_doc=False,
                             no_doc_reason="informal labour").data["ref"]
        r = self.act(ref, "submit", self.sa)
        self.assertEqual(r.status_code, 400)
        self.assertIn("supporting document", r.data["detail"].lower())

    def test_no_doc_needs_reason(self):
        ref = self.raise_pyr(amount=1000, has_supporting_doc=False,
                             no_doc_reason="").data["ref"]
        r = self.act(ref, "submit", self.sa)
        self.assertEqual(r.status_code, 400)


class CentralPaymentTests(PyrBase):
    """Head-Office (central) payment requests + two-currency mode
    (owner 2026-07-13)."""

    def setUp(self):
        super().setUp()
        self.ho = make_user("hop", User.Role.HO_PURCHASING)

    def raise_by(self, user, **extra):
        self.client.force_authenticate(user)
        body = {"doc_type": "PYR", "site_id": self.site.id, "payload": {},
                "cost_head_id": self.head.id, "payee": "Landlord Ltd",
                "payment_type": "DIRECT", "payment_method": "BANK",
                "amount_requested": 1000, "purpose": "Office rent",
                "has_supporting_doc": True}
        body.update(extra)
        return self.client.post("/api/v1/documents", body, format="json")

    def test_site_cannot_request_usd(self):
        r = self.raise_pyr(amount=1000, currency="USD")
        self.assertEqual(r.status_code, 400)
        self.assertIn("MVR only", r.data["detail"])

    def test_central_clears_to_voucher_on_submit(self):
        # A Head-Office (central) request skips BOTH the PM and the Director —
        # on submit it clears straight to a Payment Voucher for Finance, with
        # no Director step (owner 2026-07-31).
        ref = self.raise_by(self.ho).data["ref"]
        r = self.act(ref, "submit", self.ho)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "DIRECTOR_APPROVED")

    def test_commercial_costhead_clears_straight_to_finance(self):
        # A PYR on a commercial cost head (Insurance & Bonds) carries no approval
        # layer — not the site PM and not the Director; on submit it clears
        # straight to Finance's voucher, even when a site user raises it (owner
        # 2026-08-05, revised from the earlier Director step).
        ch = CostHead.objects.create(name="Insurance & Bonds z", commercial=True)
        ref = self.raise_pyr(cost_head_id=ch.id).data["ref"]
        pr = Document.objects.get(ref=ref).payment_request
        self.assertEqual(pr.origin, "COMMERCIAL")          # not SITE
        # submit → clears straight to DIRECTOR_APPROVED (ready for the voucher)
        self.assertEqual(self.act(ref, "submit", self.sa).data["status"],
                         "DIRECTOR_APPROVED")

    def test_ho_purchasing_pyr_lands_in_finance_voucher_queue(self):
        # The full "where does it land" proof: an HO Purchasing request, once
        # submitted, sits in Finance's build-a-voucher queue and can be
        # vouchered through with no Director step (owner 2026-07-31).
        from .views_documents import pending_groups
        from .vouchers import awaiting_voucher
        ref = self.raise_by(self.ho).data["ref"]
        self.act(ref, "submit", self.ho)
        self.assertIn(ref, [d.ref for d in awaiting_voucher()])
        group = next(g for g in pending_groups(self.finance)
                     if g["title"] == "Awaiting a payment voucher")
        self.assertIn(ref, [r["ref"] for r in group["items"]])
        # Finance builds the voucher, the signatory approves → PYR authorised
        self.assertEqual(self.authorise(ref).status_code, 200)

    def test_requester_can_list_their_own_pyrs_after_submit(self):
        # The gap this closes: a Head-Office request used to vanish on submit.
        # mine=1 lets the raiser follow it — and it excludes others' requests.
        mine = self.raise_by(self.ho).data["ref"]
        self.act(mine, "submit", self.ho)
        other = self.raise_pyr().data["ref"]          # raised by the site admin
        self.client.force_authenticate(self.ho)
        r = self.client.get("/api/v1/documents/list?doc_type=PYR&mine=1")
        self.assertEqual(r.status_code, 200)
        refs = [d["ref"] for d in r.data]
        self.assertIn(mine, refs)
        self.assertNotIn(other, refs)

    def test_central_submit_does_not_notify_the_director(self):
        # The auto-clear must not leave a transient "needs Director approval"
        # ping in the Director's feed.
        from .models import Notification
        ref = self.raise_by(self.ho).data["ref"]
        self.act(ref, "submit", self.ho)
        self.assertFalse(Notification.objects.filter(
            recipient=self.director, doc_ref=ref,
            title__icontains="Director").exists())

    def test_finance_initiated_clears_to_voucher_on_submit(self):
        ref = self.raise_by(self.finance, currency="USD").data["ref"]
        r = self.act(ref, "submit", self.finance)
        self.assertEqual(r.status_code, 200, r.data)
        # Accounts-initiated: no Director step — straight to the voucher queue
        self.assertEqual(r.data["status"], "DIRECTOR_APPROVED")

    def test_usd_pay_posts_mvr_at_rate(self):
        ref = self.raise_by(self.finance, currency="USD",
                            amount_requested=100).data["ref"]
        self.act(ref, "submit", self.finance)          # → DIRECTOR_APPROVED
        self.assertEqual(self.authorise(ref).status_code, 200)
        r = self.act(ref, "pay", self.finance, amount_paid=100,
                     fx_rate="15", payment_ref="TT-USD-1")
        self.assertEqual(r.status_code, 200, r.data)
        paid = CostPosting.objects.get(document__ref=ref, state="PAID")
        self.assertEqual(float(paid.amount), 1500.0)   # 100 USD * 15
        self.assertEqual(paid.currency, "MVR")

    def test_voucher_rejects_mixed_currency(self):
        # a site MVR request, Director-approved
        mvr = self.raise_pyr(amount=1000).data["ref"]
        self.act(mvr, "submit", self.sa)
        self.act(mvr, "approve", self.pm)
        self.act(mvr, "approve", self.director)
        # an Accounts USD request, cleared to voucher
        usd = self.raise_by(self.finance, currency="USD").data["ref"]
        self.act(usd, "submit", self.finance)
        self.client.force_authenticate(self.finance)
        r = self.client.post("/api/v1/payment-vouchers",
                             {"source_refs": [mvr, usd]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("single currency", r.data["detail"])


class CoPmTests(PyrBase):
    """A busy site can carry more than one PM; co-PMs share full PM authority
    (approvals + alerts). (owner 2026-08-05)"""

    def _add_co_pm(self):
        admin = make_user("adm_copm", User.Role.ADMIN)
        pm2 = make_user("pm2", User.Role.PM, site=self.site)
        self.client.force_authenticate(admin)
        r = self.client.post(f"/api/v1/sites/{self.site.id}/assign-pm",
                             {"pm_user_id": pm2.id, "mode": "add"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return pm2

    def test_co_pm_shares_approval_and_alerts(self):
        from .models import Notification
        pm2 = self._add_co_pm()
        self.site.refresh_from_db()
        self.assertEqual({p.id for p in self.site.current_pms()},
                         {self.pm.id, pm2.id})
        self.assertTrue(self.site.is_current_pm(pm2))
        # add (not replace) keeps the original PM as the primary for display
        self.assertEqual(self.site.current_pm().id, self.pm.id)

        ref = self.raise_pyr().data["ref"]
        Notification.objects.all().delete()
        self.act(ref, "submit", self.sa)
        notified = set(Notification.objects.filter(doc_ref=ref)
                       .values_list("recipient_id", flat=True))
        self.assertIn(self.pm.id, notified)       # both PMs alerted
        self.assertIn(pm2.id, notified)
        # the co-PM (not the first-assigned) can approve
        r = self.act(ref, "approve", pm2)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "PM_APPROVED")

    def test_remove_co_pm_leaves_the_other(self):
        pm2 = self._add_co_pm()
        r = self.client.post(f"/api/v1/sites/{self.site.id}/assign-pm",
                             {"pm_user_id": pm2.id, "mode": "remove"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.site.refresh_from_db()
        self.assertFalse(self.site.is_current_pm(pm2))
        self.assertTrue(self.site.is_current_pm(self.pm))   # original remains
