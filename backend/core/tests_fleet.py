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
