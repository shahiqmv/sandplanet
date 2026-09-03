from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Document, Item, Site, SitePmHistory, Supplier, User
from .tests import make_user


class QuoteBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="SJR", name="Soneva Jani", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=60),
        )
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.purchasing = make_user("hop1", User.Role.HO_PURCHASING)
        self.director = make_user("dir1", User.Role.DIRECTOR)
        self.signatory = make_user("sig1", User.Role.SIGNATORY)
        self.finance = make_user("fin1", User.Role.FINANCE)
        self.cement = Item.objects.create(code="ITM-90001",
                                          description="Cement OPC 50kg bag",
                                          unit="bag")
        self.rebar = Item.objects.create(code="ITM-90002",
                                         description="Rebar B500 12mm",
                                         unit="kg")
        self.hw = Supplier.objects.create(name="Male' Hardware Pvt Ltd")
        self.steel = Supplier.objects.create(name="Maldives Steel Traders")
        self.client = APIClient()

    def as_user(self, user):
        self.client.force_authenticate(user)

    def act(self, ref, action, body=None):
        return self.client.post(f"/api/v1/documents/{ref}/actions/{action}",
                                body or {}, format="json")

    def sent_mr(self):
        self.as_user(self.sa)
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id, "general_works": True,
            "lines": [
                {"item_id": self.cement.id, "qty_required": 200,
                 "qty_stock": 50, "qty_to_order": 150},
                {"item_id": self.rebar.id, "qty_required": 500, "qty_stock": 0,
                 "qty_to_order": 500},
            ],
        }, format="json").data
        self.act(mr["ref"], "submit")
        self.as_user(self.pm)
        self.act(mr["ref"], "approve")
        self.as_user(self.sa)
        self.act(mr["ref"], "send")
        return self.client.get(f"/api/v1/documents/{mr['ref']}").data

    def draft_pr(self, mr):
        self.as_user(self.purchasing)
        return self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "mr_refs": [mr["ref"]],
        }, format="json").data

    def add_quote(self, pr_ref, supplier, lines, terms=""):
        self.as_user(self.purchasing)
        r = self.client.post(f"/api/v1/pr/{pr_ref}/quotations", {
            "supplier": supplier.id, "quote_ref": f"QT-{supplier.id}",
            "payment_terms": terms, "lines": lines,
        }, format="json")
        assert r.status_code == 201, r.data
        return r.data


