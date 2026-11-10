"""Ask Claude about a report (owner 2026-11-09: "I generate staff cost
analysis, then ask AI to assist in preparing analysis for overtime — past
three months' comparison, who the highest OT earners are").

The report on the reader's screen is the starting point. Claude is given it
whole, and three tools to reach for more: any preset report for any period
and site the reader may run it for, overtime person by person, and payroll
person by person. The tools hold the permissions, not the prompt: a PM asking
about another site, or about a man's pay, is refused inside the tool, so the
model cannot be talked past the reader's own rights. The answer comes back as
a document — headings, paragraphs, tables — drawn on the page and printed on
the letterhead, never as free text to be pasted about.

Each question is a record: who asked what of which report, the steps the
model took, what it answered, what it cost. A follow-up carries the thread.
Runs on its own thread like the tender digest; the page polls.
"""
import json
import logging
import os
import threading
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.utils import timezone

from . import fx
from . import reports as rp
from .audit import audit

log = logging.getLogger("report_ask")

DEFAULT_MODEL = "claude-opus-5-5"
_MAX_OUTPUT_TOKENS = 16000
_MAX_STEPS = 12            # tool rounds before the model must answer
_STALE_MINUTES = 10
_MAX_ROWS = 400            # rows of one report section handed to the model
# Anthropic first-party list price, USD per million tokens, for the cost
# stamped on each answer.
_PRICES = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
    "claude-opus-5": (Decimal("5"), Decimal("25")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10")),
    "claude-fable-5-1": (Decimal("10"), Decimal("50")),
    "claude-haiku-5-5": (Decimal("0.1"), Decimal("0.5")),
}
ZERO = Decimal("0")


class AskError(Exception):
    pass


def model_name():
    from .models import CompanyParameter
    try:
        v = CompanyParameter.objects.get(key="report_ask_model").value
        return (v or "").strip() or DEFAULT_MODEL
    except CompanyParameter.DoesNotExist:
        return DEFAULT_MODEL


# ---- what the model is told -------------------------------------------------

_SYSTEM = """You are the management analyst of Sand Planet, a construction \
company in the Maldives, answering a reader inside its Planet system. The \
reader has one of the company's preset management reports on screen and asks \
you about it. Your job is to prepare the analysis they would otherwise have \
prepared by hand: compare periods, rank, explain movements, point at what \
needs attention, and say plainly what the data cannot show.

Ground every figure in data you were given or fetched with the tools. Never \
estimate a number the data does not hold; if a period or a person is missing, \
say so. When a comparison needs more data than the report on screen — other \
months, a person-by-person view — fetch it. Prefer one tool call that covers \
the whole period over several small ones.

Conventions: amounts are USD unless a table says MVR; rufiyaa converts at the \
company rate given below. Revenue is what the client has certified. Cost is \
recognised when the Signatory approves it (the payment voucher, the credit \
order, the import, the subcontractor's valuation); payroll when the run locks. \
Payroll figures exist only for locked months; overtime hours exist for every \
marked day. A Friday worked pays a fixed number of overtime hours, not a day of \
basic. Employee numbers look like EMP-0123.

Write for a director: short, concrete, numbers in tables, movements as \
percentages with the absolute beside them, no filler, no praise of the data. \
Name people by employee number and name when ranking them. If the reader may \
not see a figure (the tool said so), do not guess it and do not hint at it."""

_FORMAT = {
    "type": "object",
    "properties": {
        "title": {"type": "string",
                  "description": "The analysis's name, a short noun phrase."},
        "summary": {"type": "string",
                    "description": "The findings in a few sentences."},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "paragraphs": {"type": "array",
                                   "items": {"type": "string"}},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "table": {
                        "type": ["object", "null"],
                        "properties": {
                            "columns": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "kind": {"type": "string",
                                                 "enum": ["text", "money",
                                                          "num", "int",
                                                          "pct"]}},
                                    "required": ["label", "kind"],
                                    "additionalProperties": False}},
                            "rows": {
                                "type": "array",
                                "items": {"type": "array",
                                          "items": {"type": ["string",
                                                             "number",
                                                             "null"]}}},
                        },
                        "required": ["columns", "rows"],
                        "additionalProperties": False},
                },
                "required": ["heading", "paragraphs", "bullets", "table"],
                "additionalProperties": False,
            },
        },
        "caveats": {"type": "array", "items": {"type": "string"},
                    "description": "What the data could not show, and any "
                                   "figure that should be checked by hand."},
    },
    "required": ["title", "summary", "sections", "caveats"],
    "additionalProperties": False,
}


