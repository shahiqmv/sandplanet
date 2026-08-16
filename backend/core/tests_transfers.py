"""Site-to-site material and tool transfers (owner 2026-08-16).

Sites had no way to hand anything over: stock arrived only from a GRN or the
Head Office store, and a tool belonged to whichever site first recorded it.
Splitting a project onto its own site made that impossible to work around.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import stock, transfers
from .models import (Item, SiteTransfer, SitePmHistory, Site, StockMovement,
                     ToolAsset, User)
from .tests import make_user


class TransferBase(TestCase):
    def setUp(self):
        self.admin = make_user("tr_admin", User.Role.ADMIN)
        self.a = Site.objects.create(code="TFA", name="From Isle",
                                     status=Site.Status.ACTIVE)
        self.b = Site.objects.create(code="TFB", name="To Isle",
                                     status=Site.Status.ACTIVE)
        self.pm = make_user("tr_pm", User.Role.PM, site=self.a)
        SitePmHistory.objects.create(site=self.a, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.other_pm = make_user("tr_pm2", User.Role.PM, site=self.b)
        SitePmHistory.objects.create(site=self.b, pm_user=self.other_pm,
                                     from_date=date(2026, 1, 1))
        self.storeman = make_user("tr_store", User.Role.SITE_ADMIN,
                                  site=self.a)
        self.far_storeman = make_user("tr_store2", User.Role.SITE_ADMIN,
                                      site=self.b)
        self.cement = Item.objects.create(code="ITM-1", description="Cement",
                                          unit="bag")
        StockMovement.objects.create(site=self.a, item=self.cement,
                                     kind="RECEIPT", qty=Decimal("100"),
                                     movement_date=date(2026, 8, 1))
        self.drill = ToolAsset.objects.create(site=self.a, name="Hilti drill",
                                              serial_no="X1")

    def _raise(self, qty="40", tools=()):
        lines = [{"item_id": self.cement.id, "qty": qty}] if qty else []
        lines += [{"tool_id": t.id} for t in tools]
        return transfers.create_transfer(self.a, self.b, lines, self.storeman,
                                         reason="project split")


class RaisingATransferTests(TransferBase):
    def test_it_cannot_send_more_than_is_on_hand(self):
        tr, err = self._raise(qty="140")
        self.assertIsNone(tr)
        self.assertIn("only 100", err)

    def test_it_cannot_send_to_itself(self):
        _, err = transfers.create_transfer(
            self.a, self.a, [{"item_id": self.cement.id, "qty": "1"}],
            self.storeman)
        self.assertIn("two different sites", err)

    def test_a_tool_from_another_site_is_refused(self):
        theirs = ToolAsset.objects.create(site=self.b, name="Their grinder")
        _, err = self._raise(qty=None, tools=[theirs])
        self.assertIn("not at this site", err)

    def test_raising_moves_no_stock_yet(self):
        tr, err = self._raise()
        self.assertIsNone(err)
        self.assertEqual(tr.status, "DRAFT")
        self.assertEqual(stock.balance(self.a, self.cement), Decimal("100"))


class DespatchAndReceiveTests(TransferBase):
    def _to_despatched(self):
        tr, _ = self._raise(tools=[self.drill])
        transfers.approve(tr, self.pm)
        transfers.despatch(tr, self.storeman)
        return tr

    def test_only_the_sending_pm_approves(self):
        tr, _ = self._raise()
        _, err = transfers.approve(tr, self.other_pm)
        self.assertIn("TFA's PM", err)
        _, err = transfers.approve(tr, self.pm)
        self.assertIsNone(err)

    def test_it_cannot_be_sent_before_approval(self):
        tr, _ = self._raise()
        _, err = transfers.despatch(tr, self.storeman)
        self.assertIn("approved", err)

    def test_despatch_takes_it_off_the_sending_site(self):
        tr = self._to_despatched()
        self.assertEqual(stock.balance(self.a, self.cement), Decimal("60"))
        # ...and it has NOT landed anywhere yet — it is on a boat
        self.assertEqual(stock.balance(self.b, self.cement), Decimal("0"))
        self.assertEqual(tr.status, "DESPATCHED")

    def test_a_tool_stays_put_until_someone_counts_it_in(self):
        tr = self._to_despatched()
        self.drill.refresh_from_db()
        self.assertEqual(self.drill.site, self.a)
        transfers.receive(tr, {}, self.far_storeman)
        self.drill.refresh_from_db()
        self.assertEqual(self.drill.site, self.b)

    def test_receiving_in_full_lands_the_whole_quantity(self):
        tr = self._to_despatched()
        _, err = transfers.receive(tr, {}, self.far_storeman)
        self.assertIsNone(err)
        self.assertEqual(stock.balance(self.b, self.cement), Decimal("40"))
        self.assertEqual(stock.balance(self.a, self.cement), Decimal("60"))

    def test_a_short_count_lands_only_what_arrived_and_records_the_gap(self):
        tr = self._to_despatched()
        line = tr.lines.get(item=self.cement)
        _, err = transfers.receive(tr, {str(line.id): "36"},
                                   self.far_storeman, note="4 bags burst")
        self.assertIsNone(err)
        line.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("36"))
        self.assertEqual(line.shortage, Decimal("4"))
        self.assertEqual(stock.balance(self.b, self.cement), Decimal("36"))
        # the sending site is NOT quietly credited back the missing four
        self.assertEqual(stock.balance(self.a, self.cement), Decimal("60"))

    def test_it_cannot_receive_more_than_was_sent(self):
        tr = self._to_despatched()
        line = tr.lines.get(item=self.cement)
        _, err = transfers.receive(tr, {str(line.id): "50"},
                                   self.far_storeman)
        self.assertIn("between zero and", err)

    def test_a_tool_that_never_arrived_stays_with_the_sender(self):
        tr = self._to_despatched()
        tool_line = tr.lines.get(tool=self.drill)
        transfers.receive(tr, {str(tool_line.id): "0"}, self.far_storeman)
        self.drill.refresh_from_db()
        tool_line.refresh_from_db()
        self.assertEqual(self.drill.site, self.a)
        self.assertEqual(tool_line.shortage, Decimal("1"))

    def test_a_sent_transfer_cannot_be_cancelled(self):
        tr = self._to_despatched()
        _, err = transfers.cancel(tr, self.admin, "changed my mind")
        self.assertIn("already been sent", err)

    def test_a_draft_can_be_cancelled(self):
        tr, _ = self._raise()
        tr, err = transfers.cancel(tr, self.storeman, "wrong site")
        self.assertIsNone(err)
        self.assertEqual(tr.status, "CANCELLED")
        self.assertEqual(stock.balance(self.a, self.cement), Decimal("100"))

    def test_the_ledger_reads_as_a_move_not_an_adjustment(self):
        """Both halves point at the same MTN, so the history explains itself."""
        tr = self._to_despatched()
        transfers.receive(tr, {}, self.far_storeman)
        out = StockMovement.objects.get(site=self.a, kind="XFER_OUT")
        into = StockMovement.objects.get(site=self.b, kind="XFER_IN")
        self.assertEqual(out.document, tr.document)
        self.assertEqual(into.document, tr.document)
        self.assertIn("TFB", out.reason)
        self.assertIn("TFA", into.reason)


class TransferApiTests(TransferBase):
    """The endpoints, including who is allowed to do what."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _raise_api(self, user=None):
        self.client.force_authenticate(user or self.storeman)
        return self.client.post("/api/v1/transfers", {
            "from_site_id": self.a.id, "to_site_id": self.b.id,
            "reason": "project split",
            "lines": [{"item_id": self.cement.id, "qty": "40"},
                      {"tool_id": self.drill.id}]}, format="json")

    def test_the_full_round_trip(self):
        r = self._raise_api()
        self.assertEqual(r.status_code, 201, r.data)
        tid = r.data["id"]
        self.assertEqual(r.data["from_site"], "TFA")
        self.assertEqual(r.data["to_site"], "TFB")

        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/transfers/{tid}",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "APPROVED", r.data)

        self.client.force_authenticate(self.storeman)
        r = self.client.post(f"/api/v1/transfers/{tid}",
                             {"action": "despatch"}, format="json")
        self.assertEqual(r.data["status"], "DESPATCHED")

        line = [l for l in r.data["lines"] if l["item_id"]][0]
        self.client.force_authenticate(self.far_storeman)
        r = self.client.post(f"/api/v1/transfers/{tid}",
                             {"action": "receive",
                              "counts": {str(line["id"]): "38"},
                              "note": "two bags wet"}, format="json")
        self.assertEqual(r.data["status"], "RECEIVED", r.data)
        got = [l for l in r.data["lines"] if l["item_id"]][0]
        self.assertEqual(Decimal(got["received_qty"]), Decimal("38"))
        self.assertEqual(Decimal(got["shortage"]), Decimal("2"))

    def test_the_sending_site_cannot_receive_its_own_transfer(self):
        tid = self._raise_api().data["id"]
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/transfers/{tid}", {"action": "approve"},
                         format="json")
        self.client.force_authenticate(self.storeman)
        self.client.post(f"/api/v1/transfers/{tid}", {"action": "despatch"},
                         format="json")
        r = self.client.post(f"/api/v1/transfers/{tid}", {"action": "receive"},
                             format="json")
        self.assertEqual(r.status_code, 403)
        self.assertIn("TFB", r.data["detail"])

    def test_both_ends_can_see_it(self):
        self._raise_api()
        for user in (self.storeman, self.far_storeman):
            self.client.force_authenticate(user)
            r = self.client.get("/api/v1/transfers")
            self.assertEqual(len(r.data["transfers"]), 1, user.username)

    def test_what_a_site_can_send(self):
        self.client.force_authenticate(self.storeman)
        r = self.client.get(f"/api/v1/sites/{self.a.id}/transferable")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([i["code"] for i in r.data["items"]], ["ITM-1"])
        self.assertEqual([t["name"] for t in r.data["tools"]], ["Hilti drill"])

    def test_a_retired_tool_is_not_offered(self):
        self.drill.state = ToolAsset.State.RETIRED
        self.drill.save(update_fields=["state"])
        self.client.force_authenticate(self.storeman)
        r = self.client.get(f"/api/v1/sites/{self.a.id}/transferable")
        self.assertEqual(r.data["tools"], [])
