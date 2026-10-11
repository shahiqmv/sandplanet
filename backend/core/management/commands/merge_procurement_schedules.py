"""One-off: fold every site's per-project procurement schedules into one
schedule per site, grouped project-wise (owner 2026-10-11). Idempotent — a
site with one live schedule is left alone."""
from django.core.management.base import BaseCommand

from core.models import ProcurementSchedule, Site, User
from core.procurement_schedule import merge_site_schedules


class Command(BaseCommand):
    help = "Merge per-project procurement schedules into one per site."

    def add_arguments(self, parser):
        parser.add_argument("--site", help="site code (default: every site)")
        parser.add_argument("--actor", default="admin",
                            help="username recorded on the merge")

    def handle(self, *args, **options):
        actor = User.objects.get(username=options["actor"])
        sites = Site.objects.all()
        if options.get("site"):
            sites = sites.filter(code=options["site"])
        for site in sites.order_by("code"):
            n = ProcurementSchedule.objects.filter(
                site=site, merged_into__isnull=True,
                document__is_void=False).count()
            if n < 2:
                continue
            main, folded = merge_site_schedules(site, actor)
            self.stdout.write(
                f"{site.code}: {', '.join(folded)} folded into "
                f"{main.document.ref} ({main.lines.count()} lines, "
                f"{main.sections.count()} sections, status "
                f"{main.document.status})")
        self.stdout.write("done")
