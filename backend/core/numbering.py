from django.db import IntegrityError, transaction

from .models import DocCounter

# Global numbering, no site code (§4.1, R2). PV = Payment Voucher (M6d),
# an HO instrument batching requisitions from many sites.
# IPR/IRN global per §5.10 / D5
GLOBAL_TYPES = {"PR", "LM", "PO", "PV", "IPR", "IRN"}


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
