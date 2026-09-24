# Inquiry Desk — Architecture Blueprint

**Purpose of this document:** hand it to a fresh Claude Code session (or any developer) to build the same
inquiry-to-cash architecture for a new company. It captures the proven design of *SPH Inquiry Desk* (live for
two companies since Aug 2026: SPH Global Holdings, Dubai and SFS Ventures, India) — the stack, data model,
core mechanisms, and the mistakes we already paid for so you don't pay for them again.

> **Decide first — new codebase or third company in the existing one?**
> The SPH codebase is deliberately multi-company: one repo, `VITE_COMPANY` build switch, separate Supabase
> project + Vercel project per company. If the new company's workflow is *also* inquiry → quote → order →
> ship → invoice → collect, the cheapest path is a third company config in the existing repo, not a rebuild.
> Build fresh only if the domain is genuinely different. The rest of this document assumes a fresh build.

---

## 1. What the app is

A lightweight **inquiry-to-cash** web app for a small trading/procurement team (2–5 internal users,
20–50 active inquiries). It replaces CRM + Excel pricing sheets + Word documents. One inquiry flows through:

```
Inquiry logged → Sourcing → Pricing → Quoted → Won (customer PO → Sales Order)
   → Procurement (supplier POs, payments) → Shipment(s) → Customs/shipping documents
   → Final invoice(s) → Receivables → Paid
```

Everything hangs off the **inquiry** record. Every stage change, document issue, and payment writes to an
activity log on the inquiry.

## 2. Stack (proven, near-zero monthly cost)

- **Frontend:** React + Vite + Tailwind, single-page app. No component library — small hand-rolled
  `components/ui.jsx` (Card, Btn, Field, StageChip, …) + a theme module.
- **Backend:** Supabase only — Postgres, Auth (email+password), Storage (attachments, photos, logos),
  Edge/RPC functions (plain Postgres functions via PostgREST), Realtime.
- **Hosting:** Vercel static deploy of `vite build` output. Deploy is one bash script, no CI needed.
- **PWA:** vite-plugin-pwa; installable, service worker auto-updates when the window regains focus.
  ⚠️ This causes the #1 support complaint: "I don't see the change" = stale cached bundle. Answer is always
  "reload once (⌘R)". Design your announcements around it.
- **Documents (quotation, invoices, packing list, …):** plain React components rendered into a portal
  overlay with a dedicated print stylesheet (`window.print()` → PDF). No @react-pdf, no Puppeteer.
  Letterhead fidelity is fine and iteration is 10× faster.

## 3. Repository layout

```
repo/
  CLAUDE.md                  # build brief for AI sessions: rules, per-company table, build order
  deploy-cloud.sh            # build + vercel deploy, --company flag switches target
  .env.cloud                 # company A secrets (SUPABASE_* keys, VERCEL_TOKEN) — git-ignored
  .env.cloud.<b>             # company B secrets — git-ignored
  .env.cloud.example         # blank template — committed
  supabase/migrations/       # numbered SQL files 0001…, pushed with `supabase db push --linked`
  prototype/                 # the Vite app
    src/
      theme.js               # palette P, IS_<COMPANY> flag, stages, input styles, constants
      lib/                   #   pure logic — no React
        db.js                #   ALL Supabase I/O: loadAll(), persistInquiry(), row<->object mappers
        calc.js              #   pricing engine (pure function inquiryCalc(q))
        payments.js          #   money summary per order (paymentsSummary(q))
        format.js            #   fmtMoney/fmtDate/num/uid/today/addDays
        shipments.js         #   shipment helpers (orderShipments, assignableOrders, totals)
      state/
        AuthContext.jsx      #   session + role
        DataContext.jsx      #   THE data layer (see §6)
      components/            #   ui.jsx primitives + feature components (CommentsThread, …)
      inquiry/               #   per-inquiry tabbed pages (Overview, Pricing, Quotation, Fulfilment, Invoicing)
      screens/               #   top-level screens (Dashboard, InquiryList, Shipments, Receivables, Accounting…)
      documents/             #   printable docs per company + shared doc CSS (docStyles.js)
```

## 4. Multi-company pattern

One codebase, N fully separate deployments:

- `VITE_COMPANY=<key>` at build time selects branding. `theme.js` exports `IS_<COMPANY>` booleans; palette,
  logos, wording, and **document sets** switch on it.
