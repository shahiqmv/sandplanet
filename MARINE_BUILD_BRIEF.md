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
- Brand and company details: `SANDPLANET_MARINE_BRAND.md` (authoritative);
  logo files in `backend/pdf_templates/assets/marine/`.
- Vehicles are billed **per day**, from a **daily register approved by the
  customer's representative at their site**; operators are **Marine
  employees** (payroll allocation to the vehicle's cost centre).
- Domain: **marine.sandplanet.mv** (owner: on sandplanet.mv).

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

Marine's values, from `SANDPLANET_MARINE_BRAND.md`: legal name SANDPLANET
MARINE PRIVATE LIMITED, Reg. C21442026 (16 June 2026), TIN 1184934, Fehiali,
Gn. Fuvahmulah. Palette: marine navy `#0E1C29`, deep blue `#16527E` (shared
with the parent), ocean `#2E6FA6`, wave `#407FAF`, sky `#29ABE2` (shared),
mist `#EAF3F9`. Same type family as Planet (Barlow Condensed / Inter / IBM
Plex Mono). Lockup = document header and app bar; emblem = favicon and
small marks; white wordmark on navy. The logo files are raster (upscaled
from a PNG) — sized explicitly in templates, never stretched; replace with
the designer's vector when it arrives.

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
| `brand_mark` (upload, SVG/PNG) | official-correspondence letterhead (`_letterhead_letter.html`); Marine: `spm-emblem.png` |
| `brand_wordmark_white` (upload) | app header on the navy bar; Marine: `spm-wordmark-white.png` |
| `brand_letterhead_rule` colours | `_letterhead.html`, the invoice/quotation masthead accents |
| `company_short_code` (e.g. `SP`, `SPM`) | optional prefix on the shared series (INV, OR, PV) so a Marine document can never be mistaken for a Sand Planet one |
| `features` (JSON: `{"rental": true, "trading": false, "profile": false}`) | nav groups and API entry gates |

The PDF templates already read `co.*`; the masthead colours move from
literals to `co.brand.*` with the current values as defaults. No template is
forked.

### One address for all three (owner 2026-09-25)

The main URL stays **app.sandplanet.mv**. The top bar carries an app
switcher: Projects, Trading (`/t/`), and Sandplanet Marine. Marine is still
its own instance (own database, own session), but Caddy serves it under
the path **app.sandplanet.mv/marine/** (`handle_path /marine/*` →
the marine `web` container; Django `FORCE_SCRIPT_NAME=/marine`,
`SESSION_COOKIE_NAME=marine_sessionid`, `CSRF_COOKIE_NAME=marine_csrftoken`,
cookie paths `/marine`, `STATIC_URL=/marine/static/`). The front end detects
the prefix (`brand.js: PREFIX`) and points every request and cookie at it,
so one build serves both. A person signs in once per company; the switcher
takes them across.

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
| `HireLog` (the daily register) | one row per vehicle per day: on hire (billable day) / idle / breakdown / off-hire, hours run for the record, the operator (a Marine employee), the customer site, remarks; **approved by the customer's representative at their site** (the site's client user on the mobile app, or a signed register uploaded) — a day bills only once approved |
| `RentalInvoice` (company `INV-YYYY-NNNN` series) | one per agreement per period: **approved billable days × the daily rate** per vehicle (the rate card also holds hourly / weekly / monthly for the odd job), plus mobilisation, fuel, damages, extras; GST; due date from credit days; DRAFT → ISSUED → PAID / VOID; PDF listing the days billed |
| Receipts, credit notes, aging, statements | the trading models generalised: `TradingReceipt` → company-wide `CustomerReceipt` (the OR series already shared), `TradingCreditNote` → `CustomerCreditNote`; the Receivables page shows trading and rental invoices together |
| `VehicleMaintenance` | service schedule (hours / date based), job cards, parts from the store, downtime; the PYR for outside work posts to the vehicle's cost centre |

### Flows

1. **Fleet** — register the vehicle, its documents and rate card; expiry
   alerts (insurance, registration, roadworthiness) on the dashboard.
2. **Agreement** — draft from the customer's request, pick vehicles and
   rates, issue the PDF, customer signs, activate; the vehicle goes ON_HIRE
   for the period.
3. **Daily register** — one line per vehicle per day, entered by the
   operator (a Marine employee) or the site admin on the mobile app;
   the customer's representative approves the register at their site (the
   client user on the mobile app, or a signed paper register uploaded);
   breakdown and off-hire days are not billable and count against the
   vehicle's availability.
4. **Invoice** — at the cycle end, the invoice is generated from the approved
   days at the daily rate; Rental Manager / Finance issues it (posts revenue
   and output GST in the RENTAL book); the customer's receipt settles it
   through the shared receipt flow.
5. **Costs** — maintenance and running costs reach the vehicle's cost centre
   through the ordinary PYR / voucher chain (the PYR form offers vehicle cost
   centres when the rental flag is on); operators are Marine employees, so
   their wages reach the vehicle through a payroll allocation of the
   operator's days to the vehicles they ran (from the same daily register).
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

1. **Brand layer + feature flags** — DONE 2026-09-25. `core/brand.py`
   (tokens + Sand Planet defaults, `features`, `apps`), the `{% brand
   "token" %}` template tag (all 28 PDF templates carry no literal brand
   colour any more — a test guards it), `GET /api/v1/brand` (public),
   `company/brand/<kind>` uploads (mark, white wordmark, emblem; the mark
   feeds the letterhead), the Brand section on the Company page, CSS
   variables applied at load (`frontend/src/brand.js`), brand-aware headers,
   the **app switcher** in the top bar (Projects / Trading / sister apps
   from the Company page), the Company Profile nav gated on its flag, and
   prefix-aware API/cookie names so the same build can serve a sister
   instance under app.sandplanet.mv/marine/ (phase 2). Sand Planet's
   instance is unchanged.
2. **Second instance** — DONE 2026-09-25 (code); goes live on the droplet
   with `.env.marine`. `APP_PREFIX=/marine` in settings (FORCE_SCRIPT_NAME,
   prefixed MEDIA_URL, `marine_sessionid` / `marine_csrftoken` cookies on
   path `/marine`), `docker-compose.marine.yml` (db-marine + web-marine,
   own volume, `.env.marine`, `SEED_COMMAND=seed_marine`), the Caddy
   `handle_path /marine/*` route on the main domain, `update.sh` deploying
   both stacks when `.env.marine` exists and installing the Marine crons,
   `deploy/backup.sh` with `STACK=marine`, the `seed_marine` command
   (identity, brand, palette, logo files from the assets folder, FVM head
   office, categories, admin), a `backend-marine` dev entry on port 8001
   with its own SQLite file and media folder, and the Vite proxy for
   `/marine/`. Verified locally: app.sandplanet.mv/marine/ signs in on its
   own session while the root session stays untouched.

   **Go-live steps on the droplet:** copy `.env.marine.example` to
   `.env.marine` and fill it (Marine's own Spaces bucket, secret key,
   password); `RUN_SEED_MARINE=1 bash update.sh` once; on Sand Planet's
   Company page add the sister app "Sandplanet Marine → /marine/"; on
   Marine's Company page enter the bank accounts and change the admin
   password; create the users.
3. **Rental foundations** — DONE 2026-09-25. `CostPosting.book = RENTAL`
   and `CostPosting.vehicle` (the cost centre); rental heads seeded
   (RNT_REVENUE / MAINTENANCE / FUEL / OPERATOR / INSURANCE / OUTPUT_GST,
   `CostHead.rental`, kept out of every project picker); roles `RENTAL`
   and `RENTAL_MANAGER` (`User.FLEET_ROLES`; Finance, Signatory, Admin,
   Director read); `Vehicle` (register, status, photo, rate card with the
   daily rate as the billing basis, operator included or priced, fuel
   basis, minimum charge, purchase cost, hour meter, default operator) and
   `VehicleDocument` (registration / insurance / roadworthiness / permit
   with expiry); `core/fleet.py` + `/api/v1/fleet/…` behind the `rental`
   switch (404 when off); the `fleet_expiry` daily command (alerts at 30
   and 7 days and overdue, once per level, to the Rental team and Admin;
   cron installed for both stacks); the Fleet page in the main app (nav
   group shown only with the switch on; Rental roles land on it) with the
   register, summary tiles, the expiring-documents watch, the vehicle
   detail with rate card and documents. Only the Rental Manager changes a
   rate on the register; whoever adds a vehicle may type its first rate.
4. **Agreements and the daily register** — DONE 2026-09-25. `RentalAgreement`
   (`YYYY-RA-001`, customer, job, site, start / open-ended end, monthly or
   on-completion billing, currency, deposit, mobilisation / demobilisation,
   the customer's representative who approves the register, PO, payment
   terms and conditions copied from the standard lines in company
   parameters `rental_terms_*`) with `RentalAgreementVehicle` lines at the
   agreed daily rate (defaults to the card; only the Rental Manager
   negotiates), the letterhead agreement PDF (draft watermark until
   activated, stored on activation, signed copy uploaded after), and the
   status flow DRAFT → ACTIVE (vehicles go ON_HIRE; header locked to rep /
   PO / location / end / notes) → COMPLETED or TERMINATED with a reason
   (vehicles released unless another live agreement holds them).
   `HireLog` is the daily register: one row per vehicle-line per day,
   WORKED / STANDBY (billable) / BREAKDOWN / OFF_HIRE (not), hours,
   operator, remarks; days outside the hire period refused; bulk-saved
   from a month grid on the agreement; approved for a window in the name
   of the customer's representative (in the app, or on paper with the
   signed sheet attached) — approved days lock, the Rental Manager can
   reopen unbilled ones; a vehicle with register days cannot leave the
   agreement. `core/rental.py`, `/api/v1/fleet/agreements…`,
   `/fleet/customers` (the trading Customer rows, reachable by the Rental
   roles), `/fleet/terms`; Fleet page tabs Vehicles / Hire agreements
   (`FleetRental.jsx`). Mobile entry of the register and the client-portal
   approval are deferred to the portal work.
5. **Rental invoicing and money in** — DONE 2026-09-25. `RentalInvoice` on
   the company INV series (`commercial._next_invoice_no` counts it): raised
   on an agreement for a period from the APPROVED billable days not yet
   billed (one row per vehicle: days × agreed rate, operator days at the
   operator rate when priced separately), plus mobilisation / demobilisation
   once each and ad-hoc charges; GST at the company rate unless the customer
   is exempt; due = invoice date + the customer's credit days; each billed
   `HireLog` points at its invoice so nothing bills twice. The Rental
   Manager issues (TIN guard) → revenue posts per VEHICLE cost centre
   (`CostPosting.vehicle`, book RENTAL, head RNT_REVENUE; charges without a
   vehicle; RNT_OUTPUT_GST) and the tax-invoice PDF is stored; void reverses
   the postings and frees the days (refused once money is received).
   `RentalReceipt` / `RentalReceiptLine` on the shared OR series
   (`receipts.next_receipt_no` counts it), Finance-only, allocated
   oldest-first; aging and the statement of account mirror trading's on the
   rental tables (same statement PDF template). Fleet page tabs Invoices and
   Receivables; the agreement shows its invoices and the "bill approved
   days" preview (`FleetMoney.jsx`). Also 2026-09-25: Marine's palette
   moved off Sand Planet's navy to a sea-teal family so the two apps read
   differently at a glance — `manage.py brand_palette marine` (the seed
   applies it on first run; the Company page can fine-tune tokens).
6. **Costs and P&L** — DONE 2026-09-25. `PaymentRequest.vehicle` (+ optional
   `maintenance_job`): a PYR on a fleet cost head (`/cost-heads?rental=1`:
   maintenance / fuel / operator / insurance) needs its vehicle and every
   posting it makes — COMMITTED, PAID, INCURRED — carries the vehicle in the
   RENTAL book (`payments.cost_centre`); the Rental team raises them from
   the vehicle page, filed at Head Office on the central chain (Rental roles
   added to the PYR creators and central raisers; `scoped_site_ids` treats
   them as HO). Payroll: on lock, an operator's gross follows the vehicles
   they ran that month per the register (`fleet_costs.operator_allocation`:
   the line's per-day rate × days on each vehicle, never more than the
   gross) to RNT_OPERATOR against the vehicle; the rest stays site labour;
   reopen reverses both. `MaintenanceJob` (`YYYY-MJ-001`): kind, opened /
   closed, hour meter (updates the vehicle's), description, work done,
   vendor, downtime, next service; an open card puts an AVAILABLE vehicle
   into MAINTENANCE and closing it releases it; its cost is the PYRs charged
   to it. `fleet_costs.pnl` per vehicle over a period: revenue (the
   invoices' per-vehicle postings), costs by head, margin and %, days on
   hire, breakdown days, hours, utilisation (hire days / calendar days), a
   "not on a vehicle" row and the fleet total; USD postings at the company
   rate. Fleet page tab P&L; the vehicle page carries its cost centre P&L,
   job cards and the costs charged (`FleetCosts.jsx`).

   **Customers vs clients** (owner 2026-09-25): a customer is who we hire or
   sell to (`Customer`), a client is who we build for (the site's client
   block); the same company is often both, so `Customer.project_client`
   names the site it is the client of, `/fleet/project-clients` lists the
   sites' clients to start a customer from (name, address, TIN, contact
   copied); an existing client is picked straight from the agreement's
   hirer list ("Our project clients") and `POST /fleet/customers
   {from_site}` makes the linked customer from the site's client block in
   one step — or returns the one already linked, so a client is never
   duplicated; a linked customer's name, address, TIN, contact, phone and
   email are read-only and follow the site (post_save on Site →
   `rental.sync_client_customers`); the Fleet page has a Customers tab with the full record (TIN,
   reg no, billing address, contact, phone, email, currency, credit days,
   GST exemption), the agreement form shows the picked customer's details
   and warns when the TIN is missing, and the agreement (screen and PDF)
   carries the customer's full block (`rental.customer_info`).

   **Long-form agreement** (owner 2026-09-25): fifteen standard clauses
   (`rental.STANDARD_CLAUSES`: definitions, hire period, rates, the daily
   register, mobilisation, hirer's obligations, maintenance and breakdown,
   damage and loss, insurance, safety, invoicing and payment, termination,
   force majeure, governing law, entire agreement), overridable company-wide
   in parameter `rental_clauses` (Standard terms editor on the Hire
   agreements tab, Rental Manager); every agreement takes a copy in
   `RentalAgreement.clauses` (mig 0256) that the user edits while a draft —
   strike what does not apply, reword, add, reorder — locked on activation;
   the PDF prints them numbered on a page of their own after the schedule,
   with the agreement's special conditions prevailing.

## 6b. One sign-in for both apps (the bridge, 2026-09-26)

Separate databases, one trust (`core/peer_auth.py`). `PEER_AUTH_SECRET` is
the same value in `.env` and `.env.marine`; `PEER_URL` is each instance's
internal address of the other (`http://web-marine:8000/marine/api/v1` on
Planet, `http://web:8000/api/v1` on Marine). With it set:

- **Switching apps carries the sign-in.** The switcher asks
  `POST /auth/handoff` for a 90-second signed token and opens the other app
  with `?sso=<token>`; that app's `POST /auth/sso` verifies it, mirrors the
  user (same username, name, email, phone; an unusable local password;
  `User.home_instance` = where the password lives) and starts a session.
  On first arrival the user keeps their sister role as a starting point;
  the local admin changes it on the Users page. Extras are per instance.
- **Cold sign-in with the sister's credentials.** `POST /auth/login` tries
  locally first; for an unknown or mirrored username it calls the sister's
  `POST /auth/peer-verify` (body signed with the secret; only accounts whose
  password lives there answer, never a mirrored one) and mirrors on success.
- Deactivating a mirrored user locally shuts the bridge for them here;
  deactivating the home account shuts it everywhere (verify fails; the
  handoff needs a live session there).

## 7. Inputs — settled and open

Settled (2026-09-25): brand and company details (`SANDPLANET_MARINE_BRAND.md`);
billing per day from the customer-approved daily register; operators are
Marine employees; domain marine.sandplanet.mv. The starting fleet and rate
card the owner enters on the Fleet page once phase 3 ships.

Still open:

- Bank accounts for Marine (entered on its Company page at seed time).
- Whether Marine documents get a company prefix on the shared series
  (`SPM-INV-2026-0001`) or plain `INV-2026-0001` — the brief assumes plain,
  since the instance is separate.
- The vector logo from the designer, when available.

---
*Precedents: the trading arm (`TRADING_BUILD_BRIEF.md`) for the ledger book
wall and the customer money-in models; the subcontractor module for the
Sand Planet ↔ Marine relationship.*
