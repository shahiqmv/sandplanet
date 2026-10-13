"""Requests for quotation on a material request (owner 2026-10-13).

Purchasing asks suppliers before it buys: picks the MR's items, names the
supplier (mandatory — it is a record on the MR), adds a remark, prints the
RFQ. The supplier's quote is uploaded against it, and the PR picks it up as
its quotation with the asked items already matched to their MR lines.
"""
from django.core.files.uploadedfile import SimpleUploadedFile

from .models import AuditLog, MrRfq, Supplier
from .tests_quotes import QuoteBase


def a_quote(name="quote.jpg"):
    return SimpleUploadedFile(name, b"\xff\xd8\xff\xe0" + b"0" * 64,
                              content_type="image/jpeg")


class MrRfqTests(QuoteBase):
    def _send(self, mr, line_ids, **extra):
        self.as_user(self.purchasing)
        return self.client.post(f"/api/v1/mr/{mr['ref']}/rfqs",
                                {"line_ids": line_ids, **extra},
                                format="json")

    def test_purchasing_sends_an_rfq_to_a_named_supplier(self):
        mr = self.sent_mr()
        ids = [ln["id"] for ln in mr["lines"]]
        # the supplier is mandatory
        r = self._send(mr, ids)
        self.assertEqual(r.status_code, 400)
        self.assertIn("supplier", r.data["detail"].lower())
        r = self._send(mr, ids[:1], supplier_id=self.hw.id,
                       remark="Please quote ex-stock, delivery to the jetty.")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["ref"], "RFQ-SJR-001")
        self.assertEqual(r.data["supplier"], self.hw.name)
        self.assertEqual([str(ln["qty"]) for ln in r.data["lines"]], ["150.00"])
        # kept on the MR's record
        d = self.client.get(f"/api/v1/mr/{mr['ref']}/rfqs").data
        self.assertEqual([x["ref"] for x in d["rfqs"]], ["RFQ-SJR-001"])
        self.assertTrue(AuditLog.objects.filter(event="MR_RFQ_SENT").exists())
        # a new supplier can be named on the spot, as a local supplier
        r = self._send(mr, ids, supplier_name="Atoll Building Supplies")
        self.assertEqual(r.status_code, 201, r.data)
        s = Supplier.objects.get(name="Atoll Building Supplies")
        self.assertEqual(s.category, "LOCAL")
        self.assertEqual(r.data["ref"], "RFQ-SJR-002")

    def test_the_pdf_carries_the_items_and_the_remark_only(self):
        import fitz
        mr = self.sent_mr()
        r = self._send(mr, [mr["lines"][0]["id"]], supplier_id=self.hw.id,
                       remark="Delivery to Male jetty within a week.")
        pdf = self.client.get(f"/api/v1/mr-rfqs/{r.data['id']}/pdf")
        self.assertEqual(pdf.status_code, 200)
        doc = fitz.open("pdf", pdf.content)
        text = "".join(p.get_text() for p in doc)
        doc.close()
        for want in ("REQUEST FOR QUOTATION", "RFQ-SJR-001", self.hw.name,
                     "Quote to", "Cement OPC 50kg bag", "150",
                     "Delivery to Male jetty within a week."):
            self.assertIn(want, text)
        self.assertNotIn("Rebar", text)              # not asked
        self.assertNotIn(mr["ref"], text)            # nothing internal

    def test_only_purchasing_and_only_while_the_mr_is_with_purchasing(self):
        mr = self.sent_mr()
        self.as_user(self.sa)
        r = self.client.post(f"/api/v1/mr/{mr['ref']}/rfqs",
                             {"line_ids": [mr["lines"][0]["id"]],
                              "supplier_id": self.hw.id}, format="json")
        self.assertEqual(r.status_code, 400)
        # a draft MR is not Purchasing's yet
        self.as_user(self.sa)
        draft = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id, "general_works": True,
            "lines": [{"item_id": self.cement.id, "qty_required": 5,
                       "qty_stock": 0, "qty_to_order": 5}]},
            format="json").data
        r = self._send(draft, [draft["lines"][0]["id"]],
                       supplier_id=self.hw.id)
        self.assertEqual(r.status_code, 400)
        self.assertIn("with Purchasing", r.data["detail"])

    def test_the_pr_takes_the_quote_from_the_rfq_matched_to_the_mr(self):
        mr = self.sent_mr()
        ids = [ln["id"] for ln in mr["lines"]]
        rfq = self._send(mr, ids, supplier_id=self.steel.id).data
        pr = self.draft_pr(mr)
        # nothing to pick until the supplier's quote is uploaded
        self.assertEqual(self.client.get(
            f"/api/v1/pr/{pr['ref']}/rfq-quotes").data, [])
        r = self.client.post(f"/api/v1/mr-rfqs/{rfq['id']}/quote",
                             {"file": a_quote(), "quote_ref": "MST/889",
                              "quote_date": "2026-10-12"},
                             format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["quote_ref"], "MST/889")
        avail = self.client.get(f"/api/v1/pr/{pr['ref']}/rfq-quotes").data
        self.assertEqual([x["ref"] for x in avail], [rfq["ref"]])
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/rfq-quotes",
                             {"rfq_id": rfq["id"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["supplier"], self.steel.id)
        self.assertEqual(r.data["rfq_ref"], rfq["ref"])
        self.assertEqual(r.data["quote_ref"], "MST/889")
        self.assertTrue(r.data["file_url"])
        self.assertEqual(sorted(ln["mr_line"] for ln in r.data["lines"]),
                         sorted(ids))
        # taken once; the MR's record says where it went
        self.assertEqual(self.client.get(
            f"/api/v1/pr/{pr['ref']}/rfq-quotes").data, [])
        self.assertEqual(self.client.post(
            f"/api/v1/pr/{pr['ref']}/rfq-quotes", {"rfq_id": rfq["id"]},
            format="json").status_code, 400)
        d = self.client.get(f"/api/v1/mr/{mr['ref']}/rfqs").data
        self.assertEqual(d["rfqs"][0]["used_on"], [pr["ref"]])

    def test_one_rfq_sequence_per_site_with_the_schedule(self):
        mr = self.sent_mr()
        AuditLog.objects.create(entity="document", entity_id=1,
                                event="PSC_RFQ",
                                detail={"ref": "RFQ-SJR-001", "site": "SJR"})
        r = self._send(mr, [mr["lines"][0]["id"]], supplier_id=self.hw.id)
        self.assertEqual(r.data["ref"], "RFQ-SJR-002")
        self.assertEqual(MrRfq.objects.count(), 1)
