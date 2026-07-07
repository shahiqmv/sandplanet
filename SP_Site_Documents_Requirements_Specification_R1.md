# Sand Planet — Site Documents System
## Requirements Specification — Draft R1

**Date:** 07 July 2026 (R0 issued and reviewed same day; R1 incorporates management decisions — see §12)
**Source documents:** FRM-PRJ-01 (DPR), FRM-PRJ-02 (IR), FRM-PRJ-04 (TWS), FRM-PRJ-03 (MAR), FRM-PRC-01 R1 (MR + Instructions), FRM-PRC-02 (PR), FRM-PRC-03 (LM), FRM-PRC-04 R1 (GRN), site registers (DPR/TWS, IR, MAR, MR), Head Office master registers (MR, PR, Manifest, Pending Items Log), working prototype v1.

---

## 1. Purpose and scope

A web application replacing the Excel-based site documentation and procurement workflow for Sand Planet construction sites across the Maldives. The system covers:

- **Six site documents:** Daily Progress Report (DPR), Tomorrow Work Schedule (TWS), Inspection Request (IR), Material Approval Request (MAR), Material Requisition (MR), Goods Received Note (GRN).
- **Two Head Office documents:** Procurement Requisition (PR), Loading Manifest (LM).
- **Self-maintaining registers** for every document type, at site level and Head Office level, replacing the manual register sheets.
- **The Pending Items Log** (auto-populated from Loading Manifest pending quantities).
- **Employee database and site timesheets** (daily check-in/out and PM-approved overtime, month-locked and exported for Head Office payroll — §6A).
- **Role-gated approval workflows** (Site → PM → issue; Purchasing → Director → Finance).
- **PDF generation** of every issued document, matching the existing Excel print formats on company letterhead. The PDF is the formal record issued to clients and vendors; the app is the register and workflow engine.

Out of scope for Phase 1 (candidates for later phases): client/consultant logins, NCR module, stock book / full inventory, vendor portal, payroll or timesheets.

---

## 2. Site & Project Management module

A site in the system **is a project**: it is created at the point of award and closed when the project is over. Site management is an admin/HO function, not developer work — opening a new resort project must never require code changes.

### 2.1 Site/project record

**Identity:** Site code (short, unique, e.g. SJR — becomes part of every document reference, so it is **immutable after the first document is issued**) · Project/Site name.

**Project details:** Project scope (description of works) · Contract value (MVR/USD, currency selectable) · Duration — award date, site start date, contract duration, planned completion date (auto = start + duration, editable), actual completion date (set at closure) · Project PM (assigned from PM users — drives approval routing: IR/MAR/MR approvals and DPR verification for this site go to this PM; reassignable when PMs rotate, with history kept).

**Client details:** Client/Employer name · Client contact person, designation, phone, email · Consultant/Engineer name and contact. These auto-fill the document headers (DPR, TWS, IR, MAR) as before.

**Operational settings:** Default working hours (default 07:00–18:00) · Working-week override (default Sat–Thu per decision 5) · Site-specific holidays.

**Status lifecycle:** `Awarded` → `Active` → `Closed` (plus `On Hold` for suspended projects).

### 2.2 Lifecycle rules

- **Awarded:** site exists, users can be allocated, item requirements and MAR submissions can begin (mobilization purchasing often precedes site start), but daily documents (DPR/TWS) are not yet expected — no gap-flagging.
- **Active:** full operation; DPR gap-checking runs from the site start date.
- **On Hold:** document creation blocked except by PM/HO override (with reason); gap-checking suspended; registers readable.
- **Closed:** set by Admin/HO at project completion (actual completion date recorded). **No new documents can be created**; all registers, documents, PDFs, and timesheets remain fully readable and exportable forever (decision 9 — retain everything). Site users allocated only to a closed site are prompted for reallocation or deactivation. A closed site can be reopened by Admin (audited) for defect-liability-period documentation.
- Every status change is audited (who, when, reason).

### 2.3 Visibility and sensitivity

- **Contract value is commercially sensitive:** visible to Admin, HO roles, and the assigned Project PM only — never to site-level users, and excluded from site-facing screens and exports.
- HO dashboard gains a **projects overview**: active/awarded/on-hold/closed counts, and per project — value, PM, start, planned completion, % time elapsed, and open-items count (from the existing dashboards).

