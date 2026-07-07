"""Best-effort line-item extraction from uploaded supplier quotations.

Works on digital (text-based) PDFs via pdfplumber: first tries drawn tables,
then a text-pattern fallback. Scanned/image quotations yield nothing — the
UI tells Purchasing to enter lines manually. Every extracted row must pass
qty x rate = amount (within 1%) so garbage rows do not leak into matching.
"""

import logging
import re
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

MAX_LINES = 100

HEADER_HINTS = {
    "desc": ("description", "item", "particular", "product", "goods", "detail"),
    "qty": ("qty", "quantity", "nos", "no."),
    "unit": ("unit", "uom"),
    "rate": ("rate", "price", "unit price", "unitprice"),
    "amount": ("amount", "total", "value", "line total"),
}

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _to_decimal(text):
    if text is None:
        return None
    match = _NUM.search(str(text).replace("MVR", "").replace("Rf", ""))
    if not match:
        return None
    try:
        return Decimal(match.group().replace(",", ""))
    except InvalidOperation:
        return None


def _amount_checks(qty, rate, amount):
    if qty is None or rate is None:
        return False
    if amount is None:
        return True  # qty+rate alone acceptable; amount computed later
    if qty * rate == 0:
        return amount == 0
    return abs(qty * rate - amount) <= abs(amount) * Decimal("0.01") + Decimal("0.5")


def _map_header(row):
    columns = {}
    for idx, cell in enumerate(row):
        text = (cell or "").strip().lower()
        if not text:
            continue
        for key, hints in HEADER_HINTS.items():
            if key not in columns and any(h in text for h in hints):
                columns[key] = idx
                break
    if "desc" in columns and ("qty" in columns or "rate" in columns):
        return columns
    return None


def _rows_from_table(table):
    header = None
    header_at = -1
    for i, row in enumerate(table[:4]):
        header = _map_header(row)
        if header:
            header_at = i
            break
    if not header:
        return []
    out = []
    for row in table[header_at + 1:]:
        def cell(key):
            idx = header.get(key)
            return row[idx] if idx is not None and idx < len(row) else None

        desc = (cell("desc") or "").strip()
        qty = _to_decimal(cell("qty"))
        rate = _to_decimal(cell("rate"))
        amount = _to_decimal(cell("amount"))
        if not desc or len(desc) < 2 or not _amount_checks(qty, rate, amount):
            continue
        out.append({
            "supplier_desc": " ".join(desc.split()),
            "unit": (cell("unit") or "").strip()[:20],
            "qty": qty, "rate": rate,
            "amount": amount if amount is not None else
            (qty * rate if qty is not None and rate is not None else None),
        })
    return out


# text fallback: "<description> <qty> [unit] <rate> <amount>" at line end
_TEXT_LINE = re.compile(
    r"^(?P<desc>.{4,}?)\s+(?P<qty>\d[\d,]*\.?\d*)\s+"
    r"(?P<unit>[A-Za-z]{1,6}\.?)?\s*(?P<rate>\d[\d,]*\.?\d*)\s+"
    r"(?P<amount>\d[\d,]*\.?\d*)\s*$"
)


def _rows_from_text(text):
    out = []
    for raw in (text or "").splitlines():
        match = _TEXT_LINE.match(raw.strip())
        if not match:
            continue
        qty = _to_decimal(match.group("qty"))
        rate = _to_decimal(match.group("rate"))
        amount = _to_decimal(match.group("amount"))
        if amount is None or not _amount_checks(qty, rate, amount):
            continue
        out.append({
            "supplier_desc": " ".join(match.group("desc").split()),
            "unit": (match.group("unit") or "").strip("."),
            "qty": qty, "rate": rate, "amount": amount,
        })
    return out


def extract_quote_lines(django_file):
    """Returns a list of line dicts (possibly empty). Never raises."""
    try:
        import pdfplumber

        rows = []
        with django_file.open("rb"):
            with pdfplumber.open(django_file) as pdf:
                # 1) ruled tables (reliable column boundaries)
                for page in pdf.pages:
                    for table in page.extract_tables():
                        rows.extend(_rows_from_table(table))
                # 2) borderless layouts: tight-tolerance text lines, each
                #    validated by qty x rate = amount
                if not rows:
                    for page in pdf.pages:
                        rows.extend(_rows_from_text(
                            page.extract_text(x_tolerance=1)))
        return rows[:MAX_LINES]
    except Exception:
        logger.warning("Quotation extraction failed", exc_info=True)
        return []
