"""Seed a realistic, signed-off Procurement Schedule on the demo project so the
module can be clicked through without entering anything by hand.

Run against the demo instance only:

    python manage.py seed_procurement_demo --settings=config.settings_demo

Idempotent: skips if the project already has a schedule (use --reset to rebuild
that one schedule). It refuses to touch the live dev db.sqlite3. The workflow
(propose → confirm → sign-off) runs through the real DRF API so approvals,
numbering and audit are genuine; document links, the client-update backdating
and a demo IPR are written via the ORM. Demo logins stay password planet-demo.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (CostHead, Document, ImportOrder, ImportOrderLine, Item,
                         ProcurementSchedule, Project, ScheduleLine,
                         ScheduleLineQuote, Supplier, User)

# BOQ quotes to attach to a few lines (by description): supplier, country,
# quoted value, lead days, recommended?, awarded?
DEMO_QUOTES = {
    "Pool circulation pumps": [
        ("Hydro Systems Co.", "China", "68000", 45, True, False),
        ("Marine Pumps Intl.", "Singapore", "71500", 30, False, False),
    ],
    "Glass mosaic pool tiles": [
        ("Bisazza SpA", "Italy", "91000", 55, True, False),
        ("Mosaico Veneto", "Italy", "88400", 60, False, False),
    ],
    "Pool heat pumps": [
        ("Zodiac GmbH", "Germany", "78200", 50, True, True),   # awarded
        ("PoolTherm Ltd.", "China", "74900", 45, False, False),
    ],
}

# section, description, item(code/unit/category), qty, uom, category, supply,
# required-day-offset, tds, make, supplier, country, value, lead, link, client
LINES = [
    dict(sec=("A", "Pool Plant & Equipment"),
         desc="Pool circulation pumps", code="PMP-CIRC-01", unit="set",
         cat="Pool & Water Features", qty="17", uom="set", supply="CONTRACTOR",
         req=25, tds=True, make="Grundfos NKG",
         supplier="Hydro Systems Co.", country="China", value="68000",
         lead=45),                                    # LATE — unordered
    dict(sec=("A", "Pool Plant & Equipment"),
         desc="Sand media filters", code="FLT-SAND-01", unit="nos",
         cat="Pool & Water Features", qty="17", uom="nos", supply="CONTRACTOR",
         req=140, tds=True, make="AquaPure AP-900",
         supplier="AquaPure Ltd.", country="China", value="42500", lead=40,
         link="mar"),                                 # ON TRACK, TDS done
    dict(sec=("A", "Pool Plant & Equipment"),
         desc="Glass mosaic pool tiles", code="TIL-MOS-01", unit="m²",
         cat="Tile & Stone Finishes", qty="1250", uom="m²", supply="CONTRACTOR",
         req=100, tds=False, make="Bisazza Blue",
         supplier="Bisazza SpA", country="Italy", value="91000", lead=55),
                                                       # AT RISK — thin slack
    dict(sec=("A", "Pool Plant & Equipment"),
         desc="Pool heat pumps", code="HP-POOL-01", unit="nos",
         cat="HVAC & MEP", qty="17", uom="nos", supply="CONTRACTOR",
         req=120, tds=False, make="Zodiac Z600",
         supplier="Zodiac GmbH", country="Germany", value="76000", lead=50,
         link="ipr"),                                 # ON TRACK, Order done
    dict(sec=("A", "Pool Plant & Equipment"),
         desc="Chlorine dosing units", code="DOS-CL-01", unit="set",
         cat="Pool & Water Features", qty="17", uom="set", supply="CONTRACTOR",
         req=30, tds=False, make="Grundfos DDA",
         supplier="Reef Controls", country="China", value="33000", lead=30,
         link="grn"),                                 # DELIVERED (shortage)
    dict(sec=("B", "Client-Supplied (by Resort)"),
         desc="Sun loungers & parasols", code="FFE-LNG-01", unit="nos",
         cat="Furniture & Fit-out (FF&E)", qty="340", uom="nos",
         supply="CLIENT", req=60, client_days_ago=32),   # client — STALE
    dict(sec=("B", "Client-Supplied (by Resort)"),
         desc="Pool feature lighting", code="LGT-FEAT-01", unit="nos",
         cat="Lighting", qty="200", uom="nos", supply="CLIENT", req=90,
         client_days_ago=5, client_note="Order confirmed with vendor, "
         "shipping mid-next-month"),                     # client — fresh
]


class Command(BaseCommand):
    help = ("Seed a worked Procurement Schedule on the demo project "
            "(idempotent; --reset rebuilds it).")

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete an existing demo schedule first.")

    def handle(self, *args, **opts):
        name = str(settings.DATABASES["default"]["NAME"])
        if name.endswith("db.sqlite3"):
            raise CommandError(
                "Refusing to seed the live dev db.sqlite3 — run with "
                "--settings=config.settings_demo.")
        project = Project.objects.select_related("site").order_by("id").first()
        if project is None:
            raise CommandError("No project found — run seed / seed_demo first.")
        existing = ProcurementSchedule.objects.filter(project=project).first()
        if existing and opts["reset"]:
            doc = existing.document
            existing.lines.all().delete()       # lines before their sections
            existing.sections.all().delete()
            existing.delete()                   # then the schedule itself
            doc.approvals.all().delete()        # PROTECT — clear before doc
            doc.current_revision = None
            doc.save(update_fields=["current_revision"])
            doc.revisions.all().delete()        # PROTECT — clear before doc
            doc.delete()
            existing = None
        if existing:
            self.stdout.write(self.style.WARNING(
                f"{project.code} already has {existing.document.ref}; "
                "nothing to do (use --reset to rebuild)."))
            return

        users = {u.role: u for u in User.objects.all()}
        admin = users.get("ADMIN")
        purchasing = users.get("HO_PURCHASING")
        director = users.get("DIRECTOR")
        if not (admin and purchasing and director):
            raise CommandError("Demo users missing — run seed_demo first.")
        today = timezone.localdate()
        api = APIClient()

        # --- propose the lines (admin is a proposer, sees every site) ------
        api.force_authenticate(admin)
        pk = api.post(
            f"/api/v1/projects/{project.id}/procurement-schedule").data["id"]
        for spec in LINES:
            item = self._item(spec)
            body = {"description": spec["desc"], "section_code": spec["sec"][0],
                    "section_title": spec["sec"][1], "supply_by": spec["supply"],
                    "category": spec["cat"], "quantity": spec["qty"],
                    "uom": spec["uom"], "make_brand": spec.get("make", ""),
                    "tds_required": spec.get("tds", False),
                    "required_date": (today + timedelta(
                        days=spec["req"])).isoformat()}
            if item:
                body["item_id"] = item.id
            r = api.post(f"/api/v1/procurement-schedules/{pk}/lines", body,
                         format="json")
            if r.status_code != 201:
                raise CommandError(f"add line failed: {r.status_code} {r.data}")
        api.post(f"/api/v1/procurement-schedules/{pk}/submit")

        # --- Purchasing confirms the commercial fields --------------------
        api.force_authenticate(purchasing)
        by_desc = {ln["description"]: ln["id"] for ln in
                   api.get(f"/api/v1/procurement-schedules/{pk}").data["lines"]}
        for spec in LINES:
            if spec["supply"] == "CLIENT":
                continue
            api.patch(f"/api/v1/procurement-schedule-lines/{by_desc[spec['desc']]}",
                      {"planned_supplier": spec["supplier"],
                       "source_country": spec["country"],
                       "estimated_value": spec["value"], "currency": "USD",
                       "lead_time_days": spec["lead"]}, format="json")
        api.post(f"/api/v1/procurement-schedules/{pk}/action",
                 {"action": "confirm"}, format="json")

        # --- Director signs off the baseline ------------------------------
        api.force_authenticate(director)
        api.post(f"/api/v1/procurement-schedules/{pk}/action",
                 {"action": "sign_off"}, format="json")

        # --- wire the pipeline to real docs + backdate client updates -----
        mar = Document.objects.filter(doc_type="MAR").first()
        grn = Document.objects.filter(doc_type="GRN").first()
        ipr = self._demo_ipr(project, admin, today)
        for spec in LINES:
            line = ScheduleLine.objects.get(pk=by_desc[spec["desc"]])
            link = spec.get("link")
            if link == "mar" and mar:
                line.mar = mar
            elif link == "ipr" and ipr:
                line.ipr = ipr
            elif link == "grn" and grn:
                line.grn = grn
            if spec["supply"] == "CLIENT":
                line.client_last_update = today - timedelta(
                    days=spec["client_days_ago"])
                line.client_update_note = spec.get("client_note", "")
            line.save()

        # BOQ quotes on a few lines (one awarded, to show the full flow)
        for desc, rows in DEMO_QUOTES.items():
            line = ScheduleLine.objects.filter(pk=by_desc.get(desc)).first()
            if not line or line.quotes.exists():
                continue
            for name, country, val, lead, rec, won in rows:
                ScheduleLineQuote.objects.create(
                    line=line, supplier_name=name, country=country,
                    quoted_value=Decimal(val), currency="USD",
                    lead_time_days=lead, is_recommended=rec, is_awarded=won,
                    created_by=admin)
            if any(r[5] for r in rows):
                line.awarded_by = director
                line.awarded_at = timezone.now()
                line.save(update_fields=["awarded_by", "awarded_at"])

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {ProcurementSchedule.objects.get(document_id=pk).document.ref}"
            f" on {project.code}: {len(LINES)} lines "
            "(late / at-risk / on-track / delivered / client-stale), "
            "with BOQ quotes on 3 lines (1 awarded)."))

    def _item(self, spec):
        if not spec.get("code"):
            return None
        item, _ = Item.objects.get_or_create(
            code=spec["code"],
            defaults={"description": spec["desc"], "unit": spec["unit"],
                      "category": spec["cat"], "is_active": True})
        return item

    def _demo_ipr(self, project, actor, today):
        """An authorised IPR document with a matching order line for the heat
        pumps, so the Order stage reads 'done' and the schedule shows the
        ordered value (78,200) beside the estimate (76,000) — over by 2,200."""
        doc, created = Document.objects.get_or_create(
            ref="IPR-HO-D01", doc_type="IPR",
            defaults={"site": project.site,
                      "doc_date": today - timedelta(days=20),
                      "status": "AUTHORISED", "created_by": actor})
        item = Item.objects.filter(code="HP-POOL-01").first()
        if item and not hasattr(doc, "import_order"):
            supplier, _ = Supplier.objects.get_or_create(
                name="Zodiac GmbH",
                defaults={"category": Supplier.Category.values[0],
                          "country": "Germany", "default_currency": "USD"})
            cost_head = (CostHead.objects.filter(name__icontains="import")
                         .first()
                         or CostHead.objects.get_or_create(name="Imports")[0])
            order = ImportOrder.objects.create(
                document=doc, supplier=supplier, order_currency="USD",
                exchange_rate=Decimal("15.42"))
            ImportOrderLine.objects.create(
                order=order, line_no=1, item=item, order_qty=Decimal("17"),
                unit_price=Decimal("4600"), cost_head=cost_head)
        return doc