Current sites at go-live (imported as Active): SJR (Soneva Jani), SFR (Soneva Fushi), SSR (Soneva Secret), VKR (Vakkaru Maldives), SSL (Six Senses Laamu), BVR (Bvlgari Ranfushi), RCM (The Ritz-Carlton Maldives), MXR (Max Royal), WAM (Waldorf Astoria Maldives), CNR (Conrad Maldives), HPI (The Halcyon Private Isles). MLE (Head Office, Male') is a special non-project record for HO functions.

---

## 3. Roles and permissions

The Excel signature blocks define the real role model, which is finer than the prototype's SITE / HO / ADMIN:

| Role | Scope | Can create | Can approve | Notes |
|---|---|---|---|---|
| **Site Engineer** | one site | DPR, TWS, IR, MAR | — | Prepares DPR/TWS; submits IR (with QA/QC) and MAR (with QS) |
| **Site Admin / Storekeeper** | one site | DPR, MR, GRN | — | Owns MR sequence and register; counts and receives goods; records daily attendance (§6A) |
| **Project Manager (PM)** | one or more sites | any site doc | DPR (verify), IR, MAR, MR, OT hours | Approval is mandatory before IR/MAR/MR are issued; verifies DPR and GRN; approves overtime and signs off the monthly timesheet |
| **HO Purchasing** | all sites | PR, LM | — | Prepares PR and LM; maintains HO registers and Pending Items Log |
| **Sr PM / Director, Projects** | all sites | — | PR | PR approval authority |
| **Finance** | all sites | — | — | *Deferred (decision 6):* not a Phase 1 user. In Phase 1, HO Purchasing records the PR Action Taken (slip no. / PO no.) and payment status; a dedicated Finance role with invoice clearing against GRN comes in a later phase |
| **HO HR / Payroll** | all sites | employee records | timesheet reopen | Maintains the employee database (§6A); sole access (with Admin) to basic pay and passport data; exports month-locked timesheets for payroll |
| **Admin** | all sites | — | — | User management, site configuration, full read |

Design decisions:
- A user has exactly one role; PMs may be allocated to multiple sites (the Excel registers show one PM approving per site, but one person may cover several islands — the model must allow a site list per PM).
- **Server-enforced**: every create/approve/status-change is authorised on the server against role + site allocation, never only hidden in the UI.
- All roles have read access to their own site's registers; HO roles and Admin read all sites. Site users see the incoming LM register for their site (read-only), as in the prototype.

---

## 4. Numbering, revisions, and references

### 4.1 Numbering
- Site documents number **per site**: `TYPE-SITECODE-NNN` (e.g. `DPR-SJR-001`, `MR-VKR-014`). Zero-padded to 3 digits.
- Head Office documents number **globally**: `PR-NNN`, `LM-NNN`.
- Numbers are issued by the server at the moment of creation (first save as draft), sequentially, with no gaps and no reuse. A voided document keeps its number and is marked Void in the register — the register row remains.

### 4.2 Revisions — two distinct schemes (from the forms)
- **MAR and MR:** amendments/resubmissions keep the **same number** and step the revision: R0 → R1 → R2. Each revision is a new immutable snapshot; the register shows one row per revision (site MAR/MR registers say "one row per revision"). MAR "Revise & Resubmit" and MR amendments both follow this. New/changed MR lines must be markable (per instructions sheet: "mark new or changed lines clearly in Remarks" — the app should flag changed lines automatically).
- **IR:** a rejected inspection is resubmitted under a **new IR number**, quoting the previous IR in the "Rev / Previous IR" field. The app must link new IR → previous IR and show the chain.

### 4.3 Cross-references (the document chain)
`MR → PR → LM → GRN`, with the Pending Items Log hanging off LM:
- PR quotes one or more MR references; issuing a PR against an MR sets the HO MR-register status to "PR Raised" and records the PR ref.
- LM quotes MR and/or PR references; issuing an LM against an MR updates the site MR register (LM ref column) and MR status.
- GRN is raised **from** an LM: item lines (No., description, unit, qty loaded) copy automatically from the manifest; receiving updates LM status to Received / Received with Shortage (prototype already does this — keep it).
- Any LM line with Qty Pending > 0 automatically creates a Pending Items Log entry.
- IR may quote an NCR ref (closure); MAR/IR revisions link to predecessors as above.

All references are stored as foreign keys, not free text, wherever the target exists in the system; free-text fallback allowed for legacy/paper references.

---

## 5. Document specifications — full field maps

### 5.0 Item Master (product catalog)

A company-wide catalog of materials and consumables, referenced by MR, PR, LM, and GRN line items, so the same product carries the same description, unit, and identity through the whole chain.

**Item record:** item code (auto, e.g. `ITM-00412`) · description (full: size, grade, spec, brand where it matters) · unit (fixed per item: nos, kg, ltr, bag, m, m2, m3…) · category/trade (Civil, MEP, Finishes, Marine, General…) · preferred brand/manufacturer (optional) · specification ref (optional) · status (active/discontinued) · notes.

**Rules:**
- **Owned by HO Purchasing** (create, edit, merge duplicates, discontinue). Sites cannot edit the catalog.
- **MR entry:** line items are picked from the catalog via search/autocomplete (by description, code, or category); description and unit auto-fill and lock. This is the primary path.
- **Free-text escape hatch:** a site must never be blocked from requesting something new. A line may be entered as free text flagged *"new item — not in catalog"*; when Purchasing processes the MR they either match it to an existing item or promote it into the catalog (the MR line is then linked to the new item record). Repeated free-texting of items that already exist is visible to Purchasing and correctable at source.
- **Downstream uniformity:** PR, LM, and GRN lines created from an MR carry the item reference automatically — no retyping, no drift. GRN "Qty as per Manifest" and shortage tracking compare like with like.
- **Analytics unlocked (Phase 2):** consumption per item per site, over-ordering detection (supports the management notice on material discipline in the MR instructions), price history per item per vendor from PRs.
- Units are fixed per item to keep quantities comparable; if an item is genuinely handled in two units (e.g. cement by bag and by tonne), it exists as two catalog entries with a note.
- Seed the catalog by importing the item lines from historical MR/GRN Excel files (one-time cleanup exercise during rollout).


Fields marked **(auto)** are system-calculated or system-stamped; **(FK)** are linked references; **(sig)** are workflow signature events captured as name + timestamp (+ optional drawn signature — see §7 open question). Line-item counts in the Excel forms (14/20/22/25 rows) are print-layout limits, not data limits: the app allows unlimited rows and the PDF paginates.

### 5.1 DPR — Daily Progress Report (FRM-PRJ-01, R0) — one per site per working day

**Header:** DPR No. (auto) · Date / Day (day auto from date) · Client (auto from site) · Consultant (auto) · Project/Site (auto) · Site Code (auto) · Working Hours (default from site, editable) · Weather AM · Weather PM (Sunny/Cloudy/Rainy) · If Rained From/To · Rain Duration hrs (auto from from/to) · Work Time Lost hrs.

**1. Work Done Today** (rows): No. (auto) · Activity · Location/Area/Villa · Progress % · Remarks.

**2. Manpower** — structured count by category, not a single total:
- *Staff:* Project Manager, Site Engineer, MEP Engineer, QS/QC, Supervisor, Foreman, Site Admin/Storekeeper.
- *Trades/Labour:* Mason, Carpenter, Steel Fixer/Bar Bender, Welder, Plumber, Electrician, Painter/Tiler, Skilled Labour, Unskilled Labour, Driver/Kappi/Cleaner.
- **Total Manpower at Site (auto)** = sum of all categories.
- Categories are a single **company-wide** master list (admin-editable), applied identically at all sites (decision 4).

**3. Machinery & Equipment in Use** (rows): Item · Nos · Remarks (working/idle/breakdown).

**4. Key Materials at Site** (rows): Material · Unit · Opening Stock · Received Today · Consumed Today · **Balance (auto = Opening + Received − Consumed)** · Remarks. Key/bulk materials only. *Enhancement (Phase 2): carry yesterday's Balance forward as today's Opening Stock automatically.*

**5. Matters Affecting Progress** — free text (delays, shortages, weather impact).

**6. Visitors / Special Events / Client & Consultant Instructions** — free text.

**7. Safety:** Accidents/incidents today (Y/N) · Details / action taken (required if Y).

**Progress Photos:** minimum 4 photos with captions (location/activity), attached to the DPR; included in the PDF as a photos page(s), same DPR No. and date. **Hard validation (decision 8):** a DPR cannot be issued with fewer than 4 captioned photos.

**Signatures:** Prepared By — Site Engineer / Admin (sig) · Verified By — Project Manager (sig) · For Client/Consultant (blank block on PDF for manual sign, or recorded acknowledgement — see §7).

**Rules:** DPR + TWS issued to the client every working day; the dashboard flags a missing DPR for today (prototype behaviour — keep). Rain fields only relevant when weather is Rainy.

### 5.2 TWS — Tomorrow Work Schedule (FRM-PRJ-04, R0) — issued together with the DPR

**Header:** Schedule For (Date/Day) · Issued On (auto = today) · Client (auto) · Project/Site (auto) · Site Code (auto) · Working Hours.

**1. Planned Activities** (rows): No. (auto) · Planned Activity · Location/Area/Villa · Trade · Remarks (materials / equipment / dependencies). Carried-over activities noted in Remarks (Phase 2: "carry over unfinished" button from previous TWS/DPR).

**2. Planned Manpower** by category: *Staff:* Project Manager, Site Engineer, Supervisor/Foreman, Other staff. *Trades/Labour:* Mason/Tiler, Carpenter, Steel Fixer/Welder, Plumber/Electrician, Painter, Skilled/Unskilled Labour. **Total Planned Manpower (auto).** (Note: TWS categories are a coarser list than DPR — keep two company-wide lists, both admin-editable.)

**3. Access / Support Required from Client** — free text (permits, buggy, boat, area access, power isolation).

**Signatures:** Prepared By — Site Engineer (sig, with designation) · Acknowledged By — Client Representative (PDF block / recorded acknowledgement).

**Rules:** issue by end of the working day for the following day, together with the DPR.

### 5.3 IR — Inspection Request (FRM-PRJ-02, R0)

**Header:** IR No. (auto) · Rev / Previous IR (FK to prior IR when resubmitting) · Project/Site (auto) · Site Code (auto) · Client (auto) · Consultant/Engineer (auto) · Discipline (Civil/Structural/Architectural/MEP/Finishes/Marine/Other) · NCR Ref (if closure) · Inspection Requested Date + Time · Location/Villa.

**Part A — Contractor:** Description of work ready for inspection · Work proposed after inspection · Reference drawings/documents + Enclosed (Y/N) · QA/QC confirmation statement (fixed text on the PDF) · Submitted By — Site Engineer / QA-QC (sig, date + time) · **Approved By — Project Manager (sig, date + time — workflow gate).**

**Part B — Client/Consultant:** Received by Engineer's office (date/time) · Inspection carried out (date/time) · Observations/comments · **Result:** Approved / Approved with comments (close under Part C) / Rejected (resubmit) · Inspected By (name, position, date, time).

**Part C — Comment / Rejection Closure:** Corrective action taken by contractor (attach evidence) · Closed By Contractor — PM (sig) · Comments Closed / Verified By Client (name, date).

**Rules:** submit ≥ 24 hours before requested time (app warns, PM may override with reason). Resubmission = new IR number quoting the previous IR. Part B/C are recorded in-app by the site team on the client's behalf in Phase 1 (see §7).

### 5.4 MAR — Material Approval Request (FRM-PRJ-03, R0)

**Header:** MAR No. (auto) · Rev / Previous Rev (R0, R1… same number) · Project/Site (auto) · Site Code (auto) · Client/Employer (auto) · Consultant/Engineer (auto) · Attention To · Date Submitted.

**1. Material Details:** Material/Sample Description · Location/Use · Specification Ref · Drawing Ref · BOQ Ref · Manufacturer · Supplier · Country of Origin · Warranty (if any).

**2. Attachments/Enclosures (Y/N each):** Sample · Catalogue · Technical Data · Test Report · Compliance Sheet · Company Profile. File uploads attachable per enclosure; note on PDF: highlight the exact product/model/size in catalogues.

**3. Contractor's Confirmation:** Confirms to Specification (Y/N) · Proposed as Equivalent (Y/N) · Reasons for Alteration/Equivalent · Remarks.

**Signatures:** Submitted By — Site Engineer / QS (sig) · **Approved By — Project Manager (sig — workflow gate).**

**4. Client/Consultant Review:** Comments · **Result:** Approved / Approved with comments / Revise & resubmit / Rejected · Reviewed By (name, position, date).

**Rules:** do not order/ship before written approval (the app blocks adding a MAR-pending material to an MR? — Phase 2 consideration, flag only in Phase 1). Revise & resubmit keeps the same number at next revision and must address every comment; Approved-with-comments comments are binding conditions (shown wherever the MAR is referenced).

### 5.5 MR — Material Requisition (FRM-PRC-01, R1) — the only way a site requests materials

**Header:** MR No. (auto) · Revision (R0, amendments step R1, R2 — same number) · Project/Site (auto) · Site Code (auto) · Planned Loading/Trip (e.g. "August hired boat") · Date · Trades Covered (e.g. "MEP - Pool; Tiling - Ops Office") · Required On Site By (date).

**Items** (rows): No. (auto) · Item (picked from the Item Master, §5.0 — description and unit auto-fill; free-text allowed only as a flagged "new item") · Unit (auto from item) · Required Qty · Site Stock (physical count) · **Qty to Order (auto = Required − Stock, floor 0, manually overridable)** · Priority (Normal default / Urgent — urgent requires reason, candidate for resort supply boat) · Remarks (Trade / Purpose, e.g. "MEP - Pool", "General").

**Signatures:** Prepared By — Site Admin (sig) · **Approved By — Project Manager (sig — mandatory before sending; "unsigned MRs will be returned").**

**Rules (from the Instructions sheet — encode as validations/warnings):**
1. One consolidated MR per loading, all trades; every line identified by trade/work area in Remarks.
2. Reach HO ≥ 7 working days before loading (warn).
3. New requirements before loading = amend the existing MR (same number, next revision), changed lines flagged; do **not** raise a new MR for the same loading (warn if a second MR targets the same loading).
4. Urgent lines: reason required; channel decided by HO — the app never promises a channel.
5. Site Stock from a physical count on the day raised/amended (attestation checkbox).
6. PM approval before sending — hard gate.
7. Issued PDF goes to HO Purchasing (in-app notification replaces email; PDF archived).
8. MR number + revision quoted in all follow-ups (app threads comments to the MR).

### 5.6 GRN — Goods Received Note (FRM-PRC-04, R1)

**Header:** GRN No. (auto) · Date Received · Project/Site (auto) · Site Code (auto) · Vessel/Boat (auto from LM, editable) · Manifest Ref (FK — select from incoming LMs) · MR Reference(s) (auto from LM) · PR Reference(s) (auto from LM).

**Items** (rows, pre-filled from the manifest): No. · Item Description · Unit · Qty as per Manifest · Qty Received (physical count) · **Shortage/Excess (auto = Received − Manifest; negative = shortage, highlighted)** · Condition/Remarks (damage/rejection noted with photos).

**Signatures:** Received/Counted By — Site Admin / Storekeeper (sig) · Verified By — Site Engineer / PM (sig).

**Rules:** report all discrepancies to HO Purchasing within 24 hours of the boat's arrival (a GRN with shortage/damage auto-notifies HO Purchasing and stamps the report time). Finance clears vendor invoices against the GRN — GRNs are immutable once verified. Issuing the GRN sets the LM status to Received / Received with Shortage (prototype behaviour — keep).

### 5.7 PR — Procurement Requisition (FRM-PRC-02, R0) — Head Office

**Header:** PR No. (auto, global) · Date · Project/Site · Site Code · MR Reference(s) (FK) · Requested Delivery (date).

**Vendor rows:** No. · Vendor · Quotation Ref (quotation file attachable) · Payment Terms (e.g. 50% advance / balance on delivery, COD, 30 days credit) · Amount Cash/Bank (MVR) · Amount Credit (MVR) · **Total (auto)** · Action Taken — Slip No. / PO No. (entered by Finance). **Grand totals (auto)** for Cash/Bank, Credit, and overall.

**Signatures:** Prepared By — Purchasing (sig) · **Approved By — Sr PM / Director, Projects (sig — workflow gate)** · Finance — Payment / PO Issued (sig).

**Rules:** vendor quotations attached; a vendor may have both cash and credit amounts; Finance records the transfer slip no. (cash/bank) or PO number (credit) as Action Taken.

### 5.8 LM — Loading Manifest (FRM-PRC-03, R0) — Head Office

**Header:** Manifest No. (auto, global) · Loading Date · Vessel/Boat · Departure Point · Destination Site + Site Code · Expected Arrival (date) · Trip/Load No. · MR Reference(s) (FK) · PR Reference(s) (FK).

**Items** (rows): No. · Item Description · Unit · Qty Loaded · Qty Pending (balance not loaded this trip) · Condition/Remarks (lines belonging to a different reference are noted here). *Enhancement: pre-fill item lines from the referenced MR/PR.*

**Signatures:** Prepared By — Purchasing (sig) · Loaded/Checked By — boat crew countersign on departure (sig or PDF block) · Received At Site By (completed via the GRN link).

**Rules:** every Qty Pending > 0 line auto-creates a Pending Items Log entry; the destination site's GRN is raised from this manifest.

---

## 6. Registers

Registers are **views generated from document data** — no separate data entry, which eliminates the register-maintenance burden and the "no gaps" discipline problem. Columns replicate the Excel registers exactly for familiarity and PDF/Excel export.

**Site registers** (per site; visible to site users and HO):
- **DPR & TWS Register:** Date · Day · DPR Ref · TWS Ref · Sent to Client (Y/N) · Time Lost – Weather (hrs) · Prepared By · Remarks. One row per working day; the app inserts a highlighted gap row for any working day with no DPR. Default working week: **Saturday–Thursday, Friday off** (decision 5). A DPR issued on a Friday (when worked) is accepted and appears in the register, but a missing Friday is never flagged as a gap. Per-site calendar override and a holiday list remain available.
- **IR Register:** IR No. · Rev · Date Submitted · Discipline · Location/Villa · Inspection Date · Result · NCR Ref · Closure Status · Remarks.
- **MAR Register:** MAR No. · Rev · Date Submitted · Material Description · Discipline · Manufacturer/Origin · Result · Approval Date · Remarks — one row per revision.
- **MR Register:** MR No. · Rev · Date Sent · Planned Loading/Trip · Trades Covered · Required By · Status · Loading Manifest Ref · Remarks — one row per revision sent.
- **GRN register** (implied): GRN No. · Date · Manifest Ref · Items · Shortages · Status.

**Head Office master registers** (all sites, filterable by site — prototype's site filter kept):
- **MR Register (HO):** MR No. · Date · Site/Project · Site Code · Trade/Section · Prepared By · Approved By (PM) · Status · PR Ref (HO) · Remarks.
- **PR Register:** PR No. · Date · Site Code · MR Ref(s) · Vendor(s) · Total (MVR) · Payment Mode · Approved By · Finance Status · Action Taken (Slip/PO No.) · Remarks.
- **Manifest Register:** Manifest No. · Loading Date · Vessel · Destination Site · Site Code · MR/PR Ref(s) · Total Line Items · Received Date · Status · Shortage? (Y/N) · Remarks.
- **Pending Items Log:** Date · Site Code · HO PR Ref · Planned Manifest · Item Description · Unit · Qty Pending · Reason (e.g. Vendor Stock-Out) · Action/Next Loading · Status (Pending/Cleared) · Cleared Date · Cleared Manifest · Remarks. Auto-created from LM pending lines; HO Purchasing edits Reason/Action; clearing happens automatically when the item ships on a later LM (linked), or manually with reason.

All registers export to Excel and PDF in the existing layouts.

---

## 6A. Employees & Site Timesheets (payroll support — added at R1 review)

### 6A.1 Employee database

**Employee record:** Employee No. (auto, e.g. `EMP-0231`) · Full name · Passport no. · Nationality · Job category (from the company-wide manpower category list, §5.1 — one shared list keeps DPR manpower reporting and payroll consistent) · Basic pay (MVR/month) · Allocated site (transferable; allocation history kept, since payroll must know where each person worked and when) · Status (active/inactive) · Join date. *Recommended additions:* work permit no. + expiry date (with expiry alerts — a real operational risk with expatriate crews) and emergency contact.

**Rules:**
- Maintained by **HO HR / Payroll** (and Admin). Employees are **not** app users — labour and trades do not log in; app accounts may optionally link to an employee record (e.g. a Site Engineer who is also on payroll).
- **Confidentiality gating:** site users see only employee no., name, and job category for their site's roster — never basic pay or passport details. Basic pay and passport data are visible exclusively to HO HR/Payroll and Admin, and are excluded from all site-level exports.
- Deactivation, never deletion — attendance history is preserved.

### 6A.2 Daily timesheet

One attendance row per employee per day at their allocated site: Date · Check-in time · Check-out time · **Normal hours (auto**, calculated against the site's working hours) · OT duration requested (hrs) · **Approved OT (hrs — set by PM approval only)** · Remarks (present/absent/sick/leave/half day).

**Rules:**
- Recorded daily by the **Site Admin** (or Site Engineer) in a bulk-entry grid — the whole crew on one screen, check-in/out pre-filled from site working hours, exceptions edited.
- **OT approval:** the PM approves OT per day or batch-approves pending entries; unapproved OT is visible but can never flow into a payroll export. PM approval is stamped (name + timestamp) like any other approval in the system.
- Attendance can be entered for past days within the open month, but every late entry/edit is audited.

### 6A.3 Month close and payroll export

- At month end the site timesheet is **signed off by the PM (electronic stamp) and locked**. Corrections after lock require HO HR/Payroll to reopen the month with a reason (audited).
- **Payroll export** (Excel + printable PDF, per site and consolidated): per employee — days worked, absences, normal hours, approved OT hours, basic pay, and a **computed gross** = basic pay + (approved OT hrs × hourly rate × OT multiplier). The hourly-rate divisor and OT multiplier are **configurable company parameters**, set once to match Sand Planet policy and the Maldives Employment Act rather than hard-coded.
- Phase 1 delivers capture, approval, lock, and this export. Full payroll (allowances, deductions, payslips, bank files) is a later phase — the export feeds whatever HO currently uses.

### 6A.4 Synergy with the DPR (Phase 2)

Since attendance and DPR manpower use the same job categories, the DPR manpower section can auto-suggest counts from that day's attendance, and the system can flag mismatches between reported manpower and recorded attendance — a quiet but effective accuracy check.

---

## 7. Workflows and document lifecycles

### 7.1 State machines

Statuses extend the prototype's lists with the draft/approval stages the paper forms imply.

**DPR:** Draft → Issued to Client (by SE/Admin) → PM Verified. **Issue-then-verify (decision 3):** daily issue is never blocked on PM availability; the PM verifies electronically after issue, and both the PM's queue and the site dashboard flag unverified DPRs.

**TWS:** Draft → Issued (with the DPR) → Acknowledged (client rep acknowledgement recorded).

**IR:** Draft → Submitted (SE/QA-QC) → PM Approved → Issued to Client → Result recorded (Approved / Approved with Comments / Rejected) → [if AwC] Part C closure: Corrective Action → Closed by PM → Verified by Client → Closed. Rejected → new IR (linked). PM may Return to Draft with comments instead of approving.

**MAR:** Draft → Submitted (SE/QS) → PM Approved → Issued to Client → Result (Approved / Approved with Comments / Revise & Resubmit / Rejected). R&R → new revision (same number) restarting at Draft. Approval Date recorded on Approved/AwC.

**MR:** Draft → Submitted (Site Admin) → PM Approved → Sent to HO → [HO] PR Raised → Loading Planned (LM ref attached) → Partially Loaded / Loaded → Closed. Amendment → new revision restarting at Draft (previous revision remains visible, superseded).

**GRN:** Draft (pre-filled from LM) → Counted (Site Admin/Storekeeper) → Verified (SE/PM) → Complete / Shortage Reported / Damage Reported. Shortage/Damage auto-notifies HO Purchasing with a 24-hour clock from Date Received.

**PR:** Draft → Submitted (Purchasing) → Approved (Sr PM/Director) → Payment Processing → Paid / PO Issued → Closed. Also: Rejected, Cancelled. Phase 1 (decision 6): HO Purchasing records the payment status and Action Taken (slip/PO no.); the Finance role takes this over in a later phase.

**LM:** Draft → Loading → Departed (crew countersign) → In Transit → Received / Received with Shortage (set by the site's GRN).

### 7.2 Approval mechanics
- An approval = the approver's authenticated action, recorded as **name, role, timestamp, and optional comment**, immutable, shown in the document's audit trail and printed in the PDF signature block ("Approved by [Name], [Date] [Time] — approved electronically via Sand Planet Site Documents").
- Approvers can **Approve**, **Approve with comment**, or **Return with comment** (back to Draft).
- Documents are **immutable once issued**; corrections happen via the revision mechanism (MAR/MR), a new document (IR), or a Void + reissue (DPR/TWS/GRN/PR/LM, admin-visible, reason required).
- Every state change is written to an append-only audit log: document, from-state, to-state, actor, timestamp, comment.

### 7.3 Notifications (Phase 1: in-app; Phase 2: email/push)
- PM: documents awaiting approval at their site(s).
- HO Purchasing: MRs sent, GRN shortages/damage (urgent), MR amendments.
- Director: PRs awaiting approval. Purchasing: approved PRs awaiting payment/PO recording.
- Site: LM issued to their site (incoming boat), PR raised against their MR, pending items cleared.
- Site dashboard: no DPR issued today (existing prototype nudge — keep).

---

## 8. PDF generation

- Every issued document (and every revision) produces a **server-generated, archived PDF** matching the Excel print layout: Sand Planet ring emblem and letterhead, form number and rev in the header, document reference stamp, section numbering, signature blocks with electronic-approval stamps, photo pages for DPR.
- The PDF is generated at each workflow milestone (issue, client result, closure) and stored immutably; the register links to every generated PDF.
- Registers and the Pending Items Log export to PDF and Excel in the existing layouts.
- A4 portrait for all forms; item tables paginate with repeated headers when rows exceed one page.

---

## 9. Non-functional requirements

- **Connectivity/offline:** sites are remote islands with unreliable internet. Phase 1 minimum: the app is tolerant of dropouts (autosave drafts locally, retry sync, no data loss on submit failure). Phase 2 target: full offline drafting of DPR/TWS/GRN with background sync. This requirement shapes the front-end architecture (local-first draft storage) and must be decided before build.
- **Authentication & security:** server-side auth with hashed passwords (bcrypt/argon2), session or JWT tokens, enforced password rules, admin-managed accounts (no self-registration), account deactivation (never deletion — audit history preserved). All role/site authorisation enforced server-side. HTTPS only. **Sensitive personal data** (basic pay, passport numbers) is access-controlled at the API level, encrypted at rest where the platform supports it, and excluded from logs and site-level exports.
- **Audit & integrity:** append-only audit log; issued documents and generated PDFs immutable; numbering server-issued and gap-free; timestamps in Maldives time (UTC+5).
- **Data retention:** all documents, revisions, PDFs, and audit records retained indefinitely by default; no client contractual retention requirements identified (decision 9). Company default: never purge — storage cost is negligible at these volumes.
- **Photos/attachments:** image upload with client-side compression (site bandwidth), max size per file (suggest 5 MB post-compression), stored in object storage, virus-scanned if hosted service allows.
- **Usability:** works on mid-range Android phones and laptops (site engineers often work from phones); English UI; date format dd/mm/yy as per the Excel forms.
- **Performance:** registers paginate; a project generates ~300 DPRs/year/site — trivial volumes, so simplicity beats scale.
- **Backup:** automated daily database + object-storage backups, tested restore.

---

## 10. Recommended architecture (for discussion)

- **Backend:** single web application — Node (NestJS/Express) or Python (Django) — with **PostgreSQL**. Django is a strong fit: built-in auth, admin panel for site/user/category configuration, mature PDF ecosystem.
- **PDF:** HTML→PDF via headless Chromium (Playwright/WeasyPrint) using templates that mirror the Excel layouts — one template per form.
- **Frontend:** React SPA (reusing the prototype's screens and visual language: navy/sky brand, form cards, register tables) with local-first draft storage (IndexedDB) for connectivity tolerance.
- **Storage:** Postgres for documents/registers/audit; S3-compatible object storage for photos, attachments, and archived PDFs.
- **Hosting:** managed platform confirmed (decision 10) — e.g. Railway, Render, or DigitalOcean App Platform with managed PostgreSQL and object storage. Choose a Singapore region for Maldives latency; domain e.g. docs.sandplanet.mv; automated TLS; platform-managed daily backups plus a weekly off-platform backup export.
- **Data model sketch:** `sites` (project record: code, name, scope, contract value + currency, award/start/planned/actual dates, status, client + consultant contacts, PM assignment history, working settings — §2), `users`, `user_site_allocations`, `items` (item master, §5.0), `employees`, `employee_site_allocations` (with date ranges), `attendance` (daily rows, OT approval fields), `timesheet_months` (per site per month: status open/locked, PM sign-off), `documents` (type, ref, site, revision, status, immutable payload JSON per revision), `document_lines` (typed line items for MR/GRN/LM/PR, each with an `item_id` FK to the item master plus free-text fallback fields), `document_links` (MR→PR→LM→GRN, IR→previous IR), `approvals`, `audit_log`, `pending_items`, `attachments`, `manpower_categories`, `holidays`, `company_parameters` (OT multiplier, hourly-rate divisor, etc.).

---

## 11. Phasing

**Phase 1 — Core (replaces Excel):** auth + roles; Site & Project Management module with full lifecycle (§2); Item Master with catalog-driven MR entry (§5.0); all 8 documents with full fields; PM/Director approval gates; auto registers + Pending Items Log; MR→PR→LM→GRN chain; employee database + daily timesheets with PM-approved OT, month lock, and payroll export (§6A); PDF generation; photo upload on DPR; in-app notifications; register export.

**Phase 2:** offline drafting + sync; email notifications; DPR material-balance carry-forward; TWS activity carry-over; LM pre-fill from MR/PR; MAR-status checks on MR lines; DPR manpower auto-suggest from attendance + mismatch flags (§6A.4); work-permit expiry alerts; item-master analytics (consumption per site, over-ordering detection, vendor price history); analytics dashboard (time lost, manpower trends, shortage rates, MR lead-time compliance).

**Phase 3 (optional):** client/consultant portal for IR/MAR review and DPR acknowledgement; NCR module; vendor/PO module linking Finance systems; full payroll (allowances, deductions, payslips, bank files); full site stock book.

---

## 12. Decisions log (resolved 07 Jul 2026 — management review of R0)

1. **Client interaction:** deferred to a later phase. Phase 1: the site team records client results (IR Part B/C, MAR review, TWS acknowledgement) in-app; the client signs the printed/emailed PDF.
2. **Signatures:** electronic approval stamps (name + role + timestamp) are acceptable on all issued PDFs. No drawn/wet-signature capture required.
3. **DPR flow:** issue-then-verify. The DPR goes to the client without waiting for the PM; the PM verifies electronically afterwards.
4. **Manpower categories:** company-wide lists (admin-editable), identical at every site.
5. **Working calendar:** default working week Saturday–Thursday; Friday off in general but worked depending on load. Friday DPRs accepted; missing Fridays never flagged as gaps.
6. **Finance:** out of scope for Phase 1. HO Purchasing records payment status and Action Taken (slip/PO no.) on the PR. Finance role and invoice clearing move to a later phase.
7. **Defaults confirmed:** PR Requested Delivery is a plain date field; LM Departure Point defaults to Male'.
8. **Photo minimum:** hard requirement — a DPR cannot be issued with fewer than 4 captioned photos.
9. **Retention:** no client contractual requirements; retain everything indefinitely by default.
10. **Hosting:** managed hosting service on an established platform; no internal server administration.
11. **Item Master (added at R1 review):** a company-wide product catalog is included in Phase 1. MR lines are picked from the catalog for uniform descriptions and units end-to-end (MR→PR→LM→GRN), with a flagged free-text path for new items, promoted into the catalog by HO Purchasing. See §5.0.
12. **Employees & Timesheets (added at R1 review):** employee database (name, passport no., nationality, job category, basic pay) and daily site timesheets (check-in/out, PM-approved OT hours) included in Phase 1, with month lock and payroll export for HO. Pay and passport data restricted to HO HR/Payroll + Admin. See §6A.
13. **Site & Project Management module (added at R1 review):** sites are full project records created at award and closed at completion, with lifecycle Awarded → Active → On Hold → Closed, carrying project scope, contract value, duration dates, client details, and the assigned Project PM (which drives approval routing). Contract value visible to HO/Admin/assigned PM only. See §2.

---
*Draft R1 — approved decisions incorporated — Sand Planet Site Documents System.*
