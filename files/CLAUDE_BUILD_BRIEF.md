# Sand Planet Site Documents — Build Brief for Claude Code

You are building a production web application for Sand Planet, a construction company operating on resort islands across the Maldives. Two companion documents in this folder are authoritative — read both fully before writing code:

1. `SP_Site_Documents_Requirements_Specification_R1.md` — what the system does (WHAT). All field maps, workflows, roles, and rules. The decisions log (§12) explains why things are the way they are; do not re-litigate settled decisions.
2. `SP_Technical_Design.md` — how it is built (HOW). Stack, schema, API, PDF approach. Follow it; deviate only with a stated reason, and record any deviation in a `DECISIONS.md` at repo root.

A working front-end prototype exists (`sandplanet-site-docs_1.jsx`) — use it as the reference for visual language (navy #16527E / sky #29ABE2, form-card layout, register tables, status chips) and interaction feel, NOT as a code base to extend. Its storage, auth, and status handling are throwaway.

## Non-negotiables

- All authorization server-side: role + site allocation checked on every endpoint. UI hiding is not security.
- Issued document revisions and generated PDFs are immutable. Numbering is server-issued, sequential, gap-free (row-locked counters).
- Sensitive fields (contract_value, basic_pay, passport_no) never serialized to unauthorized roles, never logged, never in site-level exports.
- Every state change writes the append-only audit_log.
- DPR cannot issue with < 4 captioned photos (hard block).
- OT hours reach payroll export only if PM-approved. Locked timesheet months are immutable without an audited HR reopen.
- App Platform has no persistent disk: every file goes to Spaces (local: MinIO). Never write user files to the container filesystem.
- Site users must land directly on their allocated site after login — no site picker for single-site roles; site pre-filled and locked on their forms.

## Milestones (build in this order; each ends deployed to staging and demoable)

- **M0** Repo, docker-compose (Django+Postgres+MinIO), CI (lint+tests), skeleton React app served by Django.
- **M1** Schema migrations, auth, roles, Site & Project module (lifecycle), user admin, seed script (sites from spec §2, admin user, manpower categories, company parameters).
- **M2** DPR end-to-end: full form (all 7 sections + photos), issue-then-verify flow, PDF generation, DPR/TWS register with gap detection, site dashboard. ← after this, a pilot site can start using it.
- **M3** Item Master + procurement chain: MR (with amendment revisions), PR, LM, GRN prefill, Pending Items Log, HO dashboard + registers.
- **M4** IR + MAR with revision/resubmission semantics and client-result recording; TWS.
- **M5** Employees, attendance grid, OT approval, month lock, payroll export.
- **M6** Notifications, register Excel/PDF exports, polish, production deploy to DigitalOcean (SGP1), pilot-site rollout checklist.

## Working style

- Tests for the risky logic first: numbering under concurrency, state-machine transitions, revision immutability, role/site scoping, timesheet lock, register gap detection.
- Keep PDF templates in plain HTML/CSS (WeasyPrint); verify each against the corresponding Excel print layout — the Excel files are the acceptance criteria for layout.
- Ask the owner (via chat) before: adding dependencies with licensing implications, changing the schema in ways that touch document immutability, or anything requiring his hosting/DNS credentials. He performs all credential and payment steps himself.
- Small commits, one concern each; migration files never edited after merge.

## Seed/config values to confirm with the owner during M1

- OT multiplier and hourly-rate divisor (company_parameters) — pending from payroll practice.
- Real user list for pilot site; which site pilots first.
- Company letterhead assets (logo file for PDF header).
