"""Seed a realistic, fully-worked demo dataset for the Planet User Guide
screenshots (PLANET-UG-01).

ONLY ever run this against the throwaway demo instance:

    python manage.py seed_demo --settings=config.settings_demo

It refuses to run against a database whose file is the live ``db.sqlite3``
so it can never pollute the team-review server behind the cloudflared
tunnel. Master data (sites, cost heads, categories, company parameters)
must already be seeded — run ``seed`` first.

Every document is created and transitioned through the REAL DRF API with
``APIClient``/``force_authenticate`` — exactly the calls the UI makes — so
gap-free numbering, the cost ledger, approval stamps and generated PDFs are
all genuine. Master records (site contacts, contract values, employees) are
written straight through the ORM where the API deliberately does not expose
the field.

Idempotent enough for a fresh demo DB: master rows use get_or_create; the
document flows assume an empty transactional slate (the regen script drops
db.demo.sqlite3 first). Login for every demo user is password ``planet-demo``.
"""

import io
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from rest_framework.test import APIClient

from core.models import (CostHead, Employee, EmployeeSiteAllocation,
                         Item, ItemCategory, ManpowerCategory, Project,
                         Site, SitePmHistory, Supplier, User,
                         UserSiteAllocation)

PW = "planet-demo"  # shared demo password; the capture script logs in with it

# A tiny valid PNG — stands in for DPR site photos and receipt scans so the
# guide's filled forms show real thumbnails without shipping binary assets.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea72d994800000000494e44ae426082"
)

# Demo users, one per role. usernames are short so the capture script and a
# human reviewer can log in quickly.
USERS = [
    ("eng",        User.Role.SITE_ENGINEER, "Ibrahim Naseer"),
    ("storekeeper", User.Role.SITE_ADMIN,   "Aishath Reena"),
    ("pm",         User.Role.PM,            "Mohamed Shazin"),
    ("purchasing", User.Role.HO_PURCHASING, "Hassan Rasheed"),
    ("director",   User.Role.DIRECTOR,      "Ahmed Zahir"),
    ("signatory",  User.Role.SIGNATORY,     "Ali Waheed"),
    ("finance",    User.Role.FINANCE,       "Fathimath Nazly"),
    ("hr",         User.Role.HO_HR,         "Mariyam Shifa"),
    ("admin",      User.Role.ADMIN,         "System Administrator"),
]

# (description, unit, category) — a small but believable island-build catalogue.
ITEMS = [
    ("Cement OPC 50kg bag", "Bag", "Civil"),
    ("Rebar B500 12mm", "Kg", "Civil"),
    ("Rebar B500 10mm", "Kg", "Civil"),
    ("Hollow block 8\" ", "Nos", "Civil"),
    ("River sand", "m³", "Civil"),
    ("Aggregate 20mm", "m³", "Civil"),
    ("Waterproofing membrane 1.5mm", "Roll", "Finishes"),
    ("Tile adhesive 20kg", "Bag", "Finishes"),
    ("Porcelain tile 600x600 Grade A", "m²", "Finishes"),
    ("PVC pressure pipe 63mm", "m", "MEP"),
    ("PPR pipe 25mm", "m", "MEP"),
    ("Pool circulation pump 2HP", "Nos", "Pool"),
]

SUPPLIERS = [
    ("Male' Hardware Pvt Ltd", "Hardware & steel", "3323344", "sales@malehardware.mv"),
    ("Reefside Trading Pvt Ltd", "Tiles & finishes", "3310099", "info@reefside.mv"),
    ("Alia Building Supplies", "Cement & aggregates", "3345566", "orders@alia.mv"),
    ("BlueLagoon Pool Systems", "Pool plant & MEP", "3319911", "hello@bluelagoon.mv"),
]

# (name, nationality, category, basic_pay MVR, permit_no)
EMPLOYEES = [
    ("Kumara Perera", "Sri Lankan", "Mason", 9600, "WP-448120"),
    ("Rahim Uddin", "Bangladeshi", "Steel Fixer/Bar Bender", 9000, "WP-448121"),
    ("Suresh Nair", "Indian", "Plumber", 10200, "WP-448122"),
    ("Anil Chowdhury", "Bangladeshi", "Carpenter", 9300, "WP-448123"),
    ("Prakash Thapa", "Nepali", "Electrician", 10500, "WP-448124"),
    ("Mohamed Faisal", "Maldivian", "Foreman", 14000, "WP-448125"),
]

