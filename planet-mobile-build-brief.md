# Planet Mobile — Build Brief & Requirements Addendum (R6)

**Project:** Planet — Sand Planet internal operations system (planet.sandplanet.mv)
**Module:** Planet Mobile — approvals & request tracking companion app (PWA)
**Audience:** Claude Code (implementation)
**Status:** Approved for build
**Prepared:** 14 July 2026

---

## 1. Purpose

Approvers (PM, Director, Signatory) are frequently away from a desk — on boats, at jetties, between sites. Approvals stall. Separately, request originators (site engineers, storekeepers, purchasing) have no visibility of where their documents stand without opening the desktop app or calling Head Office.

Planet Mobile is a lightweight PWA that solves both:

1. **Approve on the move** — role-scoped approval queues with push notifications; approve, authorise, or return documents from a phone.
2. **Track what you raised** — originators see the live status chain of their documents and receive push notifications on milestone events (payment completed, manifest departed, client decision, etc.).

It is a **client only**. No new business logic lives in the mobile app. All rules — approval routing, the Signatory threshold, segregation of duties — remain server-enforced in the existing Django backend, exactly as built for Phase 1.

## 2. Explicitly out of scope

- Creating or editing any document. Mobile is view + action only.
- Petty cash, timesheet entry, item master, cost control views.
- Native iOS/Android apps, app store distribution.
- SMS or WhatsApp delivery (superseded by this brief).
- Offline queueing of approvals (see §10 — offline is read-only).
- International Procurement documents (Phase 1B; the notification framework must be extensible to PMR/IPR/IRN/SIN later, but do not build for them now).

## 3. Delivery vehicle: PWA

- Small React (Vite) app, installable via **Add to Home Screen**. No app stores.
- Served at **m.planet.sandplanet.mv** (preferred) or planet.sandplanet.mv/m — same DigitalOcean App Platform deployment, same origin policy decision left to Code; document the choice.
- Web app manifest: name "Planet", standalone display, theme colour navy `#16527E`, background `#F6F2E9`, ring-mark icon set (192/512 px, maskable).
- Service worker for (a) push notifications, (b) app-shell caching. Note iOS requirement: web push on iOS 16.4+ **only works for installed (home-screen) PWAs** — the sign-in screen must prompt uninstalled iOS users to install before enabling notifications.

## 4. Roles and what each sees

Reuse existing Planet accounts, roles, and site allocations. No mobile-specific user records.

| Role | Tab 1 | Tab 2 | Actions available |
|---|---|---|---|
| Originator (any user who has raised documents) | My Requests | Alerts | None (view/track only) |
| PM | Pending | Actioned | Approve / Return — IR, MAR, MR, OT (timesheet overtime) for their site(s) |
| Director, Projects / Senior PM | Pending | Actioned | Approve / Return — PR |
| Signatory (either executive director) | Pending | Actioned | Authorise / Return — PYR |
| Finance | — | — | **No approval actions on mobile.** Finance is payment-execution only (Decision: Finance ≠ authorisation). Finance users see only the originator view for documents they raised. |

A user can be both approver and originator (e.g. a PM who also raises MRs): show all applicable tabs — Pending, Actioned, My Requests, Alerts. Collapse to a bottom tab bar if more than two tabs.

**Server-side scoping is mandatory.** The API must filter queues by role and site allocation on the server. The client never decides what a user may see or action.

## 5. Screens

Interactive reference mockup: `planet-approvals-mobile-v2.jsx` (shared alongside this brief). Match its visual language — it follows the Planet design system: navy `#16527E`, sky `#29ABE2`, sand canvas `#F6F2E9`, Barlow Condensed display, Inter body, IBM Plex Mono for reference stamps, title-block card styling, zero border radius on cards/buttons.

### 5.1 Sign in
Username + password against existing Planet auth. Long-lived session per device (refresh token, 30 days rolling; configurable). After first sign-in, prompt to enable notifications (and to install, on iOS Safari).

### 5.2 Approvals inbox (Pending / Actioned)
- Card list, newest first: reference (mono), document type, site chip, one-line summary, age, amount where applicable (PR, PYR).
- Actioned tab: documents this user actioned from any client (mobile or desktop), last 30 days.

### 5.3 Document detail (approver)
- Read-only render: title-block header (form no., ref, site), key fields grid, line items, amount block, narrative/remarks, attachments (open inline; PDFs via existing WeasyPrint render where one exists).
- Sticky action bar: **Return** (secondary) + **Approve/Authorise {ref}** (primary).
- Return always requires a reason (mirrors the desktop return-for-review panel).
- Approve/Authorise triggers the stamp animation (see mockup) then returns to the inbox with a toast.