class SupplierTests(QuoteBase):
    def test_site_roles_cannot_edit_suppliers(self):
        self.as_user(self.sa)
        r = self.client.post("/api/v1/suppliers", {"name": "X"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_purchasing_creates_supplier(self):
        self.as_user(self.purchasing)
        r = self.client.post("/api/v1/suppliers",
                             {"name": "Lagoon Marine Supplies",
                              "contact_person": "Ahmed"},
                             format="json")
        self.assertEqual(r.status_code, 201)


class CoverageTests(QuoteBase):
    def test_coverage_tally_and_submit_gate(self):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        cement_line = mr["lines"][0]["id"]
        # quote covers cement only, awarded
        self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "OPC cement 50kg (Fuji brand)", "unit": "bag",
             "qty": 150, "rate": 120, "mr_line": cement_line, "awarded": True},
        ])
        r = self.client.get(f"/api/v1/pr/{pr['ref']}/coverage")
        self.assertEqual(r.data["uncovered"], ["Rebar B500 12mm"])
        # submit blocked while rebar is unquoted
        r = self.act(pr["ref"], "submit")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Rebar B500 12mm", r.data["uncovered"])
        # override requires a reason
        r = self.act(pr["ref"], "submit", {"allow_uncovered": True})
        self.assertEqual(r.status_code, 400)
        r = self.act(pr["ref"], "submit", {"allow_uncovered": True,
                                           "comment": "Rebar deferred to next "
                                                      "loading per PM"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")

    def test_legacy_unscoped_pr_shows_only_its_quoted_items(self):
        # A pre-feature PR whose MR lines were never scoped to it (the one-time
        # backfill handed them to an older PR sharing the MR). Coverage must
        # anchor to what THIS PR quoted, not the whole MR — else the un-quoted
        # rest wrongly blocks its submit and can't be removed (owner 2026-07-16).
        from .models import Document, DocumentLine
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        cement_line = mr["lines"][0]["id"]
        self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "OPC cement", "unit": "bag", "qty": 150,
             "rate": 120, "mr_line": cement_line, "awarded": True}])
        # wipe this PR's scope, as the backfill would if another PR grabbed the
        # MR's lines first
        prdoc = Document.objects.get(ref=pr["ref"])
        DocumentLine.objects.filter(ordered_pr=prdoc).update(ordered_pr=None)
        r = self.client.get(f"/api/v1/pr/{pr['ref']}/coverage")
        descs = {row["description"] for row in r.data["rows"]}
        self.assertEqual(descs, {"Cement OPC 50kg bag"})   # not the whole MR
        self.assertEqual(r.data["uncovered"], [])          # rebar isn't on it
        # so it submits clean, no override needed
        r = self.act(pr["ref"], "submit")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")

    def test_release_removes_a_matched_unscoped_line(self):
        from .models import Document, DocumentLine
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        cement_line, rebar_line = mr["lines"][0]["id"], mr["lines"][1]["id"]
        self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "cement", "unit": "bag", "qty": 150, "rate": 120,
             "mr_line": cement_line, "awarded": True},
            {"supplier_desc": "rebar", "unit": "kg", "qty": 500, "rate": 9,
             "mr_line": rebar_line, "awarded": False}])
        prdoc = Document.objects.get(ref=pr["ref"])
        DocumentLine.objects.filter(ordered_pr=prdoc).update(ordered_pr=None)
        # remove the un-awarded (matched but unscoped) rebar line
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/release-lines",
                             {"line_ids": [rebar_line]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["released"], 1)
        r = self.client.get(f"/api/v1/pr/{pr['ref']}/coverage")
        self.assertEqual({row["description"] for row in r.data["rows"]},
                         {"Cement OPC 50kg bag"})

    def test_remove_mistaken_supplier(self):
        """A supplier added by mistake can be removed so it stops showing as a
        zero-line vendor in the PR summary (owner 2026-07-14)."""
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "OPC 50kg", "unit": "bag", "qty": 150,
             "rate": 120, "mr_line": mr["lines"][0]["id"], "awarded": True},
        ])
        # a second supplier added in error, with no lines
        oops = self.add_quote(pr["ref"], self.steel, [])
        self.as_user(self.purchasing)
        self.client.post(f"/api/v1/pr/{pr['ref']}/sync-vendor-rows")
        vendors = {row["vendor"] for row in
                   self.client.get(f"/api/v1/documents/{pr['ref']}").data["lines"]}
        self.assertIn("Maldives Steel Traders", vendors)   # zero-line row shows

        r = self.client.delete(f"/api/v1/quotations/{oops['id']}")
        self.assertEqual(r.status_code, 204)
        # quotation gone and the vendor summary rebuilt without it
        quotes = self.client.get(f"/api/v1/pr/{pr['ref']}/quotations").data
        self.assertEqual([q["supplier_name"] for q in quotes],
                         ["Male' Hardware Pvt Ltd"])
        vendors = {row["vendor"] for row in
                   self.client.get(f"/api/v1/documents/{pr['ref']}").data["lines"]}
        self.assertNotIn("Maldives Steel Traders", vendors)

    def test_site_role_cannot_remove_supplier(self):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        q = self.add_quote(pr["ref"], self.hw, [])
        self.as_user(self.sa)
        r = self.client.delete(f"/api/v1/quotations/{q['id']}")
        self.assertEqual(r.status_code, 403)

    def test_matched_but_unawarded_blocks_submit(self):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "OPC 50kg", "qty": 150, "rate": 120,
             "mr_line": mr["lines"][0]["id"], "awarded": True},
            {"supplier_desc": "Deformed bar 12mm", "qty": 500, "rate": 18,
             "mr_line": mr["lines"][1]["id"], "awarded": False},
        ])
        r = self.act(pr["ref"], "submit")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["unawarded"], ["Rebar B500 12mm"])


