"""Site visits and tender meetings are one thing, and a price needs clearing.

TWO CHANGES.

A site visit and a tender meeting are the same shape: arranged for a date with
a team going, then written up afterwards with notes and photos. The old model
invented a request-and-wait step that does not exist in the process, and had
no place for who attended from the client — which is most of what makes a
meeting worth recording (owner 2026-09-09).

And the offer's status gains the approval chain: the Director reviews the
price, a signatory clears it, and only then may it go to the client. That is
statuses only; the transitions live on the model.

Nothing was stored in the visit table on production, so this restructures
rather than migrates.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("core", "0226_tender_proposal_terms")]

    operations = [
        migrations.RenameModel(old_name="TenderSiteVisit",
                               new_name="TenderEvent"),
        migrations.RenameField(model_name="attachment",
                               old_name="tender_visit",
                               new_name="tender_event"),
        migrations.RenameField(model_name="tenderevent",
                               old_name="visited_on", new_name="held_on"),
        migrations.RenameField(model_name="tenderevent",
                               old_name="requested_on",
                               new_name="scheduled_on"),
        migrations.AlterField(
            model_name="tenderevent", name="scheduled_on",
            field=models.DateField()),
        migrations.AddField(
            model_name="tenderevent", name="kind",
            field=models.CharField(
                choices=[("VISIT", "Site visit"),
                         ("MEETING", "Tender meeting")],
                default="VISIT", max_length=8)),
        migrations.AddField(
            model_name="tenderevent", name="client_attendees",
            field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="tenderevent", name="location",
            field=models.CharField(blank=True, max_length=160)),
        migrations.AlterModelOptions(
            name="tenderevent",
            options={"ordering": ["-scheduled_on", "-id"]}),
        migrations.AlterField(
            model_name="attachment", name="tender_event",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="photos", to="core.tenderevent")),
    ]
