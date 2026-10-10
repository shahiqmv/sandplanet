"""Daily (evening): the health summary every site owes its PM and the
Director, even when there are no cases (SOP-HR-04 §B.17), and the sweep
that closes an outbreak once no new case has appeared for 14 days."""
from django.core.management.base import BaseCommand

from core import health


class Command(BaseCommand):
    help = "Send the daily worker-health summary; close quiet outbreaks."

    def handle(self, *args, **options):
        closed = health.sweep_alerts()
        sent = health.daily_summary()
        self.stdout.write(f"Health daily: {sent} notification(s) sent, "
                          f"{closed} outbreak alert(s) closed.")
