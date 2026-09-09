"""The tender process as it is actually run (owner 2026-09-09).

The RFI on a tender is replaced by a Tender Query (TQ). It is not an RFI: this
app already uses RFI for the contract-stage request for information and IR for
an inspection request. A TQ is pre-contract, carries SEVERAL numbered
questions on one sheet, is issued to the client under its own reference in our
format, and the answers come back written against each question.

Site visits gain the request date and lose their required visit date — a visit
asked for and not yet held is a reason pricing has not started — and carry
photos. A tender gains the QS who is carrying it.

Neither the RFI table nor the visit table held a single row on production, so
this restructures rather than migrates.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import core.models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0224_tender_attachment_kinds"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="tenderrfi", name="uniq_tender_rfi_number"),
        migrations.DeleteModel(name="TenderRfi"),
        migrations.AddField(
            model_name="tender", name="assigned_to",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tenders", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="tendersitevisit", name="requested_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="tendersitevisit", name="visited_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterModelOptions(
            name="tendersitevisit",
            options={"ordering": ["-visited_on", "-requested_on", "-id"]},
        ),
        migrations.AddField(
            model_name="attachment", name="tender_visit",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="photos", to="core.tendersitevisit"),
        ),
        migrations.AlterField(
            model_name="attachment", name="kind",
            field=models.CharField(
                choices=core.models.Attachment.KINDS, max_length=20),
        ),
        migrations.CreateModel(
            name="TenderQuery",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                                           primary_key=True, serialize=False,
                                           verbose_name="ID")),
                ("number", models.PositiveIntegerField()),
                ("subject", models.CharField(blank=True, max_length=200)),
                ("raised_on", models.DateField()),
                ("issued_at", models.DateTimeField(blank=True, null=True)),
                ("responded_on", models.DateField(blank=True, null=True)),
                ("client_ref", models.CharField(blank=True, max_length=60)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tender", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="queries", to="core.tender")),
            ],
            options={"ordering": ["number"]},
        ),
        migrations.CreateModel(
            name="TenderQueryItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                                           primary_key=True, serialize=False,
                                           verbose_name="ID")),
                ("number", models.PositiveIntegerField()),
                ("question", models.TextField()),
                ("reference", models.CharField(blank=True, max_length=160)),
                ("answer", models.TextField(blank=True)),
                ("answered_on", models.DateField(blank=True, null=True)),
                ("query", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="items", to="core.tenderquery")),
            ],
            options={"ordering": ["number"]},
        ),
        migrations.AddConstraint(
            model_name="tenderquery",
            constraint=models.UniqueConstraint(
                fields=("tender", "number"), name="uniq_tender_query_number"),
        ),
        migrations.AddConstraint(
            model_name="tenderqueryitem",
            constraint=models.UniqueConstraint(
                fields=("query", "number"),
                name="uniq_tender_query_item_number"),
        ),
    ]
