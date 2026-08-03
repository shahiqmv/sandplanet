"""Daily sweep: bond / insurance policy-expiry renewal reminders.

Fires escalating alerts at 30 and 7 days before expiry, then overdue, to the
project QS + PM (Director from 7 days). Watermarked so it doesn't repeat, and
re-fires if a cover is renewed and later lapses again. Run daily via cron.
"""
from django.core.management.base import BaseCommand

from core import bonds


class Command(BaseCommand):
    help = "Fire bond/insurance policy-expiry renewal reminders (run daily)."

    def handle(self, *args, **options):
        fired = bonds.sweep_bond_expiry()
        self.stdout.write(f"Bond expiry sweep: {fired} reminder(s) fired.")
