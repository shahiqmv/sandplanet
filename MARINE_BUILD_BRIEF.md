# Sandplanet Marine — Build Brief

Sandplanet Marine is a new company: marine works subcontracted to it by Sand
Planet, similar marine jobs taken directly, and heavy-vehicle rental. The
project-management workflow is Sand Planet's; the brand, the books and the
rental business are its own. This brief is the plan for running it on
Planet.

Owner decisions this brief rests on (2026-09-25):

- Same people, same workflow; different letterhead and colour theme; separate
  legal entity (own TIN, GST, bank accounts, invoice series, payroll).
- Rental module: rental agreements, periodic rental invoicing, receivables;
  each vehicle has its own rate and its own cost centre (maintenance,
  operator expenses, other running costs).
- Company Profile module not needed.

---

## 1. Placement — the decision

**Same codebase, a second running instance.** One repository and one build;
two deployments, each with its own database, media and address
(app.sandplanet.mv and marine.sandplanet.mv), on the same droplet.

Why not one Planet with a company dimension: every document, ledger row,
payroll run, numbering counter and report in Planet assumes one company.
Adding a company key to all of it is months of risky work and buys nothing
the books need — Marine's TIN, GST returns, bank accounts, invoice series and
payroll must be separate anyway. A second instance gives that separation for
free and every fix ships to both.

Why not a division inside Sand Planet's Planet: the books would mix; the
letterhead, invoice series and payroll would need per-site switches; the
legal separation would be weak.

What Marine gets on day one, unchanged: sites, DPR/DMA, material requests,
purchasing and imports, payment requests and vouchers, signatory, HR and
payroll, HSE, quality, contracts and claims, receivables, mobile app.

### The two companies' books

- In **Sand Planet's Planet**, Marine is a `Subcontractor`: a subcontract
  agreement (SCA) and valuations (SVC) → payables → payment vouchers. Already
  built (`core/subcontract.py`).
- In **Marine's Planet**, Sand Planet is a client: a site with a contract, BOQ,
  progress claims, tax invoices and receivables. Already built.
- Nothing crosses between the two databases. Each company records its own
  side, which is what an auditor expects to find.

### Users

Same usernames created in both instances by an admin; people sign in to the
company they are working in. A trusted sign-in from one instance to the
other is a contained later piece if the double login becomes a nuisance —
not built up front.

## 2. The brand layer (one change, both companies)

Today the company name, TIN, address, bank accounts and signatory come from
company parameters (`pdf.company_info`); the logo is the file uploaded on
the Company page (`pdf.logo_src`, falling back to the Sand Planet asset);
the ring brandmark and the app colours are fixed
(`pdf_templates/assets/sp-mark.svg`, `frontend/src/index.css` `--navy`,
`--sky`…).

Add, as company parameters editable on the Company page:

| Parameter | Used by |
|---|---|
| `brand_name` (short name shown in the app header) | SPA header, mobile app, trading app |
| `brand_primary`, `brand_accent`, `brand_soft` | CSS custom properties set at load from `/api/v1/auth/me` or a public `/api/v1/brand` endpoint; `index.css` keeps Sand Planet's values as the defaults |
| `brand_mark` (upload, SVG/PNG) | official-correspondence letterhead (`_letterhead_letter.html`) |
| `brand_letterhead_rule` colours | `_letterhead.html`, the invoice/quotation masthead accents |
| `company_short_code` (e.g. `SP`, `SPM`) | optional prefix on the shared series (INV, OR, PV) so a Marine document can never be mistaken for a Sand Planet one |
| `features` (JSON: `{"rental": true, "trading": false, "profile": false}`) | nav groups and API entry gates |

The PDF templates already read `co.*`; the masthead colours move from
literals to `co.brand.*` with the current values as defaults. No template is
forked.

## 3. Deployment

- `docker-compose.marine.yml` alongside `docker-compose.prod.yml`: its own
  `db` (own volume), `web` (own `.env.marine`: DB name, `ALLOWED_HOSTS`,
  media path, secret key, `COMPANY=marine`), served by the **same Caddy** with
  a second host block for `marine.sandplanet.mv`. `mediamtx` (cameras) is
  not duplicated unless Marine sites get cameras.
- `update.sh` deploys both stacks (pull once, build once, `up` twice, migrate
  each). The nightly backup and off-server copy run per database; the weekly
  restore test covers both.
- Seed: a fresh database, `migrate`, company parameters and brand for Marine,
  the admin user, the bank accounts, the cost heads (the migration seeds
  them), and the users.
- Local dev: a second `launch.json` entry (`backend-marine`, port 8001) on a
  second SQLite/Postgres database, so both brands can be seen side by side.

## 4. Rental module (new; a Planet module behind the `rental` flag)

### Data model

