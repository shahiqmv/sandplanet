"""The brand layer (MARINE_BUILD_BRIEF.md §2): the company's name, colours,
marks and feature switches, as company parameters, so a second instance of
Planet (Sandplanet Marine) wears its own stationery and app chrome without a
single forked template.

Sand Planet's values are the defaults, so an instance with nothing set looks
exactly as Planet always has. Every PDF template reads colours through the
`{% brand %}` tag; the apps read the same values from `/api/v1/brand`.
"""
import json
import time

from django.core.files.storage import default_storage

# Colour tokens and their Sand Planet defaults — the literals the templates
# carried before the brand layer, so nothing moves for Sand Planet.
COLOURS = {
    "primary": "#16527E",        # navy: rules, chips, the app bar
    "primary_deep": "#0e3a5c",   # hover / deeper navy
    "primary_dark": "#0C4E82",   # the dark end of the invoice gradient
    "heading": "#10344F",        # document headings and totals
    "accent": "#29ABE2",         # sky: the letterhead rule, links
    "accent_light": "#26A9E0",   # the light end of the invoice gradient
    "accent_deep": "#1685CC",    # table heads on invoices / quotations
    "soft": "#dff1fa",           # app soft fill
    "soft2": "#E7F1F9",          # document section bands
    "soft3": "#DCEBF8",          # document total bands
    "soft4": "#F4F9FD",          # document zebra rows
}

TEXT = {
    "brand_name": "SAND PLANET",
    "brand_tagline": "Project Management",
    "brand_short_code": "SP",
}

FEATURES = {"trading": True, "rental": False, "profile": True}

# Sister apps offered in the header switcher: [{"key","name","url"}]. The
# current instance's own app is added by the endpoint.
APPS_DEFAULT = []

FILE_KINDS = {
    "logo": ("company/logo", ("png", "jpg")),
    "mark": ("company/mark", ("png", "svg", "jpg")),
    "wordmark_white": ("company/wordmark-white", ("png", "svg")),
    "emblem": ("company/emblem", ("png", "svg", "jpg")),
}

_cache = {"at": 0.0, "value": None}
TTL = 60.0


def _params():
    from .models import CompanyParameter
    keys = ([f"brand_{k}" for k in COLOURS] + list(TEXT) + ["features", "apps"])
    return {p.key: p.value for p in CompanyParameter.objects.filter(key__in=keys)}


def invalidate():
    _cache["at"] = 0.0


def brand(fresh=False):
    """The brand as one dict, cached briefly per process — a PDF calls the
    tag a hundred times a page."""
    now = time.monotonic()
    if not fresh and _cache["value"] is not None and now - _cache["at"] < TTL:
        return _cache["value"]
    p = _params()
    colours = {k: (str(p.get(f"brand_{k}") or "").strip() or v) for k, v in COLOURS.items()}
    text = {k: (str(p.get(k) or "").strip() or v) for k, v in TEXT.items()}
    feats = dict(FEATURES)
    raw = p.get("features")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if isinstance(raw, dict):
        feats.update({k: bool(v) for k, v in raw.items() if k in FEATURES})
    apps = p.get("apps")
    if isinstance(apps, str):
        try:
            apps = json.loads(apps)
        except ValueError:
            apps = None
    if not isinstance(apps, list):
        apps = list(APPS_DEFAULT)
    apps = [a for a in apps if isinstance(a, dict) and a.get("name") and a.get("url")]
    value = {"colours": colours, **text, "features": feats, "apps": apps}
    _cache["value"], _cache["at"] = value, now
    return value


def colour(token):
    return brand()["colours"].get(token, COLOURS.get(token, "#000000"))


def file_url(kind):
    base, exts = FILE_KINDS[kind]
    for ext in exts:
        name = f"{base}.{ext}"
        if default_storage.exists(name):
            return default_storage.url(name)
    return None


def public_dict(request=None):
    """What the apps load before anyone signs in: name, colours, marks,
    features and the sister-app switcher."""
    b = brand()
    apps = list(b["apps"])
    if b["features"]["trading"]:
        apps.insert(0, {"key": "trading", "name": f"{b['brand_name'].title()} Trading",
                        "url": "/t/"})
    apps.insert(0, {"key": "planet", "name": f"{b['brand_name'].title()} Projects", "url": "/"})
    return {
        "name": b["brand_name"], "tagline": b["brand_tagline"],
        "short_code": b["brand_short_code"],
        "colours": b["colours"], "features": b["features"], "apps": apps,
        "logo_url": file_url("logo"), "mark_url": file_url("mark"),
        "wordmark_white_url": file_url("wordmark_white"),
        "emblem_url": file_url("emblem"),
    }
