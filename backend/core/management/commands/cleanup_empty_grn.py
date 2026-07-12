"""Delete empty draft GRNs left behind by the old "click GRN → new ref"
behaviour (before creation was deferred until save).

Only removes a GRN that is genuinely abandoned: status DRAFT, not void, with
no line rows on any revision, no document links, and no stock movements. Run
with --dry-run first to see what would go.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Document, StockMovement


class Command(BaseCommand):
    help = "Delete abandoned empty draft GRNs (no lines, no links, no stock)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="List what would be deleted, delete nothing.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        grns = (Document.objects.filter(doc_type="GRN", status="DRAFT",
                                        is_void=False)
                .prefetch_related("revisions__lines"))
        victims = []
        for doc in grns:
            has_lines = any(r.lines.exists() for r in doc.revisions.all())
            if has_lines:
                continue
            if doc.links_from.exists() or doc.links_to.exists():
                continue
            if StockMovement.objects.filter(document=doc).exists():
                continue
            victims.append(doc)

        if not victims:
            self.stdout.write("No empty draft GRNs found.")
            return

        for doc in victims:
            self.stdout.write(f"  {doc.ref}  (site {doc.site_id}, "
                              f"{doc.created_at:%Y-%m-%d})")
        if dry:
            self.stdout.write(self.style.WARNING(
                f"[dry-run] Would delete {len(victims)} empty draft GRN(s)."))
            return

        with transaction.atomic():
            for doc in victims:
                # current_revision FK is PROTECT — detach before deleting revs
                Document.objects.filter(pk=doc.pk).update(current_revision=None)
                doc.revisions.all().delete()
                doc.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {len(victims)} empty draft GRN(s)."))
