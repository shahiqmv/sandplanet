# Finance app — build brief

Full double-entry bookkeeping inside PLANET, on its own surface at `/f/`
(like Trading's `/t/`), with the existing Finance module moved into it.

## Why

Books were kept in Odoo, not regularly, and the auditors re-keyed those
ledgers into their own QuickBooks to produce final accounts. There is no
trusted internal set of books. PLANET already captures almost every
transaction at source with approvals; what it lacks is the accounting core.
The owner wants books that are current the moment an operational event
happens (owner 2026-10-02).

## Decisions (owner, 2026-10-02)

1. **Entity:** Sand Planet only — one set of books covering Projects and
   Trading. Marine is a separate company; its accounting comes later (same
   code, its own instance), and the `books` feature stays off there.
2. **Start date:** books open on **1 January 2026**. Opening balances are the
   **audited 2025 closing balances** (31 December 2025).
3. **Catch-up:** the accounting staff enter 2026 to date and bring the
   records up to date. Odoo is not migrated — its data is not reliable.
4. **Chart of accounts:** PLANET ships a basic chart; the company's
   independent accounting consultant creates, renames, re-codes and
   re-groups accounts themselves. The owner will share last year's audit
   draft so the starting chart follows the audited statements.
5. **Currency:** multi-currency transactions; the books and all financial
   statements are in **MVR**. A foreign-currency line stores its own amount
   and rate alongside the rufiyaa value.
6. **Separate front door, not a separate system:** same login, same
   database. Approvals (signatory vouchers, Director's items) stay on
   PLANET's My Tasks and the phone and open into the Finance app.

7. **QuickBooks style** (owner, same day: "I actually need QB style
   accounting"). Two things follow. The chart uses **QuickBooks' own account
   types** (Bank, Accounts receivable, Other current assets, Fixed assets,
   Other assets, Accounts payable, Credit card, Other current liabilities,
   Long term liabilities, Equity, Income, Cost of goods sold, Expenses, Other
   income, Other expenses) with same-type sub-accounts — the auditors keep
   their copy in QuickBooks, so it maps one-to-one. And day-to-day entry is
   by **transaction forms, not debits and credits**: expense, bill, pay
   bills, invoice, receive payment, deposit, transfer; a register per bank
   account; reconcile; Profit & Loss and Balance Sheet with drill-down. The
   journal stays, for the accountant.
8. **MIRA** (owner, same day): the books follow the Maldives Inland Revenue
   Authority's standards and guidelines. See "MIRA compliance" below.

## MIRA compliance

Tax rules change — rates, forms, deadlines — so nothing here is coded from
memory. Each item is checked against MIRA's current published Acts,
Regulations, rulings and forms when it is built, held as a setting rather
than a constant, and confirmed by the accounting consultant.

- **GST** (Goods and Services Tax Act): output tax and input tax in their
  own accounts; every sale and purchase line carries its GST treatment
  (standard-rated, zero-rated, exempt, out of scope); tax invoices show what
  MIRA requires of a tax invoice (the words "Tax Invoice", supplier name and
  TIN, number, date, customer and their TIN, description, value before GST,
  GST, total); input tax is claimable only against a valid tax invoice; the
  GST return figures come out of the books for the taxable period.
- **Income tax** (Income Tax Act): the tax computation starts from the
  accounting profit, so accounts can be marked non-deductible and capital
  allowances are kept apart from accounting depreciation; interim payments
  and the year-end charge post to their own accounts.
- **Withholding**: tax withheld from payments to non-residents, and employee
  withholding tax from remuneration, each in its own payable account.
- **Records** (Tax Administration Act): entries are permanent, numbered
  without gaps, dated, and carry who entered and who posted them; a
  correction is a reversal, never an edit; source documents stay attached to
  the transaction; records are kept for the statutory period.
- **Statements**: in Maldivian Rufiyaa, under IFRS for SMEs as the audited
  statements state; foreign-currency transactions at the rate on the
  transaction date, monetary balances retranslated at the reporting date
  with the difference to profit or loss (the policy in the 2025 accounts).

### What MIRA's published guidance says (read 2026-10-02, mira.gov.mv)

*Tax invoice* (GST → Tax Invoice). Issued by a registered person to another
registered person within 28 days of a request. Must carry: the words "Tax
Invoice" prominently; name, address and TIN of the supplier; name, address
and TIN of the recipient; an invoice number that is pre-printed or
software-generated; date of issue; quantity and details of the goods or
services; the value excluding tax; the tax charged; the total inclusive of
tax (or a statement that tax is included in the price).

*Input tax* (GST → Input Tax, How does GST work?). Claimed on the GST
return, which is filed **together with an input tax statement**. Not
claimable when: incurred before GST registration; the supply was not in the
Maldives; **no valid tax invoice is held**; more than **12 months** have
passed since the end of the taxable period in which it could first have been
claimed; or it was incurred for exempt supplies. Excess input tax is not
refunded — it is carried forward against later output tax.

*Taxable period and return* (GST → Taxable Period; return form MIRA 205).
Monthly where average taxable sales exceed MVR 1 million a month, otherwise
calendar quarters; taxable sales include standard-rated and zero-rated.
Return and payment due by the 28th of the month after the period.

*Zero-rated vs exempt.* Zero-rated supplies are taxable at 0% (Schedule 1
essential goods, exports, transfer of a going concern): no GST charged,
input tax claimable, tax invoice raised, reported on the return. Exempt
supplies (utilities, postal, education, health, financial services, rent of
immovable property, international transport, and others listed): no GST, no
input tax claim on related costs, **no tax invoice**, still reported on the
return.

*Records* (GST Regulation): tax invoices and receipts issued and received,
credit and debit notes, the statements of output tax and input tax behind
each return, import/export documents — kept at least **5 years**.

*Income tax* (Income Tax Act 25/2019): interim payments 31 July and
31 January, final return 30 June; employee withholding tax on remuneration
above MVR 60,000 a month at progressive rates; non-resident withholding tax
10% (5% for non-resident contractors), monthly by the 15th. To be re-read
from the Act when those features are built.

**What this fixes in the design:** every purchase line records its GST
treatment, the supplier's TIN, the tax invoice number and date, and whether
a valid tax invoice is held — input GST goes to the recoverable account only
when it is, otherwise it is part of the cost. Every sales line records its
treatment (standard / zero-rated / exempt / out of scope) so the return's
figures and the two statements come straight from the books. The GST rate is
a setting with an effective date, never a constant.

## Principles

- **Every entry balances.** A journal cannot be posted unless debits equal
  credits, in rufiyaa, to the laari.
- **Posted is permanent.** A posted journal is never edited or deleted. A
  mistake is corrected by a reversal — a mirror entry — and a new journal.
  Both stay on the record.
- **Gap-free numbering** (`JV-0001…`), issued at posting.
- **Closed periods are closed.** Nothing posts on or before the lock date;
  nothing (except opening balances) posts before the books start.
- **One source of truth for a number.** Every figure on a report opens the
  journal behind it, and every automatic journal opens the document that
  caused it.
- **Automatic postings are rules, signed off.** Each operational event posts
  by a fixed rule the accounting consultant has reviewed. Rules look up
  accounts by their *role* (`system_key`, e.g. `AP_TRADE`), so the consultant
  can rename or re-code an account without breaking a rule.
- **Replayable.** Automatic posting must be able to run over documents that
  already exist — PLANET has operational history from July 2026 that needs
  journals once the rules are approved — and must never post the same event
  twice.

## Stages

The stages below are re-cut for QuickBooks-style working: stage 1 is the
engine QuickBooks also has underneath; stage 2 is the forms people work in.

### Stage 1 — the core (this build)
- Finance app shell at `/f/` (roles: Finance, Admin, Signatory, Director,
  PA read; Finance and Admin write).
- Existing pages mounted inside it: Dashboard, Payment Vouchers, Payables,
  International Payables, Receivables, Cost Heads. They also stay in the
  main app until Finance confirms the move, so no approval link breaks.
- Chart of accounts: QuickBooks' account types, sub-accounts, per-account
  currency, system roles; create / edit / close; a standard chart, shaped
  on the audited 2025 statements, offered when the books are empty.
- Journal engine: manual journals (draft → post), reversal, opening
  balances (dated the day before the books start), dimensions on each line
  (site, project, cost head, party).
- Trial balance (opening / movement / closing) and account ledger with
  running balance, both with Excel export for the auditor.
- Books settings: start date, lock date.

### Stage 2 — QuickBooks-style entry, and catching up 2026
- Transaction forms that post the journal for the user: **Expense** (paid
  from a bank or cash account), **Bill** and **Pay bills**, **Invoice** and
  **Receive payment**, **Deposit**, **Transfer** — each with GST treatment
  per line, customer / supplier, site and project.
- **Register** for each bank and cash account, and **Reconcile** against
  the bank statement (with statement import).
- **Customers and suppliers** as the parties on transactions, with their
  balances (the receivables and payables sub-ledgers).
- **Profit & Loss** and **Balance Sheet**, each figure opening its entries.
- Import from Excel, for January–June 2026 (before PLANET held the
  operations).

### Stage 3 — automatic posting from operations
Rule by rule, each reviewed by the consultant, each replayable over history:
PO issued / GRN verified (purchases, input GST, payables), payment vouchers
and settlements, petty cash, payroll lock (wages, advances, fines, pension),
certified claims and manual invoices (revenue, output GST, retention,
receivables), official receipts, import milestones and landed cost, trading
invoices and receipts, subcontract valuations.

### Stage 4 — statements and close
Profit & loss, balance sheet, cash flow; project and site P&L from the same
journals; GST return figures (output less input) for MIRA; aged receivables
and payables tied to their control accounts; month and year close with a
lock; year-end roll of profit to retained earnings.

### Stage 5 — the rest of a full set of books
Fixed asset register and depreciation, accruals and prepayments, recurring
journals, foreign-currency revaluation at period end, budgets.

## Open points
- The posting rules for construction revenue (stage of completion vs
  invoiced), retention and work in progress are the consultant's call.
- Whether the consultant gets a login of their own (a Finance-role user
  today) or a dedicated read-and-journal role.
- When the Finance group is removed from the main app's menu.
- Marine: a second set of books in its own instance, later.

## Where things live
`backend/core/ledger.py` (journal rules), `books.py` (the transaction forms,
the register, Profit & Loss and Balance Sheet), `reconcile.py` (bank
reconciliation and reading the bank's file), `books_import.py` (Excel
import), `gst_return.py` (MIRA 205 and its two statements), `posting.py` (posting
Planet's operations), `views_ledger.py` (API,
`/api/v1/ledger/*`, refused where the `books` feature is off); models
`LedgerAccount`, `JournalEntry`, `JournalLine`, `LedgerTxn`, `LedgerTxnLine`;
`frontend/f.html`, `frontend/src/finance/`.

## Built so far
- Stage 1 — live 2026-10-02.
- Stage 2, first part — Expense, Deposit, Transfer (`EXP-`/`DEP-`/`TRF-NNN`),
  the register per bank and cash account, Profit & Loss, Balance Sheet. A
  form posts its own journal; a change reverses that journal on its own date
  and posts a new one; a void reverses it. The register shows a changed or
  voided transaction once, as the bank statement does.
- Stage 2, second part — **Bills** and **Pay bills**, **Sales invoices** and
  **Receive payment** (`BILL-`/`BPAY-`/`SALE-`/`RCPT-NNN`), **Suppliers** and
  **Customers** (`LedgerParty`, added the first time a form names them and
  tied to Purchasing's supplier or Trading's customer of the same name),
  each party's account, and **aging** by due date that states whether it
  agrees with the payable / receivable accounts.
  - A bill or invoice is refused if that party's same number is already in.
  - A payment settles one party's documents in one currency. Each document
    leaves the books at the rufiyaa value it went in at; a different rate on
    the day is an exchange gain or loss (8020 / 9010).
  - A document with a payment against it is fixed until the payment is
    voided. A payment is voided, not edited.
  - **Opening items**: a bill or invoice still unpaid on 31 Dec 2025 is
    entered dated before the books start and posts nothing — its amount is
    already in the opening balances — so the 2026 payment has something to
    be set against. Aging agrees with the books once the opening
    receivables are listed this way.
  - The sales invoice here is a *record* of an invoice issued (its number as
    issued); the tax invoice itself is still raised in Projects / Trading.
- Stage 2, third part — **Reconcile** (`core/reconcile.py`): a bank or cash
  account agreed to its statement at a date, in the account's own currency.
  Lines the bank also shows are ticked; it finishes only when the opening
  balance plus the ticks equals the statement's closing balance; what is
  left is outstanding, and the finished statement proves the books' balance
  (statement + deposits not yet credited − payments not yet presented).
  - The bank's own file (Excel `.xlsx` or CSV; the header row is found by
    itself, Debit/Credit columns or one Amount column with a Dr/Cr marker)
    is paired with the books by amount, then by a reference the bank quotes,
    then by nearest date (60 days before to 5 after). What the bank shows
    that the books don't — charges, interest — is listed with a button that
    opens the expense or deposit form filled in, and is ticked on return.
  - A line on a finished statement is fixed: its transaction can't be
    changed or voided until that reconciliation is reopened; only the
    latest one reopens.
  - The first reconciliation starts from nil and lists the audited opening
    balance as a line to tick. If the bank's own balance at 31 Dec 2025
    differed (cheques then outstanding), the opening entry needs those as
    separate lines.
- Stage 2, fourth part — **Import from Excel** (`core/books_import.py`): a
  template (one row per expense, deposit, transfer, bill or invoice; a row
  with no Type is another line of the one above) with the chart and the
  sites on their own sheets. Each row goes through its form's rules. The
  file is checked first — the real import, rolled back — and every problem
  is listed by row; it then goes in whole or not at all, at most 2,000
  transactions a file. The same file is not taken twice; a batch can be
  undone (every transaction voided) unless something has been built on it.
- Stage 4, brought forward — **GST return** (`core/gst_return.py`), laid
  out on MIRA's forms as published and read on 2026-10-02: **MIRA 205 v25.1**
  (GST Return — General Goods and Services), the **Input Tax Statement
  v25.1** and the **Output Tax Statement v25.1**.
  - MIRA 205 boxes: 1 sales subject to GST at 8% (inclusive of GST); 2
    zero-rated; 3 exempt; 4 out of scope; 5 total (1–4); 6 output tax; 7
    input tax (statement attached); 8 GST on irrecoverable debts written off
    and on credit notes spanning a rate change; 9 GST collected in excess;
    10 liability (6 − 7 − 8 + 9); 11 amount paid; 12–13 plastic bag fee.
    Rounded to the nearest rufiyaa. Boxes 1–7 and 10 come from the books; 8,
    9 and 11–13 are not derived.
  - Output Tax Statement columns: Customer TIN, Customer Name, Invoice No.,
    Invoice Date, Value of Supplies Subject to GST at 8% or 17% (excluding
    GST), Value of Zero-Rated Supplies, Value of Exempt Supplies, Value of
    Out-of-Scope Supplies, Your Taxable Activity No.; a second sheet sums
    them per taxable activity.
  - Input Tax Statement columns: #, Supplier TIN, Supplier Name, Supplier
    Invoice Number, Invoice Date, Invoice Total (excluding GST), GST Charged
    at 6% / 8% / 12% / 16% / 17%, Your Taxable Activity Number, Revenue /
    Capital.
  - A sale is an invoice or deposit line with a GST treatment, on its
    invoice date; a line with none is not a supply. Input tax is the GST on
    an expense or bill with a tax invoice held — and such an expense must
    now carry the supplier's TIN and the invoice number. Anything else on
    the GST accounts in the period is listed apart.
  - Not read / not built: the table on the back of MIRA 205 (the PDF's
    second page would not read); GST paid to Customs on imports as input
    tax; one taxable activity number for the whole company (parameter
    `gst_activity_no`) — if construction and trading are separate taxable
    activities the statements need it per sale; excess input tax brought
    forward from an earlier period.
- Not yet: supplier and customer credit notes; a payment on account
  (unapplied); writing off a small balance; withholding tax on a payment.

## Stage 3 — posting from Planet (built 2026-10-02, `core/posting.py`)

The owner asked for Planet's own transactions to be posted, and what the
rules are. Each rule is **off until switched on** in the Finance app (Setup →
Posting from Planet), where it can be previewed first; the preview only
reads. Once on, a job every 20 minutes (`manage.py post_books`) keeps the
books in step. The engine works out the entry each event *should* have and
brings the books into line: a new event is posted, a changed one reversed
and re-posted, a vanished one reversed. Nothing is posted twice. Entries are
`kind=AUTO`, found again by `source_type` + `source_ref`.

| Rule | When | Entry |
|---|---|---|
| Claim invoices | claim CERTIFIED with its invoice number (a reopen reverses it) | Dr receivable (net to pay); Cr contract revenue (the work certified), Cr output GST; retention held → Dr retention receivable; advance invoiced → Cr advances from clients, recovered → Dr; contra after GST → Dr client back charges |
| Other project invoices | manual invoice raised (void or replaced by a claim reverses it) | Dr receivable; Cr contract revenue, Cr output GST |
| Trading invoices, credit notes | invoice ISSUED; credit note issued | Dr customer; Cr resort supply sales, Cr output GST; advance applied → Dr advances from clients |
| Money received | receipt recorded (deleted → reversed) | Dr the bank on the receipt (none named → "receipts not yet banked"); Cr receivable; an order advance → Cr advances from clients |
| Local purchases | cost INCURRED in Planet's cost ledger — the PO signed, or the cash purchase approved on a voucher (the owner's M7 rule: at authorisation, not at GRN); then PAID | Dr the cost head's account, by site, and input GST; Cr trade payables. Paid: Dr trade payables; Cr the bank on the voucher |
| Payment requisitions | PYR paid | Dr its cost by head and site; Cr the bank on the voucher. No cost in Planet → by what it is: petty cash top-up, salary advance (staff advances), payroll payment (wages payable), import charge (goods in transit), subcontract advance (supplier advances), deposit held (1310 / 1360) |
| Petty cash | entries approved by the PM | Dr each cost; Cr petty cash |
| Payroll | run locked (the timesheet estimate and its reversal are mirrored too) | Dr wages at gross by site; Cr wages payable. Deductions: Dr wages payable; Cr staff advances (advances, loans), Cr other income (fines). Dollar salaries paid per head: Dr wages payable; Cr bank |
| Subcontract valuations | SVC authorised; payable settled | Dr subcontract cost and input GST; Cr subcontractors payable. Paid: Dr payable; Cr bank |
| Import payments, store issues | TT paid on a milestone; imported goods received at a site | Dr goods in transit, exchange difference to FX gain / loss; Cr bank. Issue: Dr materials; Cr stock |

- **A PO approval posts nothing.** A purchase is posted when Planet's cost
  ledger says it is incurred, and a payment when the money is recorded as
  paid. A claim posts when its tax invoice exists, not on submission.
- **Cost heads → accounts**: each head has a usual account (Materials 5110,
  Labour 5130, Subcontract 5140, Plant 5150, Transport 5160, Site overheads
  and Other 5180, Import charges 5120, Permits 6240, Recruitment 6150,
  Insurance & bonds 6210, Input GST 1430, General stock 1510, Forex 9010);
  the accountant re-maps any of them on the screen
  (`CostHead.ledger_account`). A head with no account holds its costs back.
- **Held back, never guessed**: a payment whose voucher names no bank
  account, a head with no account, a receipt in two currencies, an entry on
  a reconciled statement or in a closed period. Each is listed with why.
- **Dollars** go in at the company rate (Planet stores no rate on a sales
  document); a PYR keeps the rate it was paid at.
- **From**: events dated before "post from" (default: the books' start) are
  left to the opening balances and hand entry.
- A rule switched off can have its entries taken out again (each reversed).
- **Not twice** (owner 2026-10-02: "doesn't the expense form duplicate the PV
  process?"). The Expense, Bill, Invoice and Deposit forms exist for what
  Planet does not hold — January to June 2026, and bank charges and the
  like. While a rule that overlaps a form is on, an entry dated from the
  first day Planet holds that kind of thing (and not before "post from")
  must be confirmed as not in Planet — a tick on the form, a "Not in
  Planet" column in the import sheet; kept on the entry
  (`LedgerTxn.outside_planet`, `books.planet_guard`). Earlier dates are not
  asked.

Open for the consultant: revenue on certification (vs stage of completion —
a WIP journal at period end); fines to other income; goods in transit are
not yet moved to stock when the IRN is posted (the group total is right,
the split between 1510 and 1520 is not); trading cost of sales at despatch
is not posted; a subcontract advance recovered on a valuation is not moved
off supplier advances; import GST is in landed cost, not input tax.

## Rent the company pays (built 2026-10-02, `core/rent.py`)

Owner: "set all rentals and post dues automatically so that accounts can
create PV." **Operations → Rentals** holds each thing the company rents
(`RentContract`, `RENT-001`): landlord, the site and cost head that bear it,
rent per period, monthly to yearly, in advance or arrears, agreed changes,
GST, start and end. A daily job (`manage.py rent_dues`, 06:10) raises each
period as it comes up — a `RentDue` with a **payable** (no parent document)
that Finance finds on Payables and puts on a voucher; settling it marks the
due paid. The cost goes to Planet's cost ledger for the period (source
`RENT`), and the posting rule **Rent** carries it into the books (head Rent
→ 6220). Earlier periods of a rental already under way are taken as paid
outside Planet unless "raise dues from" says otherwise.

## To settle before automatic posting (stage 3)
PLANET holds purchases, payments, payroll and claims from July 2026. If the
staff key July-onwards bills and invoices by hand and the rules then replay
that history, each would be in the books twice. Hand entry should cover
January–June 2026, and from July only what PLANET does not hold (rent,
utilities, bank charges, anything outside procurement); the consultant to
confirm the cut-over date.
