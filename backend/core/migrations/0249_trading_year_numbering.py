# Trading refs move from TIN-001 / TQ-001 / TSO-001 / TDN-001 / TSI-001 /
# TCN-001 to the year-based series 2026-IN-001 / 2026-SQ-001 / 2026-SO-001 /
# 2026-DN-001 / 2026-CN-001, and trading tax invoices join the company's
# INV-YYYY-NNNN series (owner 2026-09-25). Existing rows are renumbered in id
# order within their year; the counters are set so the next number follows.
from django.db import migrations


def renumber(apps, schema_editor):
    TradingOrder = apps.get_model("core", "TradingOrder")
    TradingDelivery = apps.get_model("core", "TradingDelivery")
    TradingInvoice = apps.get_model("core", "TradingInvoice")
    TradingCreditNote = apps.get_model("core", "TradingCreditNote")
    DocCounter = apps.get_model("core", "DocCounter")
    ProgressClaim = apps.get_model("core", "ProgressClaim")
    ManualInvoice = apps.get_model("core", "ManualInvoice")

    counters = {}

    def issue(code, year):
        key = (code, year)
        counters[key] = counters.get(key, 0) + 1
        return f"{year}-{code}-{counters[key]:03d}"

    old_to_new = {}
    for o in TradingOrder.objects.order_by("id"):
        if o.ref.startswith("TIN-"):
            year = o.created_at.year
            o.ref = issue("IN", year)
            o.save(update_fields=["ref"])
    for o in TradingOrder.objects.exclude(quote_ref="").order_by("id"):
        if o.quote_ref.startswith("TQ-"):
            first = o.quotations.order_by("id").first()
            year = (first.created_at if first else o.created_at).year
            o.quote_ref = issue("SQ", year)
            o.save(update_fields=["quote_ref"])
    for o in TradingOrder.objects.exclude(so_ref="").order_by("id"):
        if o.so_ref.startswith("TSO-"):
            year = (o.won_at or o.created_at).year
            o.so_ref = issue("SO", year)
            o.save(update_fields=["so_ref"])
    for d in TradingDelivery.objects.order_by("id"):
        if d.ref.startswith("TDN-"):
            old = d.ref
            d.ref = issue("DN", d.delivery_date.year)
            d.save(update_fields=["ref"])
            old_to_new[old] = d.ref
    for inv in TradingInvoice.objects.order_by("id"):
        if inv.ref.startswith("TSI-"):
            prefix = f"INV-{inv.invoice_date.year}-"
            n = (ProgressClaim.objects.filter(invoice_no__startswith=prefix).count()
                 + ManualInvoice.objects.filter(invoice_no__startswith=prefix).count()
                 + TradingInvoice.objects.filter(ref__startswith=prefix).count() + 1)
            while (ProgressClaim.objects.filter(invoice_no=f"{prefix}{n:04d}").exists()
                   or ManualInvoice.objects.filter(invoice_no=f"{prefix}{n:04d}").exists()
                   or TradingInvoice.objects.filter(ref=f"{prefix}{n:04d}").exists()):
                n += 1
            inv.ref = f"{prefix}{n:04d}"
        snap = dict(inv.snapshot or {})
        if snap.get("dn_refs"):
            snap["dn_refs"] = [old_to_new.get(r, r) for r in snap["dn_refs"]]
            for row in snap.get("lines", []):
                if row.get("dn_ref") in old_to_new:
                    row["dn_ref"] = old_to_new[row["dn_ref"]]
        inv.snapshot = snap
        inv.save(update_fields=["ref", "snapshot"])
    for cn in TradingCreditNote.objects.order_by("id"):
        if cn.ref.startswith("TCN-"):
            cn.ref = issue("CN", cn.issued_at.year)
            cn.save(update_fields=["ref"])
    for (code, year), n in counters.items():
        c, _ = DocCounter.objects.get_or_create(doc_type=f"T{code}{year}", site=None)
        if c.last_no < n:
            c.last_no = n
            c.save(update_fields=["last_no"])
    DocCounter.objects.filter(doc_type__in=["TIN", "TQ", "TSO", "TDN", "TSI", "TCN"]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0248_trading_order_terms")]
    operations = [migrations.RunPython(renumber, migrations.RunPython.noop)]
