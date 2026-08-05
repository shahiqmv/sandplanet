from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0136_alter_document_doc_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientuser",
            name="show_submittals",
            field=models.BooleanField(default=True),
        ),
    ]