| Model | Notes |
|---|---|
| `Vehicle` | reg no, make/model, class (excavator, tipper, crane…), year, owner note, status (AVAILABLE / ON_HIRE / MAINTENANCE / OFF_ROAD), photo, documents (registration, insurance, roadworthiness with expiry alerts); **rate card**: hourly, daily, weekly, monthly; operator included flag and operator rate; minimum charge; fuel basis (with / without) |
| `VehicleCostCentre` | one per vehicle, created with it: the cost dimension for its running costs |
| `CostPosting.vehicle` (nullable FK) + `book = RENTAL` | maintenance PYRs, fuel, insurance, spares and the operator's payroll share post here; the project cost views ignore the RENTAL book exactly as they ignore TRADING |
| `RentalCustomer` → reuse `Customer` | the trading customer model already carries TIN, address, credit days, GST exemption |
| `RentalAgreement` (`RA` series, YYYY-RA-001) | customer, vehicles with their agreed rates (a rate can be negotiated off the card), start / end / open-ended, billing cycle (monthly / on completion / per hire), deposit, operator included, mobilisation & demobilisation charges, site/location, terms (standard lines like trading's), signed PDF; status DRAFT → ACTIVE → COMPLETED / TERMINATED |
| `HireLog` | per vehicle per day: hours run (from the operator's sheet or the site DPR), idle, breakdown; the operator (employee); the site; approved by the customer's representative |
| `RentalInvoice` (company `INV-YYYY-NNNN` series) | one per agreement per period, built from the hire logs (hours × rate, or the flat monthly), plus mobilisation, fuel, damages, extras; GST; due date from credit days; DRAFT → ISSUED → PAID / VOID; PDF |
| Receipts, credit notes, aging, statements | the trading models generalised: `TradingReceipt` → company-wide `CustomerReceipt` (the OR series already shared), `TradingCreditNote` → `CustomerCreditNote`; the Receivables page shows trading and rental invoices together |
| `VehicleMaintenance` | service schedule (hours / date based), job cards, parts from the store, downtime; the PYR for outside work posts to the vehicle's cost centre |

### Flows

1. **Fleet** — register the vehicle, its documents and rate card; expiry
   alerts (insurance, registration, roadworthiness) on the dashboard.
2. **Agreement** — draft from the customer's request, pick vehicles and
   rates, issue the PDF, customer signs, activate; the vehicle goes ON_HIRE
   for the period.
3. **Hire log** — daily hours per vehicle, entered by the operator or the
   site admin (mobile), approved weekly by the customer's representative;
   breakdown hours are not billable and count against the vehicle's
   availability.
4. **Invoice** — at the cycle end, the invoice is generated from the approved
   logs; Sales Manager / Finance issues it (posts revenue and output GST in
   the RENTAL book); the customer's receipt settles it through the shared
   receipt flow.
5. **Costs** — maintenance and running costs reach the vehicle's cost centre
   through the ordinary PYR / voucher chain (the PYR form offers vehicle cost
   centres when the rental flag is on), operator wages through a payroll
   allocation of the operator's days to vehicles.
6. **Vehicle P&L** — revenue from invoices against the cost centre, per
   vehicle and for the fleet, by month; utilisation (hours hired / hours
   available).

### Roles

`RENTAL` (agreements, hire logs, fleet), `RENTAL_MANAGER` (issues
agreements and invoices, sets rates); Finance receipts; Signatory reads. The
site roles enter hire logs for vehicles on their site.

## 5. What is skipped or deferred

- Company Profile module: off for Marine.
- Trading app: off for Marine (flag), unless the marine company later trades.
- Cross-instance sign-in: later, only if needed.
- A marine-specific document set (vessel logs, crew lists): not in scope
  until the owner describes it.

## 6. Build order

Each phase ships and stops for the owner's review.

1. **Brand layer + feature flags** — parameters, Company page fields, CSS
   variables from the brand, PDF mastheads from `co.brand`, nav gating.
   Sand Planet's instance looks exactly as it does today.
2. **Second instance** — compose file, env, Caddy host, `update.sh` for two
   stacks, backups for two databases, seed script; marine.sandplanet.mv live
   with the Marine brand and the full project workflow.
3. **Rental foundations** — RENTAL book, `Vehicle` + cost centre, rate card,
   documents and expiry alerts, roles, fleet page.
4. **Agreements and hire logs** — `RentalAgreement` with PDF, hire log entry
   (desktop + mobile), customer approval.
5. **Rental invoicing and money in** — invoice generation from logs, issue,
   PDF, the shared receipts / aging / statements generalised for rental.
6. **Costs and P&L** — vehicle cost centres on PYRs and payroll allocation,
   maintenance job cards, vehicle and fleet P&L, utilisation.

## 7. Open inputs from the owner

- The Marine brand: logo, mark, primary and accent colours, legal name, TIN,
  address, bank accounts.
- Whether Marine documents get a company prefix on the shared series
  (`SPM-INV-2026-0001`) or plain `INV-2026-0001`.
- The fleet at start: vehicle list, classes, rate card, operators.
- Billing practice: monthly in arrears on approved hours, or flat monthly per
  vehicle; who approves the hours on the customer side.
- Whether operators are Marine employees (payroll allocation) or hired with
  the vehicle from a third party (a cost centre PYR).
- Domain: marine.sandplanet.mv or a Marine domain of its own.

---
*Precedents: the trading arm (`TRADING_BUILD_BRIEF.md`) for the ledger book
wall and the customer money-in models; the subcontractor module for the
Sand Planet ↔ Marine relationship.*
