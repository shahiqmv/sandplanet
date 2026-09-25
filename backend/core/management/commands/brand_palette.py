"""Apply a named colour palette to this instance's brand parameters.

Sandplanet Marine first went live in Sand Planet's own navy and sky, and
users could not tell the two apps apart at a glance (owner 2026-09-25).
Marine now runs in a sea-teal family: the nav band, buttons, rules and
document bands all shift, the logos stay. Re-runnable; the Company page
Brand section can still fine-tune any token afterwards."""
from django.core.management.base import BaseCommand

from core import brand
from core.models import CompanyParameter

PALETTES = {
    # Sand Planet's own navy / sky — the defaults in core/brand.py.
    "planet": dict(brand.COLOURS),
    # Sandplanet Marine: deep sea teal with a turquoise accent.
    "marine": {
        "primary": "#0F5E5B",        # the nav band, chips, navy buttons
        "primary_deep": "#083F3D",   # nav band gradient end / hover
        "primary_dark": "#0B4F4C",   # dark end of the document accent rule
        "heading": "#0A3634",        # document headings and totals
        "accent": "#1FB3A3",         # rules, links, primary buttons
        "accent_light": "#4FC9BA",   # light end of the document accent rule
        "accent_deep": "#158F84",    # table heads on invoices / agreements
        "soft": "#DDF4F0",           # app soft fill (hover, selected)
        "soft2": "#E4F4F1",          # document section bands
        "soft3": "#D3ECE7",          # document total bands
        "soft4": "#F1FAF8",          # document zebra rows
    },
}


class Command(BaseCommand):
    help = "Set the brand colour parameters from a named palette (planet | marine)."

    def add_arguments(self, parser):
        parser.add_argument("preset", choices=sorted(PALETTES))

    def handle(self, *args, **options):
        palette = PALETTES[options["preset"]]
        for token, value in palette.items():
            CompanyParameter.objects.update_or_create(
                key=f"brand_{token}",
                defaults={"value": value, "description": f"Brand colour — {token}"})
        brand.invalidate()
        self.stdout.write(f"palette '{options['preset']}' applied: {len(palette)} tokens")
