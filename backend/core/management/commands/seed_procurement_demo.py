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

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (Document, Item, ProcurementSchedule, Project,
                         ScheduleLine, User)

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
            existing.document.delete()          # cascades schedule + lines
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

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {ProcurementSchedule.objects.get(document_id=pk).document.ref}"
            f" on {project.code}: {len(LINES)} lines "
            "(late / at-risk / on-track / delivered / client-stale)."))

    def _item(self, spec):
        if not spec.get("code"):
            return None
        item, _ = Item.objects.get_or_create(
            code=spec["code"],
            defaults={"description": spec["desc"], "unit": spec["unit"],
                      "category": spec["cat"], "is_active": True})
        return item

    def _demo_ipr(self, project, actor, today):
        """A minimal authorised IPR document so the Order stage reads 'done'.
        Only its status + ref are surfaced by the pipeline."""
        doc, _ = Document.objects.get_or_create(
            ref="IPR-HO-D01", doc_type="IPR",
            defaults={"site": project.site,
                      "doc_date": today - timedelta(days=20),
                      "status": "AUTHORISED", "created_by": actor})
        return doc