class PoGenerationTests(QuoteBase):
    def full_award(self):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "OPC cement 50kg", "unit": "bag", "qty": 150,
             "rate": 120, "mr_line": mr["lines"][0]["id"], "awarded": True},
        ], terms="COD")
        self.add_quote(pr["ref"], self.steel, [
            {"supplier_desc": "Deformed bar Grade 500, 12mm dia", "unit": "kg",
             "qty": 500, "rate": 18.50, "mr_line": mr["lines"][1]["id"],
             "awarded": True},
        ], terms="30 days credit")
        # vendor rows derived from quotes
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/sync-vendor-rows")
        vendors = {line["vendor"]: line for line in r.data["lines"]}
        assert float(vendors["Male' Hardware Pvt Ltd"]["amount_cash"]) == 18000.0
        assert float(vendors["Maldives Steel Traders"]["amount_credit"]) == 9250.0
        self.act(pr["ref"], "submit")
        self.as_user(self.director)
        r = self.act(pr["ref"], "approve")
        assert r.status_code == 200, r.data
        # The award drafts the credit order. Finance's voucher covers only the
        # CASH vendor; the credit order is signed by the signatory on its own
        # (owner 2026-08-22).
        self.authorise_via_voucher(pr["ref"])
        return mr, pr

    def sign_orders(self, pr_ref):
        """Purchasing sends each drafted order, the signatory signs it."""
        pos = list(Document.objects.filter(doc_type="PO",
                                           links_from__to_document__ref=pr_ref,
                                           status="DRAFT").distinct())
        for po in pos:
            self.as_user(self.purchasing)
            self.act(po.ref, "submit")
            self.as_user(self.signatory)
            self.act(po.ref, "authorise")
            po.refresh_from_db()
        return pos

    def authorise_via_voucher(self, pr_ref):
        self.as_user(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [pr_ref]}, format="json")
        assert pv.status_code == 201, pv.data
        ref = pv.data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{ref}/actions/submit", {},
                         format="json")
        self.as_user(self.signatory)
        r = self.client.post(
            f"/api/v1/payment-vouchers/{ref}/actions/approve", {},
            format="json")
        assert r.status_code == 200, r.data

    def test_approval_generates_po_for_credit_suppliers_only(self):
        """Cash purchases settle by slip — no PO (owner, 2026-07-08)."""
        mr, pr = self.full_award()
        pos = Document.objects.filter(doc_type="PO")
        self.assertEqual(pos.count(), 1)  # steel (credit) only, not hw (COD)
        po = pos.first()
        self.assertEqual(po.supplier, self.steel)
        lines = list(po.current_revision.lines.all())
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].item_id, self.rebar.id)
        self.assertEqual(float(lines[0].rate), 18.50)
        self.assertEqual(po.current_revision.payload["pr_ref"], pr["ref"])
        # The order is drafted, not yet placed — it goes to the signatory.
        self.assertEqual(po.status, "DRAFT")
        # PO ref lands in the credit vendor's row; the cash vendor has none.
        fresh = self.client.get(f"/api/v1/documents/{pr['ref']}").data
        po_refs = {row["vendor"]: row["po_ref"] for row in fresh["lines"]}
        self.assertEqual(po_refs["Maldives Steel Traders"], po.ref)
        self.assertEqual(po_refs["Male' Hardware Pvt Ltd"], "")
        # ...and the PR says where that order actually is, so a ref alone
        # never again reads as "order out" while it is a draft.
        steel_row = next(r for r in fresh["lines"]
                         if r["vendor"] == "Maldives Steel Traders")
        self.assertEqual(steel_row["po_status"], "DRAFT")
        # The voucher authorised the CASH vendor; the drafted order settles
        # nothing until the signatory has actually signed it.
        self.assertEqual(fresh["status"], "AUTHORISED")
        self.sign_orders(pr["ref"])
        fresh = self.client.get(f"/api/v1/documents/{pr['ref']}").data
        self.assertEqual(fresh["status"], "PAYMENT_PROCESSING")
        steel_row = next(r for r in fresh["lines"]
                         if r["vendor"] == "Maldives Steel Traders")
        self.assertEqual(steel_row["po_status"], "ISSUED")
        # recording the cash vendor's slip settles the PR (Finance's role)
        self.as_user(self.finance)
        hw_line = next(row for row in fresh["lines"]
                       if row["vendor"] == "Male' Hardware Pvt Ltd")
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/vendor-payment",
                             {"line_id": hw_line["id"],
                              "payment_ref": "TRF-555"})
        self.assertEqual(r.data["status"], "PAID_PO_ISSUED")

    def test_po_issue_generates_pdf_and_lm_prefill(self):
        mr, pr = self.full_award()
        po = Document.objects.filter(doc_type="PO",
                                     supplier=self.steel).first()
        # Purchasing cannot push an order out on its own any more — the
        # signatory's approval is what issues it (owner 2026-08-22).
        self.as_user(self.purchasing)
        blocked = self.act(po.ref, "issue")
        self.assertEqual(blocked.status_code, 400)
        self.act(po.ref, "submit")
        self.as_user(self.signatory)
        r = self.act(po.ref, "authorise")
        self.assertEqual(r.data["status"], "ISSUED")
        self.assertTrue(any(a["kind"] == "GENERATED_PDF"
                            for a in r.data["attachments"]))
        self.as_user(self.purchasing)
        # LM prefill from the PO
        r = self.client.get(f"/api/v1/po/{po.ref}/lm-prefill")
        self.assertEqual(r.data["lines"][0]["qty_loaded"], 500.0)
        # LM created against the PO links PO→LM
        lm = self.client.post("/api/v1/documents", {
            "doc_type": "LM", "site_id": self.site.id,
            "po_refs": [po.ref], "payload": {"vessel": "MV Dhoni 7"},
            "lines": r.data["lines"],
        }, format="json").data
        self.assertIn({"type": "PO_LM", "ref": po.ref, "direction": "to"},
                      lm["links"])

    def test_an_import_order_po_is_untouched_by_the_local_signature_loop(self):
        """An IPR's purchase order was already authorised by a signatory on
        the IPR. It must keep issuing straight from Purchasing, not get sent
        round the local loop where it has no PR to commit (owner
        2026-08-22)."""
        from .models import Document, DocumentRevision
        from .procurement import link_documents
        ipr = Document.objects.create(
            doc_type="IPR", ref="IPR-900", site=self.site,
            doc_date=date.today(), status="AUTHORISED",
            created_by=self.purchasing)
        po = Document.objects.create(
            doc_type="PO", ref="PO-900", site=self.site, doc_date=date.today(),
            status="DRAFT", created_by=self.purchasing, supplier=self.steel)
        po.current_revision = DocumentRevision.objects.create(
            document=po, rev_label="R0", created_by=self.purchasing,
            payload={})
        po.save(update_fields=["current_revision"])
        link_documents(ipr, po, "IPR_PO")
        self.as_user(self.purchasing)
        # Purchasing still issues it directly...
        r = self.act(po.ref, "issue")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "ISSUED")
        # ...and the local signature loop refuses it.
        po2 = Document.objects.create(
            doc_type="PO", ref="PO-901", site=self.site, doc_date=date.today(),
            status="DRAFT", created_by=self.purchasing, supplier=self.steel)
        po2.current_revision = DocumentRevision.objects.create(
            document=po2, rev_label="R0", created_by=self.purchasing,
            payload={})
        po2.save(update_fields=["current_revision"])
        link_documents(ipr, po2, "IPR_PO")
        r2 = self.act(po2.ref, "submit")
        self.assertEqual(r2.status_code, 400)
        self.assertIn("import request", r2.data["detail"])

    def test_the_suppliers_credit_period_reaches_the_payable(self):
        """Sonee gives 60 days and the Suppliers page said so — yet every one
        of its orders was booked at the 30-day default, because nothing ever
        read the record (owner 2026-08-22)."""
        from datetime import date, timedelta

        from .models import Payable
        self.steel.credit_days = 60
        self.steel.save(update_fields=["credit_days"])
        mr, pr = self.full_award()
        # The sync carried the supplier's period onto the vendor row...
        row = next(l for l in self.client.get(
            f"/api/v1/documents/{pr['ref']}").data["lines"]
            if l["vendor"] == self.steel.name)
        self.assertEqual(row["credit_days"], 60)
        # ...and the payable is due on it.
        self.sign_orders(pr["ref"])
        pay = Payable.objects.get(document__ref=pr["ref"])
        self.assertEqual(pay.due_date, date.today() + timedelta(days=60))

    def test_no_agreed_period_anywhere_is_thirty_days_and_says_so(self):
        """The fallback stays 30 — but it is no longer silent."""
        from datetime import date, timedelta

        from .models import Payable
        self.assertIsNone(self.steel.credit_days)
        mr, pr = self.full_award()
        self.sign_orders(pr["ref"])
        pay = Payable.objects.get(document__ref=pr["ref"])
        self.assertEqual(pay.due_date, date.today() + timedelta(days=30))
        self.assertIn("no agreed period on file", pay.terms)

    def test_quotes_locked_after_approval(self):
        mr, pr = self.full_award()
        self.as_user(self.purchasing)
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/quotations", {
            "supplier": self.hw.id, "lines": [],
        }, format="json")
        self.assertEqual(r.status_code, 400)


