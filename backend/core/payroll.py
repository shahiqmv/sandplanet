"""Payroll computation helpers.

Kept separate from the HR views so the monthly run and the payslip share one
source of truth for pay maths. Money is quantised to 2dp at the edges.
"""
from decimal import ROUND_HALF_UP, Decimal

from .models import SalaryAdvance

TWO = Decimal("0.01")


def q(v):
    return Decimal(v).quantize(TWO, rounding=ROUND_HALF_UP)


def deductions_for(employee, year, month):
    """Advance + loan installments due for this worker in this payroll period,
    from salary-advance PYRs that Finance has PAID. An advance falls in one
    period; a loan spreads equally over its `months`."""
    period = year * 12 + (month - 1)
    advance = Decimal("0")
    loan = Decimal("0")
    rows = SalaryAdvance.objects.filter(
        employee=employee, document__status="PAID").select_related("document")
    for a in rows:
        start = a.period_year * 12 + (a.period_month - 1)
        n = max(a.months, 1)
        if start <= period < start + n:
            installment = q(a.amount / n)
            if a.kind == SalaryAdvance.Kind.LOAN:
                loan += installment
            else:
                advance += installment
    return {"advance": advance, "loan": loan}
