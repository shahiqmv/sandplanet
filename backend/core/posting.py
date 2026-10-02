"""Posting Planet's operations to the books (FINANCE_BUILD_BRIEF.md, stage 3).

Each rule reads what Planet already records — a certified claim, an issued
invoice, a receipt, the cost ledger's incurred and paid rows — and works out
the entry each event should have in the books *now*. Bringing the books into
line with that is one operation, the same whether it is the first run over
months of history or a run a minute after a single approval:

  * an event with no entry gets one;
  * an event whose entry no longer matches (a claim reopened and
    re-certified, a row reversed) has the old entry reversed and a new one
    posted;
  * an entry whose event is gone (a receipt deleted, an invoice voided) is
    reversed.

So nothing is posted twice, and running it again changes nothing.

A rule posts nothing until it is switched on. Accounts are found by their
role (`system_key`), and a cost head by the account mapped to it, so the
accountant can rename and re-code freely. Anything a rule cannot post — a
voucher with no bank account, a cost head with no account — is held back and
listed with the reason, never guessed.

Foreign currency: Planet stores no rate on a sales document, so a dollar
amount is taken at the company rate (the same rate Planet's own reports
use). A payment keeps the rate it was made at where Planet recorded one.
"""
from collections import OrderedDict, defaultdict
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import fx, ledger
from .audit import audit
from .ledger import BASE, ZERO, q2
from .models import (CompanyParameter, CostHead, CostPosting, JournalEntry,
                     LedgerAccount)

PARAM = "books_posting"

# (key, journal source_type, name, what it posts — in the accountant's words)
RULES = [
    ("claims", "P_CLAIM", "Claim invoices",
     "When a claim is certified and its tax invoice raised: debit the "
     "client (receivable); credit contract revenue and output GST. Retention "
     "held goes to retention receivable; an advance invoiced goes to "
     "advances from clients and comes off it as it is recovered."),
    ("manual_invoices", "P_MINV", "Other project invoices",
     "When an invoice is raised in Receivables: debit the client; credit "
     "contract revenue and output GST. A voided invoice, or one replaced by "
     "a claim, is reversed."),
    ("trading_invoices", "P_TINV", "Trading invoices and credit notes",
     "When a trading tax invoice is issued: debit the customer; credit "
     "resort supply sales and output GST; an advance applied comes off "
     "advances from clients. A credit note does the opposite."),
    ("receipts", "P_RCPT", "Money received",
     "When a receipt is recorded: debit the bank account it names; credit "
     "the client or customer. An advance on a trading order is credited to "
     "advances from clients."),
    ("purchases", "P_PR", "Local purchases",
     "When a purchase is authorised — the order signed, or the cash "
     "purchase approved on a voucher: debit the cost and input GST; credit "
     "the supplier (payable). When it is paid: debit the supplier; credit "
     "the bank account on the voucher."),
    ("payment_requests", "P_PYR", "Payment requisitions",
     "When a requisition is paid: debit its cost; credit the bank account on "
     "the voucher. A salary advance is debited to staff advances, a petty "
     "cash top-up to petty cash, a payroll payment to wages payable, an "
     "import charge to goods in transit."),
    ("petty_cash", "P_PETTY", "Petty cash spending",
     "When the PM approves petty cash entries: debit each cost; credit "
     "petty cash."),
    ("payroll", "P_STAFF", "Payroll",
     "When a payroll run is locked: debit wages at gross, by site; credit "
     "wages payable. Advances recovered come off staff advances and fines go "
     "to other income, both out of wages payable."),
    ("subcontract", "P_SUB", "Subcontract valuations",
     "When a valuation is authorised: debit subcontract cost and input GST; "
     "credit subcontractors payable. When it is paid: debit the payable; "
     "credit the bank."),
    ("rent", "P_RENT", "Rent",
     "When a period's rent is raised on a rental: debit the rent's cost (by "
     "site) and input GST; credit the landlord (payable). When it is paid: "
     "debit the payable; credit the bank account on the voucher."),
    ("imports", "P_IPR", "Import payments and store issues",
     "When a telegraphic transfer is paid on an import order: debit goods "
     "in transit, with the exchange difference to exchange gain or loss; "
     "credit the bank. When imported goods are issued to a site: debit "
     "materials; credit stock."),
]
RULE_KEYS = [r[0] for r in RULES]
SOURCE = {r[0]: r[1] for r in RULES}

# The account a cost head usually lands in, by the standard chart's code or
# a role. The accountant's own mapping (CostHead.ledger_account) wins.
HEAD_DEFAULT = {
    "MATERIALS": "COS_MATERIALS", "LABOUR": "COS_LABOUR",
    "SUBCONTRACT": "COS_SUBCONTRACT", "INPUT_GST": "INPUT_GST",
    "GENERAL_STOCK": "INVENTORY", "FOREX": "FX_LOSS",
    "IMPORT_CHARGES": "GOODS_IN_TRANSIT", "TRD_COGS": "COS_TRADING",
    "TRANSPORT": "#5160", "PLANT": "#5150", "SITE_OVERHEADS": "#5180",
    "OTHER": "#5180", "PERMITS": "#6240", "RECRUITMENT": "#6150",
    "INSURANCE_BONDS": "#6210", "TRD_FREIGHT": "#5120", "RENT": "#6220",
}
# Accounts a rule needs that the standard chart did not have: added, under
# a free code, the first time they are wanted.
EXTRA_ACCOUNTS = {
    "UNDEPOSITED": ("1030", "Receipts not yet banked", "OTHER_CURRENT_ASSET"),
    "CLIENT_BACK_CHARGES": ("5190", "Client back charges", "COGS"),
}


class Hold(Exception):
    """This one event can't be posted — and why."""


# ---- settings ---------------------------------------------------------------------

def _param():
    p = CompanyParameter.objects.filter(key=PARAM).first()
    return p.value if p and isinstance(p.value, dict) else {}


