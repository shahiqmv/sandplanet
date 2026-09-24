"""Trading arm — phase 1 foundations (TRADING_BUILD_BRIEF.md).

The wall: Sales roles see only /api/trading; site roles get nothing there;
the ledger book keeps trading money out of every project figure; the
trading numbering series is company-wide.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction

from . import costing
from .models import CostHead, CostPosting, Customer, Supplier, User
from .numbering import next_ref
from .tests import BaseCase, make_user


class TradingAccessTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.sales = make_user("sales1", User.Role.SALES)
        self.sm = make_user("sm1", User.Role.SALES_MANAGER)
        self.finance = make_user("fin1", User.Role.FINANCE)

    def test_sales_roles_are_not_site_roles(self):
        self.assertTrue(self.sales.is_trading)
        self.assertFalse(self.sales.is_ho)
        self.assertFalse(self.pm.is_trading)
        self.login(self.sales)
        r = self.client.get("/api/v1/sites")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 0)          # no site allocation → nothing

    def test_site_roles_cannot_enter_the_trading_api(self):
        for u in (self.pm, self.engineer):
            self.login(u)
            self.assertEqual(self.client.get("/api/v1/trading/home").status_code, 403)
            self.assertEqual(self.client.get("/api/v1/trading/customers").status_code, 403)

    def test_finance_reads_but_does_not_write(self):
        self.login(self.finance)
        r = self.client.get("/api/v1/trading/home")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can_write"])
        r = self.client.post("/api/v1/trading/customers", {"name": "Reef Resort"})
        self.assertEqual(r.status_code, 403)

    def test_sales_and_admin_write(self):
        for u in (self.sales, self.sm, self.admin):
            self.login(u)
            r = self.client.post("/api/v1/trading/customers",
                                 {"name": f"Customer {u.username}"})
            self.assertEqual(r.status_code, 201, r.data)


class CustomerTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.sales = make_user("sales1", User.Role.SALES)
        self.login(self.sales)

    def test_create_search_and_edit(self):
        r = self.client.post("/api/v1/trading/customers", {
            "name": "Kuramathi Maldives", "tin": "1001234GST501",
            "island": "Rasdhoo", "vessels": "Kuramathi 3, Kuramathi 5",
            "default_currency": "usd", "credit_days": 30})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["default_currency"], "USD")
        cid = r.data["id"]
        self.assertEqual(Customer.objects.get(id=cid).created_by, self.sales)
        r = self.client.get("/api/v1/trading/customers?search=rasdhoo")
        self.assertEqual([c["name"] for c in r.data], ["Kuramathi Maldives"])
        r = self.client.patch(f"/api/v1/trading/customers/{cid}",
                              {"credit_days": 45, "gst_exempt": True})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["credit_days"], 45)
        self.assertTrue(r.data["gst_exempt"])

    def test_duplicate_name_and_bad_currency_refused(self):
        self.client.post("/api/v1/trading/customers", {"name": "Reef Resort"})
        r = self.client.post("/api/v1/trading/customers", {"name": "reef resort"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/trading/customers",
                             {"name": "Other", "default_currency": "EUR"})
        self.assertEqual(r.status_code, 400)

    def test_inactive_customers_hidden_unless_asked(self):
        r = self.client.post("/api/v1/trading/customers", {"name": "Old Co"})
        self.client.patch(f"/api/v1/trading/customers/{r.data['id']}",
                          {"is_active": False})
        self.assertEqual(len(self.client.get("/api/v1/trading/customers").data), 0)
        self.assertEqual(
            len(self.client.get("/api/v1/trading/customers?active=all").data), 1)


class TradingSupplierTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.sales = make_user("sales1", User.Role.SALES)
        self.login(self.sales)

    def test_sales_add_their_own_suppliers(self):
        r = self.client.post("/api/v1/trading/suppliers", {
            "name": "Guangzhou Tiles Co", "category": "INTERNATIONAL",
            "country": "China", "default_currency": "USD"})
        self.assertEqual(r.status_code, 201, r.data)
        s = Supplier.objects.get(id=r.data["id"])
        self.assertTrue(s.is_trading)
        self.assertNotIn("bank_details", r.data)
        # the purchasing directory sees it too — one directory underneath
        self.login(self.admin)
        names = [x["name"] for x in self.client.get("/api/v1/suppliers").data]
        self.assertIn("Guangzhou Tiles Co", names)

    def test_only_trading_suppliers_are_listed_here(self):
        Supplier.objects.create(name="Purchasing Only", category="LOCAL")
        Supplier.objects.create(name="Both", category="LOCAL", is_trading=True)
        names = [x["name"] for x in self.client.get("/api/v1/trading/suppliers").data]
        self.assertEqual(names, ["Both"])

    def test_a_known_supplier_is_adopted_not_duplicated(self):
        known = Supplier.objects.create(name="Alia Store", category="LOCAL")
        r = self.client.post("/api/v1/trading/suppliers",
                             {"name": "alia store", "category": "LOCAL"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["id"], known.id)
        self.assertEqual(Supplier.objects.filter(name__iexact="alia store").count(), 1)
        self.assertTrue(Supplier.objects.get(id=known.id).is_trading)
        r = self.client.post("/api/v1/trading/suppliers",
                             {"name": "Alia Store", "category": "LOCAL"})
        self.assertEqual(r.status_code, 400)

    def test_forwarders_are_not_trading_suppliers(self):
        r = self.client.post("/api/v1/trading/suppliers",
                             {"name": "Fast Freight", "category": "FORWARDER"})
        self.assertEqual(r.status_code, 400)


class LedgerBookTests(BaseCase):
    """The wall on the ledger: a TRADING posting never reaches a project
    figure, and a reversal stays in its original's book."""

    def setUp(self):
        super().setUp()
        self.head = CostHead.objects.get(name="Materials")
        self.finance = make_user("fin1", User.Role.FINANCE)

    def _post(self, amount, book="PROJECT", state="INCURRED"):
        return costing.post(site=self.sjr, cost_head=self.head, state=state,
                            source="PYR", amount=amount, posted_on=date.today(),
                            book=book, currency="USD")

    def test_default_book_is_project(self):
        p = costing.post(site=self.sjr, cost_head=self.head, state="INCURRED",
                         source="PYR", amount=10)
        self.assertEqual(p.book, "PROJECT")

    def test_reversal_keeps_the_book(self):
        p = self._post(500, book="TRADING")
        rev = costing.post(site=self.sjr, cost_head=self.head, state="INCURRED",
                           source="PYR", amount=-500, reversal_of=p)
        self.assertEqual(rev.book, "TRADING")

    def test_project_cost_reads_ignore_trading_postings(self):
        self._post(1000)
        self._post(9999, book="TRADING")
        self.login(self.finance)
        r = self.client.get(f"/api/v1/cost/site/{self.sjr.id}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(str(r.data["incurred"])), Decimal("1000"))
        r = self.client.get(f"/api/v1/cost/site/{self.sjr.id}/postings")
        self.assertEqual(r.status_code, 200)
        rows = r.data if isinstance(r.data, list) else r.data.get("postings", r.data.get("results"))
        self.assertEqual(len(rows), 1)
        r = self.client.get("/api/v1/cost/portfolio")
        self.assertEqual(r.status_code, 200)
        sjr = next(x for x in r.data["sites"] if x["site_code"] == "SJR")
        self.assertEqual(Decimal(str(sjr["incurred"])), Decimal("1000"))

    def test_the_book_is_indexed_and_queryable(self):
        self._post(1, book="TRADING")
        self.assertEqual(CostPosting.objects.filter(book="TRADING").count(), 1)
        self.assertEqual(CostPosting.objects.filter(book="PROJECT").count(), 0)


class TradingNumberingTests(BaseCase):
    def test_trading_series_are_company_wide(self):
        with transaction.atomic():
            self.assertEqual(next_ref("TIN", self.sjr), "TIN-001")
            self.assertEqual(next_ref("TIN", self.vkr), "TIN-002")
            self.assertEqual(next_ref("TQ", None), "TQ-001")
            self.assertEqual(next_ref("TSO", None), "TSO-001")
            self.assertEqual(next_ref("TDN", None), "TDN-001")
            self.assertEqual(next_ref("TSI", None), "TSI-001")
            self.assertEqual(next_ref("TCN", None), "TCN-001")


# ---- phase 2: the sales front ----------------------------------------------

from unittest import skipUnless  # noqa: E402

from . import trading  # noqa: E402
from .models import (CompanyParameter, Item, TradingLine, TradingOrder,  # noqa: E402
                     TradingQuotation)


def _pdf_engine():
    try:
        from weasyprint import HTML
        HTML(string="<p>x</p>").write_pdf()
        return True
    except Exception:
        return False


class SalesFrontBase(BaseCase):
    def setUp(self):
        super().setUp()
        self.sales = make_user("sales1", User.Role.SALES)
        self.sales2 = make_user("sales2", User.Role.SALES)
        self.sm = make_user("sm1", User.Role.SALES_MANAGER)
        self.finance = make_user("fin1", User.Role.FINANCE)
        self.cust = Customer.objects.create(name="Kuramathi Maldives", tin="1001234GST501",
                                            island="Rasdhoo", default_currency="MVR")
        self.sup = Supplier.objects.create(name="Guangzhou Tiles", category="INTERNATIONAL",
                                           is_trading=True, default_currency="USD")
        CompanyParameter.objects.update_or_create(key="usd_mvr_rate",
                                                  defaults={"value": "15.42"})
        CompanyParameter.objects.update_or_create(key="gst_rate", defaults={"value": "8"})

    def new_order(self, user=None, **kw):
        self.login(user or self.sales)
        r = self.client.post("/api/v1/trading/orders",
                             {"customer": self.cust.id, "title": "Pool tiles", **kw},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def put_lines(self, oid, lines, user=None):
        self.login(user or self.sales)
        r = self.client.put(f"/api/v1/trading/orders/{oid}/lines", {"lines": lines},
                            format="json")
        return r

    TILE = {"description": "Porcelain pool tile 300x300", "qty": "1000", "uom": "m2",
            "cost": "10", "cost_currency": "USD", "margin_percent": "20"}


class InquiryRegisterTests(SalesFrontBase):
    def test_create_numbers_and_owns_the_inquiry(self):
        d = self.new_order()
        self.assertEqual(d["ref"], "TIN-001")
        self.assertEqual(d["owner"], self.sales.id)
        self.assertEqual(d["stage"], "INQUIRY")
        self.assertEqual(d["currency"], "MVR")       # the customer's default
        self.assertTrue(d["can_manage"])
        d2 = self.new_order(title="Second")
        self.assertEqual(d2["ref"], "TIN-002")
        r = self.client.get("/api/v1/trading/orders?search=kuramathi")
        self.assertEqual(len(r.data), 2)
        r = self.client.get("/api/v1/trading/orders?mine=1")
        self.assertEqual(len(r.data), 2)

    def test_everyone_in_trading_reads_but_only_the_owner_edits(self):
        d = self.new_order()
        self.login(self.sales2)
        r = self.client.get(f"/api/v1/trading/orders/{d['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can_manage"])
        r = self.client.patch(f"/api/v1/trading/orders/{d['id']}", {"title": "x"},
                              format="json")
        self.assertEqual(r.status_code, 403)
        self.login(self.sm)                           # the manager edits any
        r = self.client.patch(f"/api/v1/trading/orders/{d['id']}",
                              {"title": "Pool tiles — phase 2", "owner": self.sales2.id},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["owner"], self.sales2.id)
        self.login(self.finance)
        self.assertEqual(self.client.post("/api/v1/trading/orders",
                                          {"customer": self.cust.id, "title": "x"},
                                          format="json").status_code, 403)

    def test_header_validation(self):
        self.login(self.sales)
        r = self.client.post("/api/v1/trading/orders", {"customer": 999, "title": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/trading/orders",
                             {"customer": self.cust.id, "title": "", "currency": "EUR"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("title", r.data)


class PricingSheetTests(SalesFrontBase):
    def test_cost_converts_at_the_company_rate_and_margin_prices_the_line(self):
        d = self.new_order()
        r = self.put_lines(d["id"], [self.TILE])
        self.assertEqual(r.status_code, 200, r.data)
        ln = r.data["lines"][0]
        self.assertEqual(ln["calc"]["fx"], "15.42")
        self.assertEqual(ln["calc"]["unit_cost"], "154.2000")
        self.assertEqual(ln["calc"]["unit_sell"], "185.0400")   # +20 %
        self.assertEqual(ln["calc"]["line_sell"], "185040.00")
        k = r.data["calc"]
        self.assertEqual(k["cost_total"], "154200.00")
        self.assertEqual(k["subtotal"], "185040.00")
        self.assertEqual(k["gst"], "14803.20")
        self.assertEqual(k["total"], "199843.20")
        self.assertEqual(k["margin_percent"], "20.00")
        self.assertEqual(r.data["stage"], "PRICING")             # derived from the cost

    def test_a_typed_sell_price_wins_and_reports_its_margin(self):
        d = self.new_order()
        r = self.put_lines(d["id"], [{**self.TILE, "sell": "200"}])
        ln = r.data["lines"][0]
        self.assertEqual(ln["calc"]["unit_sell"], "200.0000")
        self.assertEqual(ln["calc"]["margin_percent"], "29.70")

    def test_line_ids_survive_a_resave_and_a_supplier_moves_to_sourcing(self):
        d = self.new_order()
        r = self.put_lines(d["id"], [{"description": "Tile", "qty": "10",
                                      "supplier": self.sup.id}])
        self.assertEqual(r.data["stage"], "SOURCING")
        lid = r.data["lines"][0]["id"]
        r = self.put_lines(d["id"], [{"id": lid, "description": "Tile 300x300",
                                      "qty": "12", "supplier": self.sup.id},
                                     {"description": "Grout", "qty": "5"}])
        self.assertEqual([x["id"] for x in r.data["lines"]][0], lid)
        self.assertEqual(r.data["lines"][0]["description"], "Tile 300x300")
        self.assertEqual(r.data["lines"][1]["sr_no"], 2)
        self.assertEqual(TradingLine.objects.filter(order_id=d["id"]).count(), 2)

    def test_same_currency_needs_no_rate_and_an_unknown_pair_is_flagged(self):
        d = self.new_order()
        r = self.put_lines(d["id"], [{**self.TILE, "cost_currency": "MVR", "cost": "150"},
                                     {**self.TILE, "cost_currency": "EUR"}])
        self.assertEqual(r.data["lines"][0]["calc"]["fx"], "1")
        self.assertTrue(r.data["lines"][1]["calc"]["fx_missing"])
        self.assertTrue(r.data["calc"]["fx_missing"])
        self.assertIn("exchange rate", r.data["quotation_blocker"])

    def test_bad_lines_refused(self):
        d = self.new_order()
        r = self.put_lines(d["id"], [{"description": "", "qty": "1"}])
        self.assertEqual(r.status_code, 400)
        r = self.put_lines(d["id"], [{"description": "x", "qty": "0"}])
        self.assertEqual(r.status_code, 400)

    def test_explicit_stage_pick_is_forward_only(self):
        d = self.new_order()
        self.put_lines(d["id"], [self.TILE])            # PRICING
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/stage",
                             {"stage": "SOURCING"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/stage",
                             {"stage": "WON"}, format="json")
        self.assertEqual(r.status_code, 400)


class QuotationTests(SalesFrontBase):
    def issue(self, oid, user=None):
        self.login(user or self.sales)
        return self.client.post(f"/api/v1/trading/orders/{oid}/quotations")

    def test_nothing_unpriced_goes_out(self):
        d = self.new_order()
        r = self.issue(d["id"])
        self.assertEqual(r.status_code, 400)
        self.put_lines(d["id"], [self.TILE, {"description": "Grout", "qty": "5"}])
        r = self.issue(d["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("unpriced", r.data["detail"])

    def test_sales_issue_the_manager_authorises(self):
        d = self.new_order()
        self.put_lines(d["id"], [self.TILE])
        r = self.issue(d["id"])
        self.assertEqual(r.status_code, 201, r.data)
        q = r.data["quotations"][0]
        self.assertEqual(q["ref"], "TQ-001")
        self.assertEqual(q["status"], "AWAITING_AUTH")
        self.assertEqual(q["total"], "199843.20")
        self.assertEqual(r.data["stage"], "PRICING")          # not quoted yet
        # neither Finance nor the owner can authorise
        for u in (self.finance, self.sales):
            self.login(u)
            self.assertEqual(self.client.post(
                f"/api/v1/trading/orders/{d['id']}/quotations/{q['id']}/authorise")
                .status_code, 400 if u is self.sales else 403)
        self.login(self.sm)
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations/{q['id']}/authorise")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["quotations"][0]["status"], "AUTHORISED")
        self.assertEqual(r.data["quotations"][0]["authorised_by"], "Sm1")
        self.assertEqual(r.data["stage"], "QUOTED")
        snap = TradingQuotation.objects.get(id=q["id"]).snapshot
        self.assertNotIn("cost", str(snap["lines"]))          # customer prices only
        self.assertEqual(snap["customer"]["tin"], "1001234GST501")

    def test_a_revision_supersedes_and_the_managers_own_is_authorised_at_once(self):
        d = self.new_order(user=self.sm)
        self.put_lines(d["id"], [self.TILE], user=self.sm)
        r = self.issue(d["id"], user=self.sm)
        self.assertEqual(r.data["quotations"][0]["status"], "AUTHORISED")
        self.assertEqual(r.data["stage"], "QUOTED")
        self.put_lines(d["id"], [{**self.TILE, "margin_percent": "25"}], user=self.sm)
        r = self.issue(d["id"], user=self.sm)
        refs = [(x["ref"], x["status"]) for x in r.data["quotations"]]
        self.assertEqual(refs, [("TQ-001", "SUPERSEDED"), ("TQ-001/R2", "AUTHORISED")])
        self.assertEqual(r.data["quotations"][1]["total"], "208170.00")

    def test_gst_exempt_customer_is_quoted_without_gst(self):
        self.cust.gst_exempt = True
        self.cust.save()
        d = self.new_order()
        r = self.put_lines(d["id"], [self.TILE])
        self.assertEqual(r.data["calc"]["gst"], "0.00")
        self.assertEqual(r.data["calc"]["total"], "185040.00")

    @skipUnless(_pdf_engine(), "PDF engine unavailable")
    def test_the_pdf_is_filed_on_authorisation_and_a_draft_renders_before(self):
        d = self.new_order()
        self.put_lines(d["id"], [{**self.TILE, "section": "Tiles"}])
        r = self.issue(d["id"])
        q = r.data["quotations"][0]
        r = self.client.get(f"/api/v1/trading/orders/{d['id']}/quotations/{q['id']}/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.login(self.sm)
        self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations/{q['id']}/authorise")
        self.assertTrue(TradingQuotation.objects.get(id=q["id"]).pdf)


class WonLostTests(SalesFrontBase):
    def quoted(self):
        d = self.new_order()
        self.put_lines(d["id"], [self.TILE])
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations")
        q = r.data["quotations"][0]
        self.login(self.sm)
        self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations/{q['id']}/authorise")
        self.login(self.sales)
        return d

    def test_won_needs_the_authorised_quote_and_the_po(self):
        d = self.new_order()
        self.put_lines(d["id"], [self.TILE])
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/won",
                             {"po_number": "PO-77", "po_date": "2026-09-24"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("quotation", r.data["detail"])
        d = self.quoted()
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/won", {"po_number": ""})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/won",
                             {"po_number": "PO-77", "po_date": "2026-09-24"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["stage"], "WON")
        self.assertEqual(r.data["so_ref"], "TSO-001")
        self.assertTrue(r.data["is_closed"])
        # the sheet is locked
        r = self.put_lines(d["id"], [self.TILE])
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations")
        self.assertEqual(r.status_code, 400)
        # but a note still can be kept
        r = self.client.patch(f"/api/v1/trading/orders/{d['id']}",
                              {"next_action": "Raise import order"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.client.patch(f"/api/v1/trading/orders/{d['id']}", {"title": "x"},
                              format="json")
        self.assertEqual(r.status_code, 400)

    def test_lost_needs_a_reason(self):
        d = self.new_order()
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/lost", {"reason": ""})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/lost",
                             {"reason": "Bought from a Malé wholesaler"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["stage"], "LOST")
        ev = [a["event"] for a in self.client.get(
            f"/api/v1/trading/orders/{d['id']}/activity").data]
        self.assertEqual(ev[0], "TIN_LOST")
        self.assertIn("TIN_CREATED", ev)


class ChaseListTests(SalesFrontBase):
    def test_home_carries_the_chase_list_and_the_managers_queue(self):
        d = self.new_order(next_action="Call back", next_action_date="2026-09-01")
        d2 = self.new_order(user=self.sales2, title="Other", next_action="Send sample",
                            next_action_date="2026-12-01")
        self.put_lines(d["id"], [self.TILE])
        self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations")
        self.login(self.sales)
        h = self.client.get("/api/v1/trading/home").data
        self.assertEqual(h["open"], 1)                          # mine only
        self.assertEqual(h["by_stage"]["PRICING"], 1)
        self.assertEqual([c["ref"] for c in h["chase"]], [d["ref"]])
        self.assertTrue(h["chase"][0]["overdue"])
        self.assertEqual(h["awaiting_authorisation"], [])
        self.login(self.sm)
        h = self.client.get("/api/v1/trading/home").data
        self.assertEqual(h["open"], 2)                          # the manager sees all
        self.assertEqual(h["awaiting_authorisation"][0]["quotation"], "TQ-001")
        self.assertNotIn(d2["ref"], [c["ref"] for c in h["chase"]])   # not due yet
        self.assertEqual(len(self.client.get("/api/v1/trading/users").data), 3)
        self.assertTrue(Item.objects.count() >= 0)
        self.assertEqual(TradingOrder.objects.count(), 2)


class QuotationPdfRowsTests(SalesFrontBase):
    def test_a_section_heading_prints_once_above_its_lines(self):
        """The line row carried its section name under the same key the
        heading row used, so the PDF printed the heading twice and the line
        never (found on the first real quotation)."""
        d = self.new_order()
        self.put_lines(d["id"], [{**self.TILE, "section": "Tiles"},
                                 {**self.TILE, "section": "Tiles", "description": "Grout"},
                                 {**self.TILE, "section": "Tools", "description": "Trowel"}])
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations")
        q = TradingQuotation.objects.get(id=r.data["quotations"][0]["id"])
        rows = trading.quotation_context(q, draft=True)["rows"]
        kinds = [("H:" + x["heading"]) if "heading" in x else x["description"] for x in rows]
        self.assertEqual(kinds, ["H:Tiles", "Porcelain pool tile 300x300", "Grout",
                                 "H:Tools", "Trowel"])
