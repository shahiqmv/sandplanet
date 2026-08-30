"""Seed PSC-SFR-004 (Soneva Fushi — Casual Accommodation) from the PM's
manually-prepared procurement schedule.

A one-off data load, kept as a command rather than a pasted shell snippet so
it is reviewable, repeatable and idempotent: it keys on (section code, s_no)
and updates rather than duplicating, so running it twice does not double the
schedule. The source is the PM's own PDF — the same document the schedule
module was evaluated against — so it doubles as the worked example new users
are pointed at (owner 2026-08-30).

Deliberately NOT set: order_by_date. The date to order by is manual (owner
2026-08-09) because production, shipping and clearance all move with the
product, the season and whatever the shipping lanes are doing. Leaving it
empty is the point — the planner shows its suggestion from the three legs
and a human commits to a date.

    manage.py seed_sfr_casual_schedule --dry-run
    manage.py seed_sfr_casual_schedule
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import ProcurementSchedule, ScheduleLine, ScheduleSection

REF = "PSC-SFR-004"

# (code, title, [(s_no, description, make, country, spec, mfg, ship, clear,
#                 required_date)])
# Lead times and dates exactly as the PM wrote them; dates read D-M-Y, which
# the source is consistent about (25-10, 15-12 fix the order).
DATA = [
    ("A", "Civil Work", [
        (1, "Timber", "Pine", "South Africa", "FF&E",
         35, 30, 10, date(2026, 11, 1)),
    ]),
    ("B", "Electrical", [
        (1, "Panel Board", "Hager / Schneider / Orange", "India",
         "Consider all MCBs to be of ZHLS grade.\nAll shall be IP 65",
         7, 10, 10, date(2026, 10, 5)),
        (2, "Distribution Board", "Hager / Schneider / Orange", "India",
         "Consider all MCBs to be of ZHLS grade.\nAll shall be IP 65",
         7, 10, 10, date(2026, 10, 5)),
        (3, "Switch & Socket", "Orange", "Sri Lanka", "",
         7, 10, 10, date(2026, 10, 5)),
        (4, "Technical Light Fixtures",
         "Philips / Osram / Locally procured", "Thailand / Singapore",
         "IP65/68 (watt / lux / K value)",
         25, 30, 10, date(2026, 11, 1)),
        (5, "Decorative Light Fixtures", "FF&E", "Thailand", "",
         25, 30, 10, date(2026, 10, 5)),
    ]),
    ("C", "Plumbing & Sanitary Fittings", [
        (1, "Hot Water Circulating Pump", "Grundfos-Rotex UPSO15-65",
         "India", "", 25, 30, 10, date(2026, 11, 1)),
        (2, "Sanitary Fixtures", "COCO", "China / Locally procured", "",
         25, 30, 10, date(2026, 10, 25)),
    ]),
    ("D", "HVAC", [
        # "Spilt" in the source; corrected, since this load is also the
        # worked example new users are shown.
        (1, "Split AC Unit", "Daikin", "Thailand / Singapore", "",
         25, 30, 10, date(2026, 11, 1)),
        (2, "Hot Water Boiler",
         "Rheem / Racold / AO Smith Model: 85V80-1 / Daikin",
         "India / Thailand / Singapore", "",
         25, 30, 10, date(2026, 11, 1)),
    ]),
    ("E", "Fire Alarm & Fire Fighting", [
        (1, "Detectors", "Numens", "China", "",
         25, 30, 10, date(2026, 11, 1)),
    ]),
    ("F", "OS&E", [
        (1, "Pocket Coil Heritage Mattress", "XiaYi Trading Co., LTD",
         "China", "", 25, 30, 10, date(2026, 12, 15)),
        (2, "Hotel Luxury Microfiber Sleeping Pillow",
         "XiaYi Trading Co., LTD", "China", "",
         25, 30, 10, date(2026, 12, 15)),
        (3, "Pillowcase", "XiaYi Trading Co., LTD", "China", "",
         25, 30, 10, date(2026, 12, 15)),
        (4, "Single Bedsheet PL Fabric", "XiaYi Trading Co., LTD", "China",
         "", 25, 30, 10, date(2026, 12, 15)),
        (5, "Bath Towel PL Fabric — 600 Gms", "XiaYi Trading Co., LTD",
         "China", "", 25, 30, 10, date(2026, 12, 15)),
    ]),
]

# The lines already on the schedule came from the BOM seed: local structural
# materials with no section, which would render as an unlabelled block above
# the imported ones. Giving them a section of their own is what makes the
# schedule read as one document.
LOCAL_SECTION = ("G", "Local / Structural Materials")


class Command(BaseCommand):
    help = f"Seed {REF} from the PM's manual procurement schedule."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change, write nothing.")

    @transaction.atomic
    def handle(self, *args, **options):
        dry = options["dry_run"]
        try:
            sched = ProcurementSchedule.objects.select_related(
                "document", "project").get(document__ref=REF)
        except ProcurementSchedule.DoesNotExist:
            self.stderr.write(f"{REF} not found.")
            return

        self.stdout.write(f"{REF} — {sched.project.code} "
                          f"({sched.document.status}), "
                          f"{sched.lines.count()} lines now")

        made = updated = 0
        for order, (code, title, rows) in enumerate(DATA, start=1):
            section, fresh = ScheduleSection.objects.get_or_create(
                schedule=sched, code=code,
                defaults={"title": title, "sort_order": order * 10})
            if not fresh and section.title != title:
                section.title = title
                if not dry:
                    section.save(update_fields=["title"])
            self.stdout.write(f"\n  {code} — {title}"
                              f"{'  (new)' if fresh else ''}")
            for (s_no, desc, make, country, spec,
                 mfg, ship, clear, required) in rows:
                values = {
                    "description": desc, "make_brand": make,
                    "source_country": country, "specification": spec,
                    "category": title, "trade": title,
                    "lead_time_days": mfg, "shipping_days": ship,
                    "clearance_days": clear, "required_date": required,
                }
                line = sched.lines.filter(section=section, s_no=s_no).first()
                if line:
                    for k, v in values.items():
                        setattr(line, k, v)
                    if not dry:
                        line.save(update_fields=list(values))
                    updated += 1
                    mark = "update"
                else:
                    if not dry:
                        ScheduleLine.objects.create(
                            schedule=sched, section=section, s_no=s_no,
                            **values)
                    made += 1
                    mark = "new   "
                total = mfg + ship + clear
                self.stdout.write(
                    f"    {mark} {s_no}. {desc[:38]:<38} "
                    f"{country[:22]:<22} {mfg:>3}+{ship:>3}+{clear:>3}"
                    f" = {total:>3}d  need {required}")

        # Park the BOM-seeded local materials under their own heading.
        # Listed, not a live queryset: counting it after the moves would
        # count the rows that are no longer loose, i.e. always zero.
        loose = list(sched.lines.filter(section__isnull=True).order_by("id"))
        if loose:
            code, title = LOCAL_SECTION
            section, _ = ScheduleSection.objects.get_or_create(
                schedule=sched, code=code,
                defaults={"title": title, "sort_order": 900})
            self.stdout.write(f"\n  {code} — {title}")
            for i, line in enumerate(loose, start=1):
                self.stdout.write(f"    move   {i}. {line.description[:38]}")
                if not dry:
                    line.section = section
                    line.s_no = i
                    line.save(update_fields=["section", "s_no"])

        self.stdout.write(f"\n{made} created, {updated} updated, "
                          f"{len(loose)} moved into {LOCAL_SECTION[0]}.")
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written."))
            transaction.set_rollback(True)