- **Each company gets its own Supabase project and its own Vercel project.** No shared data, no shared auth.
- Editable company identity (legal name, address, TRN/GST, bank details for invoices, logo, export
  registrations) lives in a `company_settings` table (single row, id=1) edited on a Company page — the
  document components read it via a module-level `getCompany()` that is fed once on load and on save.
  **Do not hardcode bank details or addresses in document components.**
- Customer-facing documents are fully company-specific files (no shared layout/wording between companies);
  operational logic is shared and gated with `IS_<COMPANY>` where behavior differs.
- Discipline rule that saved us repeatedly: when a request is company-specific, gate it. Never restyle one
  company's documents while touching another's.

## 5. Database schema (the shape, not the DDL)

Core tables (all with RLS enabled; policy = any authenticated user full access, except profiles which are
self-update + manager-update; grant table access to `authenticated`):

| Table | Purpose / notes |
|---|---|
| `profiles` | mirrors auth.users; `role` (sales / finance / manager), full_name. |
| `clients` | customers: billing_address, contacts jsonb, business_reg_no, `consignee_block` (override printed as consignee on shipping docs — first line = name), `export_lines` (VAT/contact extra lines on customs docs). |
| `suppliers`, `forwarders` | simple directories. |
| `catalog_items` | reusable item master (name, description, uom, photo, HS code, COO). |
| `inquiries` | the hub. Flat columns for list-screen fields (ref, client_id, stage, po_number, terms, freight_*, next_action_date…) + **one `fulfilment` jsonb** holding everything else: quotation snapshot, so, supplierPOs, shipment (single-order), docs {ci,pl,sa,an,pi,inv}, docsChecklist, invoices[], payments[], adjustments[], settlement, docsAuth, plRows, finalCharges. This blob pattern is the key speed win: new features rarely need migrations. |
| `line_items` | one row per pricing-sheet line: sr_no (order), qty, supplier cost + currency + fx, margin_pct, sell override, hs_code, section, photo_path, `shipment_id` (which shipment carries it), catalog_item_id. |
| `activity_log` | (inquiry_id, entry_date, text) — append-only trail. |
| `inquiry_comments` | threaded follow-ups: parent_id (1-level replies), author_id/name, body, resolved bool, `mentions uuid[]`. Own table so posting never races the inquiry save. |
| `shipments` | cross-order shipment registry: ref, client, status, mode/carrier/AWB/ports, `packages` jsonb (carton label + net/gross/dims/cbm per carton), `line_pkg` jsonb ({line_item_id: carton no}), `consolidated` bool + `price_overrides` jsonb (declared CI values for multi-customer shipments), `export_info` jsonb, `marks_nos`. |
| `sequences` | atomic document numbering — see below. |
| `company_settings` | single-row company identity + bank details. |
| commission tables | claims/entries/settings — only if the business pays sales commissions. |

**Atomic numbering:** a `sequences` table (key, prefix like `IN/XXX/{YYYY}/`, next_val, padding) with a
`next_number(p_key)` Postgres function doing `UPDATE … RETURNING` — one call per document, no duplicates
ever. Every numbered thing (inquiry ref, quote LQ, SO, PI, INV, CI, PL, SA, AN, supplier PO, shipment ref)
goes through it. **Never generate numbers client-side.**

**Realtime:** one migration creates/extends the `supabase_realtime` publication for every shared table.
The client subscribes to `postgres_changes` on all of them and debounce-refreshes (1.5 s).

**RPC for child-row replacement (CRITICAL — bug we shipped and fixed):** the app persists an inquiry's
line items and activity log by *replace-all*. Doing DELETE then INSERT as two requests lets two overlapping
saves interleave (delete, delete, insert, insert) → **the whole list duplicates**. The fix is a single
Postgres function `replace_inquiry_children(p_inquiry_id, p_items jsonb, p_notes jsonb)` that deletes and
re-inserts in ONE transaction, keeping existing uuid ids (so references like `shipments.line_pkg` survive
edits) and generating ids only for new rows. Build this from day one.

## 6. Frontend data layer (`DataContext`)

This is the heart. Principles:

- **Load everything once** (`loadAll()` = one `Promise.all` of selects), assemble inquiries with their
  items/activity/comments grouped in JS. At 20–50 active inquiries this is fast and makes every screen a
  pure in-memory render. Do not build per-screen fetching.
