"""A tender can carry several provisional sums, and a lump-sum discount.

The single `provisional_sum` figure is fine for one allowance and wrong the
moment there are two — a client asking for provisional sums against three
separate items got them added together under one unexplained line. Every
figure already entered becomes a row, so nothing is lost and no offer's total
moves; only then is the column dropped.
"""
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


def carry_provisional_sums(apps, schema_editor):
    Tender = apps.get_model("core", "Tender")
    Item = apps.get_model("core", "TenderProvisionalItem")
    made = 0
    for t in Tender.objects.exclude(provisional_sum=None).exclude(
            provisional_sum=Decimal("0")):
        Item.objects.create(tender=t, sort_order=0, label="Provisional sum",
                            amount=t.provisional_sum)
        made += 1
    if made:
        print(f"  carried {made} provisional sum(s) onto their own line")


def back_to_one_figure(apps, schema_editor):
    """Reversing puts the total back on the tender — it cannot restore the
    breakdown, which is the point of going forward."""
    from django.db.models import Sum
    Tender = apps.get_model("core", "Tender")
    Item = apps.get_model("core", "TenderProvisionalItem")
    for t in Tender.objects.all():
        total = Item.objects.filter(tender=t).aggregate(
            s=Sum("amount"))["s"]
        if total:
            t.provisional_sum = total
            t.save(update_fields=["provisional_sum"])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0229_payroll_bank_payables'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenderProvisionalItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('sort_order', models.IntegerField(default=0)),
                ('label', models.CharField(max_length=160)),
                ('amount', models.DecimalField(decimal_places=2,
                                               default=Decimal('0'),
                                               max_digits=14)),
                ('tender', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='provisional_items', to='core.tender')),
            ],
            options={'ordering': ['sort_order', 'id']},
        ),
        # carried BEFORE the column goes, or every figure already entered is
        # silently lost
        migrations.RunPython(carry_provisional_sums, back_to_one_figure),
        migrations.RemoveField(
            model_name='tender',
            name='provisional_sum',
        ),
        migrations.AddField(
            model_name='tender',
            name='discount_amount',
            field=models.DecimalField(blank=True, decimal_places=2,
                                      max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='tender',
            name='discount_label',
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
