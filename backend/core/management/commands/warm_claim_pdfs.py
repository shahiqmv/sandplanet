"""Render, ahead of time, the application PDF of every claim whose content is
frozen and not yet in the PDF cache — so the first person to open it does
not pay the 40-second layout of a 38-page valuation (owner 2026-09-03).

A DRAFT claim still changes and is skipped. Run from cron; idempotent.

    manage.py warm_claim_pdfs [--dry-run]
"""
from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.template.loader import render_to_string

from core import commercial
from core.models import ProgressClaim
from core.pdf_cache import PREFIX, cached_pdf, html_key

FROZEN = ("SUBMITTED", "CERTIFIED", "PAID")


class Command(BaseCommand):
    help = "Pre-render application PDFs for submitted/certified/paid claims."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        rendered = skipped = 0
        for claim in ProgressClaim.objects.filter(
                status__in=FROZEN).select_related("project").order_by("id"):
            html = render_to_string("pdf/claim_ipa.html",
                                    commercial.claim_pdf_context(claim))
            if default_storage.exists(f"{PREFIX}{html_key(html)}.pdf"):
                skipped += 1
                continue
            self.stdout.write(f"  {claim.project.code} {claim.ref} "
                              f"({claim.status}): rendering")
            if not o["dry_run"]:
                cached_pdf(html, warm_only=True)
            rendered += 1
        self.stdout.write(f"{rendered} rendered, {skipped} already cached."
                          + (" DRY RUN." if o["dry_run"] else ""))