- **Optimistic local writes:** `updateInquiry(id, patch)` merges into local state immediately, then
  **debounces** the persist 500 ms per inquiry (pricing-sheet typing coalesces), and **serializes** persists
  per inquiry (a save waits for the in-flight one — never two concurrent writes for the same inquiry).
- **Refresh without clobbering:** re-pull on window focus, every 2 min while visible, and on realtime
  events. A refresh keeps the local copy of any inquiry edited in the last 10 s and keeps locally-created
  rows whose insert hasn't landed. This makes multi-user editing feel safe without real CRDTs.
- **Derived stage auto-advance:** pre-Won stages (Sourcing/Pricing/Quoted) derive forward from actual work
  (supplier assigned, costs entered, quotation issued) — never backward, and explicit stage picks win.
- **Roles:** view everything; manage only your own inquiries (finance & manager see all). Enforce in UI via
  a `canManage` rule + `<fieldset disabled>` around whole pages for view-only users.

## 7. Core mechanisms worth copying exactly

### 7.1 Workflow gates (quotation → SO → shipping)
Users WILL mark orders Won and ship them without ever issuing a quotation unless you block it:
- Stage cannot enter the won-family without an issued quotation number (alert + redirect to Quotation tab).
- "Customer PO → convert to SO" requires the issued quotation.
- Starting a shipment requires it too. Legacy offenders get a visible amber banner, not a hard lock.

### 7.2 Pricing sheet
Behaves like Excel: live recalculation, per-line supplier currency + FX to USD, two-way margin% ↔ selling
price, drag-to-reorder (order persists via sr_no and drives all documents), section headings, "set all
margins", freight block (cost vs sell, charge-to-client toggle). All math in one pure `inquiryCalc(q)` —
components never compute money themselves. `paymentsSummary(q)` is the single money-truth for
invoiced/paid/outstanding.

### 7.3 Documents
- One overlay viewer component; each document is a React component using shared primitives
  (Letterhead, BillTo, KV table, totals, Sig, Foot) + per-company CSS (`DOC_CSS`).
- Commercial Invoice shows customer selling prices ONLY — never supplier costs. HS code column hides
  entirely when no line has one.
- Consignee logic: documents print client name + billing address unless the client has a
  `consignee_block` override (projects, parent companies). A "Buyer" box (if the export format needs one)
  mirrors the consignee/customer — do NOT create a third address field; we did and removed it.
- Manager authorization gate (`docsAuth`) prints the signature block only after a manager authorizes.

### 7.4 Shipments
- **Single-order** shipment lives in the inquiry blob (simple case). **Registry shipments** (own table)
  carry lines from one or many orders: tick line items in, assign each line to a carton
  (`line_pkg`), cartons carry label + weights/dims. Packing list prints per carton: bold label + its
  assigned items with quantities. An order's status timeline reflects the most advanced of its own shipment
  AND any registry shipment carrying its lines.
- **Consolidated shipments** (ship many customers' goods in a related company's name): `consolidated` flag
  frees line assignment from same-customer, consignee is the related company, CI prints editable *declared*
  unit prices (`price_overrides`, `_freight` key overrides freight).
- Empty shipments must be deletable.

### 7.5 Invoicing that follows deliveries
Orders ship in parts; customers need an invoice per delivery (GRN matching). Model: `invoices[]` on the
inquiry allows **multiple Final invoices**, each optionally scoped to `lineIds` + `inclFreight` +
a snapshot of extra `charges` (actual freight/handling for FOB orders, entered at invoicing time).
Receivable = **sum of issued finals** (before any: the quote total). Part-invoices print their own lines and
balance with no cross-invoice netting. Quoted freight rides the first invoice; each charge row bills once
(`billedOn` stamp). The register shows order-level balance only on the latest final (no double counting).

### 7.6 Receivables & statements
- **One receipt, many invoices:** "Receive customer payment" picks a customer, takes amount/date/ref/method,
  auto-allocates oldest-first (editable), writes one payment entry per settled order sharing the same
  ref/date/batchId, flips orders to Paid when settled.
- **SOA** merges payment entries sharing date+ref into ONE credit line listing the settled invoice numbers;
  supports a date range (older entries collapse into a "Balance brought forward" opening row).
- **Receipt register**: one row per receipt (grouped like the SOA), expandable allocation breakdown.
- Credit/debit notes adjust the receivable; settlement-short close writes off a deduction.

