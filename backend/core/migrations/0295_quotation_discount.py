from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0294_manual_invoice_workflow"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotation", name="discount_percent",
            field=models.DecimalField(blank=True, decimal_places=2,
                                      max_digits=5, null=True)),
        migrations.AddField(
            model_name="quotation", name="discount_amount",
            field=models.DecimalField(blank=True, decimal_places=2,
                                      max_digits=14, null=True)),
    ]
