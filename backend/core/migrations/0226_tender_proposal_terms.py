"""What the commercial proposal prints (owner 2026-09-09).

Taken from the owner's own BOQ workbook — the SJR Operation Office bill, R-01
— which is the format these offers already follow: a cover naming the
document, and a summary carrying the bills, the money and the terms the offer
is made on. All of it was retyped in Excel for every tender.
"""
from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("core", "0225_tender_query")]

    operations = [
        migrations.AddField(
            model_name="tender", name="doc_ref",
            field=models.CharField(blank=True, max_length=60)),
        migrations.AddField(
            model_name="tender", name="validity_days",
            field=models.PositiveSmallIntegerField(default=30)),
        migrations.AddField(
            model_name="tender", name="duration_days",
            field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(
            model_name="tender", name="payment_terms",
            field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="tender", name="client_provides",
            field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="tender", name="exclusions",
            field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="tender", name="variations",
            field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="tender", name="warranty_terms",
            field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="tender", name="provisional_sum",
            field=models.DecimalField(blank=True, decimal_places=2,
                                      max_digits=14, null=True)),
        migrations.AddField(
            model_name="tender", name="gst_percent",
            field=models.DecimalField(decimal_places=2, default=Decimal("8"),
                                      max_digits=5)),
        migrations.AddField(
            model_name="tender", name="prepared_by",
            field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(
            model_name="tender", name="reviewed_by",
            field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(
            model_name="tender", name="approved_by",
            field=models.CharField(blank=True, max_length=120)),
    ]
