import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, SelectOrOther, card, inputStyle, td, th } from "./ui.jsx";

const RAISE = ["PM", "HO_HR", "ADMIN", "DIRECTOR", "PA"];
const APPROVE = ["DIRECTOR", "ADMIN"];
const STATUS_TONE = {
  DRAFT: "info", SUBMITTED: "warn", RETURNED: "alert", APPROVED: "ok",
  IN_PROGRESS: "ok", COMPLETED: "ok", REJECTED: "alert", CANCELLED: "info",
};
const ROUTE_LABEL = { WP: "Work permit", BV: "Business visa" };
const CATEGORIES = [["SKILLED", "Skilled"], ["UNSKILLED", "Unskilled"],
                    ["STAFF", "Staff"]];
const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });
const fmtDate = (s) => s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—";

// Onboarding — expat recruitment / visa / mobilisation cases. PM/HR raise,
// the Director (PD) approves, HR processes the visa stages.
const COLUMNS = [
  ["ref", "Ref"], ["full_name", "Candidate"], ["route", "Route"],
  ["trade_designation", "Trade"], ["site_code", "Site"],
  ["status", "Status"], ["doc_date", "Raised"], ["updated_at", "Idle"],
];

const DAY = 864e5;

function days(from) {
  if (!from) return null;
  return Math.floor((Date.now() - new Date(from).getTime()) / DAY);
}

function ageText(d) {
  const n = days(d);
  if (n == null) return "";
  if (n <= 0) return "today";
  if (n === 1) return "yesterday";
  if (n < 31) return `${n} days ago`;
  const m = Math.floor(n / 30);
  return `${m} month${m === 1 ? "" : "s"} ago`;
}

// Only a live case can be idle — a closed one is not waiting on anybody.
function IdleFor({ since, live }) {
  const n = days(since);
  if (!live || n == null) return <span style={{ color: "var(--muted)" }}>—</span>;
  const tone = n >= 30 ? "#c0392b" : n >= 14 ? "#b35900" : "var(--muted)";
  return (
    <span style={{ color: tone, fontWeight: n >= 14 ? 700 : 400 }}>
      {n <= 0 ? "today" : `${n}d`}
    </span>
  );
}