def rules_on():
    return [k for k in _param().get("on", []) if k in RULE_KEYS]


def posting_from():
    """Events dated before this are left to the opening balances and to
    hand entry."""
    return ledger._as_date(_param().get("from")) or ledger.books_start()


def save_settings(data, actor):
    cur = _param()
    out = {"on": [k for k in cur.get("on", []) if k in RULE_KEYS],
           "from": cur.get("from") or ""}
    if "on" in data:
        want = data.get("on") or []
        bad = [k for k in want if k not in RULE_KEYS]
        if bad:
            return f"Unknown rule: {bad[0]}."
        out["on"] = [k for k in RULE_KEYS if k in want]
    if "from" in data:
        d = ledger._as_date(data.get("from"))
        if data.get("from") and d is None:
            return "The date to post from is not a date."
        if d and d < ledger.books_start():
            return (f"The books start on {ledger.books_start():%d %b %Y} — "
                    "nothing earlier can be posted.")
        out["from"] = d.isoformat() if d else ""
    CompanyParameter.objects.update_or_create(
        key=PARAM, defaults={"value": out, "description":
                             "Which of Planet's events post to the books"})
    audit("ledger", 0, "POSTING_RULES_SET", actor=actor, detail=out)
    return None


# ---- what the rules share ----------------------------------------------------------

class Ctx:
    """One run's lookups, so a rule asks the database once."""

    def __init__(self):
        self.start = posting_from()
        self.rate = fx.usd_rate()
        self._acc, self._head, self._bank = {}, {}, {}

    def account(self, key):
        if key not in self._acc:
            a = ledger.account_for(key)
            if a is None and key in EXTRA_ACCOUNTS:
                code, name, typ = EXTRA_ACCOUNTS[key]
                while LedgerAccount.objects.filter(code=code).exists():
                    code = str(int(code) + 1)
                a = LedgerAccount.objects.create(code=code, name=name,
                                                 type=typ, system_key=key)
            self._acc[key] = a
        a = self._acc[key]
        if a is None:
            raise Hold(f"the chart has no account in the role {key} — "
                       "restore it in the chart of accounts")
        if a.is_group or not a.is_active:
            raise Hold(f"{a.code} {a.name} can't take postings")
        return a

    def head(self, head):
        """The account a cost head's costs land in."""
        if head.id not in self._head:
            a = head.ledger_account
            if a is None:
                want = HEAD_DEFAULT.get(head.code)
                if want and want.startswith("#"):
                    a = LedgerAccount.objects.filter(code=want[1:]).first()
                elif want:
                    a = ledger.account_for(want)
            self._head[head.id] = a
        a = self._head[head.id]
        if a is None:
            raise Hold(f"cost head “{head.name}” has no account — map it "
                       "under Posting rules")
        if a.is_group or not a.is_active:
            raise Hold(f"cost head “{head.name}” is mapped to {a.code} "
                       f"{a.name}, which can't take postings")
        return a

    def bank(self, bank_account, what):
        """The ledger account of one of the company's bank accounts."""
        if bank_account is None:
            raise Hold(f"{what} names no bank account")
        if bank_account.id not in self._bank:
            self._bank[bank_account.id] = LedgerAccount.objects.filter(
                bank_account=bank_account).first()
        a = self._bank[bank_account.id]
        if a is None:
            raise Hold(f"bank account “{bank_account.label}” is not in the "
                       "chart — use “Add the bank accounts” on the chart")
        return a

    def mvr(self, amount, currency, rate=None):
        amount = Decimal(str(amount or 0))
        cur = (currency or BASE).upper()
        if cur == BASE:
            return q2(amount)
        if cur == "USD":
            return q2(amount * (rate or self.rate))
        raise Hold(f"an amount in {cur} — only rufiyaa and dollars can be "
                   "posted automatically")


class Entry:
    """The entry an event should have: signed lines (debit positive), merged
    by account and dimension."""

    def __init__(self, key, on, memo, ref="", source_id=None):
        self.key, self.on, self.memo = key[:40], on, memo
        self.ref, self.source_id = ref, source_id
        self._lines = OrderedDict()

    def add(self, account, amount, *, site=None, project=None, party="",
            cost_head=None, fc=None, fc_currency="", description=""):
        """`amount` in rufiyaa, debit positive. `fc` is the same amount in a
        foreign currency, same sign."""
        amount = q2(Decimal(str(amount or 0)))
        if not amount and not fc:
            return
        k = (account.id, getattr(site, "id", None),
             getattr(project, "id", None), party[:160], fc_currency,
             getattr(cost_head, "id", None))
        row = self._lines.get(k)
        if row is None:
            row = self._lines[k] = {
                "account": account, "amount": ZERO, "site": site,
                "project": project, "party": party[:160], "fc": ZERO,
                "currency": fc_currency, "cost_head": cost_head,
                "description": description[:300]}
        row["amount"] += amount
        if fc:
            row["fc"] += q2(Decimal(str(fc)))

    def bank(self, account, mvr, currency, amount, ctx, **kw):
        """A line on a bank account (debit positive), carrying its own
        currency where the account is held in one."""
        if not account.currency:
            return self.add(account, mvr, **kw)
        if account.currency == (currency or BASE).upper():
            fc = q2(Decimal(str(amount)))
        elif account.currency == "USD":
            fc = q2(Decimal(str(mvr)) / ctx.rate)
        else:
            raise Hold(f"{account.name} is held in {account.currency}")
        self.add(account, mvr, fc=fc, fc_currency=account.currency, **kw)

    def lines(self):
        out = []
        for row in self._lines.values():
            amt = row["amount"]
            if not amt:
                continue
            ln = {"account": row["account"],
                  "debit": amt if amt > 0 else ZERO,
                  "credit": -amt if amt < 0 else ZERO,
                  "description": row["description"], "currency": BASE,
                  "amount_fc": None, "fx_rate": None, "site": row["site"],
                  "project": row["project"], "cost_head": row["cost_head"],
                  "party": row["party"]}
            if row["currency"] and row["fc"]:
                fc = abs(row["fc"])
                ln.update(currency=row["currency"], amount_fc=fc,
                          fx_rate=(abs(amt) / fc).quantize(
                              Decimal("0.000001")))
            out.append(ln)
        return out

    def total(self):
        return sum((ln["debit"] for ln in self.lines()), ZERO)

    def out_of_balance(self):
        return sum((r["amount"] for r in self._lines.values()), ZERO)

    def signature(self):
        return _signature(self.on, self.lines())


