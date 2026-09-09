"""GST on subcontract agreements (owner 2026-09-09).

A GST-registered subcontractor charges it on every certificate, and it is
recoverable input tax to us — the same treatment a local purchase already
gets. Nothing was computing it.

Default 0 so every existing agreement is unchanged: most gangs are not
registered, and the four already on the system carry no GST.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("core", "0227_tender_events_and_gate")]

    operations = [
        migrations.AddField(
            model_name="subcontractagreement", name="gst_percent",
            field=models.DecimalField(decimal_places=2, default=0,
                                      max_digits=5)),
        migrations.AddField(
            model_name="subcontractor", name="gst_registered",
            field=models.BooleanField(default=False)),
    ]
