"""Re-evaluate PR settlement status. A PR that carries a zero-value vendor row
(a captured quotation with nothing awarded — a losing bid) used to be held at
PAYMENT_PROCESSING forever, because that empty row was never "settled". The
settlement rule now treats a zero-value row as already settled; this command
heals PRs that were stranded before the fix. Idempotent — a PR that is already
correct is left untouched.

    python manage.py resettle_prs
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Recompute PR PAYMENT_PROCESSING/PAID_PO_ISSUED status."

    def handle(self, *args, **opts):
        from core.models import Document
        from core.procurement import advance_pr_settlement

        prs = (Document.objects.filter(
            doc_type="PR", is_void=False,
            status__in=["AUTHORISED", "PAYMENT_PROCESSING"])
            .order_by("ref"))

        healed = 0
        for pr in prs:
            if pr.current_revision is None:
                continue
            before = pr.status
            advance_pr_settlement(pr, None)
            pr.refresh_from_db()
            if pr.status != before:
                healed += 1
                self.stdout.write(f"  [ok] {pr.ref}: {before} -> {pr.status}")
                continue
            # still stuck — show which vendor rows are blocking it
            blockers = []
            for ln in pr.current_revision.lines.all():
                net = (ln.amount_cash or 0) + (ln.amount_credit or 0)
                acted = (ln.action_taken or "").strip() or (ln.po_ref or "").strip()
                if net > 0 and not acted:
                    kind = "credit(no PO)" if (ln.amount_credit or 0) > 0 \
                        else "cash(no payment)"
                    blockers.append(
                        f"{ln.vendor or ln.free_text_desc or '?'} "
                        f"[{kind}, net {net}]")
            if blockers:
                self.stdout.write(
                    f"  [.. ] {pr.ref} ({pr.status}) blocked by: "
                    + "; ".join(blockers))

        self.stdout.write(self.style.SUCCESS(
            f"Reviewed {prs.count()} PR(s); advanced {healed}."))