class ExtractionTests(QuoteBase):
    QUOTE_HTML = """
    <html><body>
    <h2>Male' Hardware Pvt Ltd — Quotation QT-9001</h2>
    <table>
      <tr><th>Description</th><th>Qty</th><th>Unit</th><th>Rate</th>
          <th>Amount</th></tr>
      <tr><td>OPC cement Fuji brand 50kg</td><td>150</td><td>bag</td>
          <td>120.00</td><td>18,000.00</td></tr>
      <tr><td>Deformed bar G500 12mm</td><td>500</td><td>kg</td>
          <td>18.50</td><td>9,250.00</td></tr>
      <tr><td>Delivery charge</td><td>1</td><td>trip</td>
          <td>500.00</td><td>500.00</td></tr>
    </table>
    </body></html>
    """

    def test_pdf_upload_extracts_lines(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        try:
            from weasyprint import HTML
        except Exception:  # pragma: no cover - engine missing locally
            self.skipTest("WeasyPrint unavailable")
        pdf_bytes = HTML(string=self.QUOTE_HTML).write_pdf()

        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        quotation = self.add_quote(pr["ref"], self.hw, [], terms="Cash")
        with override_settings(MEDIA_ROOT="test-media"):
            upload = SimpleUploadedFile("QT-9001.pdf", pdf_bytes,
                                        content_type="application/pdf")
            r = self.client.post(f"/api/v1/quotations/{quotation['id']}/file",
                                 {"file": upload}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["extracted"], 3)
        descriptions = [line["supplier_desc"] for line in r.data["lines"]]
        self.assertIn("OPC cement Fuji brand 50kg", descriptions)
        cement = next(line for line in r.data["lines"]
                      if "OPC" in line["supplier_desc"])
        self.assertEqual(float(cement["qty"]), 150.0)
        self.assertEqual(float(cement["rate"]), 120.0)
        self.assertEqual(float(cement["amount"]), 18000.0)

    def test_upload_does_not_overwrite_existing_lines(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        try:
            from weasyprint import HTML
        except Exception:  # pragma: no cover
            self.skipTest("WeasyPrint unavailable")
        pdf_bytes = HTML(string=self.QUOTE_HTML).write_pdf()

        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        quotation = self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "Manually entered", "qty": 1, "rate": 10},
        ], terms="Cash")
        with override_settings(MEDIA_ROOT="test-media"):
            upload = SimpleUploadedFile("QT-9001.pdf", pdf_bytes,
                                        content_type="application/pdf")
            r = self.client.post(f"/api/v1/quotations/{quotation['id']}/file",
                                 {"file": upload}, format="multipart")
        self.assertEqual(r.data["extracted"], 0)
        self.assertEqual(len(r.data["lines"]), 1)

    QUOTE_HTML_CODE_FIRST = """
    <html><body style="font-family: Arial; font-size: 10pt">
    <h3>MANAS-style layout</h3>
    <p>Code Qty Item Description Rate MVR Amount MVR</p>
    <p>5735 5 TIN PAINT REMOVER BOSNY MVR150.00 MVR750.00</p>
    <p>5340 95 TIN PAINT REMOVER SPRAY DEER MVR90.00 MVR8,550.00</p>
    <p>6611 50 PCS SANDING DISC VELCRO #80 MVR5.00 MVR250.00</p>
    <p>Subtotal: MVR9,550.00</p>
    </body></html>
    """

    def test_code_first_layout_with_currency_prefixes(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        try:
            from weasyprint import HTML
        except Exception:  # pragma: no cover
            self.skipTest("WeasyPrint unavailable")
        pdf_bytes = HTML(string=self.QUOTE_HTML_CODE_FIRST).write_pdf()

        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        quotation = self.add_quote(pr["ref"], self.hw, [], terms="Cash")
        with override_settings(MEDIA_ROOT="test-media"):
            upload = SimpleUploadedFile("manas.pdf", pdf_bytes,
                                        content_type="application/pdf")
            r = self.client.post(f"/api/v1/quotations/{quotation['id']}/file",
                                 {"file": upload}, format="multipart")
        self.assertEqual(r.data["extracted"], 3, r.data["lines"])
        spray = next(line for line in r.data["lines"]
                     if "SPRAY" in line["supplier_desc"])
        self.assertEqual(float(spray["qty"]), 95.0)
        self.assertEqual(float(spray["rate"]), 90.0)
        self.assertEqual(float(spray["amount"]), 8550.0)
        self.assertEqual(spray["unit"], "TIN")
        self.assertIn("5340", spray["remarks"])


class GstTests(PoGenerationTests):
    """GST on local purchases (owner 2026-07-13): per-vendor, gross payment,
    net → project cost, GST → recoverable input-tax account."""

    def test_gross_payment_net_cost_input_tax_and_payable(self):
        from .costing import INPUT_GST_HEAD
        from .models import CostHead, CostPosting, Payable
        from .procurement import (pr_grand_total, pr_gst_total, pr_net_total)
        mr, pr = self.full_award()          # both vendors GST-registered (8%)
        prdoc = Document.objects.get(ref=pr["ref"])
        self.assertEqual(float(pr_net_total(prdoc)), 27250.0)
        self.assertEqual(float(pr_gst_total(prdoc)), 2180.0)     # 8% of 27250
        self.assertEqual(float(pr_grand_total(prdoc)), 29430.0)  # gross

        gst_head = CostHead.objects.get(name=INPUT_GST_HEAD)

        def incurred_net():
            return float(sum(p.amount for p in CostPosting.objects.filter(
                document=prdoc, state="INCURRED").exclude(
                cost_head=gst_head)))

        # Each side commits where it is signed: the cash vendor on Finance's
        # voucher, the credit vendor on its own order (owner 2026-08-22).
        self.assertEqual(incurred_net(), 18000.0)          # cash only so far
        self.sign_orders(pr["ref"])
        mat = CostPosting.objects.filter(
            document=prdoc, state="INCURRED").exclude(cost_head=gst_head)
        self.assertEqual(float(sum(p.amount for p in mat)), 27250.0)  # net
        gst = CostPosting.objects.filter(
            document=prdoc, state="INCURRED", cost_head=gst_head)
        self.assertEqual(float(sum(p.amount for p in gst)), 2180.0)
        self.assertTrue(gst.first().is_stock_pool)   # not a project cost

        # credit vendor's payable is the gross (net 9250 + GST 740)
        pay = Payable.objects.get(document=prdoc)
        self.assertEqual(float(pay.amount), 9990.0)

    def test_gst_off_for_unregistered_vendor(self):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        q = self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "OPC", "unit": "bag", "qty": 150, "rate": 120,
             "mr_line": mr["lines"][0]["id"], "awarded": True}], terms="COD")
        self.as_user(self.purchasing)
        self.client.patch(f"/api/v1/quotations/{q['id']}",
                          {"gst_applicable": False}, format="json")
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/sync-vendor-rows")
        self.assertEqual(float(r.data["lines"][0]["gst_amount"]), 0.0)


