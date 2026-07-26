"""Daily countdown alerts for onboarding cases — the medical deadline and the
business-visa expiry (the module's headline risk: a lapsed BV = an illegal
worker) — plus a stale-case digest for HR. Run from cron on the droplet:

    docker compose -f docker-compose.prod.yml exec web \
        python manage.py onboarding_clocks

Idempotent: each threshold (medical T-7/T-3/overdue; BV T-14/7/3/overdue) fires
once per case, the last level sent recorded on the case, so re-runs never
repeat. T-3 and overdue escalate to the Director. Safe to run daily.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Fire onboarding medical / business-visa countdown alerts."

    def handle(self, *args, **opts):
        from core import onboarding as ob

        res = ob.run_clocks()
        self.stdout.write(self.style.SUCCESS(
            f"Medical alerts {res['medical']}, BV alerts {res['bv']}, "
            f"stale {res['stale']} "
            f"(digest {'sent' if res['digest_sent'] else 'skipped'})."))
