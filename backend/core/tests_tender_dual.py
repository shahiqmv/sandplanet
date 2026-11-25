"""An offer made in rufiyaa, with the dollar figures beside it.

Some clients issue a bill with Rate and Amount columns for both MVR and USD
(Adaaran Club Rannalhi, owner 2026-11-25). The bill is still priced in USD —
that is the cost basis — and every rufiyaa figure is the dollar one at a rate
the company sets for that offer, because the market rate moves. Rufiyaa is
what the client is offered and pays; the books and reports go on converting
at the official rate.
"""
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import TestCase
from rest_framework.test import APIClient

from . import fx
from . import tenders as svc
from .models import Boq, BoqItemWorking, Project, Site, Tender, User
from .tests import make_user
from .tests_tenders import GateMixin

D = Decimal


class DualOfferBase(GateMixin, TestCase):
    RATE = "22"

    def setUp(self):
        self.site = Site.objects.create(code="ACR", name="Adaaran Club",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("du_qs", User.Role.QS)
        self.make_approvers("du")
        self.client = APIClient()
        self.client.force_authenticate(self.qs)
        self.t = self.open(currency="MVR", usd_shown=True,
                           offer_rate=self.RATE)

    def open(self, **extra):
        r = self.client.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "Adaaran",
            "title": "Water villa upgrade", **extra}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def price(self, tid=None, rows=None):
        """Two lines priced in USD: 2 × 86.411 and 26.8 × 12.345."""
        r = self.client.post(
            f"/api/v1/tenders/{tid or self.t['id']}/boq/items",
            {"rows": rows or [
                {"description": "Bill 2 — Works"},
                {"description": "Remove louvres", "unit": "Nos", "qty": "2",
                 "unit_cost": "60", "rate_combined": "86.411"},
                {"description": "Fascia boards", "unit": "m2", "qty": "26.8",
                 "unit_cost": "10", "rate_combined": "12.345"}]},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return r

    def tender(self, tid=None):
        return Tender.objects.get(pk=tid or self.t["id"])

    def patch(self, body, tid=None):
        return self.client.patch(f"/api/v1/tenders/{tid or self.t['id']}",
                                 body, format="json")


class DualOfferSetupTests(DualOfferBase):
    def test_it_is_an_mvr_offer_that_carries_its_rate(self):
        self.assertEqual(self.t["currency"], "MVR")
        self.assertTrue(self.t["usd_shown"])
        self.assertEqual(D(str(self.t["offer_rate"])), D("22"))
        self.assertTrue(self.tender().is_dual)

    def test_showing_usd_makes_the_offer_rufiyaa_whatever_was_picked(self):
        t = self.open(currency="USD", usd_shown=True, offer_rate="21.5")
        self.assertEqual(t["currency"], "MVR")

    def test_the_rate_is_required_and_no_reference_is_spent_without_it(self):
        from .models import Document
        before = Document.objects.filter(doc_type="TDR").count()
        r = self.client.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "Adaaran",
            "title": "No rate", "currency": "MVR", "usd_shown": True},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("exchange rate", r.data["detail"])
        self.assertEqual(Document.objects.filter(doc_type="TDR").count(),
                         before)

    def test_a_plain_offer_carries_no_rate(self):
        t = self.open(currency="USD", offer_rate="22")
        self.assertFalse(t["usd_shown"])
        self.assertIsNone(t["offer_rate"])
        self.assertFalse(self.tender(t["id"]).is_dual)

    def test_an_offer_can_be_switched_while_it_is_being_priced(self):
        t = self.open(currency="USD")
        r = self.patch({"currency": "MVR", "usd_shown": True,
                        "offer_rate": "22"}, t["id"])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(self.tender(t["id"]).is_dual)
        r = self.patch({"currency": "USD", "usd_shown": False,
                        "offer_rate": ""}, t["id"])
        self.assertEqual(r.status_code, 200, r.data)
        back = self.tender(t["id"])
        self.assertEqual((back.currency, back.usd_shown, back.offer_rate),
                         ("USD", False, None))


