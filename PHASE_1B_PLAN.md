# Phase 1B — International Procurement & HO Store — Implementation Plan

Scope: spec §5.10 (international procurement) + §6D (HO store & inventory).
Managed entirely by Head Office; requirements raised and tracked at project
level; imported goods land as **stock at landed cost** and become project
cost only at the site GRN. Four new document types: **PMR, IPR, IRN, SIN**.

This is the largest single module in the build — comparable to all of M6
combined. It is sliced into seven sub-milestones, each independently
shippable and testable. Recommended order is P1B-a → P1B-g.

---

## What already exists (foundations, no rebuild needed)

- Cost ledger with the three pools this module posts to: **General Stock**,
  **Foreign Exchange**, **Stock Adjustment** (`DEFAULT_POOLS`), and the
  reserved posting sources **IPR / STORE_ISSUE / FX / STOCK_ADJ**
  (`CostPosting.Source`).
- Payment Voucher (M6d) as the single signatory-authorisation path.
- Item Master, MAR (material approvals), MR→LM→GRN chain, Supplier list,
  document engine (state machines, revisions, approvals, PDFs, attachments).
- Costing service (`post` / `reverse_document`) — the only ledger writer.

## Key interactions with what we just built (M6/M7)

- **INCURRED timing for imports is different from local purchase.** The
  owner decided local materials are Incurred at PV authorisation because
  there is no inventory system. This module *is* that inventory system: an
  imported item carries a real **unit landed cost** on its stock lot, so
  imports post **INCURRED at the site GRN at landed cost** (§5.10.11,
  §6D.3) — the GRN becomes a cost event for store-issued goods only. Local
  purchase is unchanged. (Optional later decision: retrofit local materials
  to GRN-incurred once the store exists — not proposed here.)
- **IPR authorisation** should flow through the **Payment Voucher** like
  PR/PYR (extend the PV to accept IPR sources), keeping one authorisation
  path — see Decision D1.
- **Part payments** need a new model — the codebase has no generic payments
  table (only `Payable` + inline PYR fields).

---

## Sub-milestones

### P1B-a — Suppliers + PMR (the "requirement never disappears" slice) — DONE 2026-07-12
Standalone value first: a project requirement raised and tracked end to end.
Shipped: Supplier category/country/currency/incoterm/bank fields (bank hidden
from non-HO); PMR document (per-site `PMR-SJR-001`, project-scoped) with the
Site→PM→HO-review→Director-size-release workflow, return/cancel paths, spec +
MAR-ref line fields (soft "no approved MAR" warning), the status-thread ladder
on the doc, "🌍 Import request" button + PMR list on the site dashboard, and
PMR entries in each approver's "waiting on you" queue. NOT yet: per-line order
sizing / surplus-to-general-stock (that lands on the IPR in P1B-b).
- **Supplier/forwarder DB** (§5.10.2): add to `Supplier` — `category`
  (LOCAL / INTERNATIONAL / FORWARDER / CLEARING_AGENT), country, default
  currency, default incoterm, bank details (sensitive: HO/Finance/Admin),
  performance history (auto: on-time %, quality issues). Category filters in
  the supplier picker.
- **PMR document** (§5.10.3): new type, per-site numbering `PMR-SJR-004`,
  project-scoped. Header (required-by, discipline, BOM ref, justification);
  lines (item from Master or flagged free-text, qty, spec/model/brand, MAR
  ref with a warning when a line has no approved MAR). Workflow
  `Draft → Submitted → PM Approved → HO Staff Reviewed → Director Sized &
  Released → Sourcing → Ordered → Received → Closed` (+ Returned, Cancelled).
- **Status thread skeleton** on the site/project dashboard (fills in as the
  IPR lifecycle progresses in later slices).
- Ledger: none yet (PMR is demand, not cost).

### P1B-b — IPR + ordering + commitment — DONE 2026-07-13
Shipped: IPR document (global `IPR-001`), `ImportOrder`/`ImportOrderLine`/
`ImportAllocation` models; build the order from sized-and-released PMRs (demand
links `PMR_IPR`, PMR→SOURCING on draft, PMR→ORDERED on award); per-line
allocations split the qty between reserving projects and general stock. Workflow
Draft→Submitted→Approved (Director award)→Authorised (signatory, on a Payment
Voucher — PV extended to accept IPR sources). **COMMITTED posts at authorisation
in MVR at the agreed rate**, each project allocation to that project's site under
the line cost head, the general-stock balance to the General Stock pool. UI:
"International Orders" page (register + order form with supplier/currency/rate/
allocations + PMR demand picker) + IPR view. Migration 0038. Tests in
tests_imports.py. Full per-line demand-qty mapping is coarse (document-level PMR
links); refine if needed. NOTE original -b spec below:
- **IPR document** (§5.10.4): new type, global numbering `IPR-018`. Header
  (INTERNATIONAL supplier, currency + exchange-rate basis, incoterm, ports,
  PI ref + attachment, quotations). Lines (order qty, unit price in order
  currency, line value, **allocation** = one or more `{project, qty}` +
  general-stock balance summing to order qty, demand origin = the PMR lines
  satisfied, cost head).
