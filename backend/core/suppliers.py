"""One supplier directory for Purchasing and Trading (owner 2026-11-18).

Trading had shown only the suppliers flagged for it, so Sales could not see
the 196 Purchasing already had and typed copies in: "Kelani Cables" beside
"Kelani Cables PLC", which then split that supplier's import orders between
two records. This module holds the three things both sides share: how two
names are compared, which suppliers a new name resembles, and how a copy is
merged into the record it duplicates."""
import re

from django.db import IntegrityError, transaction

from .audit import audit
from .models import Supplier

# Words that do not tell one company from another: "SFS Ventures India Pvt
# Ltd" and "SFS Ventures India Private Limited" are the same supplier.
_NOISE = {"pvt", "pte", "private", "ltd", "limited", "plc", "llc", "llp",
          "inc", "incorporated", "corp", "corporation", "co", "company",
          "the", "and", "sdn", "bhd", "gmbh", "srl", "spa", "fze", "fzco",
          "fzc", "fzllc"}


def norm(name):
    words = re.findall(r"[a-z0-9]+", (name or "").lower().replace("&", " "))
    return "".join(w for w in words if w not in _NOISE)


def similar(name, exclude_id=None, limit=5):
    """Active suppliers whose name is, for practical purposes, this one: the
    same once company-form words and punctuation are stripped, or one wholly
    inside the other (only for names long enough not to match by chance)."""
    key = norm(name)
    if not key:
        return []
    out = []
    qs = Supplier.objects.filter(is_active=True).only(
        "id", "name", "country", "category", "is_trading")
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    for s in qs:
        other = norm(s.name)
        if not other:
            continue
        short, long_ = sorted((key, other), key=len)
        if key == other or (len(short) >= 8 and short in long_):
            out.append(s)
    out.sort(key=lambda s: (norm(s.name) != key, s.name.lower()))
    return out[:limit]


def similar_payload(found):
    return [{"id": s.id, "name": s.name, "country": s.country,
             "category": s.category, "is_trading": s.is_trading}
            for s in found]


def _relations():
    """Every model field that points at a Supplier."""
    return [f for f in Supplier._meta.get_fields(include_hidden=True)
            if f.is_relation and f.auto_created and not f.concrete
            and not f.many_to_many]


def usage(supplier):
    """How many records point at this supplier, by what — used to tell a
    supplier only Trading has touched from one Purchasing relies on."""
    out = {}
    for rel in _relations():
        n = rel.related_model._base_manager.filter(
            **{rel.field.name: supplier}).count()
        if n:
            out[f"{rel.related_model.__name__}.{rel.field.name}"] = n
    return out


def used_outside_trading(supplier):
    return any(not k.startswith("TradingLine.") for k in usage(supplier))


# Fields copied onto the kept record when it has them blank and the copy
# does not — a merge never throws away a phone number.
_FILL = ("country", "default_currency", "default_incoterm", "credit_days",
         "contact_person", "phone", "email", "address", "bank_details")


def merge(dup, into, actor, reason=""):
    """Fold `dup` into `into`: everything that points at the copy is moved
    onto the record it duplicates, blanks on the kept record are filled from
    the copy, the trading and clearing-agent flags carry over, and the copy
    is switched off with a note saying where it went. Returns (moved, err)."""
    if dup.pk == into.pk:
        return None, "A supplier cannot be merged into itself."
    if not into.is_active:
        return None, f"{into.name} is switched off — merge into an active record."
    moved = {}
    try:
        with transaction.atomic():
            for rel in _relations():
                field = rel.field.name
                qs = rel.related_model._base_manager.filter(**{field: dup})
                n = qs.count()
                if not n:
                    continue
                try:
                    with transaction.atomic():
                        qs.update(**{field: into})
                except IntegrityError:
                    raise IntegrityError(
                        f"{rel.related_model._meta.verbose_name} on both "
                        f"records clash (e.g. two ratings for the same "
                        f"period) — resolve that first.") from None
                moved[f"{rel.related_model.__name__}.{field}"] = n
            filled = []
            for f in _FILL:
                if getattr(into, f) in ("", None) and getattr(dup, f) not in ("", None):
                    setattr(into, f, getattr(dup, f))
                    filled.append(f)
            into.is_trading = into.is_trading or dup.is_trading
            if dup.is_clearing_agent:
                dup.is_clearing_agent = False
                dup.save(update_fields=["is_clearing_agent"])
                into.is_clearing_agent = True
            into.save()
            note = (f"Merged into #{into.pk} {into.name}"
                    + (f" — {reason}" if reason else "") + ".")
            dup.notes = (note + ("\n" + dup.notes if dup.notes else ""))[:4000]
            dup.is_active = False
            dup.is_trading = False
            dup.save(update_fields=["notes", "is_active", "is_trading",
                                    "updated_at"])
            detail = {"from": dup.pk, "from_name": dup.name, "into": into.pk,
                      "into_name": into.name, "moved": moved,
                      "filled": filled, "reason": reason[:200]}
            audit("supplier", into.pk, "SUPPLIER_MERGED", actor=actor,
                  detail=detail)
            audit("supplier", dup.pk, "SUPPLIER_MERGED_AWAY", actor=actor,
                  detail=detail)
    except IntegrityError as e:
        return None, str(e)
    return moved, None
