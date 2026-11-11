from django.db import migrations, models
import django.db.models.deletion

HEADS = [("CURRENCY_EXCHANGE", "Currency exchange", 910),
         ("GST_SETTLEMENT", "GST & taxes paid", 911),
         ("PRIOR_PERIOD", "Prior-period creditors", 912)]


def seed_heads(apps, schema_editor):
    """Pool heads for money that is nobody's cost (owner 2026-11-10). Code
    reaches for them by code; the names are the owner's to change."""
    CostHead = apps.get_model("core", "CostHead")
    for code, name, order in HEADS:
        if CostHead.objects.filter(code=code).exists():
            continue
        named = CostHead.objects.filter(name__iexact=name).first()
        if named:
            named.code, named.is_system, named.is_pool = code, True, True
            named.save(update_fields=["code", "is_system", "is_pool"])
            continue
        CostHead.objects.create(code=code, name=name, sort_order=order,
                                is_system=True, is_pool=True)


def unseed(apps, schema_editor):
    CostHead = apps.get_model("core", "CostHead")
    CostHead.objects.filter(code__in=[c for c, _, _ in HEADS],
                            postings__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0303_report_analysis")]
    operations = [
        migrations.AddField(
            model_name="paymentrequest", name="booking",
            field=models.CharField(
                choices=[("COST", "Cost"),
                         ("CURRENCY_EXCHANGE", "Currency exchange"),
                         ("GST_SETTLEMENT", "GST / tax payment"),
                         ("PRIOR_PERIOD", "Prior-period creditor"),
                         ("PAYABLE_SETTLEMENT", "Settles payables")],
                default="COST", max_length=20)),
        migrations.AddField(
            model_name="payable", name="settled_by_request",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="settled_payables", to="core.document")),
        migrations.RunPython(seed_heads, unseed),
    ]