- **PMR→IPR demand→order links** (many-to-one, per-line allocated qty);
  **Director consolidation + MOQ sizing** with recorded reason, surplus →
  general stock. PMR lines advance to `Ordered (IPR ref)`.
- Workflow through **Director Approved → Signatory Authorised** (via the
  Payment Voucher, D1). **COMMITTED posts at authorisation** in MVR at the
  authorisation-date rate, pro-rata to reserved projects + the **General
  Stock** pool for the unreserved balance. Withdraw/return reverse as usual.

### P1B-c — Part payments + multi-currency + FX — DONE 2026-07-13
Shipped: `ImportPaymentMilestone` (per IPR: label, trigger, percent/fixed in
order ccy, must sum to order total). HO sets the schedule + marks a milestone
DUE (its trigger met); Finance sees it in "Import Payments" and records the
actual MVR paid + TT ref. On payment: the committed-value share posts PAID to
the projects/stock at the **agreed** rate (insulating projects from FX); the
difference between actual MVR paid and that committed value posts to the
**Foreign Exchange** pool (never a project). CostPosting gained ipr_milestone
FK. API: /ipr/<ref>/milestones (set), .../<id>/due, .../<id>/pay,
/ipr/payments-due. UI: payment-schedule panel in the IPR view + Finance→Import
Payments queue. Migration 0039. NOTE: TT-advice file upload deferred to -d
(shipping-doc attachments). Original -c spec below:
- **Payment-milestone model** (new): per IPR, scheduled milestones (trigger
  + % or fixed amount), must sum to 100%. Triggers: PI attached / BL
  uploaded / arrival confirmed / date offset.
- Each due milestone becomes a **payment obligation in Finance's queue**;
  Finance executes, records the **TT reference + uploads the TT advice**
  (returns to Purchasing to share). Obligation held in order currency; the
  payment records the **actual FX rate + MVR paid**; realised FX difference
  posts to the **Foreign Exchange** pool (never a project). PAID posts here.
- Unpaid milestones on a shipped order flagged prominently.

### P1B-d — Shipment + documents + clearing — DONE 2026-07-13
Shipped: `ImportShipment` (per IPR; mode, forwarder, vessel/flight, container/
AWB, ETD/ETA, tracking, status Booked→Shipped→In transit→Arrived→Under
clearing→Cleared, + clearing charges customs/GST/port/agent/transport feeding
landed cost). `ShipmentDocument` typed uploads (BL/AWB, packing list, commercial
invoice, COO, insurance, test cert, PI, other). Completeness checklist gates the
move to Under Clearing (needs BL+packing+invoice). Uploading a B/L fires
BL-trigger milestones DUE; reaching Arrived fires ARRIVAL-trigger milestones —
both land in Finance's queue. Share-with-clearing-agent action (logged). TT-
advice upload on a paid milestone (the -c deferral). UI: Shipments & clearing
panel in the IPR view. Migration 0040. Original -d spec below:
- **Shipment records** (§5.10.6): one or more per IPR — mode (Sea/Air),
  forwarder, vessel/flight, container/AWB, ETD/ETA, tracking ref + carrier
  link, status `Booked → Shipped → In Transit → Arrived → Cleared`.
- **Shipping documents** (§5.10.7): typed attachments (BL/AWB, packing list,
  commercial invoice, COO, insurance, test certs, PI); **completeness
  checklist** gating the move to *Under Clearing*; **share-with-clearing-
  agent** action (logged). Document upload can **fire a payment-milestone
  trigger** and notify Finance.
- **Clearing** (§5.10.8): arrival/clearing statuses update every allocated
  project's dashboard; customs duty, import GST, port & handling, agent
  charges recorded against the shipment (feed landed cost).

