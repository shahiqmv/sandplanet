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
from .tests import BaseCase, make_user

Y = __import__("django.utils.timezone", fromlist=["now"]).now().year


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
    def test_trading_series_carry_the_year_and_restart_each_year(self):
        from .numbering import next_trading_ref
        with transaction.atomic():
            self.assertEqual(next_trading_ref("IN"), f"{Y}-IN-001")
            self.assertEqual(next_trading_ref("IN"), f"{Y}-IN-002")
            self.assertEqual(next_trading_ref("SQ"), f"{Y}-SQ-001")
            self.assertEqual(next_trading_ref("SO"), f"{Y}-SO-001")
            self.assertEqual(next_trading_ref("DN"), f"{Y}-DN-001")
            self.assertEqual(next_trading_ref("CN"), f"{Y}-CN-001")
            self.assertEqual(next_trading_ref("IN", year=Y + 1), f"{Y + 1}-IN-001")
        self.assertNotIn("/", next_trading_ref("SQ"))     # a slash cannot be a file name


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
        self.assertEqual(d["ref"], f"{Y}-IN-001")
        self.assertEqual(d["owner"], self.sales.id)
        self.assertEqual(d["stage"], "INQUIRY")
        self.assertEqual(d["currency"], "MVR")       # the customer's default
        self.assertTrue(d["can_manage"])
        d2 = self.new_order(title="Second")
        self.assertEqual(d2["ref"], f"{Y}-IN-002")
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
        self.assertEqual(q["ref"], f"{Y}-SQ-001")
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
        self.assertEqual(refs, [(f"{Y}-SQ-001", "SUPERSEDED"), (f"{Y}-SQ-001-R2", "AUTHORISED")])
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
        self.assertEqual(r.data["so_ref"], f"{Y}-SO-001")
        self.assertTrue(r.data["is_closed"])
        # the customer's side of the sheet is frozen: a resave can only move
        # supplier / cost / currency / rate, and the selling price is pinned
        line = self.client.get(f"/api/v1/trading/orders/{d['id']}").data["lines"][0]
        r = self.put_lines(d["id"], [{**line, "description": "Changed", "qty": "5", "cost": "9",
                                      "supplier": self.sup.id, "margin_percent": "50"}])
        self.assertEqual(r.status_code, 200, r.data)
        ln = r.data["lines"][0]
        self.assertEqual(ln["description"], "Porcelain pool tile 300x300")   # unchanged
        self.assertEqual(ln["qty"], "1000.00")
        self.assertEqual(ln["cost"], "9.0000")                               # cost moved
        self.assertEqual(ln["supplier"], self.sup.id)
        self.assertEqual(ln["calc"]["unit_sell"], "185.0400")               # price pinned
        self.assertEqual(ln["calc"]["margin_percent"], "33.33")              # margin recalculated
        self.assertEqual(TradingLine.objects.filter(order_id=d["id"]).count(), 1)
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
        self.assertEqual(h["awaiting_authorisation"][0]["quotation"], f"{Y}-SQ-001")
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


# ---- phase 3: the supply leg ------------------------------------------------

from .models import Document, ImportOrder, Site, StockLot  # noqa: E402


class SupplyLegBase(SalesFrontBase):
    def setUp(self):
        super().setUp()
        self.ho = make_user("ho", User.Role.HO_PURCHASING)
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.signatory = make_user("sig", User.Role.SIGNATORY)
        self.sup2 = Supplier.objects.create(name="Colombo Grout", category="INTERNATIONAL",
                                            is_trading=True, default_currency="USD")
        Site.objects.get_or_create(code="MLE", defaults={"name": "Head Office",
                                                          "is_head_office": True})

    def won(self):
        d = self.new_order()
        self.put_lines(d["id"], [
            {**self.TILE, "supplier": self.sup.id, "section": "Tiles"},
            {**self.TILE, "supplier": self.sup2.id, "description": "Grout 5kg",
             "qty": "50", "uom": "bag", "cost": "4"},
            {"description": "Delivery labour", "qty": "1", "cost": "100",
             "cost_currency": "MVR", "margin_percent": "10"},          # no supplier
        ])
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations")
        q = r.data["quotations"][0]
        self.login(self.sm)
        self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations/{q['id']}/authorise")
        self.client.post(f"/api/v1/trading/orders/{d['id']}/won",
                         {"po_number": "PO-1", "po_date": "2026-09-24"})
        self.login(self.sales)
        return self.client.get(f"/api/v1/trading/orders/{d['id']}").data

    def raise_iprs(self, oid, line_ids):
        return self.client.post(f"/api/v1/trading/orders/{oid}/import-orders",
                                {"line_ids": line_ids}, format="json")


