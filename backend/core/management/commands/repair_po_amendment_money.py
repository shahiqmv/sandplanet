"""Move the money an amendment changed but never posted.

Amendments approved before the money adjustment shipped (2026-08-23) swapped
the revision and nothing else, leaving the payable and the cost ledger on the
superseded figure. PO-036 was approved in that window: its order rose from
183,000 to 187,500 net, and what we owe Sonee stayed at the old number.

Compares the CURRENT revision against the revision the payable was raised on
(the earliest, R0) and posts the difference. Dry run by default; --apply
writes. Refuses a settled payable — that needs a credit note, not a posting.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from core.audit import audit
from core.models import Document, Payable, User
from core.po_amend import revision_total
from core.procurement import _post_pr_line, po_commitment


class Command(BaseCommand):
    help = "Post the money an already-approved PO amendment never moved."

    def add_arguments(self, parser):
        parser.add_argument("--ref", required=True, help="PO reference")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **o):
        actor = (User.objects.filter(role="ADMIN", is_active=True).first()
                 or User.objects.filter(is_superuser=True).first())
        po = Document.objects.filter(ref=o["ref"], doc_type="PO").first()
        if po is None:
            raise CommandError(f"{o['ref']} not found.")
        pr, row, err = po_commitment(po)
        if err:
            raise CommandError(err)
        first = po.revisions.order_by("id").first()
        current = po.current_revision
        was, now = revision_total(first), revision_total(current)
        delta = now - was
        payable = Payable.objects.filter(document=pr,
                                         document_line=row).first()
        self.stdout.write(
            f"  {po.ref}: {first.rev_label} {was} -> {current.rev_label} {now}"
            f"  (net delta {delta})")
        if payable is None:
            raise CommandError("No payable on this order's PR row.")
        if payable.status != "OUTSTANDING":
            raise CommandError(f"The payable is {payable.status} — a change "
                               "now needs a credit note.")
        # What the row currently carries, and what it should carry.
        credit = row.amount_credit or Decimal("0")
        gst = row.gst_amount or Decimal("0")
        rate = (gst / credit) if credit else Decimal("0")
        want_credit = was + delta
        gap = want_credit - credit
        gap_gst = (gap * rate).quantize(Decimal("0.01"))
        self.stdout.write(
            f"     row credit {credit} (+GST {gst}) -> {want_credit} "
            f"(+GST {gst + gap_gst})")
        self.stdout.write(
            f"     payable {payable.amount} -> {payable.amount + gap + gap_gst}")
        if gap == 0:
            self.stdout.write(self.style.SUCCESS(
                "     nothing to move — already in step."))
            return
        if not o["apply"]:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing written. Re-run with --apply."))
            return
        row.amount_credit = credit + gap
        row.gst_amount = gst + gap_gst
        row.save(update_fields=["amount_credit", "gst_amount"])
        _post_pr_line(pr, row, gap, gap_gst, actor)       # append-only delta
        payable.amount = payable.amount + gap + gap_gst
        payable.save(update_fields=["amount"])
        audit("document", po.id, "PO_AMENDMENT_MONEY_REPAIRED", actor=actor,
              detail={"ref": po.ref, "net_delta": str(gap),
                      "gst_delta": str(gap_gst),
                      "payable_now": str(payable.amount),
                      "note": "amendment approved before the adjustment "
                              "shipped"})
        self.stdout.write(self.style.SUCCESS(
            f"\n  Posted {gap} (+GST {gap_gst}); payable now {payable.amount}."))
