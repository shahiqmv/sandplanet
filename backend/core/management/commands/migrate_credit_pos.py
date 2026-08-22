"""Move PRs stuck in Finance's voucher queue onto the new order flow.

A credit purchase used to be authorised inside a Finance payment voucher, which
is what generated its purchase orders. Orders are now drafted when the Director
awards the PR and signed by the Signatory on the order itself (owner
2026-08-22), so PRs already sitting at APPROVED have no orders drafted and
nothing to sign.

This drafts them. It does NOT sign anything and posts no cost — the Signatory
still approves each order, which is the whole point of the change. Run with
--apply; without it this is a dry run.
"""
from django.core.management.base import BaseCommand

from core.models import Document, User
from core.procurement import generate_pos_for_pr, pr_cash_total


class Command(BaseCommand):
    help = "Draft credit POs for PRs approved before the order flow changed."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write. Without this it is a dry run.")

    def handle(self, *args, **opts):
        actor = (User.objects.filter(role="ADMIN", is_active=True).first()
                 or User.objects.filter(is_superuser=True).first())
        stuck = Document.objects.filter(
            doc_type="PR", is_void=False,
            status__in=("APPROVED", "PAYMENT_PROCESSING")).order_by("ref")
        drafted = skipped = 0
        for pr in stuck:
            rev = pr.current_revision
            if rev is None:
                continue
            rows = list(rev.lines.all())
            credit_rows = [ln for ln in rows if (ln.amount_credit or 0) > 0]
            missing = [ln for ln in credit_rows if not ln.po_ref.strip()]
            cash = pr_cash_total(pr)
            if not missing:
                skipped += 1
                self.stdout.write(
                    f"  {pr.ref}: {len(credit_rows)} credit row(s), all "
                    f"already ordered — nothing to do"
                    + (f" (cash {cash} still on a voucher)" if cash else ""))
                continue
            self.stdout.write(
                f"  {pr.ref}: drafting orders for {len(missing)} credit "
                f"row(s) — " + ", ".join(ln.vendor or "?" for ln in missing))
            if opts["apply"]:
                created = generate_pos_for_pr(pr, actor)
                for po in created:
                    self.stdout.write(f"      → {po.ref} ({po.status})")
                drafted += len(created)
        self.stdout.write("")
        self.stdout.write(
            f"{stuck.count()} PR(s) examined; {skipped} already ordered.")
        if opts["apply"]:
            self.stdout.write(self.style.SUCCESS(
                f"Drafted {drafted} purchase order(s). They are DRAFT — "
                f"Purchasing sends each one for the Signatory's approval."))
        else:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — nothing written. Re-run with --apply."))
