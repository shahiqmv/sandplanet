"""A BOQ belongs to a project or to a tender — exactly one.

An offer is priced before there is a project. Rather than give tenders their
own copy of the BOQ tables (which would duplicate capture, save, import, the
Excel template and the AI extraction, and leave two of each to keep in step),
the BOQ itself gains a second possible owner. When a tender is won the BOQ is
handed to the new project rather than copied, so there is never a second
priced bill to disagree with the first (owner 2026-09-08).

Every BOQ that exists today belongs to a project, so the backfill is nothing.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("core", "0221_tender")]

    operations = [
        migrations.AlterField(
            model_name="boq", name="project",
            field=models.OneToOneField(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="boq", to="core.project"),
        ),
        migrations.AddField(
            model_name="boq", name="tender",
            field=models.OneToOneField(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="boq", to="core.tender"),
        ),
        migrations.AlterField(
            model_name="boqimport", name="project",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="boq_imports", to="core.project"),
        ),
        migrations.AddField(
            model_name="boqimport", name="tender",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="boq_imports", to="core.tender"),
        ),
        migrations.AddConstraint(
            model_name="boq",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("project__isnull", False),
                             ("tender__isnull", True))
                    | models.Q(("project__isnull", True),
                               ("tender__isnull", False))),
                name="boq_has_exactly_one_owner"),
        ),
    ]
