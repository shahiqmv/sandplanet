"""Replace em dashes in profile copy that a person wrote.

The boilerplate was fixed in migration 0170, but project summaries are the
owner's own words and a migration has no business rewriting those silently.
This does it explicitly, shows every change first, and can be re-run as new
entries are added.

    python manage.py profile_strip_em_dashes --dry-run
    python manage.py profile_strip_em_dashes

An em dash between clauses becomes a comma, which reads correctly in every case
seen so far ("the main pool — a complex freeform structure" reads the same with
a comma). A dash used as a range or a bullet would not, so anything that does
not look like a clause break is reported and left alone.
"""
from django.core.management.base import BaseCommand

EM = "—"
FIELDS = {
    "ProfileEntry": ("project_name", "client_display", "summary",
                     "start_label", "start_value"),
    "ProfileCorporateRow": ("label", "value"),
    "ProfileManagement": ("name", "role", "intro"),
    "ProfileReferee": ("name", "role", "org"),
}


def _fix(text):
    """' — ' -> ', '. Returns None when the dash is not a plain clause break."""
    if f" {EM} " not in text:
        return None                      # e.g. "2020—2021", leave it
    return text.replace(f" {EM} ", ", ")


class Command(BaseCommand):
    help = "Replace em dashes in profile content written by a person."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from django.apps import apps as django_apps

        dry = opts["dry_run"]
        changed = skipped = 0
        for model_name, fields in FIELDS.items():
            model = django_apps.get_model("core", model_name)
            for obj in model.objects.all():
                dirty = []
                for f in fields:
                    val = getattr(obj, f) or ""
                    if EM not in val:
                        continue
                    new = _fix(val)
                    if new is None:
                        skipped += 1
                        self.stdout.write(
                            f"  ? {model_name}#{obj.pk}.{f} — dash is not a "
                            f"clause break, left alone: {val[:70]!r}")
                        continue
                    self.stdout.write(f"    {model_name}#{obj.pk}.{f}")
                    self.stdout.write(f"      before: {val[:100]}")
                    self.stdout.write(f"      after : {new[:100]}")
                    setattr(obj, f, new)
                    dirty.append(f)
                if dirty and not dry:
                    obj.save(update_fields=dirty)
                changed += len(dirty)

        verb = "would change" if dry else "changed"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {changed} field(s); {skipped} left alone."))