class DualOfferMoneyTests(DualOfferBase):
    def test_each_rate_is_converted_and_the_amount_built_from_it(self):
        self.price()
        ctx = svc.submission_context(self.tender())
        self.assertTrue(ctx["dual"])
        head, a, b = ctx["boq_rows"]
        self.assertTrue(head["is_heading"])
        # 86.411 × 22 = 1,901.042 → 1,901.04; × 2 = 3,802.08
        self.assertEqual((a["rate"], a["amount"]), ("1,901.04", "3,802.08"))
        self.assertEqual((a["rate_usd"], a["amount_usd"]),
                         ("86.41", "172.82"))
        # 12.345 × 22 = 271.59; × 26.8 = 7,278.612
        self.assertEqual((b["rate"], b["amount"]), ("271.59", "7,278.61"))
        self.assertEqual(b["amount_usd"], "330.85")
        # the totals are the lines added up, in each currency
        self.assertEqual(ctx["bill_total_fmt"], "11,080.69")
        self.assertEqual(ctx["bill_total_usd_fmt"], "503.67")
        self.assertEqual(ctx["bills"][0]["usd_fmt"], "503.67")

    def test_a_new_rate_moves_the_rufiyaa_and_leaves_the_dollars(self):
        self.price()
        before = svc.snapshot(self.tender())
        self.assertEqual(self.patch({"offer_rate": "21"}).status_code, 200)
        after = svc.snapshot(self.tender())
        self.assertEqual(after["bill_total_usd"], before["bill_total_usd"])
        # 86.411×21 = 1,814.63 ×2 ; 12.345×21 = 259.25 (259.245 rounds up) ×26.8
        self.assertEqual(after["bill_total"],
                         D("1814.63") * 2 + D("259.25") * D("26.8"))
        self.assertLess(after["bill_total"], before["bill_total"])

    def test_the_summary_stack_is_rufiyaa_with_a_dollar_column_that_foots(self):
        self.price()
        self.assertEqual(self.patch({
            "discount_amount": "1000", "gst_percent": "8",
            "provisional_items": [{"label": "Signage", "amount": "2200"}],
        }).status_code, 200)
        t = self.tender()
        total, usd = svc.bill_totals(t)
        st = svc.money_stack(t, total, usd)
        self.assertEqual(st["subtotal"], total)             # rufiyaa
        self.assertEqual(st["discount"], D("1000.00"))
        self.assertEqual(st["provisional"], D("2200.00"))
        u = st["usd"]
        self.assertEqual(u["subtotal"], D("503.67"))        # the bill's own
        self.assertEqual(u["discount"], D("45.45"))         # 1000 / 22
        self.assertEqual(u["provisional"], D("100.00"))
        self.assertEqual(u["net"], D("503.67") - D("45.45") + D("100.00"))
        self.assertEqual(u["gst"], D("44.66"))              # 8% of 558.22
        self.assertEqual(u["grand_total"], u["net"] + u["gst"])

    def test_the_markup_is_read_on_the_dollar_price(self):
        self.price()
        self.clear(self.t["id"], "11080.69")
        s = svc.snapshot(self.tender())
        self.assertTrue(s["dual"])
        self.assertTrue(s["bill_matches_offer"])
        self.assertEqual(s["offer_value"], D("11080.69"))
        self.assertEqual(s["offer_value_usd"], D("503.67"))
        # cost 2×60 + 26.8×10 = 388 USD
        self.assertEqual(s["estimated_cost"], D("388.000"))
        self.assertEqual(s["markup"], D("115.670"))
        self.assertEqual(s["markup_percent"], D("29.8"))
        self.assertEqual(s["cost_currency"], "USD")

    def test_the_offer_document_prints_both_currencies(self):
        self.price()
        html = render_to_string("pdf/tender_submission.html",
                                svc.submission_context(self.tender()))
        for text in ("Rate (MVR)", "Amount (MVR)", "Rate (USD)",
                     "Amount (USD)", "1,901.04", "3,802.08", "86.41",
                     "11,080.69", "503.67", "Maldivian Rufiyaa"):
            self.assertIn(text, html)
        # the rate itself is the company's business, not printed
        self.assertNotIn("22.00", html)

    def test_a_dollar_offer_prints_as_it_always_did(self):
        t = self.open(currency="USD")
        self.price(t["id"])
        ctx = svc.submission_context(self.tender(t["id"]))
        self.assertFalse(ctx["dual"])
        self.assertEqual(ctx["boq_rows"][1]["rate"], "86.41")
        self.assertNotIn("rate_usd", ctx["boq_rows"][1])
        html = render_to_string("pdf/tender_submission.html", ctx)
        self.assertNotIn("Rate (USD)", html)
        self.assertNotIn("usd", svc.money_stack(self.tender(t["id"]),
                                                D("100")))


