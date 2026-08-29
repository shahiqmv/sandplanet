"""Daily sweep: training and competency expiry reminders.

An expired plant-operator ticket is a man on an excavator he is no longer
certified to drive — an operational risk today, not only a certification one.
Escalating stages at 60 / 30 / 7 days and overdue, watermarked so a reminder
does not repeat daily. Run daily via cron.
"""
from django.core.management.base import BaseCommand

from core import hse


class Command(BaseCommand):
    help = "Fire training/competency expiry reminders (run daily)."

    def handle(self, *args, **options):
        fired = hse.sweep_training_expiry()
        self.stdout.write(f"Training expiry sweep: {fired} reminder(s) fired.")