# MS-Project-style programme paste (id, name w/ indent, duration, start, finish).
PROGRAMME_PASTE = (
    "1\tPROPOSED CONSTRUCTION OF 17 NOS SWIMMING POOLS\t233 days\t"
    "Fri 4/17/26\tSat 12/5/26\n"
    "3\t  CONTRACT MILESTONES\t228 days\tWed 4/22/26\tSat 12/5/26\n"
    "4\t    Start Date in Local Island\t0 days\tWed 4/22/26\tWed 4/22/26\n"
    "10\t  MOBILISATION & SITE SETUP\t14 days\tThu 4/23/26\tThu 5/7/26\n"
    "20\t  POOL SHELL — POOLS 1-6\t60 days\tFri 5/8/26\tTue 7/7/26\n"
    "108\t    Excavation & Formwork\t20 days\tFri 5/8/26\tThu 5/28/26\n"
    "110\t    Footing & Wall Concreting\t25 days\tFri 5/29/26\tMon 6/22/26\n"
    "140\t    Waterproofing & Screed\t15 days\tTue 6/23/26\tTue 7/7/26\n"
    "200\t  POOL FINISHES — POOLS 1-6\t45 days\tWed 7/8/26\tFri 8/21/26\n"
    "300\t  MEP & PLANT ROOM\t50 days\tWed 7/8/26\tWed 8/26/26\n"
    "400\t  HANDOVER — PHASE 1\t0 days\tFri 8/21/26\tFri 8/21/26\n"
)


