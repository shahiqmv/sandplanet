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
  const canProcess = ["HO_HR", "ADMIN"].includes(me.role);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [arrived, setArrived] = useState("");
  const [bvExp, setBvExp] = useState("");
  const [portal, setPortal] = useState(c.portal_status || "SUBMITTED");
  const [medical, setMedical] = useState("PASS");
  const [amount, setAmount] = useState("");
  const [payee, setPayee] = useState("");

  async function run(fn) {
    setBusy(true); setError(null);
    try { await fn(); onReload(); } catch (e) { setError(e.message); }
    setBusy(false);
  }
  const advance = (body) => run(() =>
    api(`/onboarding/${c.id}/stage`, { method: "POST", body: body || {} }));
  const setData = (body) => run(() =>
    api(`/onboarding/${c.id}/stage-data`, { method: "POST", body }));
  const raiseFee = () => run(() =>
    api(`/onboarding/${c.id}/fee`, { method: "POST", body: { amount, payee } }));

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
              {c.stage_label}</span>}
      </div>
      {err}
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
            {s.payment && <span style={{ fontSize: 10, color: "var(--muted)",
              border: "1px solid var(--line)", borderRadius: 4,
              padding: "0 4px" }}>fee</span>}
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
                  <Btn variant="secondary" disabled={busy || !amount || !payee}
                       onClick={raiseFee}>Raise fee PYR</Btn>
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
          {c.at_last && (
            <div><Btn variant="primary" disabled={busy}
                      onClick={() => advance()}>Complete case</Btn></div>
          )}
        </div>
      )}
      {canProcess && <Letters c={c} busy={busy} run={run} />}
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

  if (!opts.length && !done.length) return null;
  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--line)",
      paddingTop: 10 }}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
        Official letters</div>
      {done.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3,
          marginBottom: 8 }}>
          {done.map((l) => (
            <div key={l.id} style={{ display: "flex", gap: 8,
              alignItems: "baseline", fontSize: 12.5 }}>
              <a href={`/api/v1${l.download}`} target="_blank" rel="noreferrer"
                 style={{ color: "var(--navy)", fontWeight: 600 }}>{l.ref}</a>
              <span style={{ color: "var(--muted)" }}>
                {l.title} · v{l.version} · {fmtDate(l.created_at)}
                {l.created_by ? ` · ${l.created_by}` : ""}</span>
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
                {Object.keys(o.fields || {}).map((k) => (
                  <label key={k} style={{ fontSize: 11, color: "var(--muted)",
                    display: "flex", flexDirection: "column", gap: 2 }}>
                    {humanize(k)}
                    <input style={{ ...inputStyle, width: "100%" }}
                           value={fields[k] ?? ""}
                           onChange={(e) => setFields((f) =>
                             ({ ...f, [k]: e.target.value }))} />
                  </label>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <Btn variant="primary" disabled={busy}
                     onClick={() => gen(o.kind)}>Generate {o.kind}</Btn>
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
const ctl = { display: "flex", alignItems: "center", gap: 8, fontSize: 12.5,
  color: "var(--muted)" };
