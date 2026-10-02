"""Keep the books in step with Planet: for every posting rule that is
switched on (Finance app → Setup → Posting rules), post what is new,
re-post what changed and reverse what is gone. Run from cron on the droplet:

    docker compose -f docker-compose.prod.yml exec web \\
        python manage.py post_books

Running it again changes nothing — each event has one entry. With no rule
switched on it does nothing at all.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Post Planet's operations to the books for the rules switched on."

    def handle(self, *args, **opts):
        from core import brand, posting
        if not brand.brand(fresh=True)["features"].get("books"):
            self.stdout.write("The books are not switched on here.")
            return
        out = posting.post_enabled()
        if not out:
            self.stdout.write("No posting rule is switched on.")
            return
        for r in out:
            self.stdout.write(
                f"{r['rule']}: posted {r['post']}, reversed {r['reverse']}, "
                f"unchanged {r['same']}, held {len(r['held'])}")
