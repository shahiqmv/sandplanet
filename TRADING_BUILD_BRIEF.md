# Trading — Build Brief

Sand Planet's trading arm imports goods against confirmed customer orders and
delivers them to Maldivian customers. This brief is the working plan for
building it **inside Planet**, walled off from project management, with
Finance as the single money desk. It takes the proven design of the SPH
Inquiry Desk (`ARCHITECTURE-BLUEPRINT.md`) and keeps what fits a local
supplier; the export half of that blueprint does not apply.

Owner decisions this brief rests on (2026-09-24):

- Sand Planet trading arm, not a new company.
- Finance centralised: supplier money out through the payment voucher and
  signatory chain; customer money in through official receipts.
- Users: some existing Planet people plus new Sales users.
- Not mixed with the project-management workflow — separate app surface,
  separate documents, separate ledger book.
- Delivery is always against a confirmed order; we deliver to the customer's
  boat at Malé harbour; invoice on despatch; GST on sales.
- Numbering as proposed in §7. Quotes in USD or MVR, chosen per customer /
  order. Trading suppliers are entered by Sales in the trading app (one
  directory underneath Planet). Some existing Planet users move to the Sales
  role; Planet is one role per user, so a person cannot hold a site role and
  a Sales role at once.

---

## 1. The flow

```
Inquiry → Sourcing → Pricing → Quoted → Won (customer PO)
   → Sales Order → Import order (IPR chain, trading book) → goods in HO store
   → Delivery note(s) → Tax invoice per despatch → Receipts → Closed
```

Everything hangs off the **Trading Order** (the inquiry that became an
order). Every stage change, document, delivery and receipt writes to its
activity trail and the audit log.

Gates (copied from the blueprint, enforced server-side):

- No **Won** without an issued quotation revision.
- No **Sales Order** without the customer's PO reference (number + date,
  copy uploaded).
- No **import order** and no **delivery note** without a Sales Order.
- No **tax invoice** without a delivery note; the invoice is scoped to the
  deliveries it covers. Nothing is invoiced twice.
- Legacy or exceptional rows get an amber banner, never a silent bypass.

## 2. What is taken from the blueprint

| Blueprint mechanism | Planet version |
|---|---|
| Pricing sheet as one pure calc (`inquiryCalc`) | `trading.calc(order)` — cost in supplier currency, FX to MVR/USD, two-way margin % ↔ sell, sections, line order, freight cost vs charge-to-customer |
| Quotation with revisions | Quotation revisions on the order, letterhead PDF, revision number on the print |
| Workflow gates | §1 above, as document state-machine transitions |
| Multiple final invoices, each scoped to lines/deliveries, charges bill once | Tax invoice per delivery note; each extra charge row carries a `billed_on` stamp |
| One receipt, many invoices, oldest-first allocation | Existing **OfficialReceipt** extended to allocate across trading invoices |
| SOA merging one receipt into one credit line; date range with brought-forward | Existing client statement, given a Customer variant |
| Manager authorisation before the signature block prints | Sales Manager authorises quotation and invoice before the signed PDF is issued |
| Comments / follow-ups with @mentions, bell | New **thread** on the trading order (first comment feature in Planet) |
| Chase-list dashboard (next action date) | Trading dashboard: my inquiries by stage, next actions due, undelivered orders, overdue invoices |
| Editable override on every printed line ("blank = auto") | Delivery note and invoice lines editable before issue |

## 3. What is dropped

Commercial invoice, packing list, shipper's advice, arrival notice,
consignee overrides, export lines, consolidated shipments, declared price
overrides, cartons and per-carton packing. The customer is in the Maldives;
the leg is a delivery, not an export.

## 4. What stays the Planet way

- Typed models and state machines, approvals, audit, server-side
  gap-free numbering (`next_ref`) — instead of the `fulfilment` jsonb blob.
- Server-rendered letterhead PDFs filed as attachments (`_letterhead.html`).
- Delivery is to the customer's vessel at Malé harbour: the delivery note
  carries the vessel, the jetty, the date and who on the boat received the
  goods; our own cartage to the harbour is the only transport cost.
