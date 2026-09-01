"""The PO register carries the commercial face of the order.

A purchasing officer scanning the register is asking three things of every
row: who is it with, what is it worth, and on what terms. Those used to live
only inside the document (owner 2026-09-01).
"""
from decimal import Decimal

from .models import Document, DocumentLine, DocumentRevision
from .tests_pr_costing import PrCostingBase
from .views_documents import _po_summary


class PoSummaryTests(PrCostingBase):
    def make_po(self, payload, amounts):
        po = Document.objects.create(
            doc_type="PO", ref="PO-TEST-1", site=self.site,
            doc_date="2026-09-01", status="DRAFT", created_by=self.purchasing)
        rev = DocumentRevision.objects.create(
            document=po, rev_label="R0", created_by=self.purchasing,
            payload=payload)
        for i, amt in enumerate(amounts, start=1):
            DocumentLine.objects.create(revision=rev, line_no=i,
                                        free_text_desc=f"Item {i}",
                                        amount=amt)
        po.current_revision = rev
        po.save(update_fields=["current_revision"])
        return po, rev

    def test_value_is_totalled_from_the_lines(self):
        """The lines are what the supplier is held to. A total kept beside
        them is a total that can drift from them."""
        _, rev = self.make_po({"supplier_name": "Vendor B"},
                              [Decimal("2500.50"), Decimal("7000"),
                               Decimal("1.50")])
        self.assertEqual(_po_summary(rev, rev.payload)["order_value"],
                         Decimal("9502.00"))

    def test_a_line_with_no_amount_does_not_break_the_total(self):
        _, rev = self.make_po({}, [Decimal("100"), None])
        self.assertEqual(_po_summary(rev, rev.payload)["order_value"],
                         Decimal("100"))

    def test_supplier_and_terms_come_through(self):
        _, rev = self.make_po({"supplier_name": "  Manas Hardware  ",
                               "supplier_contact": "Majeed",
                               "payment_terms": "30 days credit",
                               "expected_delivery": "2026-09-20"}, [])
        s = _po_summary(rev, rev.payload)
        self.assertEqual(s["supplier"], "Manas Hardware")
        self.assertEqual(s["supplier_contact"], "Majeed")
        self.assertEqual(s["payment_terms"], "30 days credit")
        self.assertEqual(s["expected_delivery"], "2026-09-20")

    def test_an_import_order_is_named_by_its_import_request(self):
        _, rev = self.make_po({"ipr_ref": "IPR-047", "currency": "USD"}, [])
        s = _po_summary(rev, rev.payload)
        self.assertEqual((s["source_kind"], s["source_ref"]),
                         ("IMPORT", "IPR-047"))
        self.assertEqual(s["currency"], "USD")

    def test_a_local_order_is_named_by_its_requisition(self):
        _, rev = self.make_po({"pr_ref": "PR-018"}, [])
        s = _po_summary(rev, rev.payload)
        self.assertEqual((s["source_kind"], s["source_ref"]),
                         ("LOCAL", "PR-018"))

    def test_currency_defaults_to_rufiyaa(self):
        """Local orders carry no currency field — they are always MVR."""
        _, rev = self.make_po({"pr_ref": "PR-018"}, [])
        self.assertEqual(_po_summary(rev, rev.payload)["currency"], "MVR")

    def test_an_order_with_neither_source_claims_neither(self):
        _, rev = self.make_po({"supplier_name": "Walk-in"}, [])
        s = _po_summary(rev, rev.payload)
        self.assertEqual((s["source_kind"], s["source_ref"]), ("", ""))


class PoRegisterTests(PrCostingBase):
    def test_the_register_row_carries_the_order_commercially(self):
        pr = self.make_pr()
        pos = self.sign_orders(pr)
        self.client.force_authenticate(self.purchasing)
        rows = self.client.get("/api/v1/registers/po").data["rows"]
        row = next(r for r in rows if r["ref"] == pos[0].ref)
        self.assertEqual(row["supplier"], "Vendor B")
        self.assertEqual(row["payment_terms"], "Credit")
        self.assertEqual(Decimal(str(row["order_value"])), Decimal("7000"))
        self.assertEqual(row["source_kind"], "LOCAL")
        self.assertEqual(row["source_ref"], pr.ref)

    def test_other_registers_are_left_alone(self):
        """Only the PO register pays for the extra work."""
        self.make_pr()
        self.client.force_authenticate(self.purchasing)
        rows = self.client.get("/api/v1/registers/mr").data["rows"]
        self.assertTrue(rows)
        self.assertNotIn("supplier", rows[0])
        self.assertNotIn("order_value", rows[0])
