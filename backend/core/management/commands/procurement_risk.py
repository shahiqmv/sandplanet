"""Procurement Schedule late-risk alerts.

Daily (default): fire a PM + Purchasing alert (Director too when a line is LATE)
the first time each operational line escalates into at-risk / late.
Weekly (--digest): send each Director one digest of all late / at-risk lines
across every project.

Cron (prod):
  docker compose -f docker-compose.prod.yml exec web \
    python manage.py procurement_risk            # daily
  docker compose -f docker-compose.prod.yml exec web \
    python manage.py procurement_risk --digest   # weekly (e.g. Monday 07:00)
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Procurement Schedule late-risk alerts (daily) and the weekly PD "
            "digest (--digest).")

    def add_arguments(self, parser):
        parser.add_argument(
            "--digest", action="store_true",
            help="Send the PD digest instead of per-line escalation alerts.")

    def handle(self, *args, **opts):
        from core import procurement_pipeline as pp
        if opts["digest"]:
            n = pp.send_pd_digest()
            self.stdout.write(self.style.SUCCESS(
                f"PD procurement digest sent to {n} director(s)."))
        else:
            n = pp.sweep_risk_alerts()
            self.stdout.write(self.style.SUCCESS(
                f"{n} procurement risk alert(s) fired."))
