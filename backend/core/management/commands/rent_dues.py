"""Raise the rent that has come up. Run daily from cron on the droplet:

    docker compose -f docker-compose.prod.yml exec web \\
        python manage.py rent_dues

For every active rental, each period whose due date is within the rental's
lead days and has no due yet gets one — a payable Finance finds on the
payables list. Running it again raises nothing twice.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Raise rent dues that have come up, as payables."

    def handle(self, *args, **opts):
        from core import rent
        made = rent.raise_dues()
        self.stdout.write(f"Raised {len(made)} rent due(s).")
        for d in made:
            self.stdout.write(
                f"  {d.contract.ref} · {d.period_start} · "
                f"{d.currency} {d.total} · due {d.due_date}")
