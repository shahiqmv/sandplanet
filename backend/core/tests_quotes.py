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
            "doc_type": "MR", "site_id": self.site.id,
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
        rebar_line = mr["lines"][1]["id"]
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
        return mr, pr

    def test_approval_generates_po_per_supplier(self):
        mr, pr = self.full_award()
        pos = Document.objects.filter(doc_type="PO").order_by("ref")
        self.assertEqual(pos.count(), 2)
        self.assertEqual([po.ref for po in pos], ["PO-001", "PO-002"])
        by_supplier = {po.supplier.name: po for po in pos}
        hw_po = by_supplier["Male' Hardware Pvt Ltd"]
        lines = list(hw_po.current_revision.lines.all())
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].item_id, self.cement.id)
        self.assertEqual(float(lines[0].qty_required), 150.0)
        self.assertEqual(float(lines[0].rate), 120.0)
        self.assertEqual(float(lines[0].amount), 18000.0)
        self.assertEqual(hw_po.current_revision.payload["pr_ref"], pr["ref"])
        # PO refs land in the PR's vendor rows (R3 addendum)
        fresh = self.client.get(f"/api/v1/documents/{pr['ref']}").data
        po_refs = {row["vendor"]: row["po_ref"] for row in fresh["lines"]}
        self.assertEqual(po_refs["Male' Hardware Pvt Ltd"], hw_po.ref)

    def test_po_issue_generates_pdf_and_lm_prefill(self):
        self.full_award()
        po = Document.objects.filter(doc_type="PO",
                                     supplier=self.steel).first()
        self.as_user(self.purchasing)
        r = self.act(po.ref, "issue")
        self.assertEqual(r.data["status"], "ISSUED")
        self.assertTrue(any(a["kind"] == "GENERATED_PDF"
                            for a in r.data["attachments"]))
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
