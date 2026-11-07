"""Management reports: preset, for the executive committee and site PMs
(owner 2026-11-07).

Each report is written once as a builder returning one shape — headline
figures, then sections of rows — and that one shape is drawn on screen, as a
PDF on the letterhead and as an Excel book. Adding a report is a builder and
an entry in REPORTS; nothing about the page, the PDF or the workbook changes.

Who reads them is deliberately narrow: the named ExCom members (User.excom)
see every site and the company as a whole; a PM sees the reports of the sites
they are a current PM of, and nothing company-wide. Everyone else, Admin
included, is refused.

Money is reported in USD, MVR converted at the company rate (fx.py), the same
convention as the project financials.
"""
import calendar
from dataclasses import dataclass
from datetime import date
from io import BytesIO

from .models import Site
from .permissions import PAY_ROLES


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    description: str
    build: object          # build(ctx) -> report dict


@dataclass
class Context:
    """What a builder is asked for: whose eyes, which sites, which dates."""
    user: object
    sites: list            # the Site rows in scope
    company: bool          # the whole company rather than one site
    start: date
    end: date

    @property
    def site_ids(self):
        return [s.id for s in self.sites]

    @property
    def scope_label(self):
        if self.company:
            return "Company-wide"
        s = self.sites[0]
        return f"{s.code} — {s.name}"

    @property
    def period_label(self):
        if self.start == self.end:
            return f"{self.start:%d %b %Y}"
        return f"{self.start:%d %b %Y} – {self.end:%d %b %Y}"

    @property
    def sees_pay(self):
        """Person-by-person pay: the ExCom members who already see pay, and
        the Director (owner 2026-11-07: "PD can see salaries" in reports).
        A PM sees site totals only, never one person's pay."""
        u = self.user
        return bool(u.excom and (u.role in PAY_ROLES or u.role == "DIRECTOR"))


def is_reader(user):
    return bool(user.excom or user.role == "PM")


def allowed_sites(user):
    """The sites this person may run a site report for."""
    if user.excom:
        return list(Site.objects.order_by("code"))
    if user.role == "PM":
        return list(Site.objects.filter(
            pm_history__to_date__isnull=True,
            pm_history__pm_user=user).distinct().order_by("code"))
    return []


def default_period(today=None):
    today = today or date.today()
    return date(today.year, today.month, 1), today


def months_in(start, end):
    """[(year, month)] every month the period touches."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def month_label(y, m):
    return f"{calendar.month_abbr[m]} {y}"


# ---- the shape every report returns ----------------------------------------
# {"title", "kpis": [{label, value, kind, sub}], "sections": [{title, note,
#  columns: [{key, label, kind}], rows: [...], total: {...}|None}],
#  "notes": [str]}
# kind: text | money | num | int | pct | date

def col(key, label, kind="text", wide=False):
    """A column. `wide` gives a name or description the room to read on one
    or two lines instead of a word per line."""
    return {"key": key, "label": label, "kind": kind, "wide": wide}


def section(title, columns, rows, total=None, note=""):
    return {"title": title, "columns": columns, "rows": rows,
            "total": total, "note": note}


def kpi(label, value, kind="money", sub=""):
    return {"label": label, "value": value, "kind": kind, "sub": sub}


def sum_rows(rows, keys):
    out = {}
    for k in keys:
        out[k] = sum((r.get(k) or 0) for r in rows)
    return out


# ---- the register ----------------------------------------------------------

def _registry():
    from . import report_manpower, report_progress, report_revenue
    return [
        Report("revenue", "Revenue analysis",
               "Contract value, variations, work certified, billed, received "
               "and outstanding, project by project. Revenue is what the "
               "client has certified.", report_revenue.build),
        Report("manpower", "Manpower cost analysis",
               "Man-days, headcount and labour cost by site, month and trade, "
               "with overtime and Friday pay, from locked payroll runs.",
               report_manpower.build),
        Report("progress", "Site progress analysis",
               "Programme progress against time elapsed, project by project, "
               "with milestones, completion dates and the manpower on site.",
               report_progress.build),
    ]


def reports():
    return {r.key: r for r in _registry()}


def run(key, ctx):
    rep = reports()[key]
    out = rep.build(ctx)
    out.update(key=key, title=rep.title, scope=ctx.scope_label,
               period=ctx.period_label, currency="USD")
    out.setdefault("notes", [])
    return out


# ---- Excel -----------------------------------------------------------------

_FMT = {"money": "#,##0.00", "num": "#,##0.0", "int": "#,##0",
        "pct": "0.0\"%\"", "date": "dd mmm yyyy"}


def workbook(rep):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    head_fill = PatternFill("solid", fgColor="16527E")
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = rep["title"]
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"{rep['scope']}  |  {rep['period']}  |  {rep['currency']}"
    r = 4
    for k in rep["kpis"]:
        ws.cell(row=r, column=1, value=k["label"]).font = Font(bold=True)
        c = ws.cell(row=r, column=2, value=_cell(k["value"], k["kind"]))
        if k["kind"] in _FMT:
            c.number_format = _FMT[k["kind"]]
        if k.get("sub"):
            ws.cell(row=r, column=3, value=k["sub"])
        r += 1
    if rep["notes"]:
        r += 1
        for n in rep["notes"]:
            ws.cell(row=r, column=1, value=n)
            r += 1
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 50

    used = {"Summary"}
    for sec in rep["sections"]:
        name = _sheet_name(sec["title"], used)
        sh = wb.create_sheet(name)
        sh["A1"] = sec["title"]
        sh["A1"].font = Font(bold=True, size=12)
        if sec.get("note"):
            sh["A2"] = sec["note"]
        for i, c in enumerate(sec["columns"], 1):
            cell = sh.cell(row=4, column=i, value=c["label"])
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head_fill
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            sh.column_dimensions[get_column_letter(i)].width = (
                34 if c["kind"] == "text" else 15)
        row = 5
        for item in sec["rows"] + ([sec["total"]] if sec["total"] else []):
            for i, c in enumerate(sec["columns"], 1):
                v = item.get(c["key"])
                cell = sh.cell(row=row, column=i, value=_cell(v, c["kind"]))
                if c["kind"] in _FMT and v not in (None, ""):
                    cell.number_format = _FMT[c["kind"]]
                if item is sec["total"]:
                    cell.font = Font(bold=True)
            row += 1
        sh.freeze_panes = "A5"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(v, kind):
    if v is None:
        return None
    if kind in ("money", "num", "pct"):
        return float(v)
    return v


def _sheet_name(title, used):
    base = "".join(ch for ch in title if ch not in "[]:*?/\\")[:28] or "Sheet"
    name, n = base, 2
    while name in used:
        name = f"{base[:25]} {n}"
        n += 1
    used.add(name)
    return name


# ---- PDF -------------------------------------------------------------------

def pdf_html(rep, user):
    from django.template.loader import render_to_string
    from django.utils import timezone

    from .pdf import company_info, logo_src
    return render_to_string("pdf/management_report.html", {
        "rep": rep, "logo_src": logo_src(), "co": company_info(),
        "prepared_by": user.full_name or user.username,
        "prepared_on": timezone.localdate(),
        "subline": f"{rep['scope']}  |  {rep['period']}  |  "
                   f"{rep['currency']}",
    })
