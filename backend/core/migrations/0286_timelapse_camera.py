"""Time-lapse cameras on a register (site, project, location); uploads and
reels point at the camera instead of a typed label (owner 2026-10-13)."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def labels_to_cameras(apps, schema_editor):
    Camera = apps.get_model("core", "TimelapseCamera")
    Clip = apps.get_model("core", "SiteTimelapse")
    Reel = apps.get_model("core", "TimelapseReel")
    for model in (Reel, Clip):
        for row in model.objects.all():
            cam, _ = Camera.objects.get_or_create(
                site_id=row.site_id, name=row.camera_label[:80])
            model.objects.filter(pk=row.pk).update(camera=cam)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0285_site_timelapse'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TimelapseCamera',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80)),
                ('location', models.CharField(blank=True, max_length=200)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='core.project')),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='timelapse_cameras', to='core.site')),
            ],
            options={'ordering': ['site__code', 'name']},
        ),
        migrations.AddConstraint(
            model_name='timelapsecamera',
            constraint=models.UniqueConstraint(fields=('site', 'name'), name='uniq_timelapse_camera_name'),
        ),
        migrations.AddField(
            model_name='sitetimelapse', name='camera',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='uploads', to='core.timelapsecamera'),
        ),
        migrations.AddField(
            model_name='timelapsereel', name='camera',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='reel', to='core.timelapsecamera'),
        ),
        migrations.RunPython(labels_to_cameras, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name='timelapsereel', name='uniq_reel_per_camera'),
        migrations.RemoveField(model_name='sitetimelapse', name='camera_label'),
        migrations.RemoveField(model_name='timelapsereel', name='camera_label'),
        migrations.AlterField(
            model_name='sitetimelapse', name='camera',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='uploads', to='core.timelapsecamera'),
        ),
        migrations.AlterField(
            model_name='timelapsereel', name='camera',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='reel', to='core.timelapsecamera'),
        ),
        migrations.AlterModelOptions(
            name='timelapsereel', options={'ordering': ['site__code', 'camera__name']},
        ),
    ]
