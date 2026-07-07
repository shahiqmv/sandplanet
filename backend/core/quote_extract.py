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


_UNIT_TOKEN = re.compile(r"^[A-Za-z]{1,6}\.?$")
_NUMERIC_TOKEN = re.compile(r"^(MVR|Rf|USD)?-?\d[\d,]*\.?\d*$", re.I)
_INT_TOKEN = re.compile(r"^\d{2,6}$")


def _rows_from_text(text):
    """Token-based line parser. Handles both common layouts:
      A) desc-first:  <description> <qty> [unit] <rate> <amount>
      B) code-first:  [item code] <qty> [unit] <description> <rate> <amount>
    Currency prefixes (MVR150.00) are tolerated. Every candidate row must
    pass qty x rate = amount."""
    out = []
    for raw in (text or "").splitlines():
        tokens = raw.strip().split()
        if len(tokens) < 4:
            continue
        if not (_NUMERIC_TOKEN.match(tokens[-1]) and
                _NUMERIC_TOKEN.match(tokens[-2])):
            continue
        amount = _to_decimal(tokens[-1])
        rate = _to_decimal(tokens[-2])
        body = tokens[:-2]
        if amount is None or rate is None or not body:
            continue

        parsed = None
        # find the qty token: any numeric token that satisfies the check
        for i, tok in enumerate(body):
            if not _NUMERIC_TOKEN.match(tok):
                continue
            qty = _to_decimal(tok)
            if qty is None or not _amount_checks(qty, rate, amount):
                continue
            unit = ""
            if i + 1 < len(body) and _UNIT_TOKEN.match(body[i + 1]):
                unit = body[i + 1].strip(".")
                desc_tokens = body[:i] + body[i + 2:]
            else:
                desc_tokens = body[:i] + body[i + 1:]
            # a leading bare item code stays out of the description
            code = ""
            if desc_tokens and i <= 1 and _INT_TOKEN.match(desc_tokens[0]):
                code = desc_tokens[0]
                desc_tokens = desc_tokens[1:]
            desc = " ".join(desc_tokens).strip()
            if len(desc) < 3 or not re.search(r"[A-Za-z]{2,}", desc):
                continue
            parsed = {
                "supplier_desc": desc, "unit": unit,
                "qty": qty, "rate": rate, "amount": amount,
                "remarks": f"Supplier code {code}" if code else "",
            }
            break
        if parsed:
            out.append(parsed)
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
