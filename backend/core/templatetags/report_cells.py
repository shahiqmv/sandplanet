"""Formatting a management report's cells by kind (core/reports.py)."""
from datetime import date
from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def cell(value, kind):
    if value is None or value == "":
        return "—" if kind != "text" else ""
    if kind == "money":
        # Whole dollars on paper: thirteen money columns with cents do not
        # fit across a landscape page. The screen and Excel keep the cents.
        return f"{Decimal(str(value)):,.0f}"
    if kind == "num":
        return f"{Decimal(str(value)):,.1f}"
    if kind == "int":
        return f"{int(value):,}"
    if kind == "pct":
        return f"{Decimal(str(value)):,.1f}%"
    if kind == "date" and isinstance(value, date):
        return f"{value:%d %b %Y}"
    return value


@register.filter
def field(row, column):
    return cell(row.get(column["key"]), column["kind"])
