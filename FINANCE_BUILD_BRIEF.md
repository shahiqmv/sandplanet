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
`backend/core/ledger.py` (rules), `views_ledger.py` (API, `/api/v1/ledger/*`),
models `LedgerAccount`, `JournalEntry`, `JournalLine`;
`frontend/f.html`, `frontend/src/finance/`.