def _tool(name, description, props, required):
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": props,
                             "required": required,
                             "additionalProperties": False}}


_SCOPE = {"type": "string",
          "description": "A site code such as SJR, or 'all' for the company."}
_DATE = {"type": "string", "description": "YYYY-MM-DD"}

TOOLS = [
    _tool("run_report",
          "Run one of the preset management reports for a scope and period "
          "and get its figures: headline values and every section's rows. "
          "Use it for other periods (a month-by-month comparison is one call "
          "per month), other sites, or a different report. Keys: performance, "
          "pnl, revenue, cost, manpower, progress, variations, aging, "
          "cashflow (company only), exceptions.",
          {"key": {"type": "string"}, "scope": _SCOPE,
           "from": _DATE, "to": _DATE},
          ["key", "scope", "from", "to"]),
    _tool("overtime_by_person",
          "Approved overtime person by person, month by month, for a scope "
          "and period: hours and the days with overtime from the attendance "
          "register, and — where the reader may see pay and the month's "
          "payroll is locked — the overtime pay in USD. Ranked by hours.",
          {"scope": _SCOPE, "from": _DATE, "to": _DATE,
           "limit": {"type": "integer",
                     "description": "How many people, most overtime first. "
                                    "Default 30, at most 200."}},
          ["scope", "from", "to", "limit"]),
    _tool("payroll_by_person",
          "Locked payroll person by person, month by month, for a scope and "
          "period: days, overtime hours, basic earned, overtime pay, Friday "
          "pay, allowances, gross, all USD. Only for readers who may see "
          "individual pay; otherwise the tool says so.",
          {"scope": _SCOPE, "from": _DATE, "to": _DATE,
           "limit": {"type": "integer",
                     "description": "How many people, highest gross first. "
                                    "Default 50, at most 300."}},
          ["scope", "from", "to", "limit"]),
]


# ---- the tools' bodies -------------------------------------------------------

def _q2(v):
    return float(Decimal(v).quantize(Decimal("0.01")))


def _json(obj):
    def default(o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, date):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=default, separators=(",", ":"))


