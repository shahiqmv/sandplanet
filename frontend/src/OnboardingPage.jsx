import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const RAISE = ["PM", "HO_HR", "ADMIN"];
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
export default function OnboardingPage({ me, sites }) {
  const [cases, setCases] = useState(null);
  const [view, setView] = useState("list");     // 'list' | 'new'
  const [openId, setOpenId] = useState(null);    // case detail id
  const [filter, setFilter] = useState("open");  // open | mine | all
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

  return (
    <div style={{ maxWidth: 1000 }}>
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
        {[["open", "Open"], ["mine", "Raised by me"], ["all", "All"]]
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
              <th style={{ ...th, textAlign: "left" }}>Ref</th>
              <th style={{ ...th, textAlign: "left" }}>Candidate</th>
              <th style={{ ...th, textAlign: "left" }}>Route</th>
              <th style={{ ...th, textAlign: "left" }}>Trade</th>
              <th style={{ ...th, textAlign: "left" }}>Site</th>
              <th style={{ ...th, textAlign: "left" }}>Status</th>
            </tr></thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id} style={{ cursor: "pointer" }}
                    onClick={() => setOpenId(c.id)}>
                  <td style={{ ...td, fontFamily: "var(--font-mono)" }}>{c.ref}</td>
                  <td style={td}>{c.full_name}
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>
                      {c.nationality}</div></td>
                  <td style={td}>{ROUTE_LABEL[c.route] || c.route}</td>
                  <td style={td}>{c.trade_designation || "—"}</td>
                  <td style={td}>{c.site_code}</td>
                  <td style={td}><Chip tone={STATUS_TONE[c.status]}>
                    {c.status.replace(/_/g, " ")}</Chip></td>
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
  passport_no: "", passport_expiry: "", category: "", trade_designation: "",
  proposed_salary: "", currency: "MVR", route: "WP", bv_justification: "",
  permanent_address: "", mobile: "", emergency_contact: "",
  mobilisation_date: "",
};

function CaseForm({ value, onChange }) {
  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value });
  const F = ({ label, k, type = "text", req }) => (
    <label style={fld}>{label}{req && <span style={{ color: "var(--red-fg)" }}> *</span>}
      <input style={inputStyle} type={type} value={value[k]}
             onChange={set(k)} /></label>
  );
  return (
    <>
      <div style={grid}>
        <F label="Full name" k="full_name" req />
        <F label="Nationality" k="nationality" req />
        <F label="Passport no." k="passport_no" req />
        <F label="Date of birth" k="date_of_birth" type="date" />
        <label style={fld}>Gender
          <select style={inputStyle} value={value.gender} onChange={set("gender")}>
            <option value="">—</option><option>Male</option><option>Female</option>
          </select></label>
        <F label="Passport expiry" k="passport_expiry" type="date" />
        <label style={fld}>Category <span style={{ color: "var(--red-fg)" }}>*</span>
          <select style={inputStyle} value={value.category}
                  onChange={set("category")}>
            <option value="">—</option>
            {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></label>
        <F label="Trade / designation" k="trade_designation" req />
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
        <label style={fld}>Route <span style={{ color: "var(--red-fg)" }}>*</span>
          <select style={inputStyle} value={value.route} onChange={set("route")}>
            <option value="WP">Work permit (standard)</option>
            <option value="BV">Business visa (urgent)</option></select></label>
        <F label="Mobile / contact" k="mobile" />
        <F label="Expected mobilisation" k="mobilisation_date" type="date" />
      </div>
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

  async function submit(e) {
    e.preventDefault();
    if (!siteId) { setError("Choose the destination site."); return; }
    setBusy(true); setError(null);
    try {
      const c = await api(`/sites/${siteId}/onboarding`,
        { method: "POST", body: form });
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
      <CaseForm value={form} onChange={setForm} />
      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        <Btn variant="primary" disabled={busy}>Create case</Btn>
        <span style={{ fontSize: 12, color: "var(--muted)",
                       alignSelf: "center" }}>
          You'll attach the required documents next, then submit for approval.</span>
      </div>
    </form>
  );
}

function CaseDetail({ id, me, onBack }) {
  const [c, setC] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);

  const load = () => api(`/onboarding/${id}`).then((d) => { setC(d); setForm(d); })
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps

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
      <div style={{ ...card, marginTop: 8 }}>
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
            <CaseForm value={form} onChange={setForm} />
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
            <Row k="Proposed salary" v={`${c.currency} ${money(c.proposed_salary)}`} />
            <Row k="DOB / gender" v={`${fmtDate(c.date_of_birth)} · ${c.gender || "—"}`} />
            <Row k="Mobilisation" v={fmtDate(c.mobilisation_date)} />
            <Row k="Mobile" v={c.mobile || "—"} />
            <Row k="Emergency" v={c.emergency_contact || "—"} />
            {c.bv_justification && <Row k="BV reason" v={c.bv_justification} />}
            <Row k="Raised by" v={c.created_by} />
          </div>
        )}
      </div>

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
      <span style={{ flex: 1 }}>{item.label}</span>
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