def _signature(on, lines):
    return (on, tuple(sorted(
        (ln["account"].id if hasattr(ln["account"], "id") else ln["account"],
         str(q2(ln["debit"])), str(q2(ln["credit"])),
         ln["currency"] or BASE, str(ln["amount_fc"] or ""),
         getattr(ln["site"], "id", ln["site"]) or 0,
         getattr(ln["project"], "id", ln["project"]) or 0,
         ln["party"] or "") for ln in lines)))


def _entry_signature(e):
    return _signature(e.date, [
        {"account": ln.account_id, "debit": ln.debit, "credit": ln.credit,
         "currency": ln.currency, "amount_fc": ln.amount_fc,
         "site": ln.site_id, "project": ln.project_id, "party": ln.party}
        for ln in e.lines.all()])


# ---- sales --------------------------------------------------------------------------

def _claims(ctx, hold):
    from . import commercial, receivables
    from .models import ProgressClaim
    ar, rev = ctx.account("AR_TRADE"), ctx.account("REVENUE_CONTRACT")
    qs = (ProgressClaim.objects.filter(status__in=("CERTIFIED", "PAID"))
          .exclude(invoice_no="")
          .select_related("project", "project__site", "previous"))
    cache = {}

    def waterfall(c):
        if c is None:
            return defaultdict(lambda: ZERO)
        if c.id not in cache:
            cache[c.id] = commercial.claim_valuation(c)["waterfall"]
        return cache[c.id]
    for c in qs:
        what, key = f"Claim invoice {c.invoice_no}", f"CLAIM:{c.id}"
        try:
            on = receivables.invoice_date(c)
            if on < ctx.start:
                continue
            cur = receivables.contract_currency(c.project)
            inv = commercial.invoice_pdf_context(c)
            w, p = waterfall(c), waterfall(c.previous)
            site, project = c.project.site, c.project
            client = site.client_name or site.name
            e = Entry(key, on, f"{what} · {project.code} "
                      f"{c.ipc_ref} · {client}", c.invoice_no, c.id)
            dims = {"site": site, "project": project, "party": client}
            fcur = cur if cur != BASE else ""

            def m(v):
                return ctx.mvr(q2(Decimal(str(v or 0))), cur)
            net_to_pay = q2(inv["net_to_pay"])
            e.add(ar, m(net_to_pay), fc=net_to_pay if fcur else None,
                  fc_currency=fcur, **dims)
            e.add(ctx.account("OUTPUT_GST"), -m(inv["gst"]), **dims)
            contra = q2(w["deductions_present"])
            if contra:
                e.add(ctx.account("CLIENT_BACK_CHARGES"), m(contra), **dims)
            # the advance: invoiced, then recovered claim by claim
            adv = (q2(w["advance_received"] - p["advance_received"])
                   - q2(w["advance_recovered"] - p["advance_recovered"]))
            if adv:
                e.add(ctx.account("CLIENT_ADVANCES"), -m(adv), **dims)
            # retention: held on each claim, released at the end
            held = (q2(w["retention_held"] - p["retention_held"])
                    - q2(w["retention_released"] - p["retention_released"]))
            if held:
                e.add(ctx.account("RETENTION_RECEIVABLE"), m(held), **dims)
            # what is left is the work certified on this claim
            e.add(rev, -e.out_of_balance(), **dims)
            yield e
        except Hold as h:
            hold(what, str(h), key)


def _manual_invoices(ctx, hold):
    from .models import ManualInvoice
    ar, rev = ctx.account("AR_TRADE"), ctx.account("REVENUE_CONTRACT")
    qs = (ManualInvoice.objects.filter(is_void=False,
                                       superseded_at__isnull=True,
                                       invoice_date__gte=ctx.start)
          .select_related("project", "project__site"))
    for mi in qs:
        what, key = f"Invoice {mi.invoice_no}", f"MINV:{mi.id}"
        try:
            site, project = mi.project.site, mi.project
            client = site.client_name or site.name
            cur = (mi.currency or BASE).upper()
            fcur = cur if cur != BASE else ""
            dims = {"site": site, "project": project, "party": client}
            e = Entry(key, mi.invoice_date,
                      f"{what} · {project.code} · {client}", mi.invoice_no,
                      mi.id)
            gross = q2(mi.amount)
            e.add(ar, ctx.mvr(gross, cur), fc=gross if fcur else None,
                  fc_currency=fcur, **dims)
            e.add(ctx.account("OUTPUT_GST"),
                  -ctx.mvr(mi.gst_amount or 0, cur), **dims)
            e.add(rev, -e.out_of_balance(), **dims)
            yield e
        except Hold as h:
            hold(what, str(h), key)


