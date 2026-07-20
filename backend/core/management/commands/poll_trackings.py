"""Daily backstop for shipment tracking (D40) — webhooks are primary, this
catches anything missed. Run from cron on the droplet:

    docker compose -f docker-compose.prod.yml exec web \
        python manage.py poll_trackings

- Registers PENDING trackings that never got off the ground (provider outage at
  Shipped time, or a key added later).
- Polls ACTIVE trackings whose last event is older than the poll gap.
- Flags ACTIVE trackings with no event for 7 days as stale (alerts Purchasing).
Idempotent — safe to run as often as the ShipsGo rate limit allows.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Register/poll active shipment trackings (webhook backstop)."

    def add_arguments(self, parser):
        parser.add_argument("--gap-hours", type=int, default=24,
                            help="Only poll ACTIVE trackings quiet this long.")

    def handle(self, *args, **opts):
        from core import carriers as csvc, notify, tracking as trk
        from core.models import ShipmentTracking, TrackingEvent

        # Keep the carrier picklist fresh (webhook-independent).
        ok, res = csvc.sync_carriers()
        if ok:
            self.stdout.write(f"Carriers synced: {res}.")
        else:
            notify.notify_carrier_sync_failed(str(res))
            self.stderr.write(f"Carrier sync failed: {res}")

        gap = timezone.now() - timedelta(hours=opts["gap_hours"])
        registered = polled = stale = 0

        for t in ShipmentTracking.objects.filter(
                state=ShipmentTracking.State.PENDING):
            trk.register_tracking(t)
            registered += 1

        active = ShipmentTracking.objects.filter(
            state=ShipmentTracking.State.ACTIVE)
        for t in active:
            ref = t.last_event_at or t.created_at
            if ref and ref > gap:
                continue                     # recently updated — skip
            try:
                snap = trk.get_provider(t.provider).fetch(t)
                trk.ingest_snapshot(t, snap,
                                    source=TrackingEvent.Source.POLL)
                polled += 1
            except Exception as e:           # pragma: no cover - network
                t.last_error = str(e)[:300]
                t.save(update_fields=["last_error", "updated_at"])
            t.last_polled_at = timezone.now()
            t.save(update_fields=["last_polled_at", "updated_at"])
            if trk.is_stale(t):
                notify.notify_tracking_problem(t, "stale")
                stale += 1

        self.stdout.write(self.style.SUCCESS(
            f"Registered {registered}, polled {polled}, stale {stale}."))