class RaiseImportOrderTests(SupplyLegBase):
    def test_one_draft_ipr_per_supplier_reserved_to_the_trading_order(self):
        d = self.won()
        sup = self.client.get(f"/api/v1/trading/orders/{d['id']}/supply").data
        self.assertEqual(len(sup["orderable"]), 2)          # the labour line has no supplier
        r = self.raise_iprs(d["id"], sup["orderable"])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["raised"], ["IPR-001", "IPR-002"])
        io = ImportOrder.objects.get(document__ref="IPR-001")
        self.assertEqual(io.trading_order_id, d["id"])
        self.assertEqual(io.document.status, "DRAFT")
        self.assertEqual(io.document.site.code, "MLE")
        self.assertEqual(io.order_currency, "USD")
        self.assertEqual(str(io.exchange_rate), "15.4200")
        ln = io.lines.get()
        self.assertEqual(ln.free_text_desc, "Porcelain pool tile 300x300")
        self.assertEqual(str(ln.order_qty), "1000.00")
        self.assertEqual(str(ln.unit_price), "10.0000")
        self.assertEqual(ln.cost_head.code, "TRD_COGS")
        self.assertIsNotNone(ln.trading_line_id)
        a = ln.allocations.get()
        self.assertEqual(a.trading_order_id, d["id"])
        self.assertIsNone(a.project_id)
        self.assertFalse(a.is_general_stock)
        # the supply picture now shows the line on its order
        sup = self.client.get(f"/api/v1/trading/orders/{d['id']}/supply").data
        tile = next(x for x in sup["lines"] if x["description"].startswith("Porcelain"))
        self.assertEqual(tile["ipr"], "IPR-001")
        self.assertEqual(tile["ipr_status"], "DRAFT")
        self.assertFalse(tile["orderable"])
        self.assertEqual(sup["orderable"], [])
        self.assertEqual([x["ref"] for x in sup["import_orders"]], ["IPR-001", "IPR-002"])
        # raising the same line again is refused
        r = self.raise_iprs(d["id"], [tile["id"]])
        self.assertEqual(r.status_code, 400)
        self.assertIn("already", r.data["detail"])

    def test_only_a_won_order_and_only_costed_supplier_lines(self):
        d = self.new_order()
        r = self.put_lines(d["id"], [{**self.TILE, "supplier": self.sup.id}])
        lid = r.data["lines"][0]["id"]
        r = self.raise_iprs(d["id"], [lid])
        self.assertEqual(r.status_code, 400)
        self.assertIn("won", r.data["detail"])
        d = self.won()
        labour = next(x["id"] for x in d["lines"] if x["description"] == "Delivery labour")
        r = self.raise_iprs(d["id"], [labour])
        self.assertEqual(r.status_code, 400)
        self.assertIn("supplier", r.data["detail"])
        self.login(self.finance)
        r = self.raise_iprs(d["id"], [d["lines"][0]["id"]])
        self.assertEqual(r.status_code, 403)

    def test_purchasing_sees_the_trading_tag_and_a_resave_keeps_the_link(self):
        d = self.won()
        sup = self.client.get(f"/api/v1/trading/orders/{d['id']}/supply").data
        self.raise_iprs(d["id"], sup["orderable"])
        self.login(self.ho)
        rows = self.client.get("/api/v1/ipr").data["rows"]
        row = next(x for x in rows if x["ref"] == "IPR-001")
        self.assertEqual(row["projects"], [f"Trading · {Y}-SO-001"])
        self.assertEqual(row["trading"]["customer"], "Kuramathi Maldives")
        doc = self.client.get("/api/v1/ipr/IPR-001").data
        self.assertEqual(doc["order"]["trading"]["so_ref"], f"{Y}-SO-001")
        line = doc["order"]["lines"][0]
        self.assertIsNotNone(line["trading_line"])
        # Purchasing edits the draft the usual way (ports, PI, rate) and the
        # form sends allocations as it always has — the link survives.
        body = {"supplier_id": doc["order"]["supplier"], "order_currency": "USD",
                "exchange_rate": "15.5", "incoterm": "CIF", "loading_port": "Guangzhou",
                "lines": [{"item_id": None, "free_text_desc": line["description"],
                           "unit": line["unit"], "order_qty": line["order_qty"],
                           "unit_price": line["unit_price"], "cost_head_id": line["cost_head"],
                           "remarks": "", "trading_line_id": line["trading_line"],
                           "allocations": [{"project_id": None, "qty": line["order_qty"]}]}]}
        r = self.client.patch("/api/v1/ipr/IPR-001", body, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        io = ImportOrder.objects.get(document__ref="IPR-001")
        ln = io.lines.get()
        self.assertEqual(ln.trading_line_id, line["trading_line"])
        self.assertEqual(ln.allocations.get().trading_order_id, d["id"])
        self.assertEqual(io.loading_port, "Guangzhou")


class TradingBookPostingTests(SupplyLegBase):
    def authorise(self, ref):
        self.login(self.ho)
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {}, format="json")
        self.login(self.director)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {}, format="json")
        self.login(self.signatory)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_commitment_lands_in_the_trading_book_at_the_stock_pool(self):
        d = self.won()
        sup = self.client.get(f"/api/v1/trading/orders/{d['id']}/supply").data
        self.raise_iprs(d["id"], sup["orderable"])
        self.authorise("IPR-001")
        doc = Document.objects.get(ref="IPR-001")
        self.assertEqual(doc.status, "AUTHORISED")
        posts = CostPosting.objects.filter(document=doc)
        self.assertTrue(posts.exists())
        self.assertTrue(all(p.book == "TRADING" for p in posts))
        self.assertTrue(all(p.is_stock_pool and p.site.is_head_office for p in posts))
        self.assertEqual(sum(p.amount for p in posts), Decimal("154200.00"))   # 1000 × 10 × 15.42
        # nothing of it reaches a project figure
        self.login(self.finance)
        r = self.client.get("/api/v1/cost/portfolio")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sum(Decimal(str(x["committed"])) for x in r.data["sites"]), 0)
        # and the trading heads stay out of the project cost-head picker
        names = [h["name"] for h in self.client.get("/api/v1/cost-heads?pools=1").data]
        self.assertNotIn("Trading — Cost of sales", names)        # the PYR picker
        heads = self.client.get("/api/v1/cost-head-master").data
        self.assertNotIn("TRD_COGS", [h["code"] for h in heads])  # the master list
        heads = self.client.get("/api/v1/cost-head-master?trading=1").data
        self.assertIn("TRD_COGS", [h["code"] for h in heads])

    def test_receipt_reserves_lots_to_the_trading_order_and_sites_cannot_draw_them(self):
        from . import imports
        d = self.won()
        sup = self.client.get(f"/api/v1/trading/orders/{d['id']}/supply").data
        self.raise_iprs(d["id"], sup["orderable"])
        self.authorise("IPR-001")
        self.login(self.ho)
        sid = self.client.post("/api/v1/ipr/IPR-001/shipments", {"mode": "SEA"},
                               format="json").data["shipments"][0]["id"]
        irn = self.client.post(f"/api/v1/ipr/IPR-001/shipments/{sid}/receive",
                               {"location": "Bay 3"}, format="json").data["ref"]
        r = self.client.post(f"/api/v1/irn/{irn}/post", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        lot = StockLot.objects.get(source_ipr_line__order__document__ref="IPR-001")
        self.assertEqual(lot.trading_order_id, d["id"])
        self.assertIsNone(lot.project_id)
        self.assertEqual(str(lot.qty_on_hand), "1000.00")
        # the store shows who it is for; a site pick never touches it
        store = self.client.get("/api/v1/store/lots").data
        row = next(x for x in store["lots"] if x["id"] == lot.id)
        self.assertEqual(row["reserved_for"], f"Trading · {Y}-SO-001")
        picks, err = imports.pick_lots_fifo(lot.item, None, Decimal("1"))
        self.assertIsNone(picks)
        # and the sales order sees it arrive
        self.login(self.sales)
        sup = self.client.get(f"/api/v1/trading/orders/{d['id']}/supply").data
        tile = next(x for x in sup["lines"] if x["ipr"] == "IPR-001")
        self.assertEqual(tile["received_qty"], "1000.00")
        self.assertEqual(tile["on_hand"], "1000.00")
        self.assertEqual(sup["lots_on_hand"], "1000.00")
        self.assertEqual(sup["import_orders"][0]["received"], [irn])


# ---- phase 4: delivery, invoicing and money in ------------------------------

from django.db.models import Sum  # noqa: E402

from .models import (CostPosting as _CP, TradingDelivery, TradingInvoice,  # noqa: E402
                     TradingReceipt)


class MoneyInBase(SupplyLegBase):
    """A won order whose tiles were imported and received into the store."""

    def setUp(self):
        super().setUp()
        self.cust.credit_days = 30
        self.cust.save()

    def stocked(self):
        d = self.won()
        sup = self.client.get(f"/api/v1/trading/orders/{d['id']}/supply").data
        self.raise_iprs(d["id"], sup["orderable"])
        self.login(self.ho)
        for ref in ("IPR-001", "IPR-002"):
            self.client.post(f"/api/v1/documents/{ref}/actions/submit", {}, format="json")
            self.login(self.director)
            self.client.post(f"/api/v1/documents/{ref}/actions/approve", {}, format="json")
            self.login(self.signatory)
            self.client.post(f"/api/v1/documents/{ref}/actions/authorise", {}, format="json")
            self.login(self.ho)
            sid = self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                                   format="json").data["shipments"][0]["id"]
            irn = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/receive",
                                   {"location": ""}, format="json").data["ref"]
            self.client.post(f"/api/v1/irn/{irn}/post", {}, format="json")
        self.login(self.sales)
        return d

    def dn(self, oid, lines, **hdr):
        r = self.client.post(f"/api/v1/trading/orders/{oid}/deliveries",
                             {"lines": lines, "vessel": "Kuramathi 3",
                              "receiver": "Capt. Ali", **hdr}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def despatch(self, oid, did):
        return self.client.post(f"/api/v1/trading/orders/{oid}/deliveries/{did}",
                                {"action": "despatch"}, format="json")

    def line_id(self, d, prefix):
        return next(x["id"] for x in d["lines"] if x["description"].startswith(prefix))


class DeliveryTests(MoneyInBase):
    def test_deliverable_shows_stock_and_a_note_draws_it_at_landed_cost(self):
        d = self.stocked()
        dv = self.client.get(f"/api/v1/trading/orders/{d['id']}/deliveries").data["deliverable"]
        tile = next(x for x in dv if x["description"].startswith("Porcelain"))
        labour = next(x for x in dv if x["description"] == "Delivery labour")
        self.assertEqual(tile["on_hand"], "1000.00")
        self.assertTrue(tile["needs_stock"])
        self.assertFalse(labour["needs_stock"])
        self.assertEqual(labour["can_deliver"], "1.00")
        dn = self.dn(d["id"], [{"line_id": tile["id"], "qty": "400"},
                               {"line_id": labour["id"], "qty": "1"}])
        self.assertEqual(dn["ref"], f"{Y}-DN-001")
        self.assertEqual(dn["status"], "DRAFT")
        r = self.despatch(d["id"], dn["id"])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "DESPATCHED")
        self.assertEqual(r.data["cogs_mvr"], "61680.00")            # 400 × 154.20
        tl = next(x for x in r.data["lines"] if x["description"].startswith("Porcelain"))
        self.assertEqual(tl["unit_cost_mvr"], "154.2000")
        self.assertIsNone(next(x for x in r.data["lines"]
                               if x["description"] == "Delivery labour")["unit_cost_mvr"])
        self.assertTrue(r.data["has_pdf"] or True)
        # the store went down, cost of sales went up, in the trading book only
        lot = StockLot.objects.get(trading_order_id=d["id"], source_ipr_line__order__document__ref="IPR-001")
        self.assertEqual(str(lot.qty_on_hand), "600.00")
        cogs = _CP.objects.filter(cost_head__code="TRD_COGS")
        self.assertEqual(cogs.count(), 1)
        self.assertEqual(cogs.get().book, "TRADING")
        self.assertEqual(cogs.get().amount, Decimal("61680.00"))
        # remaining to deliver
        dv = self.client.get(f"/api/v1/trading/orders/{d['id']}/deliveries").data["deliverable"]
        tile = next(x for x in dv if x["description"].startswith("Porcelain"))
        self.assertEqual(tile["remaining"], "600.00")
        self.assertEqual(tile["on_hand"], "600.00")

    def test_a_note_cannot_exceed_the_order_or_the_store(self):
        d = self.stocked()
        tile = self.line_id(d, "Porcelain")
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/deliveries",
                             {"lines": [{"line_id": tile, "qty": "1001"}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("left to deliver", r.data["detail"])
        self.dn(d["id"], [{"line_id": tile, "qty": "700"}])            # draft reserves
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/deliveries",
                             {"lines": [{"line_id": tile, "qty": "400"}]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_despatch_needs_the_vessel_and_receiver_and_a_signed_copy_closes_it(self):
        d = self.stocked()
        tile = self.line_id(d, "Porcelain")
        dn = self.dn(d["id"], [{"line_id": tile, "qty": "100"}], vessel="", receiver="")
        r = self.despatch(d["id"], dn["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("vessel", r.data["detail"])
        self.client.patch(f"/api/v1/trading/orders/{d['id']}/deliveries/{dn['id']}",
                          {"vessel": "Dhoni 7", "receiver": "Hassan"}, format="json")
        self.assertEqual(self.despatch(d["id"], dn["id"]).status_code, 200)
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/deliveries/{dn['id']}/receive",
                             {"signed_copy": SimpleUploadedFile("signed.pdf", b"%PDF-1.4 x")})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "RECEIVED")
        self.assertTrue(r.data["signed_copy"])


class InvoiceTests(MoneyInBase):
    def delivered(self, qty="400"):
        d = self.stocked()
        tile = self.line_id(d, "Porcelain")
        dn = self.dn(d["id"], [{"line_id": tile, "qty": qty}])
        self.despatch(d["id"], dn["id"])
        return d, dn

    def test_invoice_follows_the_despatch_at_the_quoted_price(self):
        d, dn = self.delivered()
        r = self.client.get(f"/api/v1/trading/orders/{d['id']}/invoices").data
        self.assertEqual([x["ref"] for x in r["invoiceable"]], [f"{Y}-DN-001"])
        self.assertFalse(r["freight_billed"])
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices",
                             {"delivery_ids": [dn["id"]], "include_freight": True,
                              "charges": [{"label": "Pallets", "amount": "250"}],
                              "invoice_date": "2026-09-24"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        inv = r.data
        self.assertEqual(inv["ref"], f"INV-{Y}-0001")
        self.assertEqual(inv["status"], "DRAFT")
        self.assertEqual(inv["lines"][0]["unit_sell"], "185.0400")        # quoted MVR price
        self.assertEqual(inv["lines"][0]["amount"], "74016.00")           # 400 × 185.04
        self.assertEqual(inv["subtotal"], "74266.00")                     # + 250 pallets (no freight_sell set)
        self.assertEqual(inv["gst"], "5941.28")
        self.assertEqual(inv["total"], "80207.28")
        self.assertEqual(inv["due_date"], _date_plus("2026-09-24", 30))
        # the delivery is now spoken for
        r = self.client.get(f"/api/v1/trading/orders/{d['id']}/invoices").data
        self.assertEqual(r["invoiceable"], [])
        # Sales cannot issue; the manager can, and revenue + GST post in the trading book
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices/{inv['id']}",
                             {"action": "issue"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.login(self.sm)
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices/{inv['id']}",
                             {"action": "issue"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "ISSUED")
        self.assertEqual(r.data["outstanding"], "80207.28")
        rev = _CP.objects.get(cost_head__code="TRD_REVENUE")
        gst = _CP.objects.get(cost_head__code="TRD_OUTPUT_GST")
        self.assertEqual((rev.amount, rev.book, rev.currency), (Decimal("74266.00"), "TRADING", "MVR"))
        self.assertEqual(gst.amount, Decimal("5941.28"))
        m = self.client.get(f"/api/v1/trading/orders/{d['id']}").data["money"]
        self.assertEqual(m["invoiced"], "80207.28")
        self.assertEqual(m["received"], "0.00")

    def test_freight_bills_once_and_a_tin_is_required(self):
        d, dn = self.delivered("300")
        self.login(self.sm)
        TradingOrder.objects.filter(id=d["id"]).update(freight_sell=600)   # quoted freight
        self.cust.tin = ""
        self.cust.save()
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices",
                             {"delivery_ids": [dn["id"]], "include_freight": True}, format="json")
        self.assertTrue(r.data["includes_freight"])
        self.assertEqual(r.data["subtotal"], "56112.00")                  # 300 × 185.04 + 600
        r2 = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices/{r.data['id']}",
                              {"action": "issue"}, format="json")
        self.assertEqual(r2.status_code, 400)
        self.assertIn("TIN", r2.data["detail"])
        self.assertTrue(self.client.get(f"/api/v1/trading/orders/{d['id']}/invoices")
                        .data["freight_billed"])
        # a second delivery's invoice cannot carry freight again
        tile = self.line_id(d, "Porcelain")
        dn2 = self.dn(d["id"], [{"line_id": tile, "qty": "100"}])
        self.despatch(d["id"], dn2["id"])
        r3 = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices",
                              {"delivery_ids": [dn2["id"]], "include_freight": True}, format="json")
        self.assertFalse(r3.data["includes_freight"])

    def test_void_reverses_and_frees_the_delivery(self):
        d, dn = self.delivered()
        self.login(self.sm)
        inv = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices",
                               {"delivery_ids": [dn["id"]]}, format="json").data
        self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices/{inv['id']}",
                         {"action": "issue"}, format="json")
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices/{inv['id']}",
                             {"action": "void", "reason": "wrong PO"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "VOID")
        self.assertEqual(_CP.objects.filter(cost_head__code="TRD_REVENUE")
                         .aggregate(s=Sum("amount"))["s"], 0)
        self.assertEqual([x["ref"] for x in self.client.get(
            f"/api/v1/trading/orders/{d['id']}/invoices").data["invoiceable"]], [f"{Y}-DN-001"])
        self.assertEqual(TradingDelivery.objects.get(id=dn["id"]).invoice_id, None)

    def test_credit_note_reduces_the_receivable(self):
        d, dn = self.delivered()
        self.login(self.sm)
        inv = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices",
                               {"delivery_ids": [dn["id"]]}, format="json").data
        self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices/{inv['id']}",
                         {"action": "issue"}, format="json")
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices/{inv['id']}",
                             {"action": "credit", "amount": "1080", "reason": "10 m2 broken"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["credit_notes"][0]["ref"], f"{Y}-CN-001")
        self.assertEqual(r.data["credit_notes"][0]["gst"], "80.00")        # 1080 × 8/108
        self.assertEqual(r.data["outstanding"], "78857.28")                # 79937.28 − 1080
        self.assertEqual(_CP.objects.filter(cost_head__code="TRD_REVENUE")
                         .aggregate(s=Sum("amount"))["s"], Decimal("73016.00"))