class Command(BaseCommand):
    help = "Seed a fully-worked MVR demo dataset for the user-guide screenshots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-going", action="store_true",
            help="Log and continue past a failing section instead of raising.")

    # -- infrastructure --------------------------------------------------

    def handle(self, *args, **opts):
        self._guard_not_live()
        self.keep_going = opts["keep_going"]
        self.client = APIClient()
        self.users = {}
        self.items = {}
        self.today = date.today()

        for step in (
            self.master_users, self.enrich_site, self.build_project,
            self.catalogue, self.suppliers, self.employees,
            self.attendance_and_payroll, self.daily_reports, self.tws_and_dma,
            self.inspections, self.procurement_chain, self.payment_request,
            self.petty_cash,
        ):
            try:
                step()
            except Exception as exc:  # noqa: BLE001
                if not self.keep_going:
                    raise
                self.stderr.write(self.style.ERROR(
                    f"  [skip] {step.__name__}: {exc}"))
        self.stdout.write(self.style.SUCCESS("\nDemo seed complete."))
        self.stdout.write(f"Login: any of {', '.join(self.users)} — password {PW!r}")

    def _guard_not_live(self):
        name = str(settings.DATABASES["default"]["NAME"])
        if name.endswith("db.sqlite3") and "demo" not in name:
            raise CommandError(
                "Refusing to seed: this looks like the LIVE db.sqlite3. Run "
                "with --settings=config.settings_demo.")

    def as_(self, username):
        self.client.force_authenticate(self.users[username])

    def post(self, url, body, fmt="json", who=None):
        if who:
            self.as_(who)
        r = self.client.post(url, body, format=fmt)
        if r.status_code not in (200, 201):
            raise CommandError(f"POST {url} -> {r.status_code}: {r.data}")
        return r.data

    def act(self, ref, action, who, **body):
        self.as_(who)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/{action}",
                             body, format="json")
        if r.status_code != 200:
            raise CommandError(
                f"action {action} on {ref} as {who} -> {r.status_code}: {r.data}")
        return r.data

    def working_days(self, n, offset=1):
        """The most recent `n` working days at the demo site, newest last."""
        out, d = [], self.today - timedelta(days=offset)
        while len(out) < n:
            if d.isoweekday() in self.site.working_days:
                out.append(d)
            d -= timedelta(days=1)
        return list(reversed(out))

    def photos(self, ref, who, n=4):
        self.as_(who)
        for i in range(n):
            caption = DPR_CAPTIONS[i % len(DPR_CAPTIONS)]
            f = SimpleUploadedFile(f"p{i}.jpg", _photo_bytes(caption, i),
                                   content_type="image/jpeg")
            r = self.client.post(f"/api/v1/documents/{ref}/attachments",
                                 {"file": f, "kind": "PHOTO",
                                  "caption": caption}, format="multipart")
            if r.status_code != 201:
                raise CommandError(f"photo {i} on {ref}: {r.status_code} {r.data}")

    # -- master data -----------------------------------------------------

    def master_users(self):
        for username, role, full_name in USERS:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"role": role, "full_name": full_name})
            # Always (re)set the demo password so the capture script can log
            # in — even for the pre-existing `admin` superuser from `seed`.
            user.role = role
            user.full_name = full_name
            user.set_password(PW)
            user.save()
            self.users[username] = user
        self.stdout.write(f"  users: {', '.join(self.users)}")

    def enrich_site(self):
        """Turn the plain seeded SJR into a fully-specified project site."""
        self.site = Site.objects.get(code="SJR")
        self.site.name = "Soneva Jani"
        self.site.status = Site.Status.ACTIVE
        self.site.contract_value = Decimal("18500000.00")
        self.site.currency = "MVR"
        self.site.award_date = date(2026, 4, 10)
        self.site.start_date = date(2026, 4, 22)
        self.site.planned_completion = date(2026, 12, 5)
        self.site.duration_days = 233
        self.site.scope = ("Construction of 17 nos swimming pools with "
                           "associated plant rooms, MEP and finishes.")
        self.site.client_name = "Soneva Jani Resort"
        self.site.client_address = "Medhufaru, Noonu Atoll, Maldives"
        self.site.client_contact = "J. Perera"
        self.site.client_designation = "Resident Engineer"
        self.site.client_phone = "6560304"
        self.site.client_email = "projects@soneva.com"
        self.site.consultant_name = "Atoll Consult Pvt Ltd"
        self.site.consultant_contact = "A. Waheed, Project Consultant"
        self.site.save()

        # Allocate site users and register the project PM.
        for username in ("eng", "storekeeper", "pm"):
            UserSiteAllocation.objects.get_or_create(
                user=self.users[username], site=self.site,
                from_date=self.site.start_date)
        SitePmHistory.objects.get_or_create(
            site=self.site, pm_user=self.users["pm"],
            defaults={"from_date": self.site.start_date})
        self.stdout.write(f"  site {self.site.code} enriched (MVR "
                          f"{self.site.contract_value:,.0f})")

    def build_project(self):
        proj = self.post(f"/api/v1/sites/{self.site.id}/projects", {
            "code": "POOLS17",
            "title": "Proposed Construction of 17 Swimming Pools",
            "scope": "17 pools, plant rooms, MEP and finishes across the resort.",
            "loa_date": "2026-04-10",
            "start_date": "2026-04-22",
            "planned_completion": "2026-12-05",
            "pm": self.users["pm"].id,
        }, who="pm")
        self.project = Project.objects.get(pk=proj["id"])
        self.project.contract_value = Decimal("18500000.00")
        self.project.manpower_plan = [
            {"month": "2026-05", "workers": 32}, {"month": "2026-06", "workers": 48},
            {"month": "2026-07", "workers": 55}, {"month": "2026-08", "workers": 44},
        ]
        self.project.save()
        self.post(f"/api/v1/projects/{self.project.id}/programme",
                  {"paste": PROGRAMME_PASTE}, who="pm")
        self.stdout.write(f"  project {self.project.code} + programme "
                          f"({self.project.activities.count()} activities)")

    def catalogue(self):
        for name, _s in ((c, 10 * i) for i, c in enumerate(
                ["Civil", "Finishes", "MEP", "Pool"], start=1)):
            ItemCategory.objects.get_or_create(name=name)
        for desc, unit, cat in ITEMS:
            data = self.post("/api/v1/items",
                             {"description": desc, "unit": unit, "category": cat},
                             who="purchasing")
            self.items[desc] = Item.objects.get(pk=data["id"])
        self.stdout.write(f"  catalogue: {len(self.items)} items")

    def suppliers(self):
        for name, notes, phone, email in SUPPLIERS:
            self.post("/api/v1/suppliers",
                      {"name": name, "notes": notes, "phone": phone,
                       "email": email}, who="purchasing")
        self.stdout.write(f"  suppliers: {len(SUPPLIERS)}")

    def employees(self):
        self.emps = []
        for full_name, nat, cat_name, pay, permit in EMPLOYEES:
            cat = ManpowerCategory.objects.filter(name=cat_name).first()
            data = self.post("/api/v1/employees", {
                "full_name": full_name, "nationality": nat,
                "passport_no": f"N{permit[-6:]}",
                "job_category": cat.id if cat else None,
                "basic_pay": pay, "work_permit_no": permit,
                "work_permit_expiry": "2027-03-31",
                "join_date": "2026-04-22"}, who="hr")
            emp = Employee.objects.get(pk=data["id"])
            self.post(f"/api/v1/employees/{emp.id}/allocate",
                      {"site_id": self.site.id}, who="hr")
            self.emps.append(emp)
        self.stdout.write(f"  employees: {len(self.emps)}")

    def attendance_and_payroll(self):
        """A run of daily attendance, PM-approved OT, then a locked month —
        which posts Labour & Staff cost into the ledger."""
        days = [d for d in self.working_days(6, offset=1)]
        for i, day in enumerate(days):
            rows = [{"employee_id": e.id, "check_in": "07:00",
                     "check_out": "18:00",
                     "ot_requested": 2 if i == 0 and j < 3 else 0,
                     "remark": "PRESENT"} for j, e in enumerate(self.emps)]
            self.as_("storekeeper")
            r = self.client.put("/api/v1/attendance/bulk", {
                "site": self.site.id, "date": day.isoformat(), "rows": rows},
                format="json")
            if r.status_code != 200:
                raise CommandError(f"attendance bulk: {r.status_code} {r.data}")
        # PM approves the requested OT on the first day.
        from core.models import Attendance
        ot_ids = list(Attendance.objects.filter(site=self.site,
                                                ot_requested__gt=0)
                     .values_list("id", flat=True))
        if ot_ids:
            self.post("/api/v1/attendance/ot-approve", {"ids": ot_ids}, who="pm")
        # Lock the previous month so payroll + staff cost post (if it has days).
        lock_day = days[0]
        self.as_("pm")
        self.client.post(
            f"/api/v1/timesheets/{self.site.id}/{lock_day.year}/"
            f"{lock_day.month}/lock")
        self.stdout.write(f"  attendance: {len(days)} days x {len(self.emps)} "
                          f"crew; {lock_day.year}-{lock_day.month:02d} locked")

    # -- site documents --------------------------------------------------

    def daily_reports(self):
        """A run of issued+verified DPRs over the recent working days so the
        register reads healthy (not a wall of gaps) and progress climbs."""
        act = next((a for a in self.project.activities.all()
                    if a.duration_days and not a.is_milestone), None)
        cats = {c.name: c for c in ManpowerCategory.objects.filter(list_type="DPR")}

        def manpower(scale):
            out = {}
            for name, count in (("Mason", 6), ("Steel Fixer/Bar Bender", 5),
                                ("Carpenter", 4), ("Site Engineer", 1),
                                ("Foreman", 1)):
                if name in cats:
                    out[str(cats[name].id)] = max(1, count + scale)
            return out

        days = self.working_days(5, offset=1)
        last_ref = None
        for i, day in enumerate(days):
            todate = 35 + i * 8   # progress climbs across the week
            work_done = ([{"activity_id": act.id, "activity": act.name,
                           "location": "Pool 3", "progress_today": 8,
                           "progress_todate": todate, "remarks": "On programme",
                           "project": "POOLS17"}] if act else [])
            dpr = self.post("/api/v1/documents", {
                "doc_type": "DPR", "site_id": self.site.id,
                "doc_date": day.isoformat(),
                "payload": {
                    "weather_am": "Sunny", "weather_pm": "Cloudy",
                    "rain_time_lost": "Nil",
                    "manpower": manpower(i - 2),
                    "machinery": [{"item": "Concrete mixer", "nos": 2, "remarks": ""},
                                  {"item": "Poker vibrator", "nos": 3, "remarks": ""}],
                    "work_done": work_done,
                    "materials": [
                        {"material": "Cement OPC 50kg bag", "unit": "Bag",
                         "opening": 120, "received": 280 if i == 0 else 0,
                         "consumed": 60, "balance": 340 - i * 60, "remarks": ""},
                        {"material": "Rebar B500 12mm", "unit": "Kg",
                         "opening": 500, "received": 3960 if i == 0 else 0,
                         "consumed": 800, "balance": 3660 - i * 800, "remarks": ""}],
                    "matters_affecting": "Awaiting client approval on tile sample."
                    if i == len(days) - 1 else "Nil.",
                    "visitors": "Resident Engineer site walk 10:00"
                    if i % 2 == 0 else "",
                    "safety": "Toolbox talk held; no incidents.",
                }}, who="eng")
            self.photos(dpr["ref"], "eng", 4)
            self.act(dpr["ref"], "issue", "eng")
            self.act(dpr["ref"], "verify", "pm")
            last_ref = dpr["ref"]
        self.stdout.write(f"  DPRs: {len(days)} issued + verified "
                          f"(latest {last_ref})")

    def tws_and_dma(self):
        tomorrow = self.today + timedelta(days=1)
        tws = self.post("/api/v1/documents", {
            "doc_type": "TWS", "site_id": self.site.id,
            "doc_date": tomorrow.isoformat(),
            "payload": {"activities": [
                {"activity": "Wall concreting Pool 3", "location": "Pool 3",
                 "trade": "Mason/Tiler", "project": "POOLS17"},
                {"activity": "Rebar fixing Pool 4", "location": "Pool 4",
                 "trade": "Steel Fixer/Welder", "project": "POOLS17"}],
                "planned_manpower": [{"trade": "Mason/Tiler", "count": 8}],
                "access_support": "Buggy for material movement; villa access 08:00",
            }}, who="eng")
        self.act(tws["ref"], "issue", "eng")
        self.stdout.write(f"  {tws['ref']} issued")

        # DMA — daily manpower allocation (internal, PM issues). Documented as
        # a proposed new guide section pending owner approval.
        dma = self.post("/api/v1/documents", {
            "doc_type": "DMA", "site_id": self.site.id,
            "doc_date": self.today.isoformat(),
            "payload": {"tasks": [
                {"task": "Wall concreting — Pool 3", "location": "Pool 3",
                 "project": "POOLS17", "category": "Mason", "workers": 6,
                 "remarks": ""},
                {"task": "Rebar fixing — Pool 4", "location": "Pool 4",
                 "project": "POOLS17", "category": "Steel Fixer", "workers": 5,
                 "remarks": ""},
                {"task": "Material unloading (dhoni)", "location": "Jetty",
                 "project": "", "category": "Labourer", "workers": 6,
                 "remarks": "General"}]},
            }, who="eng")
        self.act(dma["ref"], "issue", "pm")
        self.stdout.write(f"  {dma['ref']} issued (DMA)")

    def inspections(self):
        ir = self.post("/api/v1/documents", {
            "doc_type": "IR", "site_id": self.site.id,
            "project_id": self.project.id,
            "payload": {"discipline": "Civil", "location": "Pool 3",
                        "requested_date": (self.today + timedelta(days=2))
                        .isoformat(), "requested_time": "10:00",
                        "work_description": "Pool 3 wall reinforcement — "
                        "pre-concrete inspection",
                        "work_after": "Wall concreting", "ref_drawings":
                        "ST-204, ST-205", "enclosed": True}}, who="eng")
        self.act(ir["ref"], "submit", "eng")
        self.act(ir["ref"], "approve", "pm")
        self.act(ir["ref"], "issue", "eng")
        self.act(ir["ref"], "record-result", "eng", result="APPROVED",
                 reviewed_by="J. Perera", position="Resident Engineer",
                 comment="Approved to proceed with concreting.")
        self.stdout.write(f"  {ir['ref']} issued + approved")

        mar = self.post("/api/v1/documents", {
            "doc_type": "MAR", "site_id": self.site.id,
            "project_id": self.project.id,
            "payload": {"material_description":
                        "Porcelain pool tile 600x600 anti-slip, Grade A",
                        "manufacturer": "RAK Ceramics", "origin": "UAE",
                        "spec_ref": "Finishes spec §4.2",
                        "enclosures": {"sample": True, "catalogue": True},
                        "confirms_spec": True}}, who="eng")
        self.act(mar["ref"], "submit", "eng")
        self.act(mar["ref"], "approve", "pm")
        self.act(mar["ref"], "issue", "eng")
        self.act(mar["ref"], "record-result", "eng", result="APPROVED",
                 reviewed_by="J. Perera", position="Resident Engineer")
        self.stdout.write(f"  {mar['ref']} issued + approved")

    # -- procurement chain ----------------------------------------------

    def procurement_chain(self):
        cement = self.items["Cement OPC 50kg bag"]
        rebar = self.items["Rebar B500 12mm"]
        block = self.items["Hollow block 8\" "]
        mr = self.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id,
            "payload": {"planned_loading": "August hired boat",
                        "trades_covered": "Civil — Pools 1-6",
                        "required_by": "2026-08-01", "stock_attested": True},
            "lines": [
                {"item_id": cement.id, "qty_required": 400, "qty_stock": 120,
                 "qty_to_order": 280, "priority": "NORMAL", "remarks": "Civil"},
                {"item_id": rebar.id, "qty_required": 6000, "qty_stock": 500,
                 "qty_to_order": 5500, "priority": "NORMAL", "remarks": "Civil"},
                {"item_id": block.id, "qty_required": 2500, "qty_stock": 0,
                 "qty_to_order": 2500, "priority": "URGENT",
                 "urgent_reason": "Blockwork starts next boat", "remarks": ""},
            ]}, who="storekeeper")
        self.act(mr["ref"], "submit", "storekeeper")
        self.act(mr["ref"], "approve", "pm")
        self.act(mr["ref"], "send", "storekeeper")
        self.stdout.write(f"  {mr['ref']} sent to HO")

        materials = CostHead.objects.get(name="Materials")
        pr = self.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "mr_refs": [mr["ref"]],
            "payload": {"requested_delivery": "2026-07-25"},
            "lines": [
                {"free_text_desc": "Alia Building Supplies", "vendor":
                 "Alia Building Supplies", "quotation_ref": "QT-4411",
                 "payment_terms": "COD", "purchase_type": "CASH",
                 "cost_head_id": materials.id, "amount_cash": 96500,
                 "amount_credit": 0},
                {"free_text_desc": "Male' Hardware Pvt Ltd", "vendor":
                 "Male' Hardware Pvt Ltd", "quotation_ref": "QT-8820",
                 "payment_terms": "30 days", "purchase_type": "CREDIT",
                 "cost_head_id": materials.id, "amount_cash": 0,
                 "amount_credit": 142000},
            ]}, who="purchasing")
        self.act(pr["ref"], "submit", "purchasing")
        self.act(pr["ref"], "approve", "director")
        self._authorise_via_voucher(pr["ref"])
        # Finance records the cash vendor payment (issues the PO / slip).
        self.as_("finance")
        line_cash = pr["lines"][0]["id"]
        self.client.post(f"/api/v1/pr/{pr['ref']}/vendor-payment",
                         {"line_id": line_cash, "payment_ref": "TRF-30021"})
        self.stdout.write(f"  {pr['ref']} approved + authorised (voucher)")

        # Loading manifest off the MR, then a GRN at the receiving site.
        lm = self.post("/api/v1/documents", {
            "doc_type": "LM", "site_id": self.site.id, "mr_refs": [mr["ref"]],
            "pr_refs": [pr["ref"]],
            "payload": {"vessel": "MV Dhoni 7", "departure_point": "Male'",
                        "expected_arrival": "2026-07-20"},
            "lines": [
                {"item_id": cement.id, "qty_loaded": 280, "qty_pending": 0},
                {"item_id": rebar.id, "qty_loaded": 4000, "qty_pending": 1500},
                {"item_id": block.id, "qty_loaded": 2500, "qty_pending": 0},
            ]}, who="purchasing")
        self.act(lm["ref"], "depart", "purchasing")
        self.stdout.write(f"  {lm['ref']} departed (pending items logged)")

        grn = self.post("/api/v1/documents", {
            "doc_type": "GRN", "site_id": self.site.id, "lm_ref": lm["ref"]},
            who="storekeeper")
        self.as_("storekeeper")
        self.client.patch(f"/api/v1/documents/{grn['ref']}", {"lines": [
            {"item_id": cement.id, "qty_manifest": 280, "qty_received": 280},
            {"item_id": rebar.id, "qty_manifest": 4000, "qty_received": 3960,
             "remarks": "40kg short — coil damaged"},
            {"item_id": block.id, "qty_manifest": 2500, "qty_received": 2500},
        ]}, format="json")
        self.act(grn["ref"], "count", "storekeeper")
        self.act(grn["ref"], "verify", "pm")
        self.stdout.write(f"  {grn['ref']} counted + verified")

    def payment_request(self):
        transport = CostHead.objects.get(name="Transport & Freight")
        pyr = self.post("/api/v1/documents", {
            "doc_type": "PYR", "site_id": self.site.id, "payload": {},
            "cost_head_id": transport.id, "payee": "Island Boat Services",
            "payment_type": "DIRECT", "payment_method": "BANK",
            "payee_account": "7770000012345 (BML)",
            "amount_requested": 24500, "required_by": "2026-07-18",
            "purpose": "Boat hire for July materials loading (Male'-Medhufaru)",
            "has_supporting_doc": True}, who="storekeeper")
        self.act(pyr["ref"], "submit", "storekeeper")
        self.act(pyr["ref"], "approve", "pm")
        self.act(pyr["ref"], "approve", "director")
        self._authorise_via_voucher(pyr["ref"])
        self.act(pyr["ref"], "pay", "finance", amount_paid=24500,
                 payment_ref="TRF-30044")
        self.stdout.write(f"  {pyr['ref']} paid (full chain)")

    def petty_cash(self):
        # Finance opens the imprest float; the storekeeper is custodian.
        self.as_("finance")
        r = self.client.put(f"/api/v1/petty-cash/{self.site.id}", {
            "imprest_amount": 20000, "custodian_id":
            self.users["storekeeper"].id, "trigger_pct": 30,
            "per_txn_cap": 1500}, format="json")
        if r.status_code != 200:
            raise CommandError(f"petty-cash float: {r.status_code} {r.data}")
        overheads = CostHead.objects.get(name="Site Overheads")
        entries = [("Ferry tickets — crew rotation", 850),
                   ("Drinking water (bulk)", 640),
                   ("Hardware sundries — fixings", 1180),
                   ("Fuel for site generator", 1450)]
        for payee, amount in entries:
            self.as_("storekeeper")
            f = SimpleUploadedFile("receipt.jpg",
                                   _photo_bytes(f"Receipt — {payee}", 2),
                                   content_type="image/jpeg")
            rr = self.client.post(
                f"/api/v1/petty-cash/{self.site.id}/entries",
                {"amount": amount, "cost_head_id": overheads.id,
                 "payee": payee, "purpose": payee, "has_receipt": True,
                 "receipt": f}, format="multipart")
            if rr.status_code not in (200, 201):
                raise CommandError(f"petty entry: {rr.status_code} {rr.data}")
        # PM approves the batch (posts them to Incurred cost).
        self.as_("pm")
        self.client.post(f"/api/v1/petty-cash/{self.site.id}/entries/approve",
                         {}, format="json")
        self.stdout.write(f"  petty cash: float + {len(entries)} approved entries")

    # -- helpers ---------------------------------------------------------

    def _authorise_via_voucher(self, source_ref):
        """Finance batches a Director-approved PR/PYR onto a payment voucher;
        a signatory approves it — the M6d authorisation path."""
        pv = self.post("/api/v1/payment-vouchers", {"source_refs": [source_ref]},
                       who="finance")
        self.as_("finance")
        self.client.post(f"/api/v1/payment-vouchers/{pv['ref']}/actions/submit",
                         {}, format="json")
        self.as_("signatory")
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv['ref']}/actions/approve", {},
            format="json")
        if r.status_code != 200:
            raise CommandError(f"voucher approve: {r.status_code} {r.data}")
        return pv["ref"]


