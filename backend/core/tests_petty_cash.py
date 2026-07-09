"""M6e — petty cash imprest system (§6B, §6C.3.3)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (CostHead, CostPosting, Document, PettyCashCycle,
                     PettyCashEntry, PettyCashFloat, Site, SitePmHistory, User)
from .tests import make_user


class PettyCashBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.finance = make_user("fin", User.Role.FINANCE)
        self.head = CostHead.objects.get(name="Transport & Freight")
        self.client = APIClient()

    def setup_float(self, imprest=20000, cap=1500):
        self.client.force_authenticate(self.finance)
        return self.client.put(f"/api/v1/petty-cash/{self.site.id}", {
            "imprest_amount": imprest, "custodian_id": self.sa.id,
            "trigger_pct": 30, "per_txn_cap": cap}, format="json")

    def add_entry(self, amount=500, **extra):
        self.client.force_authenticate(self.sa)
        body = {"amount": amount, "cost_head_id": self.head.id,
                "payee": "Boat crew", "purpose": "island trip",
                "has_receipt": True}
        body.update(extra)
        return self.client.post(f"/api/v1/petty-cash/{self.site.id}/entries",
                                body, format="multipart")


class PettyCashSetupTests(PettyCashBase):
    def test_finance_sets_up_float_and_opens_cycle(self):
        r = self.setup_float(20000)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(str(r.data["cash_in_hand"])),
                         Decimal("20000"))
        self.assertEqual(r.data["cycle_no"], 1)
        self.assertEqual(r.data["cycle_status"], "OPEN")

    def test_site_admin_cannot_set_up_float(self):
        self.client.force_authenticate(self.sa)
        r = self.client.put(f"/api/v1/petty-cash/{self.site.id}", {
            "imprest_amount": 5000, "custodian_id": self.sa.id},
            format="json")
        self.assertEqual(r.status_code, 403)


class PettyCashEntryTests(PettyCashBase):
    def setUp(self):
        super().setUp()
        self.setup_float(20000, cap=1500)

    def test_add_entry_reduces_cash_in_hand(self):
        r = self.add_entry(500)
        self.assertEqual(r.status_code, 201, r.data)
        self.client.force_authenticate(self.sa)
        s = self.client.get(
            f"/api/v1/petty-cash/{self.site.id}/entries").data["summary"]
        self.assertEqual(Decimal(str(s["cash_in_hand"])), Decimal("19500"))

    def test_over_cap_blocked(self):
        r = self.add_entry(2000)  # > 1500 cap
        self.assertEqual(r.status_code, 400)
        self.assertIn("cap", r.data["detail"].lower())

    def test_no_receipt_needs_reason(self):
        r = self.add_entry(300, has_receipt=False, no_receipt_reason="")
        self.assertEqual(r.status_code, 400)
        r = self.add_entry(300, has_receipt=False,
                           no_receipt_reason="informal porter")
        self.assertEqual(r.status_code, 201, r.data)

    def test_non_custodian_cannot_record(self):
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/petty-cash/{self.site.id}/entries",
                             {"amount": 100, "cost_head_id": self.head.id,
                              "payee": "x", "has_receipt": True},
                             format="multipart")
        self.assertEqual(r.status_code, 403)

    def test_pm_approve_posts_incurred_once(self):
        e1 = self.add_entry(500).data["id"]
        e2 = self.add_entry(300).data["id"]
        self.client.force_authenticate(self.pm)
        r = self.client.post(
            f"/api/v1/petty-cash/{self.site.id}/entries/approve",
            {"entry_ids": [e1, e2]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["approved"], 2)
        incurred = CostPosting.objects.filter(
            source="PETTY_CASH", state="INCURRED")
        self.assertEqual(incurred.count(), 2)
        self.assertEqual(sum(p.amount for p in incurred), Decimal("800"))


class PettyCashReplenishTests(PettyCashBase):
    def setUp(self):
        super().setUp()
        self.setup_float(20000, cap=1500)

    def _approved_entry(self, amount):
        eid = self.add_entry(amount).data["id"]
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/petty-cash/{self.site.id}/entries/approve",
                         {"entry_ids": [eid]}, format="json")
        return eid

    def test_replenish_needs_approved_entries(self):
        self.add_entry(500)  # recorded, not approved
        self.client.force_authenticate(self.sa)
        r = self.client.post(
            f"/api/v1/petty-cash/{self.site.id}/replenish", {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_replenish_pyr_amount_and_paid_restores_float(self):
        self._approved_entry(500)
        self._approved_entry(300)
        self.client.force_authenticate(self.sa)
        r = self.client.post(
            f"/api/v1/petty-cash/{self.site.id}/replenish", {}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        pyr_ref = r.data["pyr_ref"]
        pyr = Document.objects.get(ref=pyr_ref)
        self.assertEqual(pyr.payment_request.amount_requested,
                         Decimal("800"))
        self.assertEqual(pyr.payment_request.payment_type,
                         "PETTY_CASH_REPLENISH")
        # cycle now REQUESTED
        self.assertEqual(PettyCashCycle.objects.get(
            float__site=self.site, cycle_no=1).status, "REQUESTED")

        # Finance pays it (shortcut past the voucher chain by authorising
        # the doc directly — the pay action is what triggers restoration)
        pyr.status = "AUTHORISED"
        pyr.save(update_fields=["status"])
        pr = pyr.payment_request
        pr.authorised_by = self.finance
        pr.save(update_fields=["authorised_by"])
        self.client.force_authenticate(self.finance)
        pay = self.client.post(
            f"/api/v1/documents/{pyr_ref}/actions/pay",
            {"amount_paid": 800, "payment_ref": "TRF-PC-1"}, format="json")
        self.assertEqual(pay.status_code, 200, pay.data)

        # Paid leg posted per entry (not double-counting Incurred)
        pc = CostPosting.objects.filter(source="PETTY_CASH")
        self.assertEqual(pc.filter(state="INCURRED").count(), 2)
        self.assertEqual(pc.filter(state="PAID").count(), 2)
        self.assertEqual(sum(p.amount for p in pc.filter(state="PAID")),
                         Decimal("800"))
        # entries reimbursed, cycle 1 closed & immutable, cycle 2 open at full
        self.assertEqual(PettyCashEntry.objects.filter(
            status="REIMBURSED").count(), 2)
        c1 = PettyCashCycle.objects.get(float__site=self.site, cycle_no=1)
        self.assertEqual(c1.status, "REPLENISHED")
        self.assertEqual(c1.closing_float, Decimal("20000"))
        c2 = PettyCashCycle.objects.get(float__site=self.site, cycle_no=2)
        self.assertEqual(c2.status, "OPEN")
        # cash in hand back to full imprest
        self.client.force_authenticate(self.sa)
        s = self.client.get(f"/api/v1/petty-cash/{self.site.id}").data
        self.assertEqual(Decimal(str(s["cash_in_hand"])), Decimal("20000"))


class PettyCashReconcileTests(PettyCashBase):
    def setUp(self):
        super().setUp()
        self.setup_float(20000, cap=1500)

    def test_variance_requires_explanation(self):
        self.add_entry(500)
        self.client.force_authenticate(self.sa)
        # system balance is 19,500; count 19,400 → variance -100
        r = self.client.post(
            f"/api/v1/petty-cash/{self.site.id}/reconcile",
            {"counted_cash": 19400, "explanation": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(
            f"/api/v1/petty-cash/{self.site.id}/reconcile",
            {"counted_cash": 19400, "explanation": "MVR 100 note misplaced"},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(str(r.data["variance"])), Decimal("-100"))
