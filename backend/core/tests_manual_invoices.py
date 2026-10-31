"""Manual client invoices — historical + Planet-issued, folded into the same
receivables aging / statement / receipts as claim invoices."""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import receivables
from .models import ManualInvoice, Project, Site, User
from .tests import make_user


class ManualInvoiceTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="SFR", name="Soneva Fushi", status=Site.Status.ACTIVE,
            client_name="Bunny Holdings Pvt Ltd", client_address="No. 1, Male")
        self.project = Project.objects.create(
            site=self.site, code="V42", title="Villa 42",
            contract_value="10000", output_gst_pct="8", client_credit_days=30)
        self.qs = make_user("qs1", User.Role.QS)
        self.fin = make_user("fin1", User.Role.FINANCE)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.director = make_user("dir1", User.Role.DIRECTOR)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)

    def _create(self, lines=None, gst_pct="0", approve=True, **over):
        """Draft it as the QS, submit it, and (by default) have a Director
        approve it — the invoice is owed only then (owner 2026-10-31)."""
        r = self._draft(lines=lines, gst_pct=gst_pct, submit=True, **over)
        if r.status_code != 201 or not approve:
            return r
        self.client.force_authenticate(self.director)
        a = self.client.post(
            f"/api/v1/receivables/manual-invoices/{r.data['id']}/approve")
        self.client.force_authenticate(self.qs)
        assert a.status_code == 200, a.data
        a.status_code = 201
        return a

    def _draft(self, lines=None, gst_pct="0", **over):
        # Default: a single 5000 line, GST 0 → total 5000, so the receivables
        # totals the aging/receipt tests assert stay clean.
        if lines is None:
            lines = [{"description": "Value of work", "amount": "5000"}]
        body = {"project_id": self.project.id, "origin": "HISTORICAL",
                "invoice_no": "CL-2024-07", "invoice_date": "2024-05-01",
                "gst_pct": gst_pct, "lines": lines}
        body.update(over)
        return self.client.post("/api/v1/receivables/manual-invoices", body,
                                format="json")

    # ---- opening one from Receivables (owner 2026-09-30) ------------------
    def test_a_manual_invoice_opens_with_its_lines_and_documents(self):
        hist = self._create(gst_pct="8").data
        issued = self._create(origin="ISSUED", invoice_no="").data
        self.client.force_authenticate(self.fin)
        d = self.client.get(
            f"/api/v1/receivables/invoices/manual/{hist['id']}").data
        self.assertEqual((d["invoice_no"], d["type_label"]),
                         ("CL-2024-07", "Historical invoice"))
        self.assertEqual((float(d["net_due"]), float(d["gst"]),
                          float(d["amount"]), float(d["outstanding"])),
                         (5000.0, 400.0, 5400.0, 5400.0))
        self.assertEqual([ln["description"] for ln in d["lines"]],
                         ["Value of work"])
        # nothing was scanned in, and a historical invoice is not generated
        self.assertIsNone(d["pdf_url"])
        self.assertIsNone(d["attachment_url"])
        d2 = self.client.get(
            f"/api/v1/receivables/invoices/manual/{issued['id']}").data
        self.assertEqual(
            d2["pdf_url"],
            f"/api/v1/receivables/manual-invoices/{issued['id']}.pdf")
        self.assertIn(self.client.get(d2["pdf_url"]).status_code, (200, 503))
        # the ledger row carries the same link
        rows = self.client.get("/api/v1/receivables/invoices").data["invoices"]
        by = {r["manual_invoice_id"]: r for r in rows}
        self.assertEqual(by[issued["id"]]["pdf_url"], d2["pdf_url"])
        self.assertIsNone(by[hist["id"]]["pdf_url"])
        self.client.force_authenticate(self.se)
        self.assertEqual(self.client.get(
            f"/api/v1/receivables/invoices/manual/{hist['id']}").status_code, 403)

    # ---- creation --------------------------------------------------------
    def test_historical_uses_client_number_and_back_dates(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["invoice_no"], "CL-2024-07")
        self.assertEqual(r.data["origin"], "HISTORICAL")
        self.assertEqual(str(r.data["invoice_date"]), "2024-05-01")
        self.assertEqual(float(r.data["amount"]), 5000.0)
        self.assertFalse(r.data["can_pdf"])

    def test_issued_gets_a_planet_number_and_auto_computes_gst_and_total(self):
        # net 1000, GST @ 8% auto = 80, total = 1080 — all system-computed.
        r = self._create(origin="ISSUED", invoice_no="",
                         invoice_date="2026-07-01", gst_pct="8",
                         lines=[{"description": "Interim work", "amount": "1000"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["invoice_no"].startswith("INV-"))
        self.assertEqual(float(r.data["net_amount"]), 1000.0)
        self.assertEqual(float(r.data["gst_amount"]), 80.0)
        self.assertEqual(float(r.data["amount"]), 1080.0)   # net + gst
        self.assertTrue(r.data["can_pdf"])

    def test_multi_line_sums_net_then_adds_gst(self):
        # Unrelated charges on one invoice: equipment rental + food provision.
        r = self._create(gst_pct="8", lines=[
            {"description": "Excavator rental", "quantity": "2",
             "unit_price": "1500", "amount": "3000"},
            {"description": "Food provision to tiling crew", "amount": "1200"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["lines"]), 2)
        self.assertEqual(float(r.data["net_amount"]), 4200.0)   # 3000 + 1200
        self.assertEqual(float(r.data["gst_amount"]), 336.0)    # 8% of 4200
        self.assertEqual(float(r.data["amount"]), 4536.0)

    def test_historical_needs_a_client_number(self):
        r = self._create(invoice_no="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("number", r.data["detail"].lower())

    def test_needs_at_least_one_line(self):
        r = self._create(lines=[])
        self.assertEqual(r.status_code, 400)
        self.assertIn("line", r.data["detail"].lower())

    def test_site_staff_cannot_record_invoices(self):
        self.client.force_authenticate(self.se)
        self.assertEqual(self._create().status_code, 403)

    # ---- receivables integration ----------------------------------------
    def test_shows_in_aging_and_shared_numbering(self):
        # a historical invoice, 90+ days overdue (issued 2024, due +30)
        self._create()
        ag = receivables.aging()
        self.assertEqual(ag["invoice_count"], 1)
        self.assertEqual(float(ag["totals"]["total"]), 5000.0)
        self.assertEqual(float(ag["totals"]["d90p"]), 5000.0)
        # a Planet-issued invoice takes the next INV- number, not colliding
        r = self._create(origin="ISSUED", invoice_no="",
                         invoice_date="2026-07-01",
                         lines=[{"description": "Work", "amount": "2000"}])
        self.assertTrue(r.data["invoice_no"].endswith("-0001"))

    def test_receipt_settles_a_manual_invoice(self):
        mid = self._create().data["id"]
        r = self.client.post(f"/api/v1/projects/{self.project.id}/receipts",
                             {"manual_invoice_id": mid, "amount": "2000",
                              "received_on": "2024-06-01"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rows = receivables.invoice_rows()
        row = next(x for x in rows if x["manual_invoice_id"] == mid)
        self.assertEqual(float(row["received"]), 2000.0)
        self.assertEqual(float(row["outstanding"]), 3000.0)
        # statement shows the invoice debit and the receipt credit
        stmt = receivables.client_statement(self.site)
        kinds = [t["kind"] for t in stmt["rows"]]
        self.assertIn("INVOICE", kinds)
        self.assertIn("RECEIPT", kinds)
        self.assertEqual(float(stmt["closing"]), 3000.0)

    # ---- void ------------------------------------------------------------
    def test_void_drops_it_from_receivables(self):
        mid = self._create().data["id"]
        r = self.client.post(
            f"/api/v1/receivables/manual-invoices/{mid}/void")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["is_void"])
        self.assertEqual(receivables.aging()["invoice_count"], 0)

    def test_cannot_void_with_receipts(self):
        mid = self._create().data["id"]
        self.client.post(f"/api/v1/projects/{self.project.id}/receipts",
                         {"manual_invoice_id": mid, "amount": "1000",
                          "received_on": "2024-06-01"}, format="json")
        r = self.client.post(
            f"/api/v1/receivables/manual-invoices/{mid}/void")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ManualInvoice.objects.get(pk=mid).is_void)

    # ---- pdf -------------------------------------------------------------
    def test_issued_has_pdf_historical_does_not(self):
        issued = self._create(origin="ISSUED", invoice_no="",
                              invoice_date="2026-07-01", gst_pct="8",
                              lines=[{"description": "Work",
                                      "amount": "1500"}]).data
        r = self.client.get(
            f"/api/v1/receivables/manual-invoices/{issued['id']}.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        hist = self._create().data
        self.assertEqual(self.client.get(
            f"/api/v1/receivables/manual-invoices/{hist['id']}.pdf")
            .status_code, 400)


class MvrInvoiceTests(ManualInvoiceTests):
    """MRA is an MVR-based project — its bills carry MVR, and MVR money never
    mixes into USD aging totals (owner 2026-08-27)."""

    def test_currency_is_kept_and_aging_separates_it(self):
        r = self._create(currency="MVR", invoice_no="MRA-001")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["currency"], "MVR")
        from core import receivables as rcv
        rows = rcv.invoice_rows(site_id=self.site.id)
        self.assertEqual(rows[0]["currency"], "MVR")
        ag = rcv.aging()
        self.assertIn("MVR", ag["totals_by_currency"])
        self.assertEqual(ag["totals_by_currency"]["MVR"]["total"],
                         rows[0]["outstanding"])
        # MVR never leaks into a USD total (the headline block now leads
        # with the currency actually in play — audit 2026-08-28)
        self.assertEqual(ag["totals_currency"], "MVR")
        self.assertNotIn("USD", ag["totals_by_currency"])
        row = next(c for c in ag["clients"] if c["currency"] == "MVR")
        self.assertEqual(row["site_id"], self.site.id)

    def test_default_stays_usd(self):
        r = self._create(invoice_no="V42-USD-1")
        self.assertEqual(r.data["currency"], "USD")


class DeductionsAndApprovalTests(ManualInvoiceTests):
    """Deductions on a manual invoice, and draft → submit → Director approval
    → revision (owner 2026-10-31, INV-2026-0064 went out without its advance
    recovery: the form dropped the negative line)."""

    URL = "/api/v1/receivables/manual-invoices"

    def _as(self, user):
        self.client.force_authenticate(user)

    def _step(self, mid, step, user, **body):
        self._as(user)
        return self.client.post(f"{self.URL}/{mid}/{step}", body,
                                format="json")

    def test_an_advance_recovery_comes_off_before_gst(self):
        r = self._create(origin="ISSUED", invoice_no="", gst_pct="8", lines=[
            {"description": "Tennis court paint removal", "quantity": "1",
             "unit_price": "15013.80"},
            {"description": "Advance recovery", "kind": "DEDUCTION",
             "amount": "6005.52"}])
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data
        self.assertEqual((d["charges"], d["deducted_before_gst"],
                          d["net_amount"], d["gst_amount"], d["amount"]),
                         (Decimal("15013.80"), Decimal("6005.52"),
                          Decimal("9008.28"), Decimal("720.66"),
                          Decimal("9728.94")))
        self.assertEqual([ln["amount"] for ln in d["lines"]],
                         [Decimal("15013.80"), Decimal("-6005.52")])
        from . import manual_invoices as svc
        ctx = svc.manual_invoice_pdf_context(ManualInvoice.objects.get(
            pk=d["id"]))
        self.assertEqual([ln["amount_f"] for ln in ctx["less_before"]],
                         ["(6,005.52)"])
        self.assertEqual(ctx["charges_f"], "15,013.80")

    def test_a_negative_line_is_a_deduction_not_dropped(self):
        r = self._create(gst_pct="8", lines=[
            {"description": "Work", "amount": "1000"},
            {"description": "Advance recovery", "amount": "-400"}])
        self.assertEqual(r.data["amount"], Decimal("648.00"))
        self.assertEqual(r.data["lines"][1]["kind"], "DEDUCTION")

    def test_a_deduction_after_gst(self):
        r = self._create(gst_pct="8", lines=[
            {"description": "Work", "amount": "1000"},
            {"description": "Back charge", "kind": "DEDUCTION",
             "amount": "100", "before_gst": False}])
        # GST on the full 1,000, the back charge after it
        self.assertEqual((r.data["net_amount"], r.data["gst_amount"],
                          r.data["amount"]),
                         (Decimal("1000.00"), Decimal("80.00"),
                          Decimal("980.00")))

    def test_deductions_cannot_take_it_to_nothing(self):
        r = self._draft(lines=[
            {"description": "Work", "amount": "100"},
            {"description": "Advance recovery", "kind": "DEDUCTION",
             "amount": "100"}])
        self.assertEqual(r.status_code, 400)

    def test_owed_only_once_a_director_approves_and_numbered_then(self):
        r = self._draft(origin="ISSUED", invoice_no="")
        mid = r.data["id"]
        self.assertEqual((r.data["status"], r.data["invoice_no"]),
                         ("DRAFT", ""))
        self.assertFalse(receivables._manual_invoices())
        self.assertEqual(self._step(mid, "submit", self.qs).status_code, 200)
        self.assertFalse(receivables._manual_invoices())
        # the QS cannot approve; a Director can
        self.assertEqual(self._step(mid, "approve", self.qs).status_code, 400)
        a = self._step(mid, "approve", self.director)
        self.assertEqual(a.status_code, 200, a.data)
        self.assertEqual(a.data["status"], "APPROVED")
        self.assertTrue(a.data["invoice_no"].startswith("INV-"))
        self.assertEqual([m.id for m in receivables._manual_invoices()],
                         [mid])

    def test_a_director_does_not_approve_his_own(self):
        self._as(self.director)
        mid = self._draft(submit=True).data["id"]
        r = self._step(mid, "approve", self.director)
        self.assertEqual(r.status_code, 400)
        self.assertIn("another Director", r.data["detail"])
        other = make_user("dir2", User.Role.DIRECTOR)
        self.assertEqual(self._step(mid, "approve", other).status_code, 200)

    def test_returned_edited_and_resubmitted(self):
        mid = self._draft(submit=True).data["id"]
        self.assertEqual(self._step(mid, "return", self.director)
                         .status_code, 400)          # a note is needed
        r = self._step(mid, "return", self.director,
                       note="Add the advance recovery")
        self.assertEqual((r.data["status"], r.data["return_note"]),
                         ("DRAFT", "Add the advance recovery"))
        self._as(self.qs)
        e = self.client.patch(f"{self.URL}/{mid}", {
            "project_id": self.project.id, "origin": "HISTORICAL",
            "invoice_no": "CL-2024-07", "invoice_date": "2024-05-01",
            "gst_pct": "0", "submit": True,
            "lines": [{"description": "Value of work", "amount": "5000"},
                      {"description": "Advance recovery",
                       "kind": "DEDUCTION", "amount": "1000"}]},
            format="json")
        self.assertEqual(e.status_code, 200, e.data)
        self.assertEqual((e.data["status"], e.data["amount"]),
                         ("SUBMITTED", Decimal("4000.00")))

    def test_a_submitted_invoice_cannot_be_edited(self):
        mid = self._draft(submit=True).data["id"]
        self._as(self.qs)
        r = self.client.patch(f"{self.URL}/{mid}", {
            "invoice_date": "2024-05-01",
            "lines": [{"description": "x", "amount": "1"}]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_reopened_as_a_revision_keeps_its_number(self):
        r = self._create(origin="ISSUED", invoice_no="")
        mid, no = r.data["id"], r.data["invoice_no"]
        self.assertEqual(self._step(mid, "reopen", self.qs).status_code, 400)
        o = self._step(mid, "reopen", self.qs, reason="advance recovery missed")
        self.assertEqual((o.data["status"], o.data["revision"]),
                         ("DRAFT", 1))
        self.assertFalse(receivables._manual_invoices())   # not owed meanwhile
        self.assertEqual(self._step(mid, "submit", self.qs).status_code, 200)
        a = self._step(mid, "approve", self.director)
        self.assertEqual((a.data["invoice_no"], a.data["revision"]),
                         (no, 1))

    def test_no_revision_once_money_is_received(self):
        mid = self._create().data["id"]
        r = self.client.post(f"/api/v1/projects/{self.project.id}/receipts",
                             {"manual_invoice_id": mid, "amount": "100",
                              "received_on": "2024-06-01"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = self._step(mid, "reopen", self.qs, reason="change")
        self.assertEqual(r.status_code, 400)
        self.assertIn("receipt", r.data["detail"])

    def test_a_draft_cannot_take_a_receipt(self):
        mid = self._draft().data["id"]
        r = self.client.post(f"/api/v1/projects/{self.project.id}/receipts",
                             {"manual_invoice_id": mid, "amount": "100",
                              "received_on": "2024-06-01"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_draft_is_deleted_an_approved_one_is_not(self):
        mid = self._draft().data["id"]
        self._as(self.qs)
        self.assertEqual(self.client.delete(f"{self.URL}/{mid}").status_code,
                         204)
        mid = self._create().data["id"]
        self.assertEqual(self.client.delete(f"{self.URL}/{mid}").status_code,
                         400)
