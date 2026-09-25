"""Daily sweep: vehicle document expiry alerts (registration, insurance,
roadworthiness, permits) at 30 and 7 days and when overdue."""
from django.core.management.base import BaseCommand

from core import fleet


class Command(BaseCommand):
    help = "Fire vehicle document expiry alerts (run daily)."

    def handle(self, *args, **options):
        if not fleet.enabled():
            self.stdout.write("Rental module off — nothing to sweep.")
            return
        fired = fleet.sweep_expiry()
        self.stdout.write(f"Fleet expiry sweep: {fired} alert(s) fired.")