- Supplier side: the existing IPR → shipment → clearance → IRN → HO store
  chain, unchanged, tagged `book=TRADING`. StockLot already values goods at
  landed cost, so cost of sale is the landed cost of what a delivery note
  draws down.
- Customer side: the same OR-#### receipt series and receipt PDF; trading
  keeps its own receipt rows, aging and statements keyed to the Customer.
- GST: company parameter `gst_rate` (8) already exists; sales invoices add
  the output-GST line and the customer's TIN. Output GST goes to its own
  head under the trading book (mirror of the input-GST pool).

## 5. The wall (isolation guarantees)

1. **Own front end** at `/t/` (`t.html`, built like `m.html`), own nav.
   Project roles never see it; Sales roles never see sites, DPRs, MRs.
2. **Own roles**: `SALES` (manages own inquiries, sees all), `SALES_MANAGER`
   (authorises quotations/invoices, sees all). `FINANCE`, `SIGNATORY`,
   `ADMIN` see both worlds.
3. **No site on trading documents.** They hang off `Customer` and
   `TradingOrder`. Numbering series are separate (§7).
4. **`book` on CostPosting** (`PROJECT` default, `TRADING`). `costing.post()`
   is the only writer and gains the parameter. Every project-cost read
   (cost control, portfolio roll-up, client portal, finance dashboard
   project cards) filters `book=PROJECT`. Trading has its own P&L.
5. **Import orders** raised from a Sales Order get `origin=TRADING` and the
   trading book: same purchasing screen, same voucher, but never a project
   allocation and never on a procurement schedule.
6. The delivery note draws stock from lots reserved to the trading order;
   it can never issue project-reserved stock, and site GRNs can never
   receive trading lots.

## 6. Data model (new)

| Model | Notes |
|---|---|
| `Customer` | name, GST TIN, business reg no, billing address, island, vessels, contact, quote currency (MVR/USD), credit days, gst_exempt |
| `TradingOrder` | the hub: ref, customer, stage, owner (Sales user), next action + date, po_number/po_date, terms, currency, freight cost/charge, status; activity trail via AuditLog |
| `TradingLine` | sr_no, item/catalogue link or free text, qty, uom, supplier, cost, cost currency, fx, margin %, sell override, section, photo |
| `TradingQuotation` | revision no, issued date/by, authorised by, PDF; snapshot of lines and totals at issue |
| `TradingDelivery` | DN ref, date, customer's vessel + jetty, receiver on board, lines + qty, stock lots drawn, signed copy attachment, status DRAFT → DESPATCHED → RECEIVED; DESPATCHED unlocks the invoice |
| `TradingInvoice` | tax-invoice ref, date, deliveries covered, lines, extra charges, GST, authorised by, PDF; status DRAFT → ISSUED → PAID/VOID |
| `TradingCreditNote` | adjusts a receivable (short-settlement, return) |
| `TradingReceipt` / `TradingReceiptLine` | money in on the shared OR series, allocated across invoices; own table because the project receipt is keyed to a site |
| `TradingThread` / `TradingComment` | one thread per order, one-level replies, resolve, mentions |
| `ImportOrder.origin` + `ImportOrder.trading_order` | the supply link |
| `CostPosting.book` | the ledger wall |

Money truth: `trading.calc(order)` for pricing, `trading.money(order)` for
invoiced / received / outstanding. No screen computes money itself.

## 7. Numbering (revised 2026-09-25)

Year in the number, running number restarting each year, dashes not
slashes (a slash cannot be a file name — the old system's `2026/SO/665`
became `2026_SO_665` on disk): `2026-IN-001` inquiry, `2026-SQ-001`
quotation (revision suffix `-R2`), `2026-SO-001` sales order, `2026-DN-001`
delivery note, `2026-CN-001` credit note. Tax invoices continue the
company's own `INV-YYYY-NNNN` series shared with project claim invoices and
manual invoices (`commercial._next_invoice_no`). Receipts stay on the shared
`OR-####` series. Issued through `numbering.next_trading_ref`; migration
0249 renumbered the rows entered under the first scheme (TIN/TQ/TSO/TDN/
TSI/TCN).

## 8. Build order

