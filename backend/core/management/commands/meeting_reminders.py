"""Send reminders for upcoming meetings. Run periodically from cron on the
droplet (every ~15 min so the lead time is honoured reasonably closely):

    docker compose -f docker-compose.prod.yml exec web \
        python manage.py meeting_reminders

Idempotent — each meeting reminds once (Meeting.reminded_at), reset on
reschedule, so re-runs never repeat. Lead time is the `meeting_reminder_hours`
company parameter (default 2). Notifications reach the in-app bell + web push.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Notify participants of meetings coming up within the lead window."

    def handle(self, *args, **opts):
        from core import meetings
        n = meetings.send_due_reminders()
        self.stdout.write(f"Sent {n} meeting reminder(s).")
