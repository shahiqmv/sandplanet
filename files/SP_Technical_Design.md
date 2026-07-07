# Sand Planet Site Documents — Technical Design R0
Derived from Requirements Specification R1 (07 Jul 2026). Companion to the Build Brief.

## 1. Stack (committed)

- **Backend:** Python 3.12, Django 5 + Django REST Framework, PostgreSQL 16.
- **Frontend:** React (Vite) SPA, served by the Django app in production (same origin). Visual language carried over from the prototype (navy #16527E / sky #29ABE2, form cards, register tables).
- **Auth:** Django session authentication (same-origin SPA, CSRF-protected), argon2 password hashing, admin-managed accounts.
- **PDF:** WeasyPrint (HTML/CSS templates per form, mirroring the Excel layouts). Fallback if a layout proves hard: Playwright/Chromium.
- **Files:** DO Spaces (S3-compatible) via django-storages; client-side image compression before upload.
- **Hosting:** DigitalOcean App Platform (SGP1) + Managed Postgres + Spaces. No persistent local disk — all files to Spaces.
- **Timezone:** all timestamps stored UTC, displayed Maldives (UTC+5). Dates rendered dd/mm/yy.

## 2. Database schema (PostgreSQL)

Conventions: `id` = bigint identity PK; `created_at/updated_at` timestamptz on all tables (omitted below); soft-delete nowhere — rows are deactivated, never deleted; `payload` columns are `jsonb`.

```sql
-- ===== Master data =====

CREATE TYPE site_status AS ENUM ('AWARDED','ACTIVE','ON_HOLD','CLOSED');

CREATE TABLE sites (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code          varchar(6) UNIQUE NOT NULL,          -- immutable after first document (enforced in app)
  name          text NOT NULL,
  is_head_office boolean NOT NULL DEFAULT false,     -- MLE special record
  scope         text,
  contract_value numeric(14,2),                      -- sensitive: HO/Admin/assigned PM only
  currency      varchar(3) DEFAULT 'MVR',
  award_date    date,
  start_date    date,
  duration_days integer,
  planned_completion date,
  actual_completion  date,
  status        site_status NOT NULL DEFAULT 'AWARDED',
  client_name   text, client_contact text, client_designation text,
  client_phone  text, client_email text,
  consultant_name text, consultant_contact text,
  working_hours_from time DEFAULT '07:00', working_hours_to time DEFAULT '18:00',
  working_days  int[] NOT NULL DEFAULT '{6,7,1,2,3,4}'  -- ISO dow: Sat–Thu (Fri=5 off)
);

CREATE TABLE site_pm_history (           -- who is/was project PM; latest open row = current
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id bigint NOT NULL REFERENCES sites,
  pm_user_id bigint NOT NULL,            -- FK users, added after users table
  from_date date NOT NULL, to_date date
);

CREATE TABLE holidays (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id bigint REFERENCES sites,       -- NULL = company-wide
  day date NOT NULL, name text
);

CREATE TYPE user_role AS ENUM
  ('SITE_ENGINEER','SITE_ADMIN','PM','HO_PURCHASING','DIRECTOR','HO_HR','ADMIN');

CREATE TABLE users (                      -- extends Django auth user (profile 1:1) or custom user model
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username varchar(60) UNIQUE NOT NULL,
  password_hash text NOT NULL,
  full_name text NOT NULL,
  role user_role NOT NULL,
  employee_id bigint,                     -- optional link to employees
  is_active boolean NOT NULL DEFAULT true,
  last_login timestamptz
);

CREATE TABLE user_site_allocations (      -- SITE_* users: exactly one open row; PM: one or more
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES users,
  site_id bigint NOT NULL REFERENCES sites,
  from_date date NOT NULL, to_date date,
  UNIQUE (user_id, site_id, from_date)
);

CREATE TABLE manpower_categories (        -- company-wide (decision 4); two lists
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  list_type varchar(3) NOT NULL CHECK (list_type IN ('DPR','TWS')),
  grp varchar(10) NOT NULL CHECK (grp IN ('STAFF','LABOUR')),
  name text NOT NULL,
  sort_order int NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  UNIQUE (list_type, name)
);

CREATE TABLE company_parameters (         -- OT multiplier, hourly-rate divisor, etc.
  key varchar(60) PRIMARY KEY,
  value jsonb NOT NULL,
  description text
);

-- ===== Item master (§5.0) =====

CREATE TABLE items (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code varchar(12) UNIQUE NOT NULL,       -- ITM-00412, server-issued
  description text NOT NULL,
  unit varchar(10) NOT NULL,              -- fixed per item
  category text,                          -- trade/discipline
  brand text, spec_ref text, notes text,
  is_active boolean NOT NULL DEFAULT true,
  merged_into bigint REFERENCES items     -- duplicate resolution
);

-- ===== Documents (§4, §5, §7) =====

CREATE TYPE doc_type AS ENUM ('DPR','TWS','IR','MAR','MR','GRN','PR','LM');

CREATE TABLE doc_counters (               -- gap-free numbering; SELECT ... FOR UPDATE on issue
  doc_type doc_type NOT NULL,
  site_id bigint REFERENCES sites,        -- NULL for global PR/LM
  last_no int NOT NULL DEFAULT 0,
  PRIMARY KEY (doc_type, site_id)
);

CREATE TABLE documents (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  doc_type doc_type NOT NULL,
  ref varchar(20) UNIQUE NOT NULL,        -- DPR-SJR-001 / PR-014
  site_id bigint NOT NULL REFERENCES sites,
  doc_date date NOT NULL,                 -- the form's principal date
  status varchar(30) NOT NULL,            -- per-type state machine (app-enforced transitions)
  current_revision_id bigint,             -- FK document_revisions (deferred)
  previous_ir_id bigint REFERENCES documents,  -- IR resubmission chain (§4.2)
  is_void boolean NOT NULL DEFAULT false,
  void_reason text, voided_by bigint REFERENCES users, voided_at timestamptz,
  created_by bigint NOT NULL REFERENCES users
);
CREATE INDEX ON documents (doc_type, site_id, doc_date);

CREATE TABLE document_revisions (         -- immutable snapshots; MAR/MR step R0,R1…
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  document_id bigint NOT NULL REFERENCES documents,
  rev_label varchar(4) NOT NULL DEFAULT 'R0',
  payload jsonb NOT NULL,                 -- full form contents (headers, sections, free text)
  is_current boolean NOT NULL DEFAULT true,
  issued_at timestamptz,                  -- set when the revision is issued (locks it)
  created_by bigint NOT NULL REFERENCES users,
  UNIQUE (document_id, rev_label)
);

CREATE TABLE document_lines (             -- typed item lines for MR/PR/LM/GRN
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  revision_id bigint NOT NULL REFERENCES document_revisions,
  line_no int NOT NULL,
  item_id bigint REFERENCES items,        -- NULL only when free-text new item
  free_text_desc text,                    -- flagged "new item" path (§5.0)
  unit varchar(10),
  qty_required numeric(12,2), qty_stock numeric(12,2), qty_to_order numeric(12,2),
  qty_loaded numeric(12,2), qty_pending numeric(12,2),
  qty_manifest numeric(12,2), qty_received numeric(12,2),
  priority varchar(8),                    -- MR: NORMAL/URGENT
  urgent_reason text,
  amount_cash numeric(14,2), amount_credit numeric(14,2),  -- PR vendor rows
  vendor text, quotation_ref text, payment_terms text, action_taken text,
  is_changed boolean NOT NULL DEFAULT false,  -- auto-flag on MR amendment (§5.5 rule 3)
  remarks text,
  CHECK (item_id IS NOT NULL OR free_text_desc IS NOT NULL)
);
CREATE INDEX ON document_lines (item_id);

CREATE TYPE link_type AS ENUM ('MR_PR','MR_LM','PR_LM','LM_GRN','IR_NCR');
CREATE TABLE document_links (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  from_document_id bigint NOT NULL REFERENCES documents,
  to_document_id   bigint NOT NULL REFERENCES documents,
  link_type link_type NOT NULL,
  UNIQUE (from_document_id, to_document_id, link_type)
);

CREATE TABLE approvals (                  -- every workflow action, immutable (§7.2)
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  document_id bigint NOT NULL REFERENCES documents,
  revision_id bigint REFERENCES document_revisions,
  action varchar(30) NOT NULL,            -- SUBMIT/APPROVE/APPROVE_WITH_COMMENT/RETURN/VERIFY/
                                           -- ISSUE/RESULT_RECORDED/CLOSE/SIGN_OFF/...
  result varchar(40),                      -- client results: Approved/AwC/R&R/Rejected...
  actor_id bigint NOT NULL REFERENCES users,
  actor_role user_role NOT NULL,
  comment text,
  acted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE attachments (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  document_id bigint REFERENCES documents,
  revision_id bigint REFERENCES document_revisions,
  kind varchar(20) NOT NULL,              -- PHOTO/ENCLOSURE/QUOTATION/EVIDENCE/GENERATED_PDF
  file_key text NOT NULL,                 -- Spaces object key
  file_name text, content_type text, size_bytes bigint,
  caption text,                           -- DPR photo captions
  uploaded_by bigint REFERENCES users
);

CREATE TABLE pending_items (              -- §6 Pending Items Log; auto from LM lines
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lm_line_id bigint NOT NULL REFERENCES document_lines,
  site_id bigint NOT NULL REFERENCES sites,
  pr_document_id bigint REFERENCES documents,
  item_id bigint REFERENCES items, free_text_desc text,
  unit varchar(10), qty_pending numeric(12,2) NOT NULL,
  reason text, action_next text,
  status varchar(10) NOT NULL DEFAULT 'PENDING',   -- PENDING/CLEARED
  cleared_date date, cleared_lm_id bigint REFERENCES documents, cleared_reason text
);

CREATE TABLE audit_log (                  -- append-only; DB user has no UPDATE/DELETE on it
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity varchar(30) NOT NULL, entity_id bigint NOT NULL,
  event varchar(40) NOT NULL,
  from_state text, to_state text,
  actor_id bigint, detail jsonb,
  at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE notifications (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES users,
  kind varchar(40) NOT NULL, title text NOT NULL, body text,
  document_id bigint REFERENCES documents,
  read_at timestamptz
);

-- ===== Employees & timesheets (§6A) =====

CREATE TABLE employees (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  emp_no varchar(10) UNIQUE NOT NULL,     -- EMP-0231
  full_name text NOT NULL,
  passport_no text,                       -- sensitive: HR/Admin only (API-gated)
  nationality text,
  job_category_id bigint REFERENCES manpower_categories,
  basic_pay numeric(12,2),                -- sensitive: HR/Admin only (API-gated)
  work_permit_no text, work_permit_expiry date,
  emergency_contact text,
  join_date date, is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE employee_site_allocations (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  employee_id bigint NOT NULL REFERENCES employees,
  site_id bigint NOT NULL REFERENCES sites,
  from_date date NOT NULL, to_date date
);

CREATE TABLE timesheet_months (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id bigint NOT NULL REFERENCES sites,
  year int NOT NULL, month int NOT NULL,
  status varchar(10) NOT NULL DEFAULT 'OPEN',   -- OPEN/LOCKED
  signed_off_by bigint REFERENCES users, signed_off_at timestamptz,
  reopened_by bigint REFERENCES users, reopen_reason text,
  UNIQUE (site_id, year, month)
);

CREATE TABLE attendance (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  employee_id bigint NOT NULL REFERENCES employees,
  site_id bigint NOT NULL REFERENCES sites,
  day date NOT NULL,
  check_in time, check_out time,
  normal_hours numeric(4,2),              -- computed vs site working hours
  ot_requested numeric(4,2) NOT NULL DEFAULT 0,
  ot_approved numeric(4,2),               -- set only via PM approval action
  ot_approved_by bigint REFERENCES users, ot_approved_at timestamptz,
  remark varchar(12) NOT NULL DEFAULT 'PRESENT',   -- PRESENT/ABSENT/SICK/LEAVE/HALF_DAY
  entered_by bigint REFERENCES users,
  UNIQUE (employee_id, day)
);
```

**Register views:** each register in §6 is a SQL view (or DRF queryset) over `documents` + `document_revisions` + `approvals` + `document_links` — no register tables, no double entry. The DPR/TWS register generates its day rows from a calendar series (site working days per §2, minus holidays) left-joined to documents, so gaps appear automatically.

**Numbering:** `nextRef` = transaction: `SELECT last_no FROM doc_counters WHERE ... FOR UPDATE; UPDATE ...; INSERT document`. Number assigned at first save (draft), never reused; void keeps the row.

**Payload vs columns rule:** anything that must be queried, aggregated, or linked across documents lives in typed columns (`document_lines`, dates, status, refs); everything that is purely form content (weather, free text sections, manpower counts, machinery rows) lives in the revision `payload` JSON and is rendered into registers/PDFs as-is. Manpower counts in the DPR payload are keyed by `manpower_categories.id` so category renames don't break history.

## 3. API surface (REST, `/api/v1`)

Auth: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` (role, allocations → drives default landing per site, §login behavior).

Master data:
- `GET|POST /sites`, `GET|PATCH /sites/{id}`, `POST /sites/{id}/status` (lifecycle transitions, reason required)
- `GET|POST /users`, `PATCH /users/{id}`, `POST /users/{id}/deactivate`
- `GET|POST /items`, `PATCH /items/{id}`, `POST /items/{id}/merge` — `GET /items?search=` powers MR autocomplete
- `GET|POST /manpower-categories`, `GET|PUT /parameters/{key}`, `GET|POST /holidays`

Documents (uniform core + typed payload):
- `POST /documents` {doc_type, site_id, payload, lines[]} → creates draft, issues ref
- `GET /documents/{ref}` (full: revisions, lines, links, approvals, attachments, PDFs)
- `PATCH /documents/{ref}` (draft revisions only)
- `POST /documents/{ref}/revisions` (MAR R&R / MR amendment — copies current, steps label, auto-flags changed lines)
- `POST /documents/{ref}/actions/{action}` — submit / approve / return / issue / verify / record-result / close / void; server validates the per-type state machine + actor role + site scope
- `POST /documents/{ref}/attachments` (multipart; enforces DPR ≥4 photos at issue)
- `GET /documents/{ref}/pdf` and `GET /documents/{ref}/pdf/{revision}` — archived copies
- Convenience: `GET /lm/{ref}/grn-prefill` (GRN lines from manifest); `GET /mr/{ref}/lm-prefill`

Registers & dashboards:
- `GET /registers/{doc_type}?site=&status=&from=&to=` (+ `&format=xlsx|pdf` for exports)
- `GET /registers/dpr-tws?site=` (day-row register with gap flags)
- `GET /pending-items?site=&status=`, `PATCH /pending-items/{id}`
- `GET /dashboards/site/{id}`, `GET /dashboards/ho`, `GET /dashboards/projects`
- `GET /notifications`, `POST /notifications/{id}/read`

Employees & timesheets:
- `GET|POST /employees`, `PATCH /employees/{id}` (pay/passport fields serialized only for HR/Admin)
- `GET /attendance?site=&date=` (grid), `PUT /attendance/bulk` (day grid upsert)
- `POST /attendance/ot-approve` {ids[], hours?} (PM only)
- `POST /timesheets/{site}/{yyyy}/{mm}/lock`, `.../reopen`, `GET .../export?format=xlsx|pdf`
- `GET /payroll-export/{yyyy}/{mm}?site=` (HR/Admin only; computed gross per §6A.3)

Cross-cutting rules: every endpoint filters by the caller's site allocations server-side; sensitive fields (contract_value, basic_pay, passport_no) are stripped by serializer per role; all state-changing endpoints write `audit_log`; issued revisions and their PDFs are immutable.

## 4. PDF templates

One HTML/CSS template per form (8) + photos page + register/timesheet layouts, in `pdf_templates/`, styled to match the Excel prints: navy header band, sky rule, form no. + rev top-right, ref stamp, section numbering, signature blocks rendered as electronic stamps ("Approved by {name} — {role} — {dd/mm/yy hh:mm} — approved electronically via Sand Planet Site Documents"). Generated at issue and at each subsequent milestone; stored to Spaces as `pdf/{ref}/{rev}-{milestone}.pdf` and recorded in `attachments` (kind GENERATED_PDF).

## 5. Environments

- `local` — docker-compose: Django + Postgres + MinIO (Spaces stand-in).
- `staging` — DO App Platform (smallest), dev database, separate Spaces bucket; pilot site testing.
- `production` — DO App Platform + Managed Postgres 1 GiB + Spaces; weekly off-platform pg_dump export to a second location.
