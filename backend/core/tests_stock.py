"""Site inventory (Phase 1A): GRN verify feeds stock; issue/reconcile/history."""
from datetime import date

from .models import Project, StockMovement, User
from .tests import make_user
from .tests_procurement import ProcBase


class StockBase(ProcBase):
    def grn_to_verified(self, cement_qty=150, rebar_qty=300):
        """Drive MR→PR→PO→LM→GRN and verify the GRN, receiving the given
        quantities. Returns the GRN dict."""
        mr_ref = self.mr_to_sent()
        lm = self.make_lm(mr_ref)
        self.act(lm["ref"], "depart")
        self.as_user(self.sa)
        grn = self.client.post("/api/v1/documents", {
            "doc_type": "GRN", "site_id": self.site.id, "lm_ref": lm["ref"],
        }, format="json").data
        self.client.patch(f"/api/v1/documents/{grn['ref']}", {"lines": [
            {"item_id": self.cement.id, "qty_manifest": 150,
             "qty_received": cement_qty},
            {"item_id": self.rebar.id, "qty_manifest": 300,
             "qty_received": rebar_qty},
        ]}, format="json")
        self.act(grn["ref"], "count")
        self.as_user(self.pm)
        self.act(grn["ref"], "verify")
        return grn


class StockTests(StockBase):
    def test_grn_verify_creates_receipts(self):
        self.grn_to_verified(cement_qty=140, rebar_qty=300)
        moves = StockMovement.objects.filter(site=self.site)
        self.assertEqual(moves.count(), 2)
        self.assertEqual(
            {m.item_id: float(m.qty) for m in moves},
            {self.cement.id: 140.0, self.rebar.id: 300.0})
        self.assertTrue(all(m.kind == "RECEIPT" for m in moves))

    def test_balances_endpoint(self):
        self.grn_to_verified()
        self.as_user(self.sa)
        r = self.client.get(f"/api/v1/stock/{self.site.id}")
        self.assertEqual(r.status_code, 200)
        bal = {b["code"]: float(b["on_hand"]) for b in r.data["balances"]}
        self.assertEqual(bal, {"ITM-90001": 150.0, "ITM-90002": 300.0})
        self.assertTrue(r.data["can_issue"])

    def test_issue_reduces_balance(self):
        self.grn_to_verified()
        proj = Project.objects.create(site=self.site, code="P1",
                                      title="Villa 12")
        self.as_user(self.sa)
        r = self.client.post(f"/api/v1/stock/{self.site.id}/issue", {
            "project_id": proj.id,
            "lines": [{"item_id": self.cement.id, "qty": 40}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        bal = {b["code"]: float(b["on_hand"]) for b in r.data["balances"]}
        self.assertEqual(bal["ITM-90001"], 110.0)

    def test_issue_cannot_overdraw(self):
        self.grn_to_verified()
        self.as_user(self.sa)
        r = self.client.post(f"/api/v1/stock/{self.site.id}/issue", {
            "lines": [{"item_id": self.cement.id, "qty": 999}],
        }, format="json")
        self.assertEqual(r.status_code, 400)
        # nothing booked
        self.assertEqual(StockMovement.objects.filter(kind="ISSUE").count(), 0)

    def test_reconcile_books_adjustment(self):
        self.grn_to_verified()
        self.as_user(self.sa)
        r = self.client.post(f"/api/v1/stock/{self.site.id}/reconcile", {
            "item_id": self.cement.id, "counted_qty": 145,
            "reason": "5 bags damaged by rain",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(float(r.data["on_hand"]), 145.0)
        adj = StockMovement.objects.get(kind="ADJUST")
        self.assertEqual(float(adj.qty), -5.0)

    def test_reconcile_requires_reason(self):
        self.grn_to_verified()
        self.as_user(self.sa)
        r = self.client.post(f"/api/v1/stock/{self.site.id}/reconcile", {
            "item_id": self.cement.id, "counted_qty": 145,
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_history_running_balance(self):
        self.grn_to_verified()
        self.as_user(self.sa)
        self.client.post(f"/api/v1/stock/{self.site.id}/issue", {
            "lines": [{"item_id": self.cement.id, "qty": 40}],
        }, format="json")
        r = self.client.get(
            f"/api/v1/stock/{self.site.id}/{self.cement.id}/history")
        self.assertEqual(r.status_code, 200)
        hist = r.data["history"]  # newest first
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["kind"], "ISSUE")
        self.assertEqual(float(hist[0]["running"]), 110.0)
        self.assertEqual(float(hist[1]["running"]), 150.0)

    def test_issue_forbidden_for_non_site_staff(self):
        self.grn_to_verified()
        stranger = make_user("hop2", User.Role.HO_PURCHASING)
        self.as_user(stranger)
        r = self.client.post(f"/api/v1/stock/{self.site.id}/issue", {
            "lines": [{"item_id": self.cement.id, "qty": 1}],
        }, format="json")
        self.assertEqual(r.status_code, 403)
