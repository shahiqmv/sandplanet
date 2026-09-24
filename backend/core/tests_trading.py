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