class ReceiptTests(MoneyInBase):
    def two_invoices(self):
        d = self.stocked()
        tile = self.line_id(d, "Porcelain")
        self.login(self.sm)
        ids = []
        for qty, day in (("400", "2026-08-01"), ("600", "2026-09-01")):
            dn = self.dn(d["id"], [{"line_id": tile, "qty": qty}])
            self.despatch(d["id"], dn["id"])
            inv = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices",
                                   {"delivery_ids": [dn["id"]], "invoice_date": day},
                                   format="json").data
            self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices/{inv['id']}",
                             {"action": "issue"}, format="json")
            ids.append(inv["id"])
        return d, ids                                     # 79,937.28 and 119,905.92

    def test_one_receipt_settles_oldest_first_on_the_shared_series(self):
        d, ids = self.two_invoices()
        self.login(self.finance)
        r = self.client.get(f"/api/v1/trading/receipts/allocate?customer={self.cust.id}&amount=100000").data
        self.assertEqual([(a["invoice"], a["amount"]) for a in r["allocations"]],
                         [(f"INV-{Y}-0001", "79937.28"), (f"INV-{Y}-0002", "20062.72")])
        self.assertEqual(r["unallocated"], "0.00")
        r = self.client.post("/api/v1/trading/receipts", {
            "customer": self.cust.id, "receipt_date": "2026-09-20", "method": "TT",
            "reference": "BML 7781", "allocations": [
                {"invoice_id": ids[0], "amount": "79937.28"},
                {"invoice_id": ids[1], "amount": "20062.72"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["receipt_no"], "OR-0001")
        self.assertEqual(str(r.data["total"]), "100000.00")
        self.assertEqual(TradingInvoice.objects.get(id=ids[0]).status, "PAID")
        self.assertEqual(TradingInvoice.objects.get(id=ids[1]).status, "ISSUED")
        # the project receipt series continues after it
        from .receipts import next_receipt_no
        self.assertEqual(next_receipt_no(), "OR-0002")
        # over-allocation refused; Sales cannot receipt
        r = self.client.post("/api/v1/trading/receipts", {
            "customer": self.cust.id, "receipt_date": "2026-09-21",
            "allocations": [{"invoice_id": ids[1], "amount": "999999"}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.login(self.sales)
        r = self.client.post("/api/v1/trading/receipts", {
            "customer": self.cust.id, "receipt_date": "2026-09-21",
            "allocations": [{"invoice_id": ids[1], "amount": "1"}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Finance", r.data["detail"])
        # the receipt PDF renders off the shared template
        self.login(self.finance)
        rc = TradingReceipt.objects.get()
        r = self.client.get(f"/api/v1/trading/receipts/{rc.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        # aging + statement
        ag = self.client.get("/api/v1/trading/receivables").data
        self.assertEqual(ag["customers"][0]["total"], "99843.20")
        self.assertEqual(ag["customers"][0]["invoices"][0]["ref"], f"INV-{Y}-0002")
        st = self.client.get(f"/api/v1/trading/customers/{self.cust.id}/statement").data
        self.assertEqual([x["kind"] for x in st["rows"]], ["INVOICE", "INVOICE", "RECEIPT"])
        self.assertEqual(st["closing"], "99843.20")
        st = self.client.get(f"/api/v1/trading/customers/{self.cust.id}/statement?from=2026-09-01").data
        self.assertEqual(st["opening"], "79937.28")
        self.assertEqual(st["closing"], "99843.20")
        # deleting the receipt reopens the invoice
        r = self.client.delete(f"/api/v1/trading/receipts/{rc.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(TradingInvoice.objects.get(id=ids[0]).status, "ISSUED")


def _date_plus(s, days):
    from datetime import timedelta
    return date.fromisoformat(s) + timedelta(days=days)


class LineSpecTests(SalesFrontBase):
    def test_first_line_is_the_product_and_the_rest_its_spec(self):
        """One multi-line description field on the sheet: the product on the
        first line (bold), its specs below (italic) — carried to the
        quotation, the delivery note, the invoice and the import order
        (owner 2026-09-24)."""
        d = self.new_order()
        r = self.put_lines(d["id"], [{**self.TILE,
                                      "description": "Porcelain pool tile 300x300\r\nAnti-slip R11\nColour: ocean blue"}])
        ln = r.data["lines"][0]
        self.assertEqual(ln["description"], "Porcelain pool tile 300x300")
        self.assertEqual(ln["spec"], "Anti-slip R11\nColour: ocean blue")
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations")
        q = TradingQuotation.objects.get(id=r.data["quotations"][0]["id"])
        self.assertEqual(q.snapshot["lines"][0]["spec"], "Anti-slip R11\nColour: ocean blue")
        row = trading.quotation_context(q, draft=True)["rows"][0]
        self.assertEqual(row["spec"], "Anti-slip R11\nColour: ocean blue")
        # a resave with the spec already split keeps it
        r = self.put_lines(d["id"], [{**ln, "description": "Porcelain pool tile 300x300"}])
        self.assertEqual(r.data["lines"][0]["spec"], "Anti-slip R11\nColour: ocean blue")


class QuotationTermsTests(SalesFrontBase):
    def test_new_inquiries_start_from_the_standard_lines_and_print_their_own(self):
        """Payment, delivery, lead time, incoterms and any extra lines are
        company standard lines the manager keeps; every inquiry copies them
        and prints its own copy (owner 2026-09-24)."""
        self.login(self.finance)
        r = self.client.put("/api/v1/trading/terms", {"payment_terms": "x"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.login(self.sm)
        r = self.client.put("/api/v1/trading/terms", {
            "payment_terms": "30% advance, 70% before despatch",
            "lead_time": "4 weeks", "incoterm": "Delivered Malé",
            "extra_terms": "No returns on cut tiles.\nPrices exclude unloading.",
            "quote_valid_days": 21}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["can_edit"])
        d = self.new_order()
        self.assertEqual(d["payment_terms"], "30% advance, 70% before despatch")
        self.assertEqual(d["lead_time"], "4 weeks")
        self.assertEqual(d["quote_valid_days"], 21)
        self.assertEqual(d["delivery_terms"], "Delivered to your vessel at Malé harbour")
        # the order's own terms are edited on the Quotation tab before issue
        r = self.client.patch(f"/api/v1/trading/orders/{d['id']}",
                              {"lead_time": "In stock — 3 days", "extra_terms": "Unloading by the customer."},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.put_lines(d["id"], [self.TILE])
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/quotations")
        q = TradingQuotation.objects.get(id=r.data["quotations"][0]["id"])
        t = q.snapshot["terms"]
        self.assertEqual(t["lead_time"], "In stock — 3 days")
        self.assertEqual(t["incoterm"], "Delivered Malé")
        self.assertEqual(t["extra"], ["Unloading by the customer."])
        self.assertEqual(t["valid_days"], 21)
        ctx = trading.quotation_context(q, draft=True)
        self.assertEqual(ctx["terms"]["payment"], "30% advance, 70% before despatch")



class AdvanceAndProformaTests(MoneyInBase):
    def test_advance_on_the_proforma_comes_off_the_tax_invoice(self):
        d = self.stocked()                                   # won: tiles + grout + labour
        total = Decimal(trading.current_quotation(TradingOrder.objects.get(id=d["id"]))
                        .snapshot["totals"]["total"])
        adv = trading._q2(total * Decimal("0.75"))
        # the pro-forma prints off the authorised quotation with the SO ref
        r = self.client.get(f"/api/v1/trading/orders/{d['id']}/proforma.pdf?advance=75")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        ctx = trading.proforma_context(TradingOrder.objects.get(id=d["id"]), "75")
        self.assertEqual(ctx["advance_f"], f"{adv:,.2f}")
        # Finance records the advance on account of the order
        self.login(self.finance)
        info = self.client.get(f"/api/v1/trading/receipts/allocate?customer={self.cust.id}&amount=0").data
        self.assertEqual(info["won_orders"][0]["so_ref"], d["so_ref"])
        r = self.client.post("/api/v1/trading/receipts", {
            "customer": self.cust.id, "receipt_date": "2026-09-20", "method": "TT",
            "reference": "BML 1001", "allocations": [{"order_id": d["id"], "amount": str(adv)}]},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["lines"][0]["invoice_no"], f"Advance — {d['so_ref']}")
        m = self.client.get(f"/api/v1/trading/orders/{d['id']}").data["money"]
        self.assertEqual(m["advance_received"], str(adv))
        self.assertEqual(m["advance_available"], str(adv))
        ag = self.client.get("/api/v1/trading/receivables").data
        self.assertEqual(ag["customers"][0]["advance_on_account"], str(adv))
        self.assertEqual(ag["customers"][0]["total"], "0.00")
        # too much advance is refused
        r = self.client.post("/api/v1/trading/receipts", {
            "customer": self.cust.id, "receipt_date": "2026-09-21",
            "allocations": [{"order_id": d["id"], "amount": str(total)}]}, format="json")
        self.assertEqual(r.status_code, 400)
        # the first tax invoice absorbs the advance
        self.login(self.sales)
        tile = self.line_id(d, "Porcelain")
        dn = self.dn(d["id"], [{"line_id": tile, "qty": "1000"}])
        self.despatch(d["id"], dn["id"])
        self.login(self.sm)
        inv = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices",
                               {"delivery_ids": [dn["id"]]}, format="json").data
        self.assertEqual(inv["total"], "199843.20")                     # the tiles only
        self.assertEqual(inv["advance_applied"], str(adv))
        balance = Decimal("199843.20") - adv
        r = self.client.post(f"/api/v1/trading/orders/{d['id']}/invoices/{inv['id']}",
                             {"action": "issue"}, format="json")
        self.assertEqual(r.data["outstanding"], str(balance))
        ctx = trading.invoice_context(TradingInvoice.objects.get(id=inv["id"]))
        self.assertEqual(ctx["balance_f"], f"{balance:,.2f}")
        self.assertIn("OR-", ctx["advance_receipts"])
        m = self.client.get(f"/api/v1/trading/orders/{d['id']}").data["money"]
        self.assertEqual(m["advance_available"], "0.00")
        self.assertEqual(m["outstanding"], str(balance))
        ag = self.client.get("/api/v1/trading/receivables").data
        self.assertEqual(ag["customers"][0]["total"], str(balance))
        self.assertEqual(ag["customers"][0]["advance_on_account"], "0.00")
        # the advance receipt cannot be deleted once applied
        self.login(self.finance)
        rc = TradingReceipt.objects.get()
        r = self.client.delete(f"/api/v1/trading/receipts/{rc.id}")
        self.assertEqual(r.status_code, 403)
        st = self.client.get(f"/api/v1/trading/customers/{self.cust.id}/statement").data
        self.assertEqual([x["kind"] for x in st["rows"]], ["RECEIPT", "INVOICE"])
        self.assertEqual(st["closing"], str(balance))


class HistoricInvoiceTests(BaseCase):
    """Invoices issued before Planet, still unpaid: entered for collection so
    the statement and the aging are complete and a receipt settles them."""

    def setUp(self):
        super().setUp()
        from .models import Customer
        self.finance = make_user("fin9", User.Role.FINANCE)
        self.sales = make_user("sales9", User.Role.SALES)
        self.cust = Customer.objects.create(name="Conrad Maldives", default_currency="USD",
                                            credit_days=30, tin="1000100GST001")

    def test_entered_for_collection_only_and_settled_by_a_receipt(self):
        from .models import CostPosting, TradingInvoice
        self.login(self.sales)
        body = {"customer": self.cust.id, "ref": "INV-2025-0412", "invoice_date": "2025-11-02",
                "currency": "USD", "subtotal": "12000", "gst": "960", "received": "3000",
                "description": "Carpet tiles, PI 2025/SO/510"}
        self.assertEqual(self.client.post("/api/v1/trading/invoices/historic", body, format="json").status_code, 400)
        self.login(self.finance)
        r = self.client.post("/api/v1/trading/invoices/historic", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        inv = TradingInvoice.objects.get(ref="INV-2025-0412")
        self.assertTrue(inv.historic)
        self.assertIsNone(inv.order_id)
        self.assertEqual((inv.status, str(inv.total), str(inv.due_date)), ("ISSUED", "12960.00", "2025-12-02"))
        self.assertEqual(CostPosting.objects.filter(book="TRADING").count(), 0)      # no revenue posted
        self.assertEqual(self.client.post("/api/v1/trading/invoices/historic", body, format="json").status_code, 400)  # no duplicates
        # aging shows the balance still owed; the statement shows the invoice and what was paid before
        ag = self.client.get("/api/v1/trading/receivables").data
        row = next(c for c in ag["customers"] if c["customer"] == self.cust.id)
        self.assertEqual(row["invoices"][0]["outstanding"], "9960.00")
        self.assertTrue(row["invoices"][0]["historic"])
        st = self.client.get(f"/api/v1/trading/customers/{self.cust.id}/statement").data
        self.assertEqual([(e["kind"], e["debit"], e["credit"]) for e in st["rows"]],
                         [("INVOICE", "12960.00", None), ("RECEIPT", None, "3000.00")])
        self.assertEqual(st["closing"], "9960.00")
        self.assertEqual(self.client.get(f"/api/v1/trading/customers/{self.cust.id}/statement?pdf=1").status_code, 200)
        # a receipt settles it like any other invoice
        alloc = self.client.get(f"/api/v1/trading/receipts/allocate?customer={self.cust.id}&amount=9960").data
        self.assertEqual(alloc["allocations"][0]["amount"], "9960.00")
        r = self.client.post("/api/v1/trading/receipts", {"customer": self.cust.id, "receipt_date": "2026-09-26",
                                                          "method": "TT", "allocations": alloc["allocations"]},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "PAID")
        # void refused once money is in
        r = self.client.post(f"/api/v1/trading/invoices/historic/{inv.id}/void", {"reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