def _trading_invoices(ctx, hold):
    from .models import TradingCreditNote, TradingInvoice
    ar, rev = ctx.account("AR_TRADING"), ctx.account("REVENUE_TRADING")
    for inv in (TradingInvoice.objects.filter(status__in=("ISSUED", "PAID"),
                                              invoice_date__gte=ctx.start)
                .select_related("customer")):
        what, key = f"Trading invoice {inv.ref}", f"TINV:{inv.id}"
        try:
            cur = (inv.currency or BASE).upper()
            fcur = cur if cur != BASE else ""
            who = inv.customer.name if inv.customer_id else (
                (inv.snapshot or {}).get("customer", {}).get("name", ""))
            e = Entry(key, inv.invoice_date, f"{what} · {who}",
                      inv.ref, inv.id)
            applied = q2(inv.advance_applied or 0)
            owed = q2(inv.total) - applied
            e.add(ar, ctx.mvr(owed, cur), fc=owed if fcur else None,
                  fc_currency=fcur, party=who)
            if applied:
                # paid in advance (or, on an invoice from before Planet,
                # received before it): it comes off advances from clients
                e.add(ctx.account("CLIENT_ADVANCES"), ctx.mvr(applied, cur),
                      party=who)
            e.add(ctx.account("OUTPUT_GST"), -ctx.mvr(inv.gst or 0, cur),
                  party=who)
            e.add(rev, -e.out_of_balance(), party=who)
            yield e
        except Hold as h:
            hold(what, str(h), key)
    for cn in TradingCreditNote.objects.select_related("invoice",
                                                       "invoice__customer"):
        what, key = f"Credit note {cn.ref}", f"TCN:{cn.id}"
        try:
            on = timezone.localtime(cn.issued_at).date()
            if on < ctx.start or cn.invoice.status == "VOID":
                continue
            cur = (cn.invoice.currency or BASE).upper()
            fcur = cur if cur != BASE else ""
            who = cn.invoice.customer.name if cn.invoice.customer_id else ""
            e = Entry(key, on, f"{what} · against "
                      f"{cn.invoice.ref} · {who}", cn.ref, cn.id)
            amt = q2(cn.amount)
            e.add(ar, -ctx.mvr(amt, cur), fc=-amt if fcur else None,
                  fc_currency=fcur, party=who)
            e.add(ctx.account("OUTPUT_GST"), ctx.mvr(cn.gst or 0, cur),
                  party=who)
            e.add(rev, -e.out_of_balance(), party=who)
            yield e
        except Hold as h:
            hold(what, str(h), key)


def _receipts(ctx, hold):
    from . import receivables
    from .models import ClientReceipt, OfficialReceipt, TradingReceipt
    ar = ctx.account("AR_TRADE")

    def line_currency(r):
        if r.claim_id:
            return receivables.contract_currency(r.claim.project)
        if r.manual_invoice_id:
            return (r.manual_invoice.currency or BASE).upper()
        return (r.currency or BASE).upper()

    for rc in (OfficialReceipt.objects.filter(receipt_date__gte=ctx.start)
               .select_related("site", "bank_account")
               .prefetch_related("receipts__claim__project",
                                 "receipts__manual_invoice",
                                 "receipts__project")):
        what, key = f"Receipt {rc.receipt_no}", f"OR:{rc.id}"
        try:
            client = rc.site.client_name or rc.site.name
            e = Entry(key, rc.receipt_date, f"{what} · {client}"
                      + (f" · {rc.reference}" if rc.reference else ""),
                      rc.receipt_no, rc.id)
            lines = list(rc.receipts.all())
            if not lines:
                continue
            curs = {line_currency(r) for r in lines}
            if len(curs) > 1:
                raise Hold("it settles invoices in more than one currency")
            cur = curs.pop()
            fcur = cur if cur != BASE else ""
            total = sum((q2(r.amount) for r in lines), ZERO)
            bank = ctx.bank(rc.bank_account, "the receipt")
            e.bank(bank, ctx.mvr(total, cur), cur, total, ctx, party=client)
            for r in lines:
                amt = q2(r.amount)
                e.add(ar, -ctx.mvr(amt, cur), fc=-amt if fcur else None,
                      fc_currency=fcur, site=rc.site, project=r.project,
                      party=client)
            _square(e, ctx)
            yield e
        except Hold as h:
            hold(what, str(h), key)

    # a receipt noted by the QS with no official receipt: no bank is known
    for r in (ClientReceipt.objects.filter(official_receipt__isnull=True,
                                           received_on__gte=ctx.start)
              .select_related("project", "project__site", "claim__project",
                              "manual_invoice")):
        what = f"Receipt noted on {r.project.code}, {r.received_on:%d %b %Y}"
        key = f"CR:{r.id}"
        try:
            cur = line_currency(r)
            fcur = cur if cur != BASE else ""
            site = r.project.site
            client = site.client_name or site.name
            amt = q2(r.amount)
            e = Entry(key, r.received_on, f"{what} · {client}",
                      r.reference or "", r.id)
            e.add(ctx.account("UNDEPOSITED"), ctx.mvr(amt, cur), party=client)
            e.add(ar, -ctx.mvr(amt, cur), fc=-amt if fcur else None,
                  fc_currency=fcur, site=site, project=r.project,
                  party=client)
            yield e
        except Hold as h:
            hold(what, str(h), key)

    art = ctx.account("AR_TRADING")
    for rc in (TradingReceipt.objects.filter(receipt_date__gte=ctx.start)
               .select_related("customer", "bank_account")
               .prefetch_related("lines")):
        what, key = f"Receipt {rc.receipt_no}", f"TR:{rc.id}"
        try:
            who = rc.customer.name if rc.customer_id else ""
            cur = (rc.currency or BASE).upper()
            fcur = cur if cur != BASE else ""
            lines = list(rc.lines.all())
            if not lines:
                continue
            total = sum((q2(r.amount) for r in lines), ZERO)
            e = Entry(key, rc.receipt_date, f"{what} · {who}"
                      + (f" · {rc.reference}" if rc.reference else ""),
                      rc.receipt_no, rc.id)
            if rc.bank_account_id:
                e.bank(ctx.bank(rc.bank_account, "the receipt"),
                       ctx.mvr(total, cur), cur, total, ctx, party=who)
            else:
                e.add(ctx.account("UNDEPOSITED"), ctx.mvr(total, cur),
                      party=who)
            for r in lines:
                amt = q2(r.amount)
                if r.invoice_id:
                    e.add(art, -ctx.mvr(amt, cur), fc=-amt if fcur else None,
                          fc_currency=fcur, party=who)
                else:                     # an advance on a won order
                    e.add(ctx.account("CLIENT_ADVANCES"), -ctx.mvr(amt, cur),
                          party=who)
            _square(e, ctx)
            yield e
        except Hold as h:
            hold(what, str(h), key)


