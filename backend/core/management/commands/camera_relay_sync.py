"""Re-teach the camera relay any camera it has forgotten (owner 2026-10-13).

Run after every deploy and every five minutes by cron: a server reboot or a
relay restart empties the relay's list of pull cameras, and without this
the feeds stay dark until someone notices. Silent when all is in step.
"""
from django.core.management.base import BaseCommand

from core import cameras


class Command(BaseCommand):
    help = "Re-register any camera the relay has lost."

    def handle(self, *args, **options):
        for path, action, ok, msg in cameras.ensure_relay_paths():
            self.stdout.write(f"{path}: {action} — {'ok' if ok else 'FAILED'}"
                              f" ({msg})")