### 7.7 Comments / follow-ups
Own realtime table, one thread per inquiry: top-level comments + one-level replies, resolve/reopen,
`@mention` autocomplete storing user ids. Surfaced three ways: floating 💬 drawer on every inquiry tab,
💬 count chips on list rows (deep link `?comments=open` auto-opens the drawer), and a nav bell counting
open threads on inquiries you own or are tagged in.

## 8. Deploy pipeline

`deploy-cloud.sh`: sources the company env file, `VITE_COMPANY=<key> npm run build`, deploys `dist` to the
company's Vercel project (`--company x` switches env + project + output folder). Migrations:
`supabase link --project-ref <ref> -p $SUPABASE_DB_PASSWORD && supabase db push --linked --yes` per project.
Feature work lands on all companies unless company-specific; deploy each affected app.

## 9. Operational & safety rules (non-negotiable)

1. **Never** run `supabase db push --include-seed` or any user-seeding script against production.
2. Secrets live only in git-ignored `.env.cloud*`; commit blank `.example` templates. Never echo secrets
   into chat/logs.
3. **Verification pattern** (how we test on production without touching real users): create a disposable
   manager user via the admin API, mint a token via password grant, inject the session JSON into
   `localStorage['sb-<ref>-auth-token']` in a browser tab on the app origin, act, then delete the user and
   every `ZZ-`-prefixed test row. If a test consumes a document number, roll `sequences.next_val` back with
   a compare-and-set UPDATE. Never leave temp users or test data behind (orphaned profiles show up in user
   pickers — we found one months later).
4. SQL inspection/fixes on production go through the Supabase management API
   (`POST /v1/projects/<ref>/database/query`).
5. Git: commit after each meaningful change. In scripted edits, compute the whole output first, write to
   `path + '.tmp'`, then rename — a bare `open(path,'w')` truncates before your edit runs, and we lost a
   file that way pre-git (recovered it by decompiling the minified dist bundle; don't repeat this).

## 10. Pitfalls we already paid for (read twice)

- **Delete+insert child rows without a transaction ⇒ duplicated lists** under concurrent saves. Atomic RPC
  + per-inquiry save serialization (§5, §6).
- **Regenerating child-row ids on every save** silently breaks anything referencing them (carton
  assignments, price overrides). Preserve ids through the replace.
- **PWA stale bundle** makes users report fixed bugs as unfixed. Always tell them: one reload.
- **Auto-generated document content nobody can edit** (marks & numbers, packing-list contents) will be
  wrong for someone eventually. Every printed line needs either an editable override field ("blank = auto")
  or a user-owned source of truth.
- **Money entered in more ways than one place** drifts. One calc function, one payments summary, receipts
  only through the allocation flow.
- **Missing workflow gates** let users skip the quotation entirely (found in production). Gate forward
  motion, banner the legacy rows.
- zsh eats `UID` as a readonly variable — name shell vars `TUID` in ops scripts.

## 11. Build order for the new session

1. **Phase 0 — brief:** write the new company's `CLAUDE.md` from this blueprint: identity, numbering
   formats (`{CODE}/{COMPANY}/{YYYY}/###`), currency/tax regime, document set differences, spec of the
   business flow. List open questions for the owner (bank details text, LQ start number, VAT, logo file).
2. **Phase 1 — core:** Supabase schema + RLS + sequences + realtime; auth + roles; inquiries CRUD; stage
   machine + gates; chase-list dashboard; pricing sheet + calc; clients/suppliers; activity log; DataContext.
3. **Phase 2 — quotations:** photos, quotation doc + revisions, numbering.
4. **Phase 3 — fulfilment:** SO conversion, supplier POs + payments, shipments module (incl. registry +
   cartons), documents (CI/PL/SA/AN), proforma + final invoices (multi-final from day one), payments,
   receivables + SOA + receipt register.
5. **Phase 4 — collaboration & reporting:** comments/mentions/bell, registers, aging, statements, exports.
6. Stop for owner review at each phase boundary. Verify every deployed change live with the disposable-user
   pattern before reporting it done.

---
*Source system: sph-inquiry-desk (React/Vite/Tailwind + Supabase + Vercel), migrations 0001–0032 as of
2026-09-24. Questions this document can't answer are usually answered by reading the corresponding file in
that repo — layout in §3.*