def _square(e, ctx):
    """Line-by-line rounding of a dollar amount can leave a few laari: they
    go to exchange difference so the entry balances."""
    diff = e.out_of_balance()
    if not diff:
        return
    if abs(diff) > Decimal("1.00"):
        raise Hold(f"its figures don't add up (out by {abs(diff):,.2f})")
    e.add(ctx.account("FX_LOSS" if diff < 0 else "FX_GAIN"), -diff)


# ---- costs and payments: the cost ledger, mirrored ------------------------------------

def _voucher_bank(ctx, what, *, document=None, payable=None, milestone=None):
    """The bank account a payment left from: the one on its voucher."""
    from .models import PaymentVoucherLine
    if milestone is not None and milestone.voucher_id:
        return ctx.bank(milestone.voucher.debit_account,
                        f"voucher {milestone.voucher.ref}")
    qs = (PaymentVoucherLine.objects.filter(voucher__is_void=False)
          .exclude(voucher__status="CANCELLED")
          .select_related("voucher", "voucher__debit_account")
          .order_by("-voucher_id"))
    if payable is not None:
        qs = qs.filter(source_payable=payable)
    elif document is not None:
        from django.db.models import Q
        qs = qs.filter(Q(source_document=document)
                       | Q(source_payable__document=document))
    else:
        qs = qs.none()
    line = qs.first()
    if line is None:
        raise Hold("it is on no payment voucher, so the bank account it "
                   "was paid from is not known")
    return ctx.bank(line.voucher.debit_account, f"voucher {line.voucher.ref}")


def _cost_rows(source, states, start, **extra):
    return (CostPosting.objects.filter(source__in=source, state__in=states,
                                       posted_on__gte=start, **extra)
            .select_related("cost_head", "cost_head__ledger_account", "site",
                            "document", "document_line", "ipr_milestone",
                            "ipr_milestone__voucher",
                            "ipr_milestone__voucher__debit_account")
            .order_by("posted_on", "id"))


def _purchases(ctx, hold):
    ap = ctx.account("AP_TRADE")
    groups = OrderedDict()
    for r in _cost_rows(["PR"], ["INCURRED", "PAID"], ctx.start):
        groups.setdefault((r.state, r.document_id, r.posted_on), []).append(r)
    for (state, doc_id, on), rows in groups.items():
        doc = rows[0].document
        ref = doc.ref if doc else f"PR {doc_id}"
        what = (f"Purchase {ref}" if state == "INCURRED"
                else f"Payment for purchase {ref}")
        key = f"{'PRI' if state == 'INCURRED' else 'PRP'}:{doc_id}:{on}"
        try:
            e = Entry(key, on, what, ref, doc_id)
            for r in rows:
                vendor = (r.document_line.vendor if r.document_line_id
                          else "") or ""
                amt = ctx.mvr(r.amount, r.currency)
                if state == "INCURRED":
                    e.add(ctx.head(r.cost_head), amt, site=r.site,
                          cost_head=r.cost_head, party=vendor)
                    e.add(ap, -amt, party=vendor)
                else:
                    e.add(ap, amt, party=vendor)
            if state == "PAID":
                paid = e.out_of_balance()
                if paid:
                    e.bank(_voucher_bank(ctx, what, document=doc), -paid,
                           BASE, -paid, ctx)
            if e.lines():
                yield e
        except Hold as h:
            hold(what, str(h), key)


def _pyr_debit(ctx, pr, doc):
    """Where a requisition that posted no cost belongs."""
    from .models import PayrollRun, SalaryAdvance
    if pr.petty_cash_cycle_id or pr.payment_type == "PETTY_CASH_REPLENISH":
        return ctx.account("PETTY_CASH")
    if SalaryAdvance.objects.filter(document=doc).exists():
        return ctx.account("STAFF_ADVANCES")
    if PayrollRun.objects.filter(payment_request=doc).exists():
        return ctx.account("SALARIES_PAYABLE")
    if pr.subcontract_agreement_id and pr.payment_type == "ADVANCE":
        return ctx.account("SUPPLIER_ADVANCES")
    code = pr.cost_head.code if pr.cost_head_id else ""
    if code == "IMPORT_CHARGES":
        return ctx.account("GOODS_IN_TRANSIT")
    if pr.is_capitalized:
        # held as an asset, not a cost: a refundable deposit and the like
        want = "1310" if code == "RECRUITMENT" else "1360"
        a = LedgerAccount.objects.filter(code=want, is_group=False).first()
        if a is None:
            raise Hold("it is held as an asset, and the chart has no "
                       f"account {want} for it")
        return a
    raise Hold("it was paid but put no cost in Planet's cost ledger")


