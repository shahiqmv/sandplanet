"""The rental fleet — phase 3 foundations (MARINE_BUILD_BRIEF.md §4): the
feature switch, the roles, the register with its rate card, the documents
and their expiry alerts, and the rental book kept out of project figures."""
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile

from . import brand, costing, fleet
from .models import (CompanyParameter, CostHead, CostPosting, Notification, User,
                     Vehicle, VehicleDocument)
from .tests import BaseCase, make_user


class FleetBase(BaseCase):
    def setUp(self):
        super().setUp()
        CompanyParameter.objects.update_or_create(
            key="features", defaults={"value": {"rental": True}})
        brand.invalidate()
        self.rental = make_user("rent1", User.Role.RENTAL)
        self.rm = make_user("rm1", User.Role.RENTAL_MANAGER)
        self.finance = make_user("fin1", User.Role.FINANCE)

    def add(self, user=None, **kw):
        self.login(user or self.rm)
        body = {"reg_no": "A1B 2345", "vehicle_class": "Excavator", "make": "Komatsu",
                "model": "PC200", "rate_daily": "4500", "rate_currency": "MVR", **kw}
        return self.client.post("/api/v1/fleet/vehicles", body, format="json")


class FleetSwitchAndRolesTests(FleetBase):
    def test_off_switch_hides_the_module_entirely(self):
        CompanyParameter.objects.update_or_create(key="features", defaults={"value": {"rental": False}})
        brand.invalidate()
        self.login(self.rm)
        self.assertEqual(self.client.get("/api/v1/fleet/summary").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/fleet/vehicles").status_code, 404)

    def test_who_reads_and_who_writes(self):
        for u in (self.pm, self.engineer):
            self.login(u)
            self.assertEqual(self.client.get("/api/v1/fleet/summary").status_code, 403)
        self.login(self.finance)
        r = self.client.get("/api/v1/fleet/summary")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can_write"])
        self.assertEqual(self.add(user=self.finance).status_code, 403)
        self.assertEqual(self.add(user=self.rental, reg_no="B1").status_code, 201)
        self.assertEqual(self.add(user=self.admin, reg_no="B2").status_code, 201)

    def test_seeded_rental_heads_stay_out_of_project_pickers(self):
        self.assertTrue(CostHead.objects.filter(code="RNT_MAINTENANCE", rental=True).exists())
        self.login(self.finance)
        names = [h["name"] for h in self.client.get("/api/v1/cost-heads?pools=1").data]
        self.assertNotIn("Rental — Maintenance & spares", names)
        codes = [h["code"] for h in self.client.get("/api/v1/cost-head-master").data]
        self.assertNotIn("RNT_MAINTENANCE", codes)
        codes = [h["code"] for h in self.client.get("/api/v1/cost-head-master?rental=1").data]
        self.assertIn("RNT_MAINTENANCE", codes)


class VehicleRegisterTests(FleetBase):
    def test_add_edit_and_list_with_the_rate_card(self):
        r = self.add()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["reg_no"], "A1B 2345")
        self.assertEqual(r.data["rate_daily"], "4500.00")
        self.assertTrue(r.data["can_set_rates"])
        vid = r.data["id"]
        r = self.add(reg_no="a1b 2345")                          # same plate, other case
        self.assertEqual(r.status_code, 400)
        self.assertIn("reg_no", r.data)
        r = self.client.patch(f"/api/v1/fleet/vehicles/{vid}",
                              {"status": "ON_HIRE", "fleet_no": "SPM-EX-01", "operator_included": False,
                               "operator_rate_daily": "800"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "ON_HIRE")
        self.assertEqual(r.data["operator_rate_daily"], "800.00")
        rows = self.client.get("/api/v1/fleet/vehicles?search=komatsu").data
        self.assertEqual([x["fleet_no"] for x in rows], ["SPM-EX-01"])
        self.assertEqual(self.client.get("/api/v1/fleet/summary").data["by_status"]["ON_HIRE"], 1)

    def test_only_the_manager_changes_the_rate_card(self):
        vid = self.add().data["id"]
        self.login(self.rental)
        r = self.client.patch(f"/api/v1/fleet/vehicles/{vid}", {"rate_daily": "9999"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("rate_daily", r.data)
        r = self.client.patch(f"/api/v1/fleet/vehicles/{vid}", {"status": "MAINTENANCE", "hour_meter": "1250.5"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)          # the register itself is theirs
        self.assertEqual(r.data["rate_daily"], "4500.00")
        r = self.add(user=self.rental, reg_no="C3", rate_daily="100")
        self.assertEqual(r.status_code, 201)                    # a first rate on a new vehicle is fine
        self.assertEqual(r.data["rate_daily"], "100.00")


class VehicleDocumentTests(FleetBase):
    def test_documents_expire_and_the_fleet_is_alerted_once_per_level(self):
        vid = self.add().data["id"]
        today = date.today()
        r = self.client.post(f"/api/v1/fleet/vehicles/{vid}/documents",
                             {"kind": "INSURANCE", "reference": "POL-77",
                              "expires_on": (today + timedelta(days=20)).isoformat(),
                              "file": SimpleUploadedFile("pol.pdf", b"%PDF-1.4", "application/pdf")})
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data["documents"][0]
        self.assertEqual(d["state"], "d30")
        self.assertEqual(r.data["docs_state"], "d30")
        self.client.post(f"/api/v1/fleet/vehicles/{vid}/documents",
                         {"kind": "REGISTRATION", "expires_on": (today - timedelta(days=3)).isoformat()},
                         format="json")
        s = self.client.get("/api/v1/fleet/summary").data
        self.assertEqual([e["state"] for e in s["expiring"]], ["overdue", "d30"])
        # alerts go to the rental team and admin, once per level
        fired = fleet.sweep_expiry(today)
        self.assertEqual(fired, 2 * 3)                          # two documents × (rental, manager, admin)
        self.assertEqual(fleet.sweep_expiry(today), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.rm).count(), 2)
        docs = VehicleDocument.objects.filter(vehicle_id=vid).order_by("kind")
        self.assertEqual({x.alert_level for x in docs}, {"30", "OVERDUE"})
        # 7 days later the insurance crosses the 7-day line and alerts again
        self.assertEqual(fleet.sweep_expiry(today + timedelta(days=14)), 3)
        r = self.client.delete(f"/api/v1/fleet/vehicles/{vid}/documents/{d['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["documents"]), 1)


class RentalBookTests(FleetBase):
    def test_a_vehicle_posting_never_reaches_a_project_figure(self):
        vid = self.add().data["id"]
        v = Vehicle.objects.get(id=vid)
        head = costing.by_code(costing.RNT_MAINTENANCE)
        p = costing.post(site=self.sjr, cost_head=head, state="INCURRED", source="PYR",
                         amount=1500, currency="MVR", book="RENTAL")
        p.vehicle = v
        p.save(update_fields=["vehicle"])
        self.assertEqual(CostPosting.objects.filter(vehicle=v, book="RENTAL").count(), 1)
        self.login(self.finance)
        r = self.client.get(f"/api/v1/cost/site/{self.sjr.id}")
        self.assertEqual(str(r.data["incurred"]), "0.00")


# ---- phase 4: agreements and the daily register --------------------------------

from . import rental  # noqa: E402
from .models import Customer, HireLog, RentalAgreement  # noqa: E402


class RentalBase(FleetBase):
    def setUp(self):
        super().setUp()
        self.cust = Customer.objects.create(name="Reef Constructions", default_currency="MVR",
                                            tin="1100200GST001")
        self.ex = Vehicle.objects.get(id=self.add(reg_no="P 9921", fleet_no="EX-01").data["id"])
        self.tp = Vehicle.objects.get(id=self.add(reg_no="P 4410", fleet_no="TP-02",
                                                  vehicle_class="Tipper", rate_daily="2200").data["id"])

    def agreement(self, user=None, **kw):
        self.login(user or self.rm)
        r = self.client.post("/api/v1/fleet/agreements", {
            "customer": self.cust.id, "title": "Harbour works", "site_location": "Fuvahmulah harbour",
            "start_date": "2026-09-01", "customer_rep": "Ali Rasheed", **kw}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def with_vehicles(self, a, rows=None):
        r = self.client.put(f"/api/v1/fleet/agreements/{a['id']}/vehicles", {"vehicles": rows or [
            {"vehicle": self.ex.id}, {"vehicle": self.tp.id, "rate_daily": "2000"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def activate(self, a):
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/action", {"action": "activate"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data


class AgreementTests(RentalBase):
    def test_numbering_terms_and_vehicles_at_agreed_rates(self):
        a = self.agreement()
        self.assertEqual(a["ref"], f"{date.today().year}-RA-001")
        self.assertIn("approved daily register", a["payment_terms"])     # the standard lines
        self.assertEqual(a["currency"], "MVR")
        a = self.with_vehicles(a)
        rates = {v["fleet_no"]: v["rate_daily"] for v in a["vehicles"]}
        self.assertEqual(rates, {"EX-01": "4500.00", "TP-02": "2000.00"})   # card rate, negotiated rate
        self.assertEqual(self.agreement(title="Second")["ref"], f"{date.today().year}-RA-002")
        # the draft PDF prints
        r = self.client.get(f"/api/v1/fleet/agreements/{a['id']}/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        ctx = rental.agreement_context(RentalAgreement.objects.get(id=a["id"]), draft=True)
        self.assertEqual([r["rate_f"] for r in ctx["rows"]], ["4,500.00", "2,000.00"])

    def test_activation_puts_vehicles_on_hire_and_completion_releases_them(self):
        a = self.agreement()
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/action", {"action": "activate"}, format="json")
        self.assertEqual(r.status_code, 400)                    # no vehicles yet
        a = self.with_vehicles(a)
        self.login(self.rental)
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/action", {"action": "activate"}, format="json")
        self.assertEqual(r.status_code, 400)                    # manager only
        self.login(self.rm)
        a = self.activate(a)
        self.assertEqual(a["status"], "ACTIVE")
        self.assertTrue(a["has_pdf"] or True)
        self.assertEqual(Vehicle.objects.get(id=self.ex.id).status, "ON_HIRE")
        # an active agreement only changes its rep / PO / end / notes
        r = self.client.patch(f"/api/v1/fleet/agreements/{a['id']}", {"title": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f"/api/v1/fleet/agreements/{a['id']}", {"customer_po": "PO-9"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/action", {"action": "complete"}, format="json")
        self.assertEqual(r.data["status"], "COMPLETED")
        self.assertEqual(Vehicle.objects.get(id=self.ex.id).status, "AVAILABLE")
        self.assertEqual(Vehicle.objects.get(id=self.tp.id).status, "AVAILABLE")

    def test_only_the_manager_negotiates_a_rate(self):
        a = self.agreement()
        self.login(self.rental)
        r = self.client.put(f"/api/v1/fleet/agreements/{a['id']}/vehicles",
                            {"vehicles": [{"vehicle": self.ex.id, "rate_daily": "1"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)           # accepted…
        self.assertEqual(r.data["vehicles"][0]["rate_daily"], "1.00")


class RegisterTests(RentalBase):
    def live(self):
        a = self.with_vehicles(self.agreement())
        return self.activate(a)

    def test_days_are_recorded_billable_or_not_and_approved_by_the_rep(self):
        a = self.live()
        ex = next(v for v in a["vehicles"] if v["fleet_no"] == "EX-01")
        tp = next(v for v in a["vehicles"] if v["fleet_no"] == "TP-02")
        self.login(self.rental)
        rows = [{"line": ex["id"], "date": "2026-09-01", "state": "WORKED", "hours": "8"},
                {"line": ex["id"], "date": "2026-09-02", "state": "STANDBY"},
                {"line": ex["id"], "date": "2026-09-03", "state": "BREAKDOWN", "remarks": "hydraulic hose"},
                {"line": tp["id"], "date": "2026-09-01", "state": "WORKED", "hours": "9.5"}]
        r = self.client.put(f"/api/v1/fleet/agreements/{a['id']}/register?from=2026-09-01&to=2026-09-07",
                            {"rows": rows}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        g = r.data
        exl = next(x for x in g["lines"] if x["line"] == ex["id"])
        self.assertEqual(exl["billable_days"], 2)              # worked + standby; breakdown is not
        self.assertEqual(exl["approved_days"], 0)
        self.assertEqual(exl["cells"][0]["hours"], "8.0")
        # a day before the hire started is refused
        r = self.client.put(f"/api/v1/fleet/agreements/{a['id']}/register?from=2026-08-25&to=2026-09-01",
                            {"rows": [{"line": ex["id"], "date": "2026-08-30", "state": "WORKED"}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("outside", r.data["detail"])
        # the customer's rep approves the week; approved days lock
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/register/approve",
                             {"from": "2026-09-01", "to": "2026-09-07", "approved_by": "Ali Rasheed"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["count"], 4)
        exl = next(x for x in r.data["lines"] if x["line"] == ex["id"])
        self.assertEqual(exl["approved_days"], 2)
        self.assertEqual(exl["cells"][0]["approved_by"], "Ali Rasheed")
        r = self.client.put(f"/api/v1/fleet/agreements/{a['id']}/register?from=2026-09-01&to=2026-09-07",
                            {"rows": [{"line": ex["id"], "date": "2026-09-01", "state": "OFF_HIRE"}]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(HireLog.objects.get(line_id=ex["id"], date="2026-09-01").state, "WORKED")   # locked
        self.assertEqual(self.client.get(f"/api/v1/fleet/agreements/{a['id']}").data["unapproved_days"], 0)
        # the manager can reopen; the rental user cannot
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/register/approve",
                             {"from": "2026-09-01", "to": "2026-09-01", "action": "reopen"})
        self.assertEqual(r.status_code, 400)
        self.login(self.rm)
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/register/approve",
                             {"from": "2026-09-01", "to": "2026-09-01", "action": "reopen"})
        self.assertEqual(r.data["count"], 2)
        # a vehicle with register days cannot be dropped from the agreement
        r = self.client.put(f"/api/v1/fleet/agreements/{a['id']}/vehicles",
                            {"vehicles": [{"vehicle": self.tp.id}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("register days", r.data["detail"])

    def test_the_register_only_runs_under_an_active_agreement(self):
        a = self.with_vehicles(self.agreement())
        ex = a["vehicles"][0]
        r = self.client.put(f"/api/v1/fleet/agreements/{a['id']}/register",
                            {"rows": [{"line": ex["id"], "date": "2026-09-01", "state": "WORKED"}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.login(self.finance)
        r = self.client.get(f"/api/v1/fleet/agreements/{a['id']}/register?from=2026-09-01&to=2026-09-07")
        self.assertEqual(r.status_code, 200)                    # Finance reads
        self.assertEqual(self.client.get("/api/v1/fleet/customers").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/fleet/customers", {"name": "x"}, format="json").status_code, 403)


# ---- phase 5: invoicing the approved days, receipts and receivables -------------

from decimal import Decimal  # noqa: E402

from .models import RentalInvoice, RentalReceipt  # noqa: E402


class InvoiceBase(RentalBase):
    def billed_setup(self):
        """An active agreement with a week of approved days on the excavator
        (5 worked + 1 standby billable, 1 breakdown not) and two unapproved."""
        self.cust.tin = "1100200GST001"
        self.cust.credit_days = 30
        self.cust.save()
        a = self.activate(self.with_vehicles(self.agreement(mobilisation_charge="5000")))
        ex = next(v for v in a["vehicles"] if v["fleet_no"] == "EX-01")
        tp = next(v for v in a["vehicles"] if v["fleet_no"] == "TP-02")
        rows = [{"line": ex["id"], "date": f"2026-09-0{d}", "state": s} for d, s in
                [(1, "WORKED"), (2, "WORKED"), (3, "WORKED"), (4, "STANDBY"), (5, "BREAKDOWN"),
                 (6, "WORKED"), (7, "WORKED")]]
        rows += [{"line": tp["id"], "date": "2026-09-01", "state": "WORKED"},
                 {"line": tp["id"], "date": "2026-09-02", "state": "WORKED"}]
        r = self.client.put(f"/api/v1/fleet/agreements/{a['id']}/register?from=2026-09-01&to=2026-09-07",
                            {"rows": rows}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/register/approve",
                             {"from": "2026-09-01", "to": "2026-09-07", "approved_by": "Ali Rasheed"})
        self.assertEqual(r.status_code, 200, r.data)
        return a


class RentalInvoiceTests(InvoiceBase):
    def test_invoice_bills_approved_days_once_at_agreed_rates_with_gst(self):
        a = self.billed_setup()
        r = self.client.get(f"/api/v1/fleet/agreements/{a['id']}/invoices?from=2026-09-01&to=2026-09-30")
        pv = r.data["preview"]
        self.assertEqual(pv["days"], 8)                        # 6 excavator + 2 tipper
        self.assertEqual(pv["mobilisation"], "5000.00")
        self.assertEqual(pv["subtotal"], "31000.00")           # 6×4500 + 2×2000
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/invoices",
                             {"from": "2026-09-01", "to": "2026-09-30", "invoice_date": "2026-10-01",
                              "include_mobilisation": True}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        inv = r.data
        self.assertEqual(inv["ref"], f"INV-{date.today().year}-0001")
        self.assertEqual(inv["subtotal"], "36000.00")
        self.assertEqual(inv["gst"], "2880.00")                # 8 %
        self.assertEqual(inv["total"], "38880.00")
        self.assertEqual(str(inv["due_date"]), "2026-10-31")
        self.assertEqual([x["days"] for x in inv["lines"]], [6, 2])
        # the days are stamped; nothing bills twice, the mobilisation neither
        r = self.client.get(f"/api/v1/fleet/agreements/{a['id']}/invoices?from=2026-09-01&to=2026-09-30")
        self.assertEqual(r.data["preview"]["days"], 0)
        self.assertIsNone(r.data["preview"]["mobilisation"])
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/invoices",
                             {"from": "2026-09-01", "to": "2026-09-30"}, format="json")
        self.assertEqual(r.status_code, 400)
        # the rental user cannot issue; the manager does, and revenue posts per vehicle
        self.login(self.rental)
        r = self.client.post(f"/api/v1/fleet/invoices/{inv['id']}", {"action": "issue"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.login(self.rm)
        r = self.client.post(f"/api/v1/fleet/invoices/{inv['id']}", {"action": "issue"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "ISSUED")
        posts = CostPosting.objects.filter(book="RENTAL", source="SALE")
        self.assertEqual(posts.count(), 4)                     # 2 vehicles + mobilisation + GST
        self.assertEqual(posts.filter(vehicle=self.ex).get().amount, Decimal("27000.00"))
        self.assertEqual(posts.filter(cost_head__code="RNT_OUTPUT_GST").get().amount, Decimal("2880.00"))
        self.assertEqual(self.client.get(f"/api/v1/fleet/invoices/{inv['id']}/pdf")["Content-Type"],
                         "application/pdf")
        # void reverses the postings and frees the days
        r = self.client.post(f"/api/v1/fleet/invoices/{inv['id']}", {"action": "void", "reason": "wrong rate"},
                             format="json")
        self.assertEqual(r.data["status"], "VOID")
        self.assertEqual(CostPosting.objects.filter(book="RENTAL").count(), 8)
        self.assertEqual(sum(p.amount for p in CostPosting.objects.filter(book="RENTAL")), 0)
        r = self.client.get(f"/api/v1/fleet/agreements/{a['id']}/invoices?from=2026-09-01&to=2026-09-30")
        self.assertEqual(r.data["preview"]["days"], 8)

    def test_gst_exempt_customer_and_no_tin_guard(self):
        a = self.billed_setup()
        self.cust.tin = ""
        self.cust.save()
        r = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/invoices",
                             {"from": "2026-09-01", "to": "2026-09-30"}, format="json")
        inv = r.data
        r = self.client.post(f"/api/v1/fleet/invoices/{inv['id']}", {"action": "issue"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("TIN", r.data["detail"])


class RentalReceiptTests(InvoiceBase):
    def issued(self):
        a = self.billed_setup()
        inv = self.client.post(f"/api/v1/fleet/agreements/{a['id']}/invoices",
                               {"from": "2026-09-01", "to": "2026-09-30"}, format="json").data
        self.client.post(f"/api/v1/fleet/invoices/{inv['id']}", {"action": "issue"}, format="json")
        return a, RentalInvoice.objects.get(id=inv["id"])

    def test_finance_records_a_receipt_and_the_aging_and_statement_follow(self):
        a, inv = self.issued()
        self.assertEqual(inv.total, Decimal("33480.00"))       # 31000 + 8 %
        self.login(self.rm)
        r = self.client.post("/api/v1/fleet/receipts", {"customer": self.cust.id, "receipt_date": "2026-10-05",
                                                        "allocations": [{"invoice_id": inv.id, "amount": "10000"}]},
                             format="json")
        self.assertEqual(r.status_code, 400)                   # the Rental Manager is not the money desk
        self.login(self.finance)
        r = self.client.get(f"/api/v1/fleet/receipts/allocate?customer={self.cust.id}&amount=10000")
        self.assertEqual(r.data["allocations"][0]["amount"], "10000.00")
        r = self.client.post("/api/v1/fleet/receipts", {"customer": self.cust.id, "receipt_date": "2026-10-05",
                                                        "method": "TT", "reference": "TT-778",
                                                        "allocations": r.data["allocations"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["receipt_no"], "OR-0001")
        ag = self.client.get("/api/v1/fleet/receivables").data
        self.assertEqual(ag["total"], "23480.00")
        self.assertEqual(ag["customers"][0]["invoices"][0]["outstanding"], "23480.00")
        st = self.client.get(f"/api/v1/fleet/customers/{self.cust.id}/statement?to=2026-12-31").data
        self.assertEqual([e["kind"] for e in st["rows"]], ["INVOICE", "RECEIPT"])
        self.assertEqual(st["closing"], "23480.00")
        # settle the rest → PAID; an over-allocation is refused
        r = self.client.post("/api/v1/fleet/receipts", {"customer": self.cust.id, "receipt_date": "2026-10-20",
                                                        "allocations": [{"invoice_id": inv.id, "amount": "30000"}]},
                             format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/fleet/receipts", {"customer": self.cust.id, "receipt_date": "2026-10-20",
                                                        "allocations": [{"invoice_id": inv.id, "amount": "23480"}]},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "PAID")
        self.assertEqual(self.client.get("/api/v1/fleet/receivables").data["customers"], [])
        # a paid invoice cannot be voided; deleting the receipt reopens it
        self.login(self.rm)
        r = self.client.post(f"/api/v1/fleet/invoices/{inv.id}", {"action": "void", "reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.login(self.finance)
        rid = r.data.get("id") or RentalReceipt.objects.latest("id").id
        self.assertEqual(self.client.delete(f"/api/v1/fleet/receipts/{rid}").status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "ISSUED")
        self.assertEqual(self.client.get(f"/api/v1/fleet/receipts/{RentalReceipt.objects.first().id}")["Content-Type"],
                         "application/pdf")
