"""The tenders & offers register (owner 2026-09-08).

Phase 1: the record, its revisions and its outcome. The BOQ does not move
here — that is the next phase, when `Boq.project` becomes nullable and a BOQ
can be owned by a tender until an award hands it to the project.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("core", "0220_costhead_code_overhead")]

    operations = [
        migrations.CreateModel(
            name="Tender",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                                           primary_key=True, serialize=False,
                                           verbose_name="ID")),
                ("client_name", models.CharField(max_length=160)),
                ("client_contact", models.TextField(blank=True)),
                ("title", models.TextField()),
                ("scope", models.TextField(blank=True)),
                ("enquiry_date", models.DateField(blank=True, null=True)),
                ("due_date", models.DateField(blank=True, null=True)),
                ("our_format", models.BooleanField(default=True)),
                ("currency", models.CharField(default="USD", max_length=3)),
                ("value_submitted", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=14, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("outcome_date", models.DateField(blank=True, null=True)),
                ("outcome_ref", models.CharField(blank=True, max_length=60)),
                ("value_awarded", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=14, null=True)),
                ("lost_reason", models.TextField(blank=True)),
                ("lost_to", models.CharField(blank=True, max_length=160)),
                ("document", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="tender", to="core.document")),
                ("awarded_project", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="won_from", to="core.project")),
            ],
            options={"ordering": ["-id"]},
        ),
    ]