class Tools:
    """The three tools, bound to one reader. Every refusal is the reader's
    own rights, said to the model as a tool error."""

    def __init__(self, user):
        self.user = user
        self.sites = rp.allowed_sites(user)
        self.by_code = {s.code.upper(): s for s in self.sites}

    def _scope(self, scope):
        want = (scope or "").strip()
        if want.lower() == "all":
            if not self.user.excom:
                raise AskError("This reader may run site reports only, not "
                               "company-wide ones.")
            return list(self.sites), True
        s = self.by_code.get(want.upper())
        if s is None:
            raise AskError(f"'{want}' is not a site this reader may report "
                           f"on. Their sites: "
                           + ", ".join(sorted(self.by_code)) + ".")
        return [s], False

    @staticmethod
    def _period(a, b):
        try:
            start, end = date.fromisoformat(a), date.fromisoformat(b)
        except (TypeError, ValueError):
            raise AskError("Dates must be YYYY-MM-DD.")
        if end < start:
            raise AskError("The period ends before it starts.")
        if (end - start).days > 366 * 3:
            raise AskError("Keep the period to three years or less.")
        return start, end

    def _ctx(self, scope, a, b):
        sites, company = self._scope(scope)
        start, end = self._period(a, b)
        return rp.Context(user=self.user, sites=sites, company=company,
                          start=start, end=end)

    def call(self, name, args):
        fn = {"run_report": self.run_report,
              "overtime_by_person": self.overtime_by_person,
              "payroll_by_person": self.payroll_by_person}.get(name)
        if fn is None:
            raise AskError(f"No tool called {name}.")
        return fn(**args)

    def run_report(self, key, scope, **kw):
        if key not in rp.reports():
            raise AskError(f"No report called '{key}'.")
        rep = rp.reports()[key]
        if key == "pack":
            raise AskError("Run the individual reports instead of the pack.")
        ctx = self._ctx(scope, kw.get("from"), kw.get("to"))
        if rep.company_only and not ctx.company:
            raise AskError(f"'{key}' is company-wide only: scope 'all'.")
        out = rp.run(key, ctx)
        sections = []
        for s in out["sections"]:
            rows = s["rows"]
            note = s.get("note", "")
            if len(rows) > _MAX_ROWS:
                note = (f"{note} (first {_MAX_ROWS} of {len(rows)} rows "
                        "shown)").strip()
                rows = rows[:_MAX_ROWS]
            sections.append({"title": s["title"], "chapter": s.get("chapter"),
                             "note": note,
                             "columns": [{"key": c["key"], "label": c["label"],
                                          "kind": c["kind"]}
                                         for c in s["columns"]],
                             "rows": rows, "total": s.get("total")})
        return _json({"report": out["title"], "scope": out["scope"],
                      "period": out["period"], "currency": out["currency"],
                      "kpis": out["kpis"], "sections": sections,
                      "notes": out["notes"]})

    def overtime_by_person(self, scope, limit=30, **kw):
        from .models import Attendance, PayrollLine
        ctx = self._ctx(scope, kw.get("from"), kw.get("to"))
        limit = max(1, min(int(limit or 30), 200))
        rows = (Attendance.objects.filter(
            site_id__in=ctx.site_ids, day__gte=ctx.start, day__lte=ctx.end,
            ot_approved__gt=0)
            .values("employee_id", "employee__emp_no", "employee__full_name",
                    "employee__job_category__name", "site__code",
                    "day__year", "day__month", "ot_approved"))
        per = {}
        for r in rows:
            p = per.setdefault(r["employee_id"], {
                "emp_no": r["employee__emp_no"],
                "name": r["employee__full_name"],
                "trade": r["employee__job_category__name"] or "Unassigned",
                "sites": set(), "hours": ZERO, "days": 0, "months": {}})
            p["sites"].add(r["site__code"])
            p["hours"] += r["ot_approved"]
            p["days"] += 1
            key = f"{r['day__year']}-{r['day__month']:02d}"
            m = p["months"].setdefault(key, {"hours": ZERO, "days": 0})
            m["hours"] += r["ot_approved"]
            m["days"] += 1
        ranked_ids = sorted(per, key=lambda e: -per[e]["hours"])[:limit]
        ranked = [per[e] for e in ranked_ids]
        pay_note = ("Overtime pay is not shown to this reader: a PM sees "
                    "site totals, not one person's pay."
                    if not ctx.sees_pay else
                    "ot_pay_usd is from locked payroll runs only; a month "
                    "not yet locked has hours but no pay here.")
        if ctx.sees_pay and ranked_ids:
            rate = fx.usd_rate()
            months = rp.months_in(ctx.start, ctx.end)
            lines = (PayrollLine.objects.filter(
                run__status="LOCKED", excluded=False,
                employee_id__in=ranked_ids)
                .filter(run__year__gte=months[0][0],
                        run__year__lte=months[-1][0])
                .select_related("run"))
            pay = defaultdict(lambda: ZERO)
            for ln in lines:
                if (ln.run.year, ln.run.month) not in months:
                    continue
                pay[(ln.employee_id, f"{ln.run.year}-{ln.run.month:02d}")] \
                    += fx.to_usd(ln.ot_hours * ln.ot_rate, ln.run.currency,
                                 rate)
            for eid in ranked_ids:
                p = per[eid]
                total, found = ZERO, False
                for mk, m in p["months"].items():
                    v = pay.get((eid, mk))
                    if v is not None:
                        m["ot_pay_usd"] = _q2(v)
                        total += v
                        found = True
                if found:           # a man with no locked month has no pay yet
                    p["ot_pay_usd"] = _q2(total)
        out = []
        for p in ranked:
            out.append({"emp_no": p["emp_no"], "name": p["name"],
                        "trade": p["trade"], "sites": sorted(p["sites"]),
                        "ot_hours": float(p["hours"]), "days_with_ot": p["days"],
                        **({"ot_pay_usd": p["ot_pay_usd"]}
                           if "ot_pay_usd" in p else {}),
                        "months": {k: {**m, "hours": float(m["hours"])}
                                   for k, m in sorted(p["months"].items())}})
        return _json({"scope": ctx.scope_label, "period": ctx.period_label,
                      "people_with_overtime": len(per), "shown": len(out),
                      "total_ot_hours": float(sum((p["hours"] for p in
                                                   per.values()), ZERO)),
                      "note": pay_note, "people": out})

    def payroll_by_person(self, scope, limit=50, **kw):
        from .models import PayrollRun
        from .payroll import compute_line, friday_ot_hours
        ctx = self._ctx(scope, kw.get("from"), kw.get("to"))
        if not ctx.sees_pay:
            raise AskError("This reader may not see individual pay. Site "
                           "totals are in the manpower report (run_report "
                           "'manpower'); overtime hours person by person are "
                           "in overtime_by_person.")
        limit = max(1, min(int(limit or 50), 300))
        rate = fx.usd_rate()
        fri = friday_ot_hours()
        months = set(rp.months_in(ctx.start, ctx.end))
        runs = [r for r in PayrollRun.objects.filter(status="LOCKED")
                .filter(year__gte=min(y for y, _ in months),
                        year__lte=max(y for y, _ in months))
                if (r.year, r.month) in months]
        wanted = set(ctx.site_ids)
        per = {}
        for run in runs:
            if run.site_id is not None and run.site_id not in wanted \
                    and not ctx.company:
                continue
            for ln in run.lines.filter(excluded=False).select_related(
                    "employee__job_category", "site"):
                site_id = ln.site_id or run.site_id
                if not ctx.company and site_id not in wanted:
                    continue
                money = compute_line(ln, fri)
                usd = lambda v: fx.to_usd(v, run.currency, rate)  # noqa: E731
                e = ln.employee
                p = per.setdefault(e.id, {
                    "emp_no": e.emp_no, "name": e.full_name,
                    "trade": (e.job_category.name if e.job_category
                              else "Unassigned"),
                    "gross": ZERO, "months": {}})
                mk = f"{run.year}-{run.month:02d}"
                m = {"days": float(ln.days_worked),
                     "ot_hours": float(ln.ot_hours),
                     "fridays": float(ln.fridays_worked),
                     "basic_usd": _q2(usd(money["earned_basic"])),
                     "ot_pay_usd": _q2(usd(money["ot_pay"])),
                     "friday_pay_usd": _q2(usd(money["friday_pay"])),
                     "allowance_usd": _q2(usd(money["allowance"])),
                     "gross_usd": _q2(usd(money["gross"])),
                     "run": run.ref, "currency": run.currency}
                p["months"][mk] = m
                p["gross"] += usd(money["gross"])
        ranked = sorted(per.values(), key=lambda p: -p["gross"])[:limit]
        for p in ranked:
            p["gross_usd"] = _q2(p.pop("gross"))
            p["months"] = dict(sorted(p["months"].items()))
        return _json({"scope": ctx.scope_label, "period": ctx.period_label,
                      "people_paid": len(per), "shown": len(ranked),
                      "locked_months": sorted({f"{r.year}-{r.month:02d}"
                                               for r in runs}),
                      "note": "Locked runs only. A person's month at several "
                              "sites is one line under the run's site.",
                      "people": ranked})


