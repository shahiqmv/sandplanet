"""Attachment kinds for tender documents (owner 2026-09-09).

Choices only — nothing changes in the database. Recorded as a migration so the
model and the migration state stay in step.
"""
from django.db import migrations, models

import core.models


class Migration(migrations.Migration):

    dependencies = [("core", "0223_tender_rfi_visit")]

    operations = [
        migrations.AlterField(
            model_name="attachment", name="kind",
            field=models.CharField(
                choices=core.models.Attachment.KINDS, max_length=20),
        ),
    ]