def _payment_requests(ctx, hold):
    from .models import PaymentRequest
    qs = (PaymentRequest.objects.filter(
        paid_date__isnull=False, paid_date__gte=ctx.start,
        amount_paid__isnull=False, document__status__in=("PAID", "CLOSED"))
        .select_related("document", "document__site", "cost_head"))
    costs = defaultdict(list)
    for r in _cost_rows(["PYR"], ["INCURRED"], date(2000, 1, 1)):
        costs[r.document_id].append(r)
    for pr in qs:
        doc = pr.document
        what, key = f"Payment {doc.ref}", f"PYR:{doc.id}"
        try:
            cur = (pr.currency or BASE).upper()
            paid = q2(pr.amount_paid)
            if not paid:
                continue
            value = ctx.mvr(paid, cur, pr.fx_rate or None)
            e = Entry(key, pr.paid_date,
                      f"{what} · {pr.payee}"
                      + (f" · {pr.payment_ref}" if pr.payment_ref else ""),
                      doc.ref, doc.id)
            e.bank(_voucher_bank(ctx, what, document=doc), -value, cur,
                   -paid, ctx, party=pr.payee or "")
            rows = costs.get(doc.id, [])
            for r in rows:
                e.add(ctx.head(r.cost_head), ctx.mvr(r.amount, r.currency),
                      site=r.site, cost_head=r.cost_head,
                      party=pr.payee or "")
            if not any(ln["debit"] for ln in e.lines()):
                e.add(_pyr_debit(ctx, pr, doc), value, site=doc.site,
                      party=pr.payee or "")
            else:
                _square(e, ctx)
            yield e
        except Hold as h:
            hold(what, str(h), key)


def _petty_cash(ctx, hold):
    groups = OrderedDict()
    for r in _cost_rows(["PETTY_CASH"], ["INCURRED"], ctx.start):
        groups.setdefault((r.site_id, r.posted_on), []).append(r)
    for (site_id, on), rows in groups.items():
        site = rows[0].site
        what = f"Petty cash at {site.code}, {on:%d %b %Y}"
        key = f"PC:{site_id}:{on}"
        try:
            e = Entry(key, on, what, f"PC {site.code}",
                      site_id)
            for r in rows:
                amt = ctx.mvr(r.amount, r.currency)
                e.add(ctx.head(r.cost_head), amt, site=site,
                      cost_head=r.cost_head)
                e.add(ctx.account("PETTY_CASH"), -amt, site=site)
            if e.lines():
                yield e
        except Hold as h:
            hold(what, str(h), key)


def _payroll(ctx, hold):
    from .models import Payable, PayrollRun
    payable = ctx.account("SALARIES_PAYABLE")
    groups = OrderedDict()
    for r in _cost_rows(["STAFF"], ["INCURRED"], ctx.start):
        groups.setdefault((r.staff_year, r.staff_month, r.posted_on,
                           r.currency), []).append(r)
    for (y, mth, on, cur), rows in groups.items():
        what = f"Wages for {mth:02d}/{y}" if y and mth else "Wages"
        key = f"STAFF:{y}-{mth}:{on}:{cur}"
        try:
            e = Entry(key, on,
                      f"{what} ({cur}), by site", f"WAGES {y}-{mth:02d}"
                      if y and mth else "WAGES")
            fcur = cur if cur != BASE else ""
            for r in rows:
                amt = ctx.mvr(r.amount, cur)
                e.add(ctx.head(r.cost_head), amt, site=r.site,
                      cost_head=r.cost_head)
                e.add(payable, -amt, fc=-q2(r.amount) if fcur else None,
                      fc_currency=fcur)
            if e.lines():
                yield e
        except Hold as h:
            hold(what, str(h), key)
    # what the run took back from the men: advances and loans, and fines
    for run in PayrollRun.objects.filter(status="LOCKED",
                                         locked_at__isnull=False):
        what, key = f"Deductions on payroll {run.ref}", f"RUND:{run.id}"
        try:
            on = timezone.localtime(run.locked_at).date()
            if on < ctx.start:
                continue
            cur = (run.currency or BASE).upper()
            adv = fines = ZERO
            for ln in run.lines.all():
                if ln.excluded:
                    continue
                adv += Decimal(ln.advance or 0) + Decimal(ln.loan or 0)
                fines += Decimal(ln.penalty or 0)
            if not adv and not fines:
                continue
            e = Entry(key, on, what, run.ref, run.id)
            e.add(payable, ctx.mvr(adv + fines, cur))
            e.add(ctx.account("STAFF_ADVANCES"), -ctx.mvr(adv, cur))
            e.add(ctx.account("OTHER_INCOME"), -ctx.mvr(fines, cur),
                  description="Fines deducted from wages")
            _square(e, ctx)
            yield e
        except Hold as h:
            hold(what, str(h), key)
    # a dollar salary paid head by head through a voucher
    for p in (Payable.objects.filter(payroll_line__isnull=False,
                                     status="SETTLED",
                                     settled_on__gte=ctx.start)
              .select_related("payroll_line__run")):
        what, key = f"Salary paid to {p.vendor}", f"SALP:{p.id}"
        try:
            cur = (p.payroll_line.run.currency or BASE).upper()
            amt = q2(p.amount)
            value = ctx.mvr(amt, cur)
            e = Entry(key, p.settled_on, what,
                      p.settled_ref[:40] if p.settled_ref else "", p.id)
            e.add(payable, value, party=p.vendor[:160])
            e.bank(_voucher_bank(ctx, what, payable=p), -value, cur, -amt,
                   ctx, party=p.vendor[:160])
            yield e
        except Hold as h:
            hold(what, str(h), key)


def _subcontract(ctx, hold):
    ap = ctx.account("AP_SUBCONTRACT")
    groups = OrderedDict()
    for r in _cost_rows(["SUBCONTRACT"], ["INCURRED", "PAID"], ctx.start):
        groups.setdefault((r.state, r.document_id, r.posted_on), []).append(r)
    for (state, doc_id, on), rows in groups.items():
        doc = rows[0].document
        ref = doc.ref if doc else f"SVC {doc_id}"
        what = (f"Subcontract valuation {ref}" if state == "INCURRED"
                else f"Payment of subcontract valuation {ref}")
        key = f"{'SVI' if state == 'INCURRED' else 'SVP'}:{doc_id}:{on}"
        try:
            e = Entry(key, on, what, ref, doc_id)
            who = (doc.supplier.name if doc and doc.supplier_id else "")
            for r in rows:
                amt = ctx.mvr(r.amount, r.currency)
                if state == "INCURRED":
                    e.add(ctx.head(r.cost_head), amt, site=r.site,
                          cost_head=r.cost_head, party=who)
                    e.add(ap, -amt, party=who)
                else:
                    e.add(ap, amt, party=who)
            if state == "PAID":
                paid = e.out_of_balance()
                if paid:
                    e.bank(_voucher_bank(ctx, what, document=doc), -paid,
                           BASE, -paid, ctx)
            if e.lines():
                yield e
        except Hold as h:
            hold(what, str(h), key)


