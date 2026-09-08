"""RFIs and site visits on a tender (owner 2026-09-08).

The RFI trail is what explains why a price moved between revisions; the visit
notes are half of what the price rested on and lived only in the estimator's
head.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0222_boq_owner"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TenderSiteVisit",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                                           primary_key=True, serialize=False,
                                           verbose_name="ID")),
                ("visited_on", models.DateField()),
                ("attendees", models.TextField(blank=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tender", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="visits", to="core.tender")),
            ],
            options={"ordering": ["-visited_on", "-id"]},
        ),
        migrations.CreateModel(
            name="TenderRfi",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                                           primary_key=True, serialize=False,
                                           verbose_name="ID")),
                ("number", models.PositiveIntegerField()),
                ("question", models.TextField()),
                ("raised_on", models.DateField()),
                ("answer", models.TextField(blank=True)),
                ("answered_on", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tender", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="rfis", to="core.tender")),
            ],
            options={"ordering": ["number"]},
        ),
        migrations.AddConstraint(
            model_name="tenderrfi",
            constraint=models.UniqueConstraint(
                fields=("tender", "number"), name="uniq_tender_rfi_number"),
        ),
    ]
