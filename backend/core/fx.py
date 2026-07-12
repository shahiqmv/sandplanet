"""Currency conversion for project financials.

Site operations are paid in MVR; resort contracts and the project P&L are
reported in USD. A single company-wide rate (MVR per USD, default the 15.42
peg) converts MVR amounts to USD. Admin / Finance / QS can update the rate.
"""
from decimal import Decimal, InvalidOperation

from .models import CompanyParameter

PARAM_KEY = "usd_mvr_rate"        # MVR per 1 USD
DEFAULT_RATE = Decimal("15.42")   # the effective Maldives peg


def usd_rate():
    """Current MVR-per-USD rate from the company parameter, or the default."""
    p = CompanyParameter.objects.filter(key=PARAM_KEY).first()
    if p and p.value:
        try:
            r = Decimal(str(p.value))
            if r > 0:
                return r
        except (InvalidOperation, ValueError):
            pass
    return DEFAULT_RATE


def to_usd(amount, currency, rate=None):
    """Convert `amount` in `currency` to USD. USD passes through; MVR (or any
    non-USD) is divided by the rate."""
    if amount is None:
        return Decimal("0")
    amount = Decimal(str(amount))
    if currency == "USD":
        return amount
    rate = rate or usd_rate()
    return (amount / rate) if rate else amount
