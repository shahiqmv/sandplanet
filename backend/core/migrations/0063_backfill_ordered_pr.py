"""Backfill ordered_pr on MR lines for PRs raised before per-line scoping.

Before this feature a PR always answered a whole MR, so treat every live
legacy PR as having taken all of its MR's orderable lines. Without this, those
MRs would look fully un-ordered and wrongly reappear in the "raise a PR" list
(owner 2026-07-15)."""
from django.db import migrations


def backfill(apps, schema_editor):
    DocumentLine = apps.get_model("core", "DocumentLine")
    DocumentLink = apps.get_model("core", "DocumentLink")
    links = (DocumentLink.objects
             .filter(link_type="MR_PR", from_document__doc_type="PR",
                     from_document__is_void=False)
             .exclude(from_document__status__in=["CANCELLED", "REJECTED"])
             .select_related("from_document", "to_document"))
    for link in links:
        pr = link.from_document
        rev_id = link.to_document.current_revision_id
        if not rev_id:
            continue
        for ln in DocumentLine.objects.filter(
                revision_id=rev_id).exclude(fulfil_source="STORE"):
            if ln.ordered_pr_id is None and (
                    ln.qty_to_order is None or ln.qty_to_order > 0):
                ln.ordered_pr_id = pr.id
                ln.save(update_fields=["ordered_pr"])


class Migration(migrations.Migration):
    dependencies = [("core", "0062_documentline_ordered_pr")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