# ---- the call ----------------------------------------------------------------

def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise AskError("Asking needs an ANTHROPIC_API_KEY — ask the "
                       "administrator to set it in the server environment.")
    try:
        import anthropic
    except ImportError:                          # pragma: no cover - env dep
        raise AskError("The anthropic SDK isn't installed on the server.")
    return anthropic.Anthropic(api_key=key)


def _request(client, model, system, messages):
    """One model turn. Isolated so tests can stand in for the model."""
    with client.beta.messages.stream(
            model=model, max_tokens=_MAX_OUTPUT_TOKENS, system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": "high",
                           "format": {"type": "json_schema",
                                      "schema": _FORMAT}},
            tools=TOOLS,
            # A policy decline reruns on a substitute model rather than
            # leaving the reader with nothing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=messages) as stream:
        return stream.get_final_message()


def _dump(block):
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    return dict(block) if isinstance(block, dict) else dict(vars(block))


def _opening(user, rep, question):
    """The first user turn: the report on screen, then the question. The
    report is cached: every follow-up on the thread reads it again."""
    tools = Tools(user)
    today = timezone.localdate()
    ctx = rp.Context(user=user, sites=tools.sites, company=bool(user.excom),
                     start=today, end=today)
    sites = ", ".join(f"{s.code} ({s.name})" for s in tools.sites)
    facts = (f"Today is {today:%d %B %Y}. The reader is "
             f"{user.full_name or user.username}, role {user.role}"
             f"{', ExCom' if user.excom else ''}. Sites they may report on: "
             f"{sites or 'none'}"
             f"{'; and the company as a whole' if user.excom else ''}. "
             + ("They may see individual pay. " if ctx.sees_pay else
                "They may NOT see individual pay — site totals only. ")
             + f"Company rate: MVR {fx.usd_rate()} per USD.")
    return [{"type": "text",
             "text": facts + "\n\nThe report on screen:\n" + _json(rep),
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": question}]


def _answer(client, model, user, messages, steps):
    """Drive the tool loop to a final answer. Returns (answer dict, usage)."""
    tools = Tools(user)
    usage = {"input": 0, "output": 0, "model": model}
    for _ in range(_MAX_STEPS + 1):
        msg = _request(client, model, _SYSTEM, messages)
        u = msg.usage
        usage["input"] += ((u.input_tokens or 0)
                           + (getattr(u, "cache_creation_input_tokens", 0) or 0)
                           + (getattr(u, "cache_read_input_tokens", 0) or 0))
        usage["output"] += u.output_tokens or 0
        usage["model"] = msg.model or model
        content = [_dump(b) for b in msg.content]
        messages.append({"role": "assistant", "content": content})
        if msg.stop_reason == "refusal":
            raise AskError("The model declined to answer this question.")
        if msg.stop_reason == "max_tokens":
            raise AskError("The answer ran too long; ask a narrower "
                           "question.")
        calls = [b for b in content if b.get("type") == "tool_use"]
        if not calls:
            text = "".join(b.get("text", "") for b in content
                           if b.get("type") == "text")
            try:
                return json.loads(text), usage
            except ValueError:
                raise AskError("The model returned no readable answer.")
        results = []
        for c in calls:
            args = c.get("input") or {}
            step = {"tool": c["name"], "input": args}
            try:
                out = tools.call(c["name"], dict(args))
                results.append({"type": "tool_result",
                                "tool_use_id": c["id"], "content": out})
            except AskError as e:
                step["error"] = str(e)
                results.append({"type": "tool_result",
                                "tool_use_id": c["id"], "content": str(e),
                                "is_error": True})
            except Exception as e:               # a report that broke
                log.exception("report_ask tool %s failed", c["name"])
                step["error"] = f"failed: {e}"
                results.append({"type": "tool_result",
                                "tool_use_id": c["id"],
                                "content": f"The tool failed: {e}",
                                "is_error": True})
            steps.append(step)
        messages.append({"role": "user", "content": results})
    raise AskError("The question needed more data than one answer can "
                   "gather; narrow it or ask in parts.")


def _cost(usage):
    price_in, price_out = _PRICES.get(usage.get("model") or "",
                                      _PRICES[DEFAULT_MODEL])
    return ((Decimal(usage["input"]) * price_in
             + Decimal(usage["output"]) * price_out)
            / Decimal(1_000_000)).quantize(Decimal("0.0001"))


# ---- the record --------------------------------------------------------------

def start(user, report_key, scope, start_d, end_d, question, rep,
          follow_up_of=None, background=True):
    """Open an analysis record and run it. `rep` is the report dict the
    reader has on screen (the view already checked they may see it)."""
    from django.conf import settings

    from .models import ReportAnalysis
    question = (question or "").strip()
    if not question:
        return None, "Ask something."
    if len(question) > 4000:
        return None, "Keep the question under 4,000 characters."
    parent = None
    if follow_up_of is not None:
        parent = ReportAnalysis.objects.filter(pk=follow_up_of,
                                               user=user).first()
        if parent is None:
            return None, "That earlier question is not yours to follow up."
        if parent.status != "DONE":
            return None, "Wait for the earlier answer first."
    if ReportAnalysis.objects.filter(user=user, status="RUNNING").exclude(
            started_at__lt=timezone.now()
            - timezone.timedelta(minutes=_STALE_MINUTES)).exists():
        return None, "Your earlier question is still being answered."
    if parent is not None:
        messages = list(parent.messages) + [
            {"role": "user", "content": question}]
        root = parent.thread or parent
    else:
        messages = [{"role": "user", "content": _opening(user, rep, question)}]
        root = None
    a = ReportAnalysis.objects.create(
        user=user, report_key=report_key, scope=scope, start=start_d,
        end=end_d, question=question, thread=root, model=model_name(),
        messages=messages, status="RUNNING")
    audit("report", user.id, "REPORT_ASKED", actor=user,
          detail={"analysis": a.id, "report": report_key, "scope": scope,
                  "from": str(start_d), "to": str(end_d),
                  "follow_up_of": follow_up_of})
    if background and not getattr(settings, "TESTING", False):
        threading.Thread(target=run, args=(a.id, True), daemon=True).start()
    else:
        run(a.id, False)
        a.refresh_from_db()
    return a, None


def run(analysis_id, own_thread=True):
    from django.db import close_old_connections

    from .models import ReportAnalysis
    if own_thread:
        close_old_connections()
    a = ReportAnalysis.objects.select_related("user").get(pk=analysis_id)
    steps = []
    try:
        client = _client()
        messages = list(a.messages)
        answer, usage = _answer(client, a.model, a.user, messages, steps)
        a.answer = answer
        a.messages = messages
        a.input_tokens = usage["input"]
        a.output_tokens = usage["output"]
        a.model = usage.get("model") or a.model
        a.cost_usd = _cost(usage)
        a.status = "DONE"
    except AskError as e:
        a.status, a.error = "FAILED", str(e)
    except Exception as e:                       # never leave it RUNNING
        log.exception("Report analysis %s failed", analysis_id)
        a.status, a.error = "FAILED", f"The answer failed: {e}"
    a.steps = steps
    a.finished_at = timezone.now()
    a.save()
    if own_thread:
        close_old_connections()


def is_stale(a):
    return (a.status == "RUNNING" and a.started_at
            < timezone.now() - timezone.timedelta(minutes=_STALE_MINUTES))


def _step_label(step):
    i = step.get("input") or {}
    names = {"run_report": "Ran the {key} report",
             "overtime_by_person": "Looked at overtime person by person",
             "payroll_by_person": "Looked at payroll person by person"}
    label = names.get(step.get("tool"), step.get("tool", "")).format(
        key=i.get("key", ""))
    where = i.get("scope", "")
    when = f"{i.get('from', '')} to {i.get('to', '')}" if i.get("from") else ""
    out = label
    if where:
        out += f" for {'the company' if where == 'all' else where}"
    if when:
        out += f", {when}"
    if step.get("error"):
        out += f" — {step['error']}"
    return out


def payload(a):
    if a is None:
        return None
    if is_stale(a):
        a.status, a.error = "FAILED", ("The answer did not finish — the "
                                       "server restarted while it ran. Ask "
                                       "again.")
        a.finished_at = timezone.now()
        a.save(update_fields=["status", "error", "finished_at"])
    return {"id": a.id, "thread": a.thread_id or a.id, "status": a.status,
            "question": a.question, "answer": a.answer, "error": a.error,
            "steps": [_step_label(s) for s in a.steps],
            "model": a.model, "started_at": a.started_at,
            "finished_at": a.finished_at,
            "report_key": a.report_key, "scope": a.scope,
            "from": a.start, "to": a.end,
            "input_tokens": a.input_tokens, "output_tokens": a.output_tokens,
            "cost_usd": str(a.cost_usd) if a.cost_usd is not None else None}


def pdf_html(a, user):
    from django.template.loader import render_to_string

    from .pdf import company_info, logo_src
    ans = a.answer or {}
    scope = "Company-wide" if a.scope == "all" else a.scope
    return render_to_string("pdf/report_analysis.html", {
        "a": a, "ans": ans, "logo_src": logo_src(), "co": company_info(),
        "prepared_by": user.full_name or user.username,
        "prepared_on": timezone.localdate(),
        "subline": f"{rp.reports()[a.report_key].title}  |  {scope}  |  "
                   f"{a.start:%d %b %Y} – {a.end:%d %b %Y}",
        "items": [_printable(x) for x in thread_items(a)
                  if x.status == "DONE"],
    })


def _printable(a):
    """An answer laid out for the template: each table cell paired with
    its column's kind, which the template cannot do itself."""
    ans = a.answer or {}
    sections = []
    for sec in ans.get("sections") or []:
        table = sec.get("table")
        if table:
            kinds = [c.get("kind", "text") for c in table.get("columns", [])]
            table = {"columns": table.get("columns", []),
                     "rows": [[{"v": v, "kind": k}
                               for v, k in zip(row, kinds)]
                              for row in table.get("rows", [])]}
        sections.append({"heading": sec.get("heading", ""),
                         "paragraphs": sec.get("paragraphs") or [],
                         "bullets": sec.get("bullets") or [], "table": table})
    return {"question": a.question, "title": ans.get("title", ""),
            "summary": ans.get("summary", ""), "sections": sections,
            "caveats": ans.get("caveats") or [], "asked_at": a.started_at}


def thread_items(a):
    """Every question on this analysis's thread, oldest first."""
    root = a.thread or a
    return [root] + list(root.followers.order_by("started_at"))