DPR_CAPTIONS = [
    "Pool 3 wall reinforcement in progress",
    "Formwork alignment check — east bank",
    "Concrete pour Pool 2 footing",
    "Material stock — cement store",
]

# A small palette of Sand Planet-ish tones for the placeholder site photos.
_PHOTO_COLORS = [(21, 71, 110), (58, 123, 168), (176, 137, 84), (94, 107, 120),
                 (39, 93, 74), (140, 74, 60)]


def _photo_bytes(caption, idx):
    """A believable placeholder 'site photo' — a solid tone with a caption
    strip — so the DPR's photo grid and petty-cash receipts render as real
    thumbnails instead of blank boxes. Generated in-memory (no binary assets
    committed)."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = 800, 600
    img = Image.new("RGB", (w, h), _PHOTO_COLORS[idx % len(_PHOTO_COLORS)])
    d = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("arialbd.ttf", 34)
        small = ImageFont.truetype("arial.ttf", 26)
    except Exception:  # noqa: BLE001 — fall back to the bundled bitmap font
        big = small = ImageFont.load_default()
    d.text((40, 40), "SITE PHOTO", font=big, fill=(255, 255, 255))
    d.rectangle([(0, h - 90), (w, h)], fill=(0, 0, 0))
    d.text((40, h - 66), caption, font=small, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()
