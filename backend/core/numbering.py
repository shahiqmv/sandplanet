from django.db import IntegrityError, transaction

from .models import DocCounter

# Global numbering, no site code (§4.1, R2). PV = Payment Voucher (M6d),
# an HO instrument batching requisitions from many sites.
# IPR/IRN global per §5.10 / D5
GLOBAL_TYPES = {"PR", "LM", "PO", "PV", "IPR", "IRN", "SIN", "LOA", "SPL", "AC",
                "IM30", "SHP"}
# Trading series (TRADING_BUILD_BRIEF.md §7): company-wide, no site, the
# year in the number and a running number that restarts each year —
# 2026-IN-001 inquiry, 2026-SQ-001 quotation, 2026-SO-001 sales order,
# 2026-DN-001 delivery note, 2026-CN-001 credit note (owner 2026-09-25,
# after the old 2026/SO/665 form: dashes, because a slash cannot be a file
# name). Tax invoices continue the company's INV-YYYY-NNNN series.
TRADING_CODES = ("IN", "SQ", "SO", "DN", "CN",
                 "RA")                            # rental agreement (MARINE brief §4)


def next_trading_ref(code, year=None):
    """Gap-free per code per year, row-locked like every other counter."""
    from django.utils import timezone
    assert code in TRADING_CODES, code
    year = year or timezone.now().year
    key = f"T{code}{year}"                          # its own counter row
    try:
        with transaction.atomic():
            DocCounter.objects.get_or_create(doc_type=key, site=None)
    except IntegrityError:
        pass
    counter = DocCounter.objects.select_for_update().get(doc_type=key, site=None)
    counter.last_no += 1
    counter.save(update_fields=["last_no"])
    return f"{year}-{code}-{counter.last_no:03d}"


def next_ref(doc_type, site):
    """Issue the next gap-free number for this counter.

    Must be called inside the same transaction that creates the document row,
    so a failed create rolls the counter back — numbers are sequential with
    no gaps and no reuse (spec §4.1). The counter row is locked FOR UPDATE
    for the rest of the transaction, serializing concurrent issuers.
    """
    counter_site = None if doc_type in GLOBAL_TYPES else site
    try:
        with transaction.atomic():
            DocCounter.objects.get_or_create(doc_type=doc_type, site=counter_site)
    except IntegrityError:
        pass  # concurrent creator won the race; the row exists now
    counter = (
        DocCounter.objects.select_for_update()
        .get(doc_type=doc_type, site=counter_site)
    )
    counter.last_no += 1
    counter.save(update_fields=["last_no"])
    if counter_site is None:
        return f"{doc_type}-{counter.last_no:03d}"
    return f"{doc_type}-{site.code}-{counter.last_no:03d}"
