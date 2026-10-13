"""Convert waiting time-lapse uploads and rebuild each camera's joined reel
(owner 2026-10-13). Run every ten minutes by cron; a lock keeps two runs
from working on the same files. Silent when there is nothing to do."""
import fcntl

from django.core.management.base import BaseCommand

from core import timelapse


class Command(BaseCommand):
    help = "Convert new time-lapse uploads and join them into each reel."

    def handle(self, *args, **options):
        with open("/tmp/timelapse_build.lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return                       # a run is already working
            converted, failed, built = timelapse.build_pending()
            if converted or failed or built:
                self.stdout.write(f"converted {converted}, failed {failed}, "
                                  f"reels rebuilt {built}")