def _rent(ctx, hold):
    ap = ctx.account("AP_TRADE")
    groups = OrderedDict()
    for r in (_cost_rows(["RENT"], ["INCURRED", "PAID"], ctx.start)
              .select_related("rent_due", "rent_due__contract")):
        groups.setdefault((r.state, r.rent_due_id, r.posted_on), []).append(r)
    for (state, due_id, on), rows in groups.items():
        due = rows[0].rent_due
        c = due.contract if due else None
        ref = c.ref if c else "RENT"
        what = (f"Rent {ref}, period from {due.period_start:%d %b %Y}"
                if due else "Rent")
        if state == "PAID":
            what = "Payment of " + what[0].lower() + what[1:]
        key = f"{'RNI' if state == 'INCURRED' else 'RNP'}:{due_id}:{on}"
        try:
            who = c.landlord if c else ""
            e = Entry(key, on, f"{what} · {c.title}" if c else what, ref,
                      due_id)
            for r in rows:
                amt = ctx.mvr(r.amount, r.currency)
                if state == "INCURRED":
                    e.add(ctx.head(r.cost_head), amt, site=r.site,
                          cost_head=r.cost_head, party=who)
                    e.add(ap, -amt, party=who)
                else:
                    e.add(ap, amt, party=who)
            if state == "PAID":
                paid = e.out_of_balance()
                if paid:
                    payable = getattr(due, "payable", None)
                    e.bank(_voucher_bank(ctx, what, payable=payable), -paid,
                           due.currency, -q2(due.total), ctx, party=who)
            if e.lines():
                yield e
        except Hold as h:
            hold(what, str(h), key)


def _imports(ctx, hold):
    git = ctx.account("GOODS_IN_TRANSIT")
    groups = OrderedDict()
    for r in _cost_rows(["IPR", "FX"], ["PAID"], ctx.start):
        groups.setdefault((r.ipr_milestone_id, r.document_id, r.posted_on),
                          []).append(r)
    for (ms_id, doc_id, on), rows in groups.items():
        doc, ms = rows[0].document, rows[0].ipr_milestone
        ref = doc.ref if doc else f"IPR {doc_id}"
        what = f"Import payment on {ref}"
        key = f"IPRP:{ms_id or 0}:{doc_id}:{on}"
        try:
            e = Entry(key, on, what
                      + (f" · TT {ms.tt_ref}" if ms and ms.tt_ref else ""),
                      ref, doc_id)
            who = (doc.supplier.name if doc and doc.supplier_id else "")
            for r in rows:
                amt = ctx.mvr(r.amount, r.currency)
                if r.source == "FX":
                    e.add(ctx.account("FX_LOSS" if amt > 0 else "FX_GAIN"),
                          amt, party=who)
                else:
                    e.add(git, amt, party=who)
            paid = e.out_of_balance()
            if paid:
                e.bank(_voucher_bank(ctx, what, milestone=ms, document=doc),
                       -paid, BASE, -paid, ctx, party=who)
            if e.lines():
                yield e
        except Hold as h:
            hold(what, str(h), key)
    # imported goods issued from the store to a site: out of stock, into cost
    stock = ctx.account("INVENTORY")
    groups = OrderedDict()
    for r in _cost_rows(["STORE_ISSUE"], ["INCURRED"], ctx.start,
                        book="PROJECT"):
        groups.setdefault((r.document_id, r.posted_on), []).append(r)
    for (doc_id, on), rows in groups.items():
        doc = rows[0].document
        ref = doc.ref if doc else "store issue"
        what, key = f"Store issue {ref}", f"SI:{doc_id or 0}:{on}"
        try:
            e = Entry(key, on, what, ref, doc_id)
            for r in rows:
                amt = ctx.mvr(r.amount, r.currency)
                e.add(ctx.head(r.cost_head), amt, site=r.site,
                      cost_head=r.cost_head)
                e.add(stock, -amt)
            if e.lines():
                yield e
        except Hold as h:
            hold(what, str(h), key)


COLLECT = {
    "claims": _claims, "manual_invoices": _manual_invoices,
    "trading_invoices": _trading_invoices, "receipts": _receipts,
    "purchases": _purchases, "payment_requests": _payment_requests,
    "petty_cash": _petty_cash, "payroll": _payroll,
    "subcontract": _subcontract, "rent": _rent, "imports": _imports,
}


# ---- bringing the books into line -----------------------------------------------------

class _Undo(Exception):
    pass


