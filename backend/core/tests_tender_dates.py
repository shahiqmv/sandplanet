"""The date an offer carries is the day it was sent for approval.

It printed the day the enquiry was opened until the offer was issued, then
the day of issue: the document the approvers signed off was dated weeks
before it was priced, and changed its date when it went out. The date is now
fixed with the value when the offer goes up (owner 2026-11-26).
"""
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import tenders as svc
from .models import AuditLog, Site, Tender, User
from .tests import make_user
from .tests_tenders import GateMixin

TODAY = timezone.localdate()
SENT = TODAY - timedelta(days=9)


def on(day):
    """Run as if today were `day`."""
    return patch("django.utils.timezone.localdate", return_value=day)


class OfferDateTests(GateMixin, TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="HDR", name="Hudhuranfushi",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("od_qs", User.Role.QS)
        self.make_approvers("od")
        self.client = APIClient()
        self.client.force_authenticate(self.qs)
        self.t = self.client.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "Aitken Spence",
            "title": "Water villas", "enquiry_date": "2026-10-01"},
            format="json").data
        self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                         {"rows": [{"description": "Works", "unit": "item",
                                    "qty": "1", "unit_cost": "1",
                                    "rate_combined": "500"}]}, format="json")

    def tender(self):
        return Tender.objects.get(pk=self.t["id"])

    def printed(self):
        return svc.submission_context(self.tender())["issue_date"]

    def send(self, day):
        with on(day):
            r = self.client.post(
                f"/api/v1/tenders/{self.t['id']}/send-for-approval",
                {"value": "500"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_an_offer_still_being_priced_carries_todays_date_not_the_enquirys(self):
        self.assertEqual(svc.offer_date(self.tender()), TODAY)
        self.assertNotEqual(svc.offer_date(self.tender()), date(2026, 10, 1))

    def test_the_date_is_fixed_when_the_offer_is_sent_up_and_stays(self):
        self.send(SENT)
        self.assertEqual(svc.offer_date(self.tender()), SENT)
        self.assertEqual(self.printed(), SENT.strftime("%d %B %Y"))
        # approved, cleared and issued days later: the same document, the same date
        r = self.approve_through(self.t["id"])
        self.assertEqual(r.status_code, 200, r.data)
        t = self.tender()
        self.assertEqual(t.document.status, "ISSUED")
        self.assertEqual(timezone.localtime(
            t.document.current_revision.issued_at).date(), TODAY)
        self.assertEqual(svc.offer_date(t), SENT)

    def test_sent_back_it_is_being_priced_again_and_takes_a_new_date_when_resent(self):
        self.send(SENT)
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/tenders/{self.t['id']}/return",
                             {"comment": "Check the prelims"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(svc.offer_date(self.tender()), TODAY)
        self.client.force_authenticate(self.qs)
        again = SENT + timedelta(days=4)
        self.send(again)
        self.assertEqual(svc.offer_date(self.tender()), again)

    def test_a_further_revision_takes_its_own_date(self):
        self.send(SENT)
        self.approve_through(self.t["id"])
        r = self.client.post(f"/api/v1/tenders/{self.t['id']}/revision",
                             {"note": "Client asked for a discount"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(svc.offer_date(self.tender()), TODAY)   # R1, pricing
        later = TODAY - timedelta(days=1)
        self.send(later)
        self.assertEqual(svc.offer_date(self.tender()), later)

    def test_an_offer_sent_up_before_the_date_was_kept_takes_it_from_the_trail(self):
        self.send(SENT)
        t = self.tender()
        rev = t.document.current_revision
        rev.payload = {k: v for k, v in rev.payload.items()
                       if k != "sent_for_approval_on"}
        rev.save(update_fields=["payload"])
        sent_at = timezone.now() - timedelta(days=6)
        AuditLog.objects.filter(entity="tender", entity_id=t.id,
                                event="TENDER_SENT_FOR_APPROVAL").update(at=sent_at)
        self.assertEqual(svc.offer_date(self.tender()),
                         timezone.localtime(sent_at).date())

    def test_an_offer_issued_before_the_date_was_kept_keeps_its_issue_date(self):
        self.send(SENT)
        self.approve_through(self.t["id"])
        t = self.tender()
        rev = t.document.current_revision
        rev.payload = {k: v for k, v in rev.payload.items()
                       if k != "sent_for_approval_on"}
        rev.issued_at = timezone.now() - timedelta(days=3)
        rev.save(update_fields=["payload", "issued_at"])
        self.assertEqual(svc.offer_date(self.tender()),
                         timezone.localtime(rev.issued_at).date())