class QuotesAfterWithdrawalTests(QuoteBase):
    """PR-159 (BVR, 2026-09-03): authorised, then sent back to draft by
    Finance — and from then on not one quotation could be added, edited or
    removed. Every quote change rebuilt the vendor rows by deleting them,
    and the cost ledger (the authorisation's postings and the withdrawal's
    reversing mirrors) still pointed at those rows."""

    def _authorised_pr(self):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        cement, rebar = mr["lines"][0], mr["lines"][1]
        self.add_quote(pr["ref"], self.hw, [
            {"mr_line": cement["id"], "qty": 150, "rate": "120",
             "awarded": True}])
        # cash, like all three of PR-159's rows — so no PO is drafted and
        # the whole PR travels on the payment voucher
        self.add_quote(pr["ref"], self.steel, [
            {"mr_line": rebar["id"], "qty": 500, "rate": "9",
             "awarded": True}])
        self.as_user(self.purchasing); self.act(pr["ref"], "submit")
        self.as_user(self.director); self.act(pr["ref"], "approve")
        # A PR is authorised on a payment voucher: Finance builds it, a
        # signatory approves it.
        self.as_user(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [pr["ref"]]}, format="json")
        self.assertEqual(pv.status_code, 201, pv.data)
        pref = pv.data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pref}/actions/submit",
                         {}, format="json")
        self.as_user(self.signatory)
        r = self.client.post(f"/api/v1/payment-vouchers/{pref}/actions/approve",
                             {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        doc = Document.objects.get(ref=pr["ref"])
        self.assertEqual(doc.status, "AUTHORISED")
        return doc

    def _withdrawn_pr(self):
        from .models import CostPosting
        pr = self._authorised_pr()
        self.assertTrue(CostPosting.objects.filter(document=pr).exists())
        self.as_user(self.finance)
        r = self.act(pr.ref, "withdraw-authorisation",
                     {"comment": "wrong vendor account"})
        self.assertEqual(r.status_code, 200, r.data)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "DRAFT")
        return pr

    def _rows(self, pr):
        return {ln.vendor: ln for ln in pr.current_revision.lines.all()}

    def test_a_new_quotation_can_be_captured_after_withdrawal(self):
        from .models import CostPosting
        pr = self._withdrawn_pr()
        before = self._rows(pr)
        ids_before = {v: ln.id for v, ln in before.items()}
        third = Supplier.objects.create(name="Ace Hardware")
        self.as_user(self.purchasing)
        # add a third supplier's quote — the exact action that 500'd
        r = self.client.post(f"/api/v1/pr/{pr.ref}/quotations", {
            "supplier": third.id, "quote_ref": "NHW/4472",
            "payment_terms": "", "lines": [
                {"supplier_desc": "Adhesive", "qty": 10, "rate": "19.44",
                 "awarded": True}]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        after = self._rows(pr)
        self.assertIn("Ace Hardware", after)
        # the rows the ledger points at are the SAME rows, not recreated
        for vendor, lid in ids_before.items():
            self.assertEqual(after[vendor].id, lid, vendor)
        self.assertTrue(CostPosting.objects.filter(
            document_line__in=list(ids_before.values())).exists())

    def test_a_quotation_can_be_edited_and_removed_after_withdrawal(self):
        pr = self._withdrawn_pr()
        self.as_user(self.purchasing)
        quotes = self.client.get(f"/api/v1/pr/{pr.ref}/quotations").data
        steel = next(q for q in quotes
                     if q["supplier_name"] == self.steel.name)
        r = self.client.patch(f"/api/v1/quotations/{steel['id']}",
                              {"quote_ref": "MST-777"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self._rows(pr)[self.steel.name].quotation_ref,
                         "MST-777")
        r = self.client.delete(f"/api/v1/quotations/{steel['id']}")
        self.assertIn(r.status_code, (200, 204), getattr(r, "data", None))

    def test_a_removed_quotations_row_stays_at_zero_when_the_ledger_holds_it(self):
        """Deleting it would take the postings' target with it. It stays,
        empty, and says why."""
        pr = self._withdrawn_pr()
        self.as_user(self.purchasing)
        row_id = self._rows(pr)[self.steel.name].id
        steel = next(q for q in self.client.get(
            f"/api/v1/pr/{pr.ref}/quotations").data
            if q["supplier_name"] == self.steel.name)
        r = self.client.delete(f"/api/v1/quotations/{steel['id']}")
        self.assertIn(r.status_code, (200, 204), getattr(r, "data", None))
        ln = pr.current_revision.lines.get(id=row_id)
        self.assertIsNone(ln.amount_cash)
        self.assertIsNone(ln.amount_credit)
        self.assertIn("quotation removed", ln.remarks)

    def test_a_draft_pr_still_drops_the_row_of_a_removed_quotation(self):
        """No ledger, no reason to keep it — the ordinary case is unchanged."""
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        q = self.add_quote(pr["ref"], self.hw, [
            {"mr_line": mr["lines"][0]["id"], "qty": 1, "rate": "5",
             "awarded": True}])
        doc = Document.objects.get(ref=pr["ref"])
        self.assertIn(self.hw.name, self._rows(doc))
        self.client.delete(f"/api/v1/quotations/{q['id']}")
        self.assertNotIn(self.hw.name, self._rows(doc))