def _sync_rule(key, actor, ctx, commit):
    """Post, re-post and reverse until this rule's entries match Planet —
    or, without `commit`, work out what that would take and write nothing.
    Returns its report."""
    holds, wanted, held_keys = [], OrderedDict(), set()

    def hold(what, why, k=None):
        # a held event keeps whatever entry it already has
        holds.append({"what": what, "why": why})
        if k:
            held_keys.add(k[:40])
    try:
        for e in COLLECT[key](ctx, hold):
            diff = e.out_of_balance()
            if diff:
                hold(e.memo, f"its entry is out of balance by {abs(diff):,.2f}",
                     e.key)
                continue
            if e.lines():
                wanted[e.key] = e
    except Hold as h:                   # the rule itself can't start
        hold(dict((r[0], r[2]) for r in RULES)[key], str(h))
    live = {}
    for j in (JournalEntry.objects.filter(
            kind="AUTO", status="POSTED", source_type=SOURCE[key],
            reversed_by__isnull=True).prefetch_related("lines")):
        live[j.source_ref] = j
    posted, reversed_, same, total, sample = 0, 0, 0, ZERO, []

    def reverse(j, why):
        nonlocal reversed_
        if commit:
            _, msg = ledger.reverse(j, actor, on=j.date, reason=why)
        else:
            from . import reconcile
            msg = (reconcile.reversal_block(j)
                   or ledger.check_date(j.date, "REVERSAL"))
        if msg:
            hold(j.memo, f"its entry {j.ref} can't be reversed — {msg}")
            return False
        reversed_ += 1
        return True
    for k, j in live.items():
        if k not in wanted and k not in held_keys:
            reverse(j, "no longer in Planet")
    for k, e in wanted.items():
        j = live.get(k)
        if j is not None:
            if _entry_signature(j) == e.signature():
                same += 1
                continue
            if not reverse(j, "changed in Planet"):
                continue
        try:
            if commit:
                ledger.post_entry(
                    on=e.on, memo=e.memo, lines=e.lines(), actor=actor,
                    kind="AUTO", source_type=SOURCE[key],
                    source_id=e.source_id, source_ref=e.key)
            elif (msg := ledger.check_date(e.on, "AUTO")):
                raise ValueError(msg)
        except ValueError as exc:
            hold(e.memo, str(exc))
            continue
        posted += 1
        total += e.total()
        if len(sample) < 40:
            sample.append({
                "date": e.on, "memo": e.memo, "amount": e.total(),
                "lines": [{"account": f"{ln['account'].code} "
                                      f"{ln['account'].name}",
                           "debit": ln["debit"], "credit": ln["credit"],
                           "site": ln["site"].code if ln["site"] else ""}
                          for ln in e.lines()]})
    return {"rule": key, "post": posted, "post_mvr": total,
            "reverse": reversed_, "same": same, "held": holds,
            "sample": sample}


def run(keys, actor, commit=False):
    """Bring the books into line with Planet for these rules — or, without
    `commit`, report what that would take. A preview reads and compares; it
    posts and reverses nothing."""
    keys = [k for k in RULE_KEYS if k in keys]
    out = []
    try:
        with transaction.atomic():
            ctx = Ctx()
            for k in keys:
                out.append(_sync_rule(k, actor, ctx, commit))
            if not commit:
                raise _Undo
    except _Undo:
        pass
    if commit:
        audit("ledger", 0, "OPERATIONS_POSTED", actor=actor, detail={
            r["rule"]: {"posted": r["post"], "reversed": r["reverse"],
                        "held": len(r["held"])} for r in out})
    return out


def take_out(key, actor):
    """Reverse every entry a rule has in the books — for when the
    accountant wants the rule done differently. The rule must be off first,
    or the next run would put them straight back. Returns (count, error)."""
    if key not in RULE_KEYS:
        return 0, "Unknown rule."
    if key in rules_on():
        return 0, "Switch the rule off first."
    n = 0
    try:
        with transaction.atomic():
            for j in JournalEntry.objects.filter(
                    kind="AUTO", status="POSTED", source_type=SOURCE[key],
                    reversed_by__isnull=True):
                _, msg = ledger.reverse(j, actor, on=j.date,
                                        reason="posting rule taken out")
                if msg:
                    raise ValueError(f"{j.ref}: {msg}")
                n += 1
    except ValueError as exc:
        return 0, (f"Its entries can't all be taken out — {exc} Nothing was "
                   "changed.")
    audit("ledger", 0, "POSTING_RULE_TAKEN_OUT", actor=actor,
          detail={"rule": key, "reversed": n})
    return n, None


def post_enabled(actor=None):
    """What the scheduled job runs: every rule that is switched on."""
    on = rules_on()
    return run(on, actor, commit=True) if on else []


def status():
    """The rules, which are on, and what each has in the books."""
    from django.db.models import Count
    on = set(rules_on())
    have = {r["source_type"]: r["n"] for r in JournalEntry.objects.filter(
        kind="AUTO", status="POSTED", reversed_by__isnull=True)
        .values("source_type").annotate(n=Count("id"))}
    return {
        "rules": [{"key": k, "name": name, "what": what, "on": k in on,
                   "entries": have.get(src, 0)}
                  for k, src, name, what in RULES],
        "from": posting_from(),
        "books_start": ledger.books_start(),
        "usd_rate": fx.usd_rate(),
    }


def heads():
    """Each cost head and the account its costs post to."""
    ctx = Ctx()
    used = set(CostPosting.objects.filter(state__in=("INCURRED", "PAID"))
               .values_list("cost_head_id", flat=True).distinct())
    out = []
    for h in CostHead.objects.filter(is_active=True).select_related(
            "ledger_account").order_by("sort_order", "name"):
        if h.code.endswith(("_REVENUE", "_OUTPUT_GST")):
            continue          # sales, posted from the invoices themselves
        try:
            a = ctx.head(h)
        except Hold:
            a = None
        out.append({"id": h.id, "code": h.code, "name": h.name,
                    "account": a.id if a else None,
                    "account_label": f"{a.code} {a.name}" if a else "",
                    "mapped": h.ledger_account_id is not None,
                    "used": h.id in used})
    return out


def map_head(head, account_id, actor):
    if account_id in (None, ""):
        head.ledger_account = None
    else:
        a = LedgerAccount.objects.filter(pk=account_id).first()
        if a is None or a.is_group or not a.is_active:
            return "Pick an account that can take postings."
        head.ledger_account = a
    head.save(update_fields=["ledger_account"])
    audit("cost_head", head.id, "HEAD_ACCOUNT_SET", actor=actor,
          detail={"head": head.code, "account": head.ledger_account.code
                  if head.ledger_account_id else None})
    return None