Each phase ships, is verified live, and stops for owner review.

1. **Foundations** — DONE 2026-09-24. `book` on the ledger with every
   project read filtered; Customer; Sales roles; trading supplier directory
   (`Supplier.is_trading`); `/t/` shell with sign-in, nav, customers and
   suppliers pages; numbering series. Trading cost heads move to phase 4,
   where their sign convention is designed with the postings.
2. **Sales front** — DONE 2026-09-24. Inquiry register (`TradingOrder`,
   TIN series), pricing sheet (`TradingLine`, `trading.calc`: cost ccy →
   sell ccy at the company USD rate or a typed rate, margin ↔ sell,
   freight cost vs charge, GST from the company rate or exempt), stages
   derived forward from the work with explicit forward picks, quotation
   revisions frozen as snapshots (`TradingQuotation`, TQ series, `/R2`),
   Sales Manager authorisation → filed letterhead PDF (draft render
   before), Won with the customer's PO → TSO series and a locked sheet,
   Lost with a reason, activity trail, chase-list dashboard with the
   manager's authorisation queue. Sales manage their own inquiries; the
   manager and Admin manage all; Finance and Signatory read.
3. **Supply leg** — DONE 2026-09-24. From a won order the Supply tab raises
   one draft IPR per supplier (`trading.raise_import_orders`) into the
   normal chain: `ImportOrder.trading_order`, every allocation
   `trading_order`-reserved (never a project), lines linked back
   (`ImportOrderLine.trading_line`), cost head `TRD_COGS`. Purchasing
   completes and submits the draft as usual; award and signatory
   authorisation are unchanged. Commitment and payment post to the General
   Stock pool at HO in the **TRADING book**; FX and charge corrections
   carry the book. The IRN files lots with `StockLot.trading_order`, which
   site picks and MR availability never touch. The store shows "Trading ·
   TSO-nnn"; the purchasing register and order header carry the trading
   tag. The order's Supply tab shows each line's IPR, shipped, received,
   in store and landed MVR/unit, plus each import order's shipments and
   landed total. Trading heads seeded (TRD_COGS, TRD_REVENUE,
   TRD_OUTPUT_GST, TRD_FREIGHT; `CostHead.trading`) and hidden from every
   project picker.
4. **Delivery and invoicing** — DONE 2026-09-24. `TradingDelivery` (TDN):
   lines capped by what is left to deliver and what is in the store for the
   order; despatch needs the vessel and the receiver on board, draws the
   order's lots FIFO, posts cost of sales (TRD_COGS, INCURRED, book TRADING)
   at landed cost and files the delivery-note PDF; the signed copy marks it
   received. `TradingInvoice` (TSI): one or more despatched notes at the
   authorised quotation's prices, quoted freight billed once, extra charges,
   GST unless exempt, due date from the customer's credit days; the Sales
   Manager issues it (needs the customer's TIN), which posts revenue and
   output GST and files the tax-invoice PDF; void reverses and frees the
   deliveries. `TradingCreditNote` (TCN) reduces the receivable with the GST
   share. `TradingReceipt` on the shared OR series (Finance/Admin only):
   oldest-first auto-allocation across the customer's open invoices, the
   official-receipt PDF, invoices flip to PAID when settled. Receivables
   page: aging by customer (not due / 1–30 / 31–60 / 61–90 / 90+), receipts
   register, statement of account with brought-forward and PDF.
5. **Collaboration and reporting** — threads with mentions and a bell,
   trading P&L and margin per order, registers, exports.

## 9. Open points

- GST: 8 % on all sales assumed (company parameter); `Customer.gst_exempt`
  exists for any exception the owner names.
- Sales users: the owner assigns the role on the Users page (existing people
  change role; new people are created as Sales).
- **Carrier site — resolved 2026-09-24.** No trading site is needed: every
  IPR already sits on the head-office site, and its cost is split per
  allocation. A trading allocation posts to the stock pool at HO in the
  TRADING book, so nothing reaches a project and no site list changes.

---
*Source design: `ARCHITECTURE-BLUEPRINT.md` (SPH Inquiry Desk). July 2026
architecture decision (separate app, shared backend, ledger book) stands.*
