"""Move tracked tools out of counted stock onto the tools register.

Tools received while the category tick was off (late July to 1 Oct 2026) were
booked by their GRN as consumable stock. This lists them, and with --apply
creates one register row per unit and takes the same number out of stock.

    python manage.py convert_stock_tools            # list only
    python manage.py convert_stock_tools --apply    # do it
"""
from django.core.management.base import BaseCommand

from core import tools


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **opts):
        rows = tools.stock_to_convert()
        by_site = {}
        for site, item, n, grn in rows:
            by_site.setdefault(site.code, []).append((item.description, n,
                                                      grn.ref if grn else "—"))
        for code in sorted(by_site):
            lines = by_site[code]
            self.stdout.write(f"{code}: {sum(l[1] for l in lines)} units")
            for name, n, ref in lines:
                self.stdout.write(f"    {n:>3} x {name}  (latest {ref})")
        total = sum(r[2] for r in rows)
        self.stdout.write(f"TOTAL {total} units, {len(rows)} lines, "
                          f"{len(by_site)} sites")
        if not opts["apply"]:
            self.stdout.write("Listed only — re-run with --apply to move them.")
            return
        from core.models import ToolAsset
        before = ToolAsset.objects.count()
        moved = tools.convert_stock()
        made = ToolAsset.objects.count() - before
        assert made == total == sum(m[2] for m in moved), (made, total)
        assert not tools.stock_to_convert(), "something is still in stock"
        self.stdout.write(self.style.SUCCESS(
            f"Moved {made} units onto the register."))