### 5.4 Signatory PIN confirmation
- PYR at or above the configured threshold (same server-side threshold already in Finance workflow config): authorisation requires a **4-digit mobile PIN** re-entry in a confirmation sheet showing the amount ("Stamp & authorise").
- PIN is set on first mobile sign-in by a Signatory; stored server-side hashed (same treatment as passwords); 5 failed attempts locks mobile authorisation for that user until an admin unlocks.
- **The server enforces this**: the authorise endpoint for above-threshold PYRs must reject requests without a valid PIN proof, regardless of client.
- Below-threshold PYRs authorise with a single tap.

### 5.5 My Requests (originator)
- All documents raised by the user, newest activity first: ref, type, status chip, one-line status ("3 items · departed Male' on Dhoni 5"), unread-change dot.
- Detail = **tracking timeline**: vertical stepper of the document chain with refs, actors, and dates. Done steps green, current step sky with halo, future steps grey. Chain examples:
  - MR → PM approval → PR → Signatory authorisation → PYR paid → LM departed → GRN received
  - IR → PM approval → sent to client → client decision
  - MAR → PM approval → sent to client → client decision (show client comment text on the card when "Approved with Comments")
- The timeline is **derived from existing document links and status history** — no new chain data model. Steps render from the reference relationships Planet already stores (MR refs on PR, PR/MR refs on LM, LM ref on GRN, PR/GRN refs on PYR) plus each document's status audit trail.
- Show partial/pending item notes where they exist (e.g. items moved to the Pending Items Log on partial loading).

### 5.6 Alerts (originator)
- Reverse-chronological feed of notification events, unread state, "tap to track" opens the timeline directly.
- Feed and push are the same events: the feed is the persistent record; push is the delivery.

## 6. Notification system

### 6.1 Transport
- **Web Push (VAPID)** — `pywebpush` on Django, standard Push API + service worker on the client.
- New model: `PushSubscription` (user FK, endpoint, keys, user agent label, created, last_success). Users can have multiple devices. Purge subscriptions after repeated delivery failures (410 Gone).
- Notification tap deep-links: approvers → document detail; originators → tracking timeline.

### 6.2 Event matrix — milestone events only

Push on **milestones**, not every transition, to keep signal high. Rejections/returns are always pushed.

**To approvers (queue events):**

