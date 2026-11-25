"""The purchasing registers are drawn a page at a time.

They used to send their newest 300 rows and stop. With 490 PRs on file the
register ended at PR-191 — everything older was simply not there, and the
search box looked only through the rows that had been sent (owner
2026-11-25). Paging and the search now happen on the server, over the whole
register.
"""
from decimal import Decimal

from .models import Document, DocumentLine, DocumentLink, DocumentRevision
from .tests_pr_costing import PrCostingBase


class RegisterPagingTests(PrCostingBase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.purchasing)

    def doc(self, doc_type, ref, payload=None, status="DRAFT", lines=(),
            **extra):
        d = Document.objects.create(
            doc_type=doc_type, ref=ref, site=self.site, doc_date="2026-09-01",
            status=status, created_by=self.purchasing, **extra)
        rev = DocumentRevision.objects.create(
            document=d, rev_label="R0", created_by=self.purchasing,
            payload=payload or {})
        for i, (cash, slip) in enumerate(lines, start=1):
            DocumentLine.objects.create(
                revision=rev, line_no=i, free_text_desc=f"Item {i}",
                amount_cash=cash, action_taken=slip)
        d.current_revision = rev
        d.save(update_fields=["current_revision"])
        return d

    def refs(self, register, **params):
        r = self.client.get(f"/api/v1/registers/{register}", params)
        self.assertEqual(r.status_code, 200, r.data)
        return [row["ref"] for row in r.data["rows"]], r.data

    def many(self, n):
        Document.objects.bulk_create([
            Document(doc_type="PR", ref=f"PR-T{i:04d}", site=self.site,
                     doc_date="2026-09-01", status="DRAFT",
                     created_by=self.purchasing)
            for i in range(1, n + 1)])

    def test_every_row_is_reachable_a_page_at_a_time(self):
        self.many(320)
        refs, data = self.refs("pr")
        self.assertEqual(data["total"], 320)
        self.assertEqual(len(refs), 50)
        self.assertEqual(refs[0], "PR-T0320")               # newest first
        seen = []
        for offset in range(0, 320, 50):
            seen += self.refs("pr", offset=offset)[0]
        self.assertEqual(len(seen), 320)
        self.assertEqual(len(set(seen)), 320)
        self.assertEqual(seen[-1], "PR-T0001")              # the oldest is there

    def test_the_page_size_is_capped_and_bad_paging_refused(self):
        self.many(230)
        refs, data = self.refs("pr", limit=5000)
        self.assertEqual((len(refs), data["limit"]), (200, 200))
        self.assertEqual(self.client.get(
            "/api/v1/registers/pr", {"offset": "x"}).status_code, 400)

    def test_search_reaches_rows_far_beyond_the_first_page(self):
        old = self.doc("PR", "PR-OLD-7", {"requested_delivery": "2026-03-14"})
        self.many(320)
        self.assertNotIn(old.ref, self.refs("pr")[0])
        refs, data = self.refs("pr", q="old-7")
        self.assertEqual((refs, data["total"]), ([old.ref], 1))
        self.assertEqual(self.refs("pr", q="2026-03-14")[0], [old.ref])

    def test_search_matches_what_the_row_shows(self):
        po = self.doc("PO", "PO-901", {"supplier_name": "Manas Hardware",
                                       "payment_terms": "30 days credit"},
                      status="ISSUED")
        other = self.doc("PO", "PO-902", {"supplier_name": "Reefside"})
        pr = self.doc("PR", "PR-901", status="AUTHORISED")
        DocumentLink.objects.create(from_document=pr, to_document=po,
                                    link_type="PR_PO")
        self.assertEqual(self.refs("po", q="manas")[0], [po.ref])
        self.assertEqual(self.refs("po", q="pr-901")[0], [po.ref])   # linked
        self.assertEqual(self.refs("pr", q="po-901")[0], [pr.ref])
        self.assertEqual(self.refs("po", q="issued")[0], [po.ref])
        self.assertEqual(self.refs("po", q=self.site.code.lower())[0],
                         [other.ref, po.ref])
        self.assertEqual(self.refs("pr", q="authorised")[0], [pr.ref])
        # every word must match
        self.assertEqual(self.refs("po", q="manas issued")[0], [po.ref])
        self.assertEqual(self.refs("po", q="manas reefside")[0], [])

    def test_a_void_document_is_found_as_void_not_by_its_old_status(self):
        d = self.doc("PR", "PR-950", status="AUTHORISED", is_void=True)
        self.assertEqual(self.refs("pr", q="void")[0], [d.ref])
        self.assertEqual(self.refs("pr", q="authorised")[0], [])

    def test_paid_and_part_find_prs_by_their_payments(self):
        cash = Decimal("100")
        paid = self.doc("PR", "PR-960", status="AUTHORISED",
                        lines=[(cash, "TT-1"), (cash, "TT-2")])
        part = self.doc("PR", "PR-961", status="AUTHORISED",
                        lines=[(cash, "TT-3"), (cash, "")])
        self.doc("PR", "PR-962", status="AUTHORISED", lines=[(cash, " ")])
        self.doc("PR", "PR-963", status="AUTHORISED",
                 lines=[(Decimal("0"), "")])                 # credit only
        self.assertEqual(self.refs("pr", q="paid")[0], [part.ref, paid.ref])
        self.assertEqual(self.refs("pr", q="part")[0], [part.ref])


class DocumentListPagingTests(PrCostingBase):
    """The general documents list keeps its newest-200 answer for pickers and
    dashboard cards; a register that asks for a page gets one, with the
    count, and can reach every row."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.purchasing)
        Document.objects.bulk_create([
            Document(doc_type="PYR", ref=f"PYR-T{i:04d}", site=self.site,
                     doc_date="2026-09-01", created_by=self.purchasing,
                     status="PAID" if i % 2 else "AUTHORISED",
                     is_void=(i == 2))
            for i in range(1, 261)])

    def page(self, **params):
        r = self.client.get("/api/v1/documents/list",
                            {"doc_type": "PYR", **params})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_without_a_limit_the_answer_is_the_list_it_always_was(self):
        self.assertEqual(len(self.page()), 200)

    def test_a_page_carries_the_count_and_the_oldest_is_reachable(self):
        d = self.page(mine=1, limit=50)
        self.assertEqual((d["total"], len(d["rows"])), (260, 50))
        self.assertEqual(d["rows"][0]["ref"], "PYR-T0260")
        last = self.page(mine=1, limit=50, offset=250)
        self.assertEqual([r["ref"] for r in last["rows"]][-1], "PYR-T0001")
        self.assertEqual(len(last["rows"]), 10)

    def test_the_tabs_are_filtered_before_the_page_is_cut(self):
        self.assertEqual(self.page(limit=50, statuses="PAID")["total"], 130)
        both = self.page(limit=50, statuses="PAID,AUTHORISED")
        self.assertEqual(both["total"], 260)
        live = self.page(limit=50, statuses="AUTHORISED", live=1)
        self.assertEqual(live["total"], 129)                # one is void

    def test_bad_paging_is_refused(self):
        r = self.client.get("/api/v1/documents/list",
                            {"doc_type": "PYR", "limit": "many"})
        self.assertEqual(r.status_code, 400)