class DualOfferApprovalTests(DualOfferBase):
    def test_the_rate_is_fixed_with_the_value_that_goes_up(self):
        self.price()
        r = self.client.post(
            f"/api/v1/tenders/{self.t['id']}/send-for-approval",
            {"value": "11080.69"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        t = self.tender()
        self.assertEqual(D(t.document.current_revision.payload["offer_rate"]),
                         D("22"))
        r = self.patch({"offer_rate": "25"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("part of the price", r.data["detail"])
        self.assertEqual(self.tender().offer_rate, D("22"))
        # the same terms saved again, unchanged, are not a change of rate
        self.assertEqual(self.patch({"currency": "MVR", "usd_shown": True,
                                     "offer_rate": "22.0000",
                                     "validity_days": 45}).status_code, 200)


class DualOfferAwardTests(DualOfferBase):
    def win(self, tid=None, value="11080.69"):
        tid = tid or self.t["id"]
        self.issue(tid, value)
        r = self.client.post(f"/api/v1/tenders/{tid}/awarded",
                             {"outcome_ref": "LOA/1",
                              "project_code": f"WV{tid}"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return Project.objects.get(site=self.site, code=f"WV{tid}")

    def test_the_project_bill_is_the_rufiyaa_bill_that_was_offered(self):
        self.price()
        boq = Boq.objects.get(tender_id=self.t["id"])
        item = boq.items.get(description="Remove louvres")
        BoqItemWorking.objects.create(item=item, kind="LABOUR",
                                      description="Carpenter",
                                      rate_expr="=120/2", rate=D("60"),
                                      qty=D("1"), amount=D("60"))
        offered = svc.snapshot(self.tender())["bill_total"]
        p = self.win()
        boq = Boq.objects.get(project=p)
        self.assertEqual(boq.currency, "MVR")
        self.assertEqual(str(p.contract_value), "11080.69")
        self.assertEqual(D(boq.total).quantize(D("0.001")), offered)
        a = boq.items.get(description="Remove louvres")
        self.assertEqual(a.rate_supply, D("1901.040"))
        # cost goes over at the OFFICIAL rate, not the offer's
        official = D(str(fx.usd_rate()))
        self.assertEqual(a.unit_cost, (D("60") * official).quantize(D("0.001")))
        self.assertEqual(a.markup_percent,
                         ((a.rate_supply / a.unit_cost - 1) * 100)
                         .quantize(D("0.01")))
        w = a.workings.get()
        self.assertEqual(w.rate, (D("60") * official).quantize(D("0.001")))
        self.assertEqual(D(w.rate_expr), w.rate)
        self.assertEqual(w.amount, w.rate)

    def test_a_plain_rufiyaa_offer_hands_over_a_rufiyaa_bill_untouched(self):
        t = self.open(currency="MVR")
        self.price(t["id"])
        p = self.win(t["id"], "503.67")
        boq = Boq.objects.get(project=p)
        self.assertEqual(boq.currency, "MVR")
        self.assertEqual(boq.items.get(description="Remove louvres").rate_supply,
                         D("86.411"))

    def test_a_dollar_offer_still_hands_over_a_dollar_bill(self):
        t = self.open(currency="USD")
        self.price(t["id"])
        p = self.win(t["id"], "503.67")
        self.assertEqual(Boq.objects.get(project=p).currency, "USD")

    def test_the_portfolio_reads_a_rufiyaa_contract_at_the_official_rate(self):
        from .views_cost import _contract_value
        self.price()
        self.win()
        official = D(str(fx.usd_rate()))
        self.assertEqual(_contract_value(self.site).quantize(D("0.01")),
                         (D("11080.69") / official).quantize(D("0.01")))


class SplitRateBillPrintTests(DualOfferBase):
    """A bill priced material and labour apart prints both rates.

    It printed one Rate column holding the material rate alone, beside an
    amount that included the labour: qty × rate was not the amount, and a
    labour-only line showed an amount against no rate (owner 2026-11-26)."""

    ROWS = [
        {"description": "Bill 1"},
        {"description": "Tiling", "unit": "m2", "qty": "10",
         "unit_cost": "5", "rate_supply": "12.50", "rate_install": "7.50"},
        {"description": "Fix only", "unit": "Nos", "qty": "4",
         "labour_cost": "5", "rate_install": "25"},
    ]

    def split_bill(self, tid):
        self.price(tid, self.ROWS)
        # rows that carry a labour rate make the bill a split one
        self.assertTrue(Boq.objects.get(tender_id=tid).split_rates)
        return svc.submission_context(self.tender(tid))

    def test_a_split_bill_prints_material_and_labour(self):
        t = self.open(currency="USD")
        ctx = self.split_bill(t["id"])
        self.assertEqual([h["label"] for h in ctx["bill_heads"]],
                         ["Material", "Labour", "Amount"])
        _, tiling, fix = ctx["boq_rows"]
        self.assertEqual(tiling["cells"], ["12.50", "7.50", "200.00"])
        self.assertEqual(fix["cells"], ["", "25.00", "100.00"])
        self.assertEqual(ctx["bill_tot_cells"], ["", "300.00"])
        html = render_to_string("pdf/tender_submission.html", ctx)
        for text in ("Material", "Labour", "12.50", "7.50", "300.00"):
            self.assertIn(text, html)

    def test_a_combined_bill_prints_one_rate_that_makes_the_amount(self):
        t = self.open(currency="USD")
        self.price(t["id"], self.ROWS)
        # saving labour rates marks the bill split; one that is not, but
        # still carries a labour rate on a line, prints the whole rate
        Boq.objects.filter(tender_id=t["id"]).update(split_rates=False)
        ctx = svc.submission_context(self.tender(t["id"]))
        self.assertEqual([h["label"] for h in ctx["bill_heads"]],
                         ["Rate", "Amount"])
        _, tiling, fix = ctx["boq_rows"]
        # the rate is the whole rate, so 10 × 20.00 is the 200.00 beside it
        self.assertEqual(tiling["cells"], ["20.00", "200.00"])
        self.assertEqual(fix["cells"], ["25.00", "100.00"])
        self.assertEqual(ctx["bill_tot_cells"], ["300.00"])

    def test_a_split_bill_in_two_currencies_prints_both_legs_of_each(self):
        ctx = self.split_bill(self.t["id"])       # MVR with USD shown, at 22
        self.assertEqual(
            [h["label"] for h in ctx["bill_heads"]],
            ["Material (MVR)", "Labour (MVR)", "Amount (MVR)",
             "Material (USD)", "Labour (USD)", "Amount (USD)"])
        _, tiling, fix = ctx["boq_rows"]
        self.assertEqual(tiling["cells"], ["275.00", "165.00", "4,400.00",
                                           "12.50", "7.50", "200.00"])
        self.assertEqual(fix["cells"], ["", "550.00", "2,200.00",
                                        "", "25.00", "100.00"])
        self.assertEqual(ctx["bill_tot_cells"],
                         ["", "6,600.00", "", "", "300.00"])
        html = render_to_string("pdf/tender_submission.html", ctx)
        self.assertIn("Labour (MVR)", html)
        self.assertIn("6,600.00", html)


class OfferMatchesBillTests(DualOfferBase):
    def test_an_offer_at_the_bills_total_is_not_flagged_for_a_fraction_of_a_cent(self):
        t = self.open(currency="USD")
        self.price(t["id"])                      # the bill totals 503.668
        self.clear(t["id"], "503.67")
        self.assertTrue(svc.snapshot(self.tender(t["id"]))["bill_matches_offer"])

    def test_a_real_difference_is_still_flagged(self):
        t = self.open(currency="USD")
        self.price(t["id"])
        self.clear(t["id"], "500")
        self.assertFalse(svc.snapshot(self.tender(t["id"]))["bill_matches_offer"])