| Event | Recipient |
|---|---|
| IR / MAR / MR submitted, OT submitted | PM of that site |
| PR submitted for approval | Director, Projects / Senior PM |
| PYR ready for authorisation | Both Signatories (first to action wins; the other's item clears) |

Optional digest: if an approver has >3 unactioned items older than 24h, send one daily reminder ("4 documents waiting on you"), not per-document repeats.

**To originators (status events):**

| Event | Notify originator of |
|---|---|
| Approved by PM / Director / Signatory | the approved document |
| **Returned / Rejected / Revise & Resubmit** (always pushed) | the returned document, with reason text |
| Client decision on IR / MAR (incl. Approved with Comments) | the IR / MAR |
| PYR paid | the PR chain originator (Purchasing) |
| LM departed (status → In Transit) | originator of each MR carried on that manifest |
| GRN issued against LM | originator of each MR carried (note shortages if any) |
| Items moved to Pending Items Log | originator of the affected MR |

**Not pushed** (visible in timeline only): PR raised against an MR, loading started, intermediate Finance processing states.

### 6.3 Implementation shape
- Emit events from the **existing status-transition code paths** (signals or explicit service calls at each transition — Code to choose and apply consistently). Every event writes a `Notification` row (recipient, event type, document ref, message, read flag, created) and then attempts push delivery.
- The Alerts feed reads `Notification` rows; push failure never loses the alert.
- Per-user toggle in mobile settings: "Notify me on milestone updates" (originator events) on/off. Approver queue events and returns/rejections are not disableable.

## 7. API

Add a mobile-scoped API (suggest `/api/mobile/v1/`), token-authenticated (existing auth + refresh tokens):

- `GET  /queue` — pending approvals for the authenticated user's role/sites
- `GET  /actioned?days=30`
- `GET  /documents/{ref}` — read-only render payload incl. line items, attachments, status history
- `POST /documents/{ref}/approve` — body: `{comment?, pin_proof?}`; server validates role, state, threshold/PIN
- `POST /documents/{ref}/return` — body: `{reason}` (required)
- `GET  /requests` — documents originated by user, with latest-activity summary
- `GET  /requests/{ref}/timeline` — derived chain steps
- `GET  /alerts`, `POST /alerts/{id}/read`
- `POST /push/subscribe`, `DELETE /push/subscribe`
- `POST /pin` (set/change Signatory PIN), admin unlock endpoint

All approve/return endpoints are idempotent and re-validate document state (409 if already actioned by someone else — surface as "Already actioned by {name}" in the client).

## 8. Security requirements (non-negotiable)

1. Every rule enforced server-side; the mobile client is untrusted.
2. Signatory threshold and PIN enforcement live in the same authorisation service the desktop uses — one code path, not a mobile copy.
3. Audit trail entries for mobile actions identical to desktop (actor, timestamp, action, comment), plus a `channel: mobile` marker.
4. Refresh tokens revocable per device from the desktop admin (lost phone scenario). Sign-out destroys the device's push subscription.
5. No document data cached beyond the current session beyond the app shell; attachment URLs are short-lived signed URLs (Spaces).

## 9. Design system notes for Code

- Tokens and components as per the mockup file: `FormCard`-style navy header + 3px sky rule, mono reference stamps, status chips (OK green / alert red / mist neutral), stamp animation on action (rotate −9°, spring scale-in, ~900 ms before navigating back).
- Type: Barlow Condensed (600/700) for headings, buttons, tabs; Inter for body; IBM Plex Mono (500/600) for refs. Self-host fonts — do not rely on Google Fonts CDN from site connections.
- Everything square-cornered except the phone-OS-level surfaces; sand `#F6F2E9` canvas, white cards, `#C9D9E5` borders.
- Touch targets ≥ 44 px; action bar sticky above the keyboard/safe-area inset.

## 10. Connectivity behaviour

Island connections drop. Requirements:
- App shell loads offline; queues/requests show last-fetched data with a visible "Last updated {time}" bar when stale.
- **Approve/return require connectivity.** If offline, disable the action bar with "You're offline — actions need a connection." Do not queue actions offline (risk: stale state, double-actioning).
- Push delivery failures fall back silently to the in-app Alerts feed (already persistent per §6.3).

## 11. Decisions log — proposed entries (for Ahmed to confirm)

- **D34.** Mobile companion delivered as a PWA, not native apps; approvals + originator tracking only; document creation stays desktop-only.
- **D35.** SMS/WhatsApp notification track dropped in favour of web push + in-app alerts feed.
- **D36.** Signatory authorisation on mobile requires a server-verified 4-digit PIN at/above the existing Finance threshold; below threshold, single tap.
- **D37.** Originator notifications fire on milestone events only (approvals, returns/rejections, client decisions, payment completed, manifest departed, GRN, pending-item moves); returns/rejections always pushed and non-disableable.
- **D38.** Tracking timelines are derived from existing document reference links and status history; no new chain data model.
- **D39.** Finance role has no approval actions on mobile, consistent with Finance-as-execution-only.

## 12. Acceptance criteria

1. PM approves an IR from a phone; desktop register reflects the new status and the audit trail shows `channel: mobile`.
2. Signatory authorising PYR ≥ threshold is blocked without PIN (verified by direct API call bypassing the UI); succeeds with PIN; project cost commits at that authorisation, per existing rules.
3. Return without a reason is rejected server-side.
4. Two Signatories: one authorises; the other's queue clears and a direct authorise attempt returns 409.
5. LM status → In Transit pushes a notification to the originators of all MRs referenced on the manifest; tapping opens the correct timeline at the correct step.
6. PYR marked paid notifies the PR originator; the event appears in their Alerts feed even with push disabled.
7. iOS 16.4+ installed PWA and Android Chrome both receive pushes; tap deep-links correctly.
8. Offline: app opens, shows stale-data bar, actions disabled with the offline message.
9. Seeded demo data covers all three approver queues and one full MR→GRN chain for screenshot generation (reuse the Playwright screenshot pipeline planned for the User Guide).

## 13. Suggested build order

1. Mobile API endpoints + tests (queues, document render, approve/return with threshold/PIN enforcement, 409 handling)
2. Notification model + event emission at status transitions + Alerts feed API
3. PWA shell: auth, manifest, service worker, install/notification prompts
4. Approver screens (inbox → detail → actions → stamp)
5. Originator screens (requests → timeline → alerts)
6. Web push wiring end-to-end (VAPID, subscription lifecycle, deep links)
7. Offline behaviour, digest reminders, admin device revocation
8. Seed data + Playwright screenshots + User Guide section

---

*Reference mockup: `planet-approvals-mobile-v2.jsx`. Questions or conflicts with the existing R5 spec should be raised before implementation, not resolved silently — flag them the way spec corrections have been handled to date (decisions log entry, then propagate).*