// Money on the case that has not actually gone. A fee only shows in the stage
// block while the case sits at that stage, so once an authorised-but-unpaid
// fee let the case move on, the outstanding amount disappeared from the
// screen (owner 2026-08-16). Authorised is enough to keep the case moving; it
// is not enough to stop showing what is owed.
function UnpaidFees({ fees }) {
  if (!fees?.length) return null;
  return (
    <>
      {fees.map((f) => (
        <div key={f.pyr_ref} style={{ fontSize: 11, marginTop: 1,
                                      color: f.authorised ? "#b35900"
                                                          : "#8a6d00" }}>
          {f.label}: {f.pyr_ref}
          {f.amount != null && ` · ${f.currency} ${Number(f.amount)
            .toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
          {f.authorised ? " — authorised, not paid"
                        : ` — ${(f.pyr_status || "").toLowerCase()
                            .replace(/_/g, " ")}`}
        </div>
      ))}
    </>
  );
}

// Where a payment stage has actually got to.
function FeeState({ fee }) {
  if (!fee) return null;
  const line = (text, tone) => (
    <div style={{ fontSize: 11, color: tone, marginTop: 1 }}>{text}</div>
  );
  if (!fee.raised) return line("fee not raised yet", "#b35900");
  if (fee.paid) return line(`${fee.pyr_ref} paid — ready to advance`,
                            "#1a7f37");
  return line(`${fee.pyr_ref} · ${(fee.pyr_status || "")
    .toLowerCase().replace(/_/g, " ")} — with Finance`, "#b35900");
}

function SortHeader({ col, label, sort, setSort }) {
  const on = sort.key === col;
  return (
    <th style={{ ...th, textAlign: "left", cursor: "pointer",
                 whiteSpace: "nowrap", userSelect: "none" }}
        onClick={() => setSort(
          on ? { key: col, dir: sort.dir === "asc" ? "desc" : "asc" }
             : { key: col, dir: col === "doc_date" ? "desc" : "asc" })}>
      {label}
      <span style={{ opacity: on ? 1 : .25, marginLeft: 4 }}>
        {on && sort.dir === "asc" ? "▲" : "▼"}
      </span>
    </th>
  );
}

export default function OnboardingPage({ me, sites }) {
  const [cases, setCases] = useState(null);
  const [view, setView] = useState("list");     // 'list' | 'new'
  const [openId, setOpenId] = useState(null);    // case detail id
  const [filter, setFilter] = useState("open");  // open | mine | all
  // Newest first by default — the list had no order anyone could rely on.
  const [sort, setSort] = useState({ key: "doc_date", dir: "desc" });
  const [error, setError] = useState(null);
  const canRaise = RAISE.includes(me.role);

  function load() {
    const q = filter === "open" ? "?open=1"
      : filter === "mine" ? "?mine=1" : "";
    api(`/onboarding${q}`).then(setCases).catch((e) => setError(e.message));
  }
  useEffect(() => { load(); }, [filter]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (view === "new")
    return <NewCase sites={sites} onCancel={() => setView("list")}
             onDone={(c) => { setView("list"); setOpenId(c.id); load(); }} />;
  if (openId)
    return <CaseDetail id={openId} me={me}
             onBack={() => { setOpenId(null); load(); }} />;

  // Sorted on the client, over everything the server returned, so the order
  // does not change under you as pages load.
  const sorted = [...(cases || [])].sort((a, b) => {
    const dir = sort.dir === "asc" ? 1 : -1;
    const x = a[sort.key], y = b[sort.key];
    if (x == null && y == null) return 0;
    if (x == null) return 1;            // blanks last, whichever way we sort
    if (y == null) return -1;
    const cmp = typeof x === "string" && typeof y === "string"
      ? x.localeCompare(y, undefined, { numeric: true })
      : (x > y ? 1 : x < y ? -1 : 0);
    return cmp * dir || (a.id > b.id ? -1 : 1);
  });

  return (
    <div style={{ maxWidth: 1180 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h1 style={{ margin: 0 }}>Onboarding</h1>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          Expat recruitment · visa / permit · mobilisation</span>
        {canRaise && (
          <Btn variant="primary" style={{ marginLeft: "auto" }}
               onClick={() => setView("new")}>+ New case</Btn>
        )}
      </div>
      <div style={{ display: "flex", gap: 6, margin: "12px 0" }}>
        {[["open", "Active"], ["mine", "Raised by me"], ["all", "All"]]
          .map(([k, l]) => (
          <button key={k} onClick={() => setFilter(k)}
            style={{ padding: "5px 13px", border: "1px solid var(--line)",
              borderRadius: 6, cursor: "pointer", fontSize: 13,
              background: filter === k ? "var(--navy)" : "#fff",
              color: filter === k ? "#fff" : "var(--navy)" }}>{l}</button>
        ))}
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {cases === null ? <div style={card}>Loading…</div>
       : !cases.length ? <div style={card}>No cases.</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              {COLUMNS.map(([key, label]) => (
                <SortHeader key={key} col={key} label={label}
                            sort={sort} setSort={setSort} />
              ))}
            </tr></thead>
            <tbody>
              {sorted.map((c) => (
                <tr key={c.id} style={{ cursor: "pointer" }}
                    onClick={() => setOpenId(c.id)}>
                  <td style={{ ...td, fontFamily: "var(--font-mono)" }}>{c.ref}</td>
                  <td style={td}>{c.full_name}
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>
                      {c.nationality}</div></td>
                  <td style={td}>{ROUTE_LABEL[c.route] || c.route}</td>
                  <td style={td}>{c.trade_designation || "—"}</td>
                  <td style={td}>{c.site_code}</td>
                  <td style={td}>
                    {["APPROVED", "IN_PROGRESS"].includes(c.status)
                     && (c.pending_label || c.stage_label) ? (
                      <>
                        <div style={{ fontWeight: 600,
                                      color: "var(--sp-navy)" }}>
                          {(c.pending_label || c.stage_label)} pending</div>
                        {/* A payment stage reads "pending" whether HR still
                            has to raise the fee, Finance still has to pay it,
                            or it is paid and simply needs advancing — three
                            very different waits (owner 2026-08-16). */}
                        {c.at_payment && <FeeState fee={c.fee} />}
                        <UnpaidFees fees={c.outstanding_fees} />
                        <div style={{ display: "flex", gap: 10,
                                      flexWrap: "wrap", fontSize: 11,
                                      color: "var(--muted)", marginTop: 1 }}>
                          {c.medical_due && !c.medical_result && (
                            <span>Medical<Countdown d={c.medical_due}
                                                    warnAt={7} /></span>)}
                          {c.bv_expiry && c.stage !== "WP_ISSUED" && (
                            <span>BV exp<Countdown d={c.bv_expiry}
                                                   warnAt={14} /></span>)}
                        </div>
                      </>
                    ) : (
                      <>
                        <Chip tone={STATUS_TONE[c.status]}>
                          {c.status.replace(/_/g, " ")}</Chip>
                        <UnpaidFees fees={c.outstanding_fees} />
                      </>
                    )}
                  </td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>
                    {c.doc_date}
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>
                      {ageText(c.doc_date)}
                    </div>
                  </td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>
                    {/* How long since anything happened to it. A case that
                        has not moved in a month is the one to chase, and the
                        list gave no way to see that. */}
                    <IdleFor since={c.updated_at} live={
                      ["APPROVED", "IN_PROGRESS"].includes(c.status)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const BLANK = {
  full_name: "", nationality: "", date_of_birth: "", gender: "",
  marital_status: "", old_passport_no: "",
  passport_no: "", passport_expiry: "", category: "", trade_designation: "",
  proposed_salary: "", currency: "MVR", allowances: [], route: "WP",
  bv_justification: "", bv_purpose: "", subcontractor_id: "",
  quota_pool: "SANDPLANET",
  permanent_address: "", mobile: "", emergency_contact: "",
  mobilisation_date: "",
};

// A text/date field bound to one key of the form. Defined at module level (not
// inside CaseForm) so it keeps a stable identity across renders — otherwise
// React remounts the <input> on every keystroke and it loses focus.
function Field({ label, k, type = "text", req, value, onChange }) {
  return (
    <label style={fld}>{label}{req && <span style={{ color: "var(--red-fg)" }}> *</span>}
      <input style={inputStyle} type={type} value={value[k]}
             onChange={(e) => onChange({ ...value, [k]: e.target.value })} />
    </label>
  );
}

const ALLOWANCE_TYPES = ["Food", "Accommodation", "Transport"];

function AllowancesEditor({ list, currency, onChange }) {
  const rows = list || [];
  const upd = (i, patch) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>
        Allowances (optional) — monthly, shown on the appointment letter</div>
      {rows.map((r, i) => {
        const other = !ALLOWANCE_TYPES.includes(r.type);
        return (
          <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6,
            alignItems: "center", flexWrap: "wrap" }}>
            <select style={{ ...inputStyle, width: 150 }}
              value={other ? "Other" : r.type}
              onChange={(e) => upd(i, { type:
                e.target.value === "Other" ? "" : e.target.value })}>
              {ALLOWANCE_TYPES.map((t) => <option key={t}>{t}</option>)}
              <option value="Other">Other…</option>
            </select>
            {other && (
              <input style={{ ...inputStyle, width: 150 }}
                placeholder="Allowance name" value={r.type}
                onChange={(e) => upd(i, { type: e.target.value })} />
            )}
            <input style={{ ...inputStyle, width: 120 }} inputMode="decimal"
              placeholder="Amount" value={r.amount}
              onChange={(e) => upd(i, { amount: e.target.value })} />
            <select style={{ ...inputStyle, width: 80 }}
              value={r.currency || currency || "MVR"}
              onChange={(e) => upd(i, { currency: e.target.value })}>
              <option value="MVR">MVR</option>
              <option value="USD">USD</option>
            </select>
            <button type="button" title="Remove"
              onClick={() => onChange(rows.filter((_, j) => j !== i))}
              style={{ border: "none", background: "none", cursor: "pointer",
                color: "var(--red-fg)", fontSize: 16 }}>×</button>
          </div>
        );
      })}
      <button type="button"
        onClick={() => onChange([...rows,
          { type: "Food", amount: "", currency: currency || "MVR" }])}
        style={{ border: "1px dashed var(--line)", background: "none",
          borderRadius: 6, padding: "3px 10px", fontSize: 12, cursor: "pointer",
          color: "var(--navy)" }}>+ Add allowance</button>
    </div>
  );
}

function CaseForm({ value, onChange, subs = [] }) {
  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value });
  // A subcontractor's BV worker is never on payroll and never gets a work
  // permit, so salary + quota pool don't apply to them.
  const isSub = value.route === "BV" && value.bv_purpose === "SUBCONTRACT";
  const F = (p) => <Field {...p} value={value} onChange={onChange} />;
  return (
    <>
      <div style={grid}>
        {F({ label: "Full name", k: "full_name", req: true })}
        {F({ label: "Nationality", k: "nationality", req: true })}
        {F({ label: "Passport no.", k: "passport_no", req: true })}
        {F({ label: "Date of birth", k: "date_of_birth", type: "date" })}
        <label style={fld}>Gender
          <select style={inputStyle} value={value.gender} onChange={set("gender")}>
            <option value="">—</option><option>Male</option><option>Female</option>
          </select></label>
        <label style={fld}>Marital status
          <select style={inputStyle} value={value.marital_status || ""}
                  onChange={set("marital_status")}>
            <option value="">—</option>
            <option value="Single">Single</option>
            <option value="Married">Married</option></select></label>
        {F({ label: "Passport expiry", k: "passport_expiry", type: "date" })}
        {F({ label: "Old passport no.", k: "old_passport_no" })}
        <label style={fld}>Category <span style={{ color: "var(--red-fg)" }}>*</span>
          <select style={inputStyle} value={value.category}
                  onChange={set("category")}>
            <option value="">—</option>
            {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></label>
        {F({ label: "Trade / designation", k: "trade_designation", req: true })}
        {!isSub && (
          <label style={fld}>Proposed salary
            <span style={{ color: "var(--red-fg)" }}> *</span>
            <div style={{ display: "flex", gap: 4 }}>
              <input style={{ ...inputStyle, flex: 1 }} inputMode="decimal"
                     value={value.proposed_salary}
                     onChange={set("proposed_salary")} />
              <select style={{ ...inputStyle, width: 70 }} value={value.currency}
                      onChange={set("currency")}>
                <option>MVR</option><option>USD</option></select>
            </div></label>
        )}
        <label style={fld}>Route <span style={{ color: "var(--red-fg)" }}>*</span>
          <select style={inputStyle} value={value.route} onChange={set("route")}>
            <option value="WP">Work permit (standard)</option>
            <option value="BV">Business visa (urgent)</option></select></label>
        {!isSub && (
          <label style={fld}>Quota pool (portal login)
            <select style={inputStyle} value={value.quota_pool || "SANDPLANET"}
                    onChange={set("quota_pool")}>
              <option value="SANDPLANET">Sand Planet</option>
              <option value="MARINE">Sand Planet Marine</option></select></label>
        )}
        {F({ label: "Mobile / contact", k: "mobile" })}
        {F({ label: "Expected mobilisation", k: "mobilisation_date",
             type: "date" })}
      </div>
      {!isSub && (
        <AllowancesEditor list={value.allowances} currency={value.currency}
          onChange={(a) => onChange({ ...value, allowances: a })} />
      )}
      {value.route === "BV" && (
        <div style={{ display: "grid", gap: 8,
          gridTemplateColumns: "1fr 1fr", marginTop: 8 }}>
          <label style={fld}>BV purpose
            <span style={{ color: "var(--red-fg)" }}> *</span>
            <select style={inputStyle} value={value.bv_purpose || ""}
                    onChange={(e) => {
                      const p = e.target.value;
                      onChange({ ...value, bv_purpose: p,
                        ...(p === "SUBCONTRACT"
                          ? { proposed_salary: "", subcontractor_id: "" }
                          : { subcontractor_id: "" }) });
                    }}>
              <option value="">—</option>
              <option value="RECRUITMENT">Recruitment (→ work permit)</option>
              <option value="SUBCONTRACT">Subcontractor's worker</option>
            </select></label>
          {value.bv_purpose === "SUBCONTRACT" && (
            <label style={fld}>Subcontractor
              <span style={{ color: "var(--red-fg)" }}> *</span>
              <select style={inputStyle} value={value.subcontractor_id || ""}
                      onChange={set("subcontractor_id")}>
                <option value="">
                  {subs.length ? "Select…" : "No approved subcontractors"}</option>
                {subs.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select></label>
          )}
        </div>
      )}
      {value.route === "BV" && (
        <label style={{ ...fld, marginTop: 8 }}>
          Business-visa justification <span style={{ color: "var(--red-fg)" }}>*</span>
          <textarea style={{ ...inputStyle, minHeight: 40 }}
            value={value.bv_justification}
            onChange={set("bv_justification")} /></label>
      )}
      <label style={{ ...fld, marginTop: 8 }}>Permanent address
        <textarea style={{ ...inputStyle, minHeight: 40 }}
          value={value.permanent_address}
          onChange={set("permanent_address")} /></label>
      <label style={{ ...fld, marginTop: 8 }}>Emergency contact
        <input style={inputStyle} value={value.emergency_contact}
          onChange={(e) => onChange({ ...value,
            emergency_contact: e.target.value })} /></label>
    </>
  );
}

function NewCase({ sites, onCancel, onDone }) {
  const [siteId, setSiteId] = useState(sites?.[0]?.id || "");
  const [form, setForm] = useState({ ...BLANK });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [scanMsg, setScanMsg] = useState("");
  const [subs, setSubs] = useState([]);
  const scanFile = useRef(null);

  useEffect(() => {
    if (!siteId) { setSubs([]); return; }
    api(`/onboarding/subcontractors?site_id=${siteId}`)
      .then(setSubs).catch(() => setSubs([]));
  }, [siteId]);

  async function scanPassport(file) {
    if (!file) return;
    setScanning(true); setScanMsg(""); setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { fields } = await apiUpload("/onboarding/passport-scan", fd);
      setForm((f) => {
        const merged = { ...f };
        for (const [k, v] of Object.entries(fields || {})) {
          if (v) merged[k] = v;          // only overwrite with a read value
        }
        return merged;
      });
      scanFile.current = file;           // stored as the passport copy on create
      const got = Object.values(fields || {}).filter(Boolean).length;
      setScanMsg(got
        ? `Read ${got} field${got > 1 ? "s" : ""} — review below before saving.`
        : "Couldn't read it clearly — enter the details manually.");
    } catch (err) { setError(err.message); }
    setScanning(false);
  }

  async function submit(e) {
    e.preventDefault();
    if (!siteId) { setError("Choose the destination site."); return; }
    setBusy(true); setError(null);
    try {
      const c = await api(`/sites/${siteId}/onboarding`,
        { method: "POST", body: form });
      if (scanFile.current) {            // keep the scanned image as the copy
        try {
          const fd = new FormData();
          fd.append("kind", "PASSPORT_COPY");
          fd.append("file", scanFile.current);
          await apiUpload(`/onboarding/${c.id}/documents`, fd);
        } catch { /* non-fatal — HR can attach it in the checklist */ }
      }
      onDone(c);
    } catch (err) { setError(err.message); setBusy(false); }
  }

  return (
    <form onSubmit={submit} style={{ ...card, maxWidth: 860 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>New onboarding case</h2>
        <button type="button" onClick={onCancel} style={linkBtn}>Cancel</button>
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      <label style={{ ...fld, marginBottom: 8 }}>Destination site
        <span style={{ color: "var(--red-fg)" }}> *</span>
        <select style={inputStyle} value={siteId}
                onChange={(e) => setSiteId(e.target.value)}>
          <option value="">Select…</option>
          {(sites || []).map((s) => (
            <option key={s.id} value={s.id}>{s.code} — {s.name}</option>))}
        </select></label>
      <div style={{ border: "1px dashed var(--sky)", borderRadius: 8,
        padding: 10, marginBottom: 10, background: "var(--sky-soft)",
        display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <label style={{ fontSize: 12.5, fontWeight: 600, color: "var(--navy)",
          cursor: scanning ? "default" : "pointer", whiteSpace: "nowrap" }}>
          📷 Scan passport to autofill
          <input type="file" accept="image/*,application/pdf"
                 disabled={scanning} style={{ display: "none" }}
                 onChange={(e) => scanPassport(e.target.files[0])} />
        </label>
        <span style={{ fontSize: 11, color: "var(--muted)" }}>
          {scanning ? "Reading passport…" : scanMsg
            || "Upload the passport photo page — details are read in and kept "
               + "as the passport copy."}</span>
      </div>
      <CaseForm value={form} onChange={setForm} subs={subs} />
      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        <Btn variant="primary" disabled={busy}>Create case</Btn>
        <span style={{ fontSize: 12, color: "var(--muted)",
                       alignSelf: "center" }}>
          You'll attach the required documents next, then submit for approval.</span>
      </div>
    </form>
  );
}

export function CaseDetail({ id, me, onBack }) {
  const [c, setC] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);

  const [subs, setSubs] = useState([]);
  const load = () => api(`/onboarding/${id}`).then((d) => { setC(d); setForm(d); })
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (c?.site_id) api(`/onboarding/subcontractors?site_id=${c.site_id}`)
      .then(setSubs).catch(() => setSubs([]));
  }, [c?.site_id]);

  if (error) return <div style={card}>{error}
    <div><button style={linkBtn} onClick={onBack}>← Back</button></div></div>;
  if (!c) return <div style={card}>Loading…</div>;

  const editable = ["DRAFT", "RETURNED"].includes(c.status);
  const canRaise = RAISE.includes(me.role);
  const canApprove = APPROVE.includes(me.role);

  async function act(fn) {
    setBusy(true); setError(null);
    try { await fn(); await load(); } catch (e) { setError(e.message); }
    setBusy(false);
  }
  const submit = () => act(() =>
    api(`/onboarding/${id}/submit`, { method: "POST" }));
  const decide = (action) => act(async () => {
    let note = "";
    if (action === "return" || action === "reject") {
      note = window.prompt(action === "return"
        ? "Reason to return to the raiser:" : "Reason to reject:") || "";
      if ((action === "return") && !note.trim()) throw new Error("A reason is required.");
    }
    await api(`/onboarding/${id}/action`,
      { method: "POST", body: { action, note } });
  });
  async function saveEdit() {
    await act(() => api(`/onboarding/${id}`, { method: "PATCH", body: form }));
    setEditing(false);
  }

  return (
    <div style={{ maxWidth: 860 }}>
      <button style={linkBtn} onClick={onBack}>← All cases</button>
      <div style={{ ...card, marginTop: 8, display: "flex", gap: 14,
                    alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10,
                      flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, fontFamily: "var(--font-mono)" }}>{c.ref}</h2>
          <Chip tone={STATUS_TONE[c.status]}>{c.status.replace(/_/g, " ")}</Chip>
          <span style={{ color: "var(--muted)" }}>{c.site_code} ·{" "}
            {ROUTE_LABEL[c.route]}</span>
          {editable && canRaise && !editing && (
            <button style={{ ...linkBtn, marginLeft: "auto" }}
                    onClick={() => setEditing(true)}>Edit details</button>
          )}
        </div>
        {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}

        {editing ? (
          <div style={{ marginTop: 10 }}>
            <CaseForm value={form} onChange={setForm} subs={subs} />
            <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
              <Btn variant="primary" disabled={busy} onClick={saveEdit}>Save</Btn>
              <button style={linkBtn} onClick={() => { setEditing(false);
                setForm(c); }}>Cancel</button>
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: "2px 20px", marginTop: 10,
            gridTemplateColumns: "repeat(2, 1fr)", fontSize: 13 }}>
            <Row k="Candidate" v={`${c.full_name} · ${c.nationality}`} />
            <Row k="Passport" v={`${c.passport_no}${c.passport_expiry
              ? " · exp " + fmtDate(c.passport_expiry) : ""}`} />
            <Row k="Trade / category" v={`${c.trade_designation} · ${c.category}`} />
            <Row k="Quota pool" v={c.quota_pool_label || "Sand Planet"} />
            <Row k="Proposed salary" v={`${c.currency} ${money(c.proposed_salary)}`} />
            {(c.allowances || []).length > 0 && (
              <Row k="Allowances" v={c.allowances.map((a) =>
                `${a.type} ${a.currency || c.currency} ${money(a.amount)}`)
                .join(" · ")} />
            )}
            <Row k="DOB / gender" v={`${fmtDate(c.date_of_birth)} · ${c.gender || "—"}`} />
            <Row k="Mobilisation" v={fmtDate(c.mobilisation_date)} />
            <Row k="Mobile" v={c.mobile || "—"} />
            <Row k="Emergency" v={c.emergency_contact || "—"} />
            {c.route === "BV" && <Row k="BV purpose"
              v={c.bv_purpose_label || "—"} />}
            {c.is_subcontract && <Row k="Subcontractor"
              v={c.subcontractor_name || "—"} />}
            {c.bv_expiry && <Row k="Visa expiry"
              v={`${fmtDate(c.bv_expiry)}${c.bv_renewals
                ? ` · ${c.bv_renewals} extension${c.bv_renewals > 1 ? "s" : ""}`
                : ""}`} />}
            {c.bv_justification && <Row k="BV reason" v={c.bv_justification} />}
            <Row k="Raised by" v={c.created_by} />
          </div>
        )}
        </div>
        {c.photo_att_id && (
          <img src={`/api/v1/onboarding/${c.id}/attachments/${c.photo_att_id}`}
               alt="Passport photo"
               style={{ width: 96, height: 120, objectFit: "cover",
                 borderRadius: 6, border: "1px solid var(--line)",
                 flexShrink: 0 }} />
        )}
      </div>

      {/* processing */}
      {["APPROVED", "IN_PROGRESS", "COMPLETED"].includes(c.status) && (
        <Processing c={c} me={me} onReload={load} />
      )}

      {/* checklist */}
      <div style={{ ...card, marginTop: 12 }}>
        <h3 style={{ marginTop: 0 }}>Documents</h3>
        {c.checklist.map((d) => (
          <ChecklistRow key={d.kind} caseId={id} item={d}
            editable={editable && canRaise} onChange={load} />
        ))}
      </div>

      {/* actions */}
      <div style={{ ...card, marginTop: 12, display: "flex", gap: 8,
                    flexWrap: "wrap" }}>
        {editable && canRaise && (
          <Btn variant="primary" disabled={busy || c.missing_docs.length}
               onClick={submit}
               title={c.missing_docs.length
                 ? "Attach all documents first" : ""}>
            Submit for Director approval</Btn>
        )}
        {c.status === "SUBMITTED" && canApprove && (<>
          <Btn variant="primary" disabled={busy}
               onClick={() => decide("approve")}>Approve (Director)</Btn>
          <Btn variant="secondary" disabled={busy}
               onClick={() => decide("return")}>Return</Btn>
          <Btn variant="danger" disabled={busy}
               onClick={() => decide("reject")}>Reject</Btn>
        </>)}
        {c.status !== "SUBMITTED" && c.can_send_back && canApprove && (
          <Btn variant="secondary" disabled={busy}
               onClick={() => decide("return")}
               title="Return this case to the raiser to correct details">
            ↩ Send back to edit</Btn>
        )}
        {editable && canRaise && (
          <button style={{ ...linkBtn, color: "var(--red-fg)" }}
            onClick={() => decide("cancel")}>Cancel case</button>
        )}
        {c.status === "SUBMITTED" && !canApprove && (
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            Awaiting Director approval.</span>
        )}
      </div>

      {/* timeline */}
      {c.approvals.length > 0 && (
        <div style={{ ...card, marginTop: 12 }}>
          <h3 style={{ marginTop: 0 }}>History</h3>
          {c.approvals.map((a, i) => (
            <div key={i} style={{ fontSize: 12.5, padding: "3px 0",
              borderBottom: "1px solid var(--line)" }}>
              <b>{a.action}</b> · {a.by} ({a.role}) · {fmtDate(a.at)}
              {a.comment && <span style={{ color: "var(--muted)" }}>
                {" — "}{a.comment}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const PORTAL_OPTS = [["SUBMITTED", "Submitted"],
  ["ADDITIONAL_INFO", "Additional info requested"], ["APPROVED", "Approved"],
  ["REJECTED", "Rejected"]];

function Processing({ c, me, onReload }) {
  const canProcess = ["HO_HR", "ADMIN", "PA"].includes(me.role);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [arrived, setArrived] = useState("");
  const [bvExp, setBvExp] = useState("");
  const [portal, setPortal] = useState(c.portal_status || "SUBMITTED");
  const [medical, setMedical] = useState("PASS");
  const [amount, setAmount] = useState("");
  const [payee, setPayee] = useState("");
  const [invoice, setInvoice] = useState(null);
  const [arrEdit, setArrEdit] = useState("");

  async function run(fn) {
    setBusy(true); setError(null);
    try { await fn(); onReload(); } catch (e) { setError(e.message); }
    setBusy(false);
  }
  const advance = (body) => run(() =>
    api(`/onboarding/${c.id}/stage`, { method: "POST", body: body || {} }));
  const setData = (body) => run(() =>
    api(`/onboarding/${c.id}/stage-data`, { method: "POST", body }));
  const raiseFee = () => run(() => {
    const fd = new FormData();
    fd.append("amount", amount);
    fd.append("payee", payee);
    if (invoice) fd.append("file", invoice);
    return apiUpload(`/onboarding/${c.id}/fee`, fd);
  });

  const err = error && <p style={{ color: "var(--red-fg)" }}>{error}</p>;

  if (c.status === "APPROVED") {
    return (
      <div style={{ ...card, marginTop: 12 }}>
        <h3 style={{ marginTop: 0 }}>Processing</h3>
        <p style={{ fontSize: 13 }}>Approved — ready to start the{" "}
          {ROUTE_LABEL[c.route]} track.</p>
        {err}
        {canProcess ? (
          <Btn variant="primary" disabled={busy} onClick={() => advance()}>
            Begin processing</Btn>
        ) : <span style={{ fontSize: 13, color: "var(--muted)" }}>
          Awaiting HR to start processing.</span>}
      </div>
    );
  }

  return (
    <div style={{ ...card, marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h3 style={{ margin: 0 }}>Processing</h3>
        {c.status === "COMPLETED"
          ? <Chip tone="ok">Completed</Chip>
          : <span style={{ color: "var(--muted)", fontSize: 13 }}>
              {c.pending_label
                ? <><b>{c.pending_label}</b> pending</>
                : c.stage_label}</span>}
      </div>
      {err}
      {c.employee_no && (
        <div style={{ marginTop: 8, padding: "8px 10px", borderRadius: 8,
          background: "var(--green-bg)", color: "var(--green-fg)",
          fontSize: 12.5, fontWeight: 600 }}>
          ✓ On site payroll as {c.employee_no} · DIRECT — on the site manpower
          list from arrival
        </div>
      )}
      {/* stepper */}
      <div style={{ margin: "10px 0" }}>
        {c.stages.map((s) => (
          <div key={s.key} style={{ display: "flex", alignItems: "center",
            gap: 8, padding: "2px 0", fontSize: 12.5 }}>
            <span style={{ width: 14, textAlign: "center", color:
              s.state === "done" ? "var(--green-fg)"
              : s.state === "current" ? "var(--navy)" : "var(--line)" }}>
              {s.state === "done" ? "✓" : s.state === "current" ? "●" : "○"}</span>
            <span style={{ fontWeight: s.state === "current" ? 700 : 400,
              color: s.state === "future" ? "var(--muted)" : "var(--ink)" }}>
              {s.label}</span>
            {s.payment && (s.waived
              ? <span style={{ fontSize: 10, color: "var(--green-fg)",
                  border: "1px solid var(--green-fg)", borderRadius: 4,
                  padding: "0 4px" }}>no fee</span>
              : <span style={{ fontSize: 10, color: "var(--muted)",
                  border: "1px solid var(--line)", borderRadius: 4,
                  padding: "0 4px" }}>fee</span>)}
          </div>
        ))}
      </div>
      {/* captured data */}
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12,
        color: "var(--muted)" }}>
        {c.portal_status && <span>Portal: <b>{c.portal_status}</b></span>}
        {c.arrived_date && <span>Arrived: <b>{fmtDate(c.arrived_date)}</b></span>}
        {c.medical_due && <span>Medical by: <b>{fmtDate(c.medical_due)}</b>
          {!c.medical_result && <Countdown d={c.medical_due} warnAt={7} />}</span>}
        {c.medical_result && <span>Medical: <b>{c.medical_result}</b></span>}
        {c.bv_expiry && <span>BV expiry: <b>{fmtDate(c.bv_expiry)}</b>
          {c.status === "IN_PROGRESS" && c.stage !== "WP_ISSUED" &&
            <Countdown d={c.bv_expiry} warnAt={14} />}</span>}
      </div>

      {/* HR controls */}
      {canProcess && c.status === "IN_PROGRESS" && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column",
          gap: 8 }}>
          {c.at_application && (
            <div style={ctl}>
              <span>Portal status</span>
              <select style={{ ...inputStyle, width: 220 }} value={portal}
                      onChange={(e) => setPortal(e.target.value)}>
                {PORTAL_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <Btn variant="secondary" disabled={busy}
                   onClick={() => setData({ portal_status: portal })}>
                Update</Btn>
            </div>
          )}
          {c.at_medical && (
            <div style={ctl}>
              <span>Medical result</span>
              <select style={{ ...inputStyle, width: 120 }} value={medical}
                      onChange={(e) => setMedical(e.target.value)}>
                <option value="PASS">Pass</option>
                <option value="FAIL">Fail</option></select>
              <Btn variant="secondary" disabled={busy}
                   onClick={() => setData({ medical_result: medical })}>
                Record</Btn>
            </div>
          )}
          {c.arrived_date && (
            <div style={ctl}>
              <span>Arrival date</span>
              <input type="date" style={inputStyle}
                     value={arrEdit || c.arrived_date}
                     onChange={(e) => setArrEdit(e.target.value)} />
              <Btn variant="secondary" disabled={busy}
                   onClick={() => setData(
                     { arrived_date: arrEdit || c.arrived_date })}>
                Update</Btn>
              <span style={{ fontSize: 11, color: "var(--muted)" }}>
                salary counts from this date</span>
            </div>
          )}
          {c.at_payment && c.fee && (
            <div style={{ border: "1px solid var(--line)", borderRadius: 8,
              padding: 10, background: "var(--sky-soft)" }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
                {c.fee.label}
                {c.fee.refundable && <span style={{ fontWeight: 400,
                  color: "var(--muted)" }}> · refundable deposit</span>}</div>
              {!c.fee.raised ? (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                  alignItems: "center" }}>
                  <input style={{ ...inputStyle, width: 130 }} type="number"
                         placeholder="Amount (MVR)" value={amount}
                         onChange={(e) => setAmount(e.target.value)} />
                  <input style={{ ...inputStyle, width: 200 }} placeholder="Pay to"
                         value={payee} onChange={(e) => setPayee(e.target.value)} />
                  <label style={{ fontSize: 11, color: "var(--navy)",
                    cursor: "pointer", fontWeight: 600 }}>
                    {invoice ? `✓ ${invoice.name}`
                      : `Attach ${c.fee.invoice_label}`}
                    <input type="file" accept="image/*,application/pdf"
                           style={{ display: "none" }}
                           onChange={(e) => setInvoice(e.target.files[0])} />
                  </label>
                  <Btn variant="secondary" disabled={busy || !amount || !payee}
                       onClick={raiseFee}>Raise fee PYR</Btn>
                  <button type="button" disabled={busy}
                    onClick={() => advance({ waive_fee: true,
                      ...(c.next_needs ? { arrived_date: arrived,
                                           bv_expiry: bvExp } : {}) })}
                    title="No fee for this case (e.g. Indian nationals pay no
visa fee) — advance without a payment"
                    style={{ border: "none", background: "none", cursor: "pointer",
                      color: "var(--muted)", fontSize: 12,
                      textDecoration: "underline" }}>
                    Fee not applicable →</button>
                </div>
              ) : c.fee.paid ? (
                <div style={{ fontSize: 12.5, color: "var(--green-fg)" }}>
                  ✓ {c.fee.pyr_ref} paid — clear to advance.</div>
              ) : (
                <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
                  Awaiting payment — {c.fee.pyr_ref} ({c.fee.pyr_status}). The
                  Finance team settles the PYR before this stage can close.</div>
              )}
            </div>
          )}
          {c.next_needs && (
            <div style={ctl}>
              <span>Arrival date</span>
              <input type="date" style={inputStyle} value={arrived}
                     onChange={(e) => setArrived(e.target.value)} />
              {c.next_needs === "arrival_bv" && (<>
                <span>BV expiry</span>
                <input type="date" style={inputStyle} value={bvExp}
                       onChange={(e) => setBvExp(e.target.value)} /></>)}
            </div>
          )}
          {c.next_stage && (
            <div>
              <Btn variant="primary"
                   disabled={busy || (c.at_payment && !c.fee?.paid)}
                   onClick={() => advance(c.next_needs
                     ? { arrived_date: arrived, bv_expiry: bvExp } : {})}>
                Advance → {c.next_label}</Btn>
            </div>
          )}
          {c.at_last && !c.on_site && (
            <div><Btn variant="primary" disabled={busy}
                      onClick={() => advance()}>Complete case</Btn></div>
          )}
          {(c.can_extend || c.on_site) && <VisaActions c={c} run={run}
            busy={busy} />}
        </div>
      )}
      {c.documents?.length > 0 &&
        <StageDocs c={c} canProcess={canProcess} busy={busy} run={run} />}
      {canProcess && <Letters c={c} busy={busy} run={run} />}
    </div>
  );
}

function VisaActions({ c, run, busy }) {
  const [open, setOpen] = useState(null);     // 'extend' | 'depart' | null
  const [expiry, setExpiry] = useState("");
  const [amount, setAmount] = useState("");
  const [payee, setPayee] = useState("");
  const [invoice, setInvoice] = useState(null);
  const [departed, setDeparted] = useState("");

  const extend = () => run(async () => {
    const fd = new FormData();
    fd.append("new_expiry", expiry);
    fd.append("amount", amount);
    fd.append("payee", payee);
    if (invoice) fd.append("file", invoice);
    await apiUpload(`/onboarding/${c.id}/extend`, fd);
    setOpen(null);
  });
  const depart = () => run(async () => {
    await api(`/onboarding/${c.id}/close`,
              { method: "POST", body: { departed_date: departed } });
    setOpen(null);
  });

  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: 10,
      background: "var(--sky-soft)", display: "flex", flexDirection: "column",
      gap: 8 }}>
      <div style={{ fontSize: 12.5, fontWeight: 600 }}>
        {c.on_site ? "On site — subcontract worker" : "Business visa"}</div>
      {open !== "extend" ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {c.can_extend && <Btn variant="secondary" disabled={busy}
            onClick={() => setOpen("extend")}>Extend visa</Btn>}
          {c.on_site && <Btn variant="secondary" disabled={busy}
            onClick={() => setOpen(open === "depart" ? null : "depart")}>
            Worker departed…</Btn>}
        </div>
      ) : (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
          alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "var(--muted)" }}>New expiry</span>
          <input type="date" style={inputStyle} value={expiry}
                 onChange={(e) => setExpiry(e.target.value)} />
          <input style={{ ...inputStyle, width: 120 }} type="number"
                 placeholder="Fee (MVR)" value={amount}
                 onChange={(e) => setAmount(e.target.value)} />
          <input style={{ ...inputStyle, width: 160 }} placeholder="Pay to"
                 value={payee} onChange={(e) => setPayee(e.target.value)} />
          <label style={{ fontSize: 11, color: "var(--navy)", cursor: "pointer",
            fontWeight: 600 }}>
            {invoice ? `✓ ${invoice.name}` : "Attach invoice"}
            <input type="file" accept="image/*,application/pdf"
                   style={{ display: "none" }}
                   onChange={(e) => setInvoice(e.target.files[0])} />
          </label>
          <Btn variant="primary" disabled={busy || !expiry || !amount || !payee}
               onClick={extend}>Extend</Btn>
          <Btn variant="ghost" disabled={busy}
               onClick={() => setOpen(null)}>Cancel</Btn>
        </div>
      )}
      {open === "depart" && (
        <div style={{ display: "flex", gap: 8, alignItems: "center",
          flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, color: "var(--muted)" }}>
            Departure date</span>
          <input type="date" style={inputStyle} value={departed}
                 onChange={(e) => setDeparted(e.target.value)} />
          <Btn variant="primary" disabled={busy} onClick={depart}>
            Close case — departed</Btn>
        </div>
      )}
    </div>
  );
}

function StageDocs({ c, canProcess, busy, run }) {
  const dl = (att) => `/api/v1/onboarding/${c.id}/attachments/${att.id}`;
  const upload = (slot, file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("slot", slot);
    fd.append("file", file);
    run(() => apiUpload(`/onboarding/${c.id}/stage-doc`, fd));
  };
  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--line)",
      paddingTop: 10 }}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
        Stage documents</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {c.documents.map((d) => (
          <div key={d.slot} style={{ display: "flex", gap: 10,
            alignItems: "center", flexWrap: "wrap", fontSize: 12.5 }}>
            <span style={{ minWidth: 170, fontWeight: 600 }}>{d.label}</span>
            {d.pyr_ref && (
              <span style={{ color: d.paid ? "var(--green-fg)"
                : "var(--muted)" }}>
                {d.pyr_ref} · {d.paid ? "PAID" : d.pyr_status}</span>
            )}
            {d.slip && (
              <a href={dl(d.slip)} target="_blank" rel="noreferrer"
                 style={{ color: "var(--navy)", fontWeight: 600 }}>
                Payment slip</a>
            )}
            {d.doc
              ? <a href={dl(d.doc)} target="_blank" rel="noreferrer"
                   style={{ color: "var(--navy)", fontWeight: 600 }}>
                  {d.doc.name || "Document"}</a>
              : <span style={{ color: "var(--muted)" }}>— not uploaded</span>}
            {canProcess && (
              <label style={{ fontSize: 11, color: "var(--sky)",
                cursor: "pointer", fontWeight: 600 }}>
                {d.doc ? "Replace" : "Upload"}
                <input type="file" style={{ display: "none" }}
                       onChange={(e) => upload(d.slot, e.target.files[0])} />
              </label>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const humanize = (k) => k.replace(/_/g, " ")
  .replace(/\b\w/g, (ch) => ch.toUpperCase());

function Countdown({ d, warnAt }) {
  const n = Math.round((new Date(d + "T00:00:00")
    - new Date(new Date().toDateString())) / 86400000);
  const tone = n < 0 ? "var(--red-fg)"
    : n <= warnAt ? "var(--amber-fg)" : "var(--muted)";
  return <span style={{ color: tone, fontWeight: 600 }}>
    {" · "}{n < 0 ? `overdue ${Math.abs(n)}d` : `in ${n}d`}</span>;
}

// Preset picks for the letter fields that are usually the same company values
// (HR can still type a different one via "Other…").
const LETTER_FIELD_OPTIONS = {
  accommodation: ["2nd Floor, Ma. Jamburoaluge, Bodufulhah Goalhi"],
  local_contact: ["Ahmed Shahiq, Mobile: +9607992611",
                  "Ibrahim Fikury Hussain, Mobile +9607782174"],
};

function Letters({ c, busy, run }) {
  const [openKind, setOpenKind] = useState(null);
  const [fields, setFields] = useState({});
  const opts = (c.letter_options || []).filter((o) => o.available);
  const done = c.letters || [];
  const gen = (kind) => run(async () => {
    await api(`/onboarding/${c.id}/letter`,
              { method: "POST", body: { kind, fields } });
    setOpenKind(null);
  });
  function begin(o) { setOpenKind(o.kind); setFields({ ...(o.fields || {}) }); }

  // Nothing is generated before the signatory signs the case off (owner
  // 2026-08-11) — say so plainly instead of showing an empty panel.
  const locked = !c.signatory_signed_at;
  if (!opts.length && !done.length && !locked) return null;
  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--line)",
      paddingTop: 10 }}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6,
        display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        Official letters
        {c.signatory_signed_at
          ? <Chip tone="ok">Signed off{c.signatory_signed_by
              ? ` · ${c.signatory_signed_by}` : ""}</Chip>
          : <Chip tone="warn">Awaiting signatory sign-off</Chip>}</div>
      {locked && (
        <div style={{ fontSize: 12, color: "#8a6d00", marginBottom: 8 }}>
          A signatory must sign this case off before any letter is generated
          or the case advances a stage. Every document then carries their
          signature and the company seal.</div>)}
      {done.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3,
          marginBottom: 8 }}>
          {done.map((l) => (
            <div key={l.id} style={{ display: "flex", gap: 8,
              alignItems: "baseline", fontSize: 12.5, flexWrap: "wrap" }}>
              <a href={`/api/v1${l.download}`} target="_blank" rel="noreferrer"
                 style={{ color: "var(--navy)", fontWeight: 600 }}>{l.ref}</a>
              {l.status === "PENDING" && <Chip tone="warn">Pending signatory</Chip>}
              {l.status === "SIGNED" && <Chip tone="ok">Signed</Chip>}
              <span style={{ color: "var(--muted)" }}>
                {l.title} · v{l.version} · {fmtDate(l.created_at)}
                {l.status === "PENDING" ? " · draft (awaiting stamp)" : ""}
                {l.status === "SIGNED" && l.approved_by
                  ? ` · signed by ${l.approved_by}` : ""}
                {l.status !== "SIGNED" && l.created_by
                  ? ` · ${l.created_by}` : ""}</span>
            </div>
          ))}
        </div>
      )}
      {opts.map((o) => (
        <div key={o.kind} style={{ marginBottom: 6 }}>
          {openKind === o.kind ? (
            <div style={{ border: "1px solid var(--line)", borderRadius: 8,
              padding: 10 }}>
              <div style={{ fontWeight: 600, fontSize: 12.5, marginBottom: 8 }}>
                {o.title}</div>
              <div style={{ display: "grid",
                gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {Object.keys(o.fields || {}).filter((k) => k !== "allowances")
                  .map((k) => (
                  <label key={k} style={{ fontSize: 11, color: "var(--muted)",
                    display: "flex", flexDirection: "column", gap: 2 }}>
                    {humanize(k)}
                    {LETTER_FIELD_OPTIONS[k] ? (
                      <SelectOrOther value={fields[k] ?? ""}
                        options={LETTER_FIELD_OPTIONS[k]} placeholder="Select…"
                        onChange={(v) => setFields((f) => ({ ...f, [k]: v }))} />
                    ) : (
                      <input style={{ ...inputStyle, width: "100%" }}
                             value={fields[k] ?? ""}
                             onChange={(e) => setFields((f) =>
                               ({ ...f, [k]: e.target.value }))} />
                    )}
                  </label>
                ))}
              </div>
              {o.needs_sign && (
                <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 8 }}>
                  This case is signed off — the letter is stamped with the
                  signatory's signature and the company seal, ready to
                  print.</div>)}
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <Btn variant="primary" disabled={busy}
                     onClick={() => gen(o.kind)}>
                  Generate
                </Btn>
                <Btn variant="ghost" disabled={busy}
                     onClick={() => setOpenKind(null)}>Cancel</Btn>
              </div>
            </div>
          ) : (
            <Btn variant="secondary" disabled={busy} onClick={() => begin(o)}>
              {done.some((l) => l.kind === o.kind)
                ? `Regenerate ${o.title}` : `Generate ${o.title}`}</Btn>
          )}
        </div>
      ))}
    </div>
  );
}

function ChecklistRow({ caseId, item, editable, onChange }) {
  const ref = useRef(null);
  const [busy, setBusy] = useState(false);
  async function upload(file) {
    if (!file) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("kind", item.kind);
    fd.append("file", file);
    try { await apiUpload(`/onboarding/${caseId}/documents`, fd); onChange(); }
    catch { /* surfaced on reload */ }
    setBusy(false);
  }
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10,
                  padding: "5px 0", fontSize: 13 }}>
      <span style={{ color: item.present ? "var(--green-fg)" : "var(--muted)",
                     width: 16 }}>{item.present ? "✓" : "○"}</span>
      <span style={{ flex: 1 }}>
        {item.present && item.att_id
          ? <a href={`/api/v1/onboarding/${caseId}/attachments/${item.att_id}`}
               target="_blank" rel="noreferrer"
               style={{ color: "var(--navy)" }}>{item.label}</a>
          : item.label}
        {item.required === false && (
          <span style={{ color: "var(--muted)", fontSize: 11 }}> · optional</span>
        )}</span>
      {editable && (
        <>
          <button style={linkBtn} disabled={busy}
                  onClick={() => ref.current?.click()}>
            {busy ? "…" : item.present ? "Replace" : "Upload"}</button>
          <input ref={ref} type="file" style={{ display: "none" }}
                 accept="image/*,application/pdf"
                 onChange={(e) => upload(e.target.files[0])} />
        </>
      )}
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div style={{ display: "flex", gap: 8, padding: "2px 0" }}>
      <span style={{ color: "var(--muted)", minWidth: 120 }}>{k}</span>
      <span>{v}</span>
    </div>
  );
}

const fld = { display: "flex", flexDirection: "column", gap: 3, fontSize: 12,
  color: "var(--muted)" };
const grid = { display: "grid", gap: 8,
  gridTemplateColumns: "repeat(3, 1fr)" };
const linkBtn = { border: "none", background: "none", cursor: "pointer",
  color: "var(--navy)", fontSize: 13, padding: 0 };
const ctl = { display: "flex", alignItems: "center", gap: 8, fontSize: 12.5,
  color: "var(--muted)" };