### P1B-e — IRN + landed cost + stock lots (store core) — DONE 2026-07-13
Shipped: landed cost = goods (at agreed rate) + every shipment charge
(freight/insurance/duty/GST/port/agent/transport, freight+insurance added to
the shipment) apportioned across lines by value; live total + uplift % on the
IPR. IRN document (global `IRN-001`) opened against a shipment: count received
vs order per line, shortage/excess + damage. Posting creates `StockLot`s valued
at unit landed cost, splitting each line's received qty across its IPR
allocations (reserved projects + general stock). A discrepancy notifies the
Director. Stock lots are a company asset (HO store), not project cost — that
comes at the site GRN in -f. UI: landed-cost line + "Receive at store" on the
IPR, an IRN count/post view, and an "HO Store" page (valued lots, total value).
Migration 0042. Reservation-override (§6D.2) deferred to -f. Original spec:
- **Landed cost** (§5.10.9): `goods (at FX rate) + freight + insurance +
  duty + import GST + clearing + port & handling + local transport`;
  apportion shipment charges across lines by **value (default) / weight /
  volume**. Live order-value-vs-landed-cost + uplift % on the IPR.
- **IRN document** (§5.10.8): global `IRN-014`. Count vs packing list per
  line, shortage/excess (auto), condition/damage notes + photos; a
  discrepancy notifies the Director and forms the claim record.
- **Stock lots** (§6D.1): IRN **creates lots** valued at unit landed cost,
  applying the IPR allocations (reserved qty → projects, balance → general).
  Lot = item, source IRN/IPR, qty on hand, unit landed cost, reservation,
  location, received date. **Stock is a company asset, not project cost.**
- **Reservation + override** (§6D.2): reserved lot can't go to another site
  without a Senior-PM/Director override (audited, notifies losing PM).
  Reserved stock shows as **committed exposure** on the owning project.

### P1B-f — Onward movement: SIN + MR-from-store + INCURRED-at-GRN (imports)
- **SIN document** (§6D.3): global `SIN-042`. Source = auto-release
  (reserved) or against an MR line; lines = lot / item / qty / unit landed
  cost / remaining lot balance. Reduces stock, moves value to *In transit to
  site*. **FIFO within a reservation.**
- **Reserved-lot auto-release on clearance** (§5.10.10): SIN generated
  automatically, lot → *Awaiting shipment to site*, scheduled onto the next
  **Loading Manifest** — no site MR needed.
- **MR fulfilment source**: MR line records `Local purchase` / `Store
  issue`; Purchasing fulfils a general-stock MR line from the store via a
  SIN instead of a PR. Manifests may mix purchased + store-issued items.
- **INCURRED at the site GRN, at landed cost** (§5.10.11) — the import cost
  event. Shortage at GRN against a SIN raises a discrepancy as usual.

### P1B-g — Reporting + stock take + management dashboard
- **Store reporting** (§6D.5): stock on hand by item + value, reserved vs
  general, ageing (90/180 days), in transit (at sea + to sites), issues by
  project this month, slow-moving/dead stock. Excel/PDF export.
- **Stock take + adjustments** (§6D.4): periodic count per item/lot,
  variances need reason + Director approval, post to **Stock Adjustment**
  pool (never a project); damage/write-off with photos to the same pool.
- **Management dashboard**: stock on hand / stock in transit, reserved vs
  general; the full **PMR status thread** on site dashboards (§5.10.11) —
  status, quantities, dates, days-late-vs-required — **never prices/landed
  cost** (§6C.5).

---

## Decisions — RESOLVED (owner, 2026-07-12)

- **D1 — IPR authorisation path → YES.** Route IPR signatory authorisation
  through the **Payment Voucher** (extend the PV to accept IPR sources) for one
  consistent authorisation path.
- **D2 — Imports Incurred at GRN/landed cost → YES**, while local purchase
  stays Incurred-at-PV. The store gives the valuation the earlier decision
  lacked. Local purchase unchanged.
- **D3 — Ship the spine first → YES.** Deliver order→pay→ship→clear→receive→
  issue→GRN (P1B-a..f); **stock-take (§6D.4)** and fuller **reporting (§6D.5)**
  are a fast-follow (P1B-g).
- **D4 — FX rate source → MANUAL per transaction**, recorded on the posting
  (matches the "agreed exchange-rate basis"); no stored rate table.
- **D5 — Numbering → YES.** PMR per-site (`PMR-SJR-004`), IPR / IRN / SIN
  global (`IPR-018`).

## Rough sizing
Seven sub-milestones; P1B-a is the smallest and a good standalone start
(suppliers + PMR + status-thread skeleton). P1B-b, -c, -e are the heaviest
(ordering/commitment, multi-currency payments, landed-cost/stock-lots). Each
slice lands with tests and a browser check, same cadence as M6/M7.
