import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { NATIONALITIES } from "./constants.js";
import { SelectOrOther, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const EMPTY = { full_name: "", nationality: "", job_category: "",
                basic_pay: "", currency: "MVR", passport_no: "",
                employment_type: "PERMANENT", join_date: "" };

const EMPLOYMENT = [["PERMANENT", "Permanent"], ["CONTRACT", "Contract"]];

// Work-permit status → badge colour + label. NA = not tracked (contract or
// no expiry set); OK hidden to keep the table calm.
const PERMIT_TONE = { EXPIRED: "#c0392b", EXPIRING: "#b35900",
                      OK: "#1a7f37" };
function PermitBadge({ emp }) {
  const pending = emp.permit_pending
    ? <span style={{ color: "#b35900", fontSize: 11 }}> · renewal pending</span>
    : null;
  if (!emp.permit_state || emp.permit_state === "NA") {
    return pending ? <span>—{pending}</span> : "—";
  }
  if (emp.permit_state === "OK") {
    return <span style={{ color: "#5a6b78", fontSize: 12 }}>
      {emp.work_permit_expiry}{pending}</span>;
  }
  const label = emp.permit_state === "EXPIRED"
    ? `Expired ${Math.abs(emp.permit_days)}d ago`
    : `${emp.permit_days}d left`;
  return (
    <span style={{ fontSize: 12 }}
          title={`Permit ${emp.work_permit_no || ""} · ${emp.work_permit_expiry}`}>
      <span style={{ color: PERMIT_TONE[emp.permit_state], fontWeight: 600 }}>
        ⚠ {label}</span>{pending}</span>
  );
}

export default function EmployeesPage({ me, sites }) {
  const [employees, setEmployees] = useState([]);
  const [categories, setCategories] = useState([]);
  const [alerts, setAlerts] = useState(null);
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);   // employee being edited
  const [batch, setBatch] = useState(false);       // batch-renew modal

  const isHr = ["HO_HR", "ADMIN"].includes(me.role);
  const seesPay = ["HO_HR", "FINANCE", "ADMIN"].includes(me.role);

  function load() {
    api("/employees").then(setEmployees);
    api("/permits/alerts").then(setAlerts).catch(() => setAlerts(null));
  }
  useEffect(() => {
    load();
    api("/manpower-categories").then((all) =>
      setCategories(all.filter((c) => c.list_type === "DPR" && c.is_active)));
  }, []);

  async function add() {
    setError(null);
    try {
      const body = { ...draft };
      if (!body.basic_pay) delete body.basic_pay;
      if (!body.join_date) delete body.join_date;
      if (!body.job_category) delete body.job_category;
      await api("/employees", { method: "POST", body });
      setDraft(EMPTY);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function allocate(employee, siteId) {
    if (!siteId) return;
    await api(`/employees/${employee.id}/allocate`,
              { method: "POST", body: { site_id: +siteId } });
    load();
  }

  return (
    <>
      <section style={card}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "baseline", flexWrap: "wrap", gap: 10 }}>
          <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
            Employees
          </h2>
          {isHr && (
            <button onClick={() => setBatch(true)} style={ghostButton}>
              🪪 Renew work permits</button>
          )}
        </div>

        {alerts && (alerts.expired.length > 0 || alerts.expiring.length > 0) && (
          <div style={{ border: "1px solid #f0c9a8", background: "#fdf6ef",
                        borderRadius: 8, padding: "10px 12px", margin: "6px 0",
                        fontSize: 13 }}>
            <strong style={{ color: "#b35900" }}>
              Work permits needing attention
            </strong>
            <span style={{ color: "#5a6b78" }}>
              {" "}— permanent workers expiring within {alerts.within_days} days
            </span>
            {isHr && (
              <button onClick={() => setBatch(true)}
                      style={{ ...buttonStyle, padding: "3px 12px",
                               fontSize: 12, marginLeft: 10 }}>
                Renew as batch →</button>
            )}
            <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap",
                          gap: 6 }}>
              {[...alerts.expired, ...alerts.expiring].map((r) => (
                <button key={r.id}
                        onClick={() => isHr && setEditing(
                          employees.find((e) => e.id === r.id) || null)}
                        title={`${r.work_permit_no || "no permit no"} · `
                               + `${r.work_permit_expiry}`}
                        style={{ border: "none", borderRadius: 6, cursor:
                          isHr ? "pointer" : "default", padding: "3px 8px",
                          fontSize: 12, color: "#fff",
                          background: r.state === "EXPIRED"
                            ? "#c0392b" : "#b35900" }}>
                  {r.emp_no} {r.full_name}
                  {r.site_code ? ` · ${r.site_code}` : ""}
                  {" · "}
                  {r.state === "EXPIRED"
                    ? `expired ${Math.abs(r.days)}d`
                    : `${r.days}d left`}
                </button>
              ))}
            </div>
          </div>
        )}

        {isHr && (
          <div style={{ display: "flex", gap: 8, margin: "12px 0",
                        flexWrap: "wrap" }}>
            <input placeholder="Full name" value={draft.full_name}
                   onChange={(e) => setDraft({ ...draft,
                                               full_name: e.target.value })}
                   style={{ ...inputStyle, flex: 1.5, minWidth: 160 }} />
            <SelectOrOther value={draft.nationality} options={NATIONALITIES}
                           placeholder="Nationality…" width={140}
                           onChange={(v) => setDraft({ ...draft,
                                                       nationality: v })} />
            <select value={draft.job_category}
                    onChange={(e) => setDraft({ ...draft,
                                                job_category: e.target.value })}
                    style={{ ...inputStyle, width: 160 }}>
              <option value="">Job category…</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <input placeholder="Basic pay" type="number"
                   value={draft.basic_pay}
                   onChange={(e) => setDraft({ ...draft,
                                               basic_pay: e.target.value })}
                   style={{ ...inputStyle, width: 110 }} />
            <select value={draft.currency}
                    onChange={(e) => setDraft({ ...draft,
                                                currency: e.target.value })}
                    style={{ ...inputStyle, width: 80 }}>
              <option value="MVR">MVR</option>
              <option value="USD">USD</option>
            </select>
            <select value={draft.employment_type}
                    onChange={(e) => setDraft({ ...draft,
                                                employment_type: e.target.value })}
                    style={{ ...inputStyle, width: 120 }}
                    title={"Permanent workers are on the company work permit; "
                           + "contract workers are temporary"}>
              {EMPLOYMENT.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
            <button onClick={add} disabled={!draft.full_name}
                    style={buttonStyle}>Add employee</button>
          </div>
        )}
        <p style={{ color: "#5a6b78", fontSize: 12, margin: "0 0 8px" }}>
          {isHr ? "Click a row to open the full profile (photo, DOB, permit, "
                + "currency, overtime, pay)." : ""}
        </p>
        {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th} />
            <th style={th}>Emp No</th><th style={th}>Name</th>
            <th style={th}>Category</th><th style={th}>Site</th>
            <th style={th}>Permit</th>
            {seesPay && <th style={th}>Basic Pay</th>}
            {seesPay && <th style={th}>Cur.</th>}
            {seesPay && <th style={th}>OT</th>}
            <th style={th}>Allocate</th>
          </tr></thead>
          <tbody>
            {employees.map((emp) => (
              <tr key={emp.id} style={{ cursor: isHr ? "pointer" : "default" }}>
                <td style={td} onClick={() => isHr && setEditing(emp)}>
                  {emp.photo_url ? (
                    <img src={emp.photo_url} alt=""
                         style={{ width: 30, height: 30, borderRadius: "50%",
                                  objectFit: "cover",
                                  border: "1px solid var(--sp-border)" }} />
                  ) : (
                    <span style={{ display: "inline-flex", width: 30,
                                   height: 30, borderRadius: "50%",
                                   background: "#eef2f5", color: "#9fb0bc",
                                   alignItems: "center",
                                   justifyContent: "center", fontSize: 12 }}>
                      {emp.full_name?.[0] || "?"}</span>
                  )}
                </td>
                <td style={{ ...td, fontWeight: 600, color: "var(--sp-navy)" }}
                    onClick={() => isHr && setEditing(emp)}>{emp.emp_no}</td>
                <td style={td} onClick={() => isHr && setEditing(emp)}>
                  {emp.full_name}</td>
                <td style={td}>{emp.job_category_name}</td>
                <td style={td}>{emp.site_code || "—"}</td>
                <td style={td} onClick={() => isHr && setEditing(emp)}>
                  <PermitBadge emp={emp} /></td>
                {seesPay && <td style={td}>{emp.basic_pay}</td>}
                {seesPay && <td style={td}>{emp.currency}</td>}
                {seesPay && (
                  <td style={td}>
                    {emp.ot_effective
                      ? <span title="Overtime applies"
                              style={{ color: "#1a7f37" }}>
                          ✓ {emp.ot_rate}/hr</span>
                      : <span style={{ color: "#9fb0bc" }}>—</span>}
                  </td>
                )}
                <td style={td}>
                  {isHr ? (
                    <select value="" style={{ ...inputStyle, width: 120,
                                              padding: "3px 6px" }}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => allocate(emp, e.target.value)}>
                      <option value="">Transfer to…</option>
                      {sites.filter((s) => !s.is_head_office &&
                                           s.code !== emp.site_code)
                        .map((s) => (
                          <option key={s.id} value={s.id}>{s.code}</option>
                        ))}
                    </select>
                  ) : "—"}
                </td>
              </tr>
            ))}
            {employees.length === 0 && (
              <tr><td style={td} colSpan={10}>No employees yet.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      {editing && (
        <EmployeeProfile employee={editing} categories={categories}
          seesPay={seesPay} isHr={isHr}
          onClose={() => setEditing(null)}
          onChanged={load}
          onSaved={() => { setEditing(null); load(); }} />
      )}

      {batch && (
        <BatchRenewModal
          candidates={employees
            .filter((e) => e.employment_type === "PERMANENT" && e.is_active)
            .sort((a, b) => (a.work_permit_expiry || "9999")
              .localeCompare(b.work_permit_expiry || "9999"))}
          onClose={() => setBatch(false)}
          onDone={() => { setBatch(false); load(); }} />
      )}
    </>
  );
}

// Batch permit renewal: pick permanent workers, set months + fee each, and
// raise ONE PYR (Permits & Fees, Head Office) for the total. Each expiry
// extends only once Finance pays that PYR. Workers expiring soon / expired
// are pre-ticked; those with a renewal already pending payment are shown.
function BatchRenewModal({ candidates, onClose, onDone }) {
  const [rows, setRows] = useState(candidates.map((c) => ({
    id: c.id, emp_no: c.emp_no, full_name: c.full_name,
    expiry: c.work_permit_expiry, state: c.permit_state,
    pending: c.permit_pending,
    sel: ["EXPIRING", "EXPIRED"].includes(c.permit_state) && !c.permit_pending,
    months: "12", fee: "" })));
  const [payee, setPayee] = useState("Immigration Maldives");
  const [currency, setCurrency] = useState("MVR");
  const [filter, setFilter] = useState("");
  const [bulk, setBulk] = useState({ months: "12", fee: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  const setRow = (id, patch) => setRows((rs) =>
    rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const chosen = rows.filter((r) => r.sel);
  const total = chosen.reduce((a, r) => a + (parseFloat(r.fee) || 0), 0);

  const q = filter.trim().toLowerCase();
  const visible = q
    ? rows.filter((r) => `${r.emp_no} ${r.full_name}`.toLowerCase().includes(q))
    : rows;
  const visIds = new Set(visible.map((r) => r.id));
  const allVisSel = visible.length > 0 && visible.every((r) => r.sel);

  const setAll = (sel) => setRows((rs) =>
    rs.map((r) => (visIds.has(r.id) ? { ...r, sel } : r)));
  const applyBulk = () => setRows((rs) => rs.map((r) =>
    (r.sel ? { ...r, months: bulk.months,
               fee: bulk.fee === "" ? r.fee : bulk.fee } : r)));

  async function submit() {
    setError(null);
    if (!chosen.length) { setError("Select at least one worker."); return; }
    if (chosen.some((r) => !(parseInt(r.months, 10) > 0))) {
      setError("Every selected worker needs a renewal length."); return;
    }
    setBusy(true);
    try {
      const res = await api("/permits/batch-renew", { method: "POST", body: {
        payee, currency,
        lines: chosen.map((r) => ({ employee_id: r.id,
          months: parseInt(r.months, 10), fee: parseFloat(r.fee) || 0 })),
      } });
      setDone(res);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const stickyTh = { ...th, position: "sticky", top: 0, background: "#fff",
                     zIndex: 1 };

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)",
                  display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 60, padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 980, width: "96vw", maxHeight: "92vh",
                    display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 16 }}>
            Batch work-permit renewal</h2>
          <button onClick={onClose}
                  style={{ ...ghostButton, marginLeft: "auto" }}>Close</button>
        </div>

        {done ? (
          <div style={{ marginTop: 16 }}>
            <p style={{ color: "#1a7f37", fontSize: 14 }}>
              Raised <strong>{done.ref}</strong> for {done.count} permit(s),
              {" "}{done.currency} {Number(done.amount).toLocaleString()}. The
              expiries extend automatically once Finance pays this PYR; it now
              runs the normal payment approval workflow.
            </p>
            <button onClick={onDone} style={buttonStyle}>Done</button>
          </div>
        ) : (
          <>
            <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "6px 0 8px" }}>
              One PYR is raised for the total fee (Permits &amp; Fees, Head
              Office). Each expiry moves forward only when Finance pays it.
            </p>

            {/* toolbar: filter + select-all + bulk apply */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                          alignItems: "center", marginBottom: 8 }}>
              <input placeholder="Filter by name / emp no." value={filter}
                     onChange={(e) => setFilter(e.target.value)}
                     style={{ ...inputStyle, width: 200 }} />
              <button onClick={() => setAll(!allVisSel)} style={ghostButton}>
                {allVisSel ? "Clear shown" : "Select shown"}</button>
              <span style={{ width: 1, height: 20, background: "var(--sp-border)",
                             margin: "0 2px" }} />
              <span style={{ fontSize: 12.5, color: "#5a6b78" }}>
                Set selected to</span>
              <select value={bulk.months}
                      onChange={(e) => setBulk({ ...bulk,
                                                 months: e.target.value })}
                      style={{ ...inputStyle, width: 80 }}>
                {[3, 6, 12, 24].map((m) => (
                  <option key={m} value={m}>{m}m</option>
                ))}
              </select>
              <input type="number" min="0" placeholder="fee each"
                     value={bulk.fee}
                     onChange={(e) => setBulk({ ...bulk, fee: e.target.value })}
                     style={{ ...inputStyle, width: 90 }} />
              <button onClick={applyBulk} style={ghostButton}
                      disabled={!chosen.length}>Apply to selected</button>
            </div>

            {/* scrollable worker list with a sticky header */}
            <div style={{ flex: 1, overflow: "auto", border:
                          "1px solid var(--sp-border)", borderRadius: 8 }}>
              <table style={{ width: "100%", borderCollapse: "collapse",
                              fontSize: 13 }}>
                <thead><tr>
                  <th style={{ ...stickyTh, width: 32 }}>
                    <input type="checkbox" checked={allVisSel}
                           onChange={() => setAll(!allVisSel)} /></th>
                  <th style={stickyTh}>Worker</th>
                  <th style={stickyTh}>Current expiry</th>
                  <th style={stickyTh}>Months</th><th style={stickyTh}>Fee</th>
                </tr></thead>
                <tbody>
                  {visible.map((r) => (
                    <tr key={r.id} style={{ opacity: r.sel ? 1 : 0.55 }}>
                      <td style={td}>
                        <input type="checkbox" checked={r.sel}
                               onChange={(e) => setRow(r.id,
                                 { sel: e.target.checked })} /></td>
                      <td style={td}>{r.emp_no} {r.full_name}
                        {r.pending && (
                          <span style={{ fontSize: 11, color: "#b35900",
                                     marginLeft: 6 }}>· renewal pending</span>
                        )}</td>
                      <td style={{ ...td, whiteSpace: "nowrap",
                                   color: ["EXPIRED", "EXPIRING"].includes(r.state)
                                     ? "#c0392b" : "inherit" }}>
                        {r.expiry || "—"}</td>
                      <td style={td}>
                        <select value={r.months}
                                onChange={(e) => setRow(r.id,
                                  { months: e.target.value })}
                                style={{ ...inputStyle, width: 80 }}>
                          {[3, 6, 12, 24].map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select></td>
                      <td style={td}>
                        <input type="number" min="0" value={r.fee}
                               placeholder="0"
                               onChange={(e) => setRow(r.id,
                                 { fee: e.target.value })}
                               style={{ ...inputStyle, width: 90 }} /></td>
                    </tr>
                  ))}
                  {visible.length === 0 && (
                    <tr><td style={{ ...td, textAlign: "center",
                                     color: "#5a6b78" }} colSpan={5}>
                      No workers match "{filter}".</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* fixed action bar */}
            <div style={{ borderTop: "1px solid var(--sp-border)",
                          paddingTop: 12, marginTop: 12 }}>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                            alignItems: "center" }}>
                <label style={{ fontSize: 12.5 }}>Pay to{" "}
                  <input value={payee}
                         onChange={(e) => setPayee(e.target.value)}
                         style={{ ...inputStyle, width: 200 }} /></label>
                <label style={{ fontSize: 12.5 }}>Currency{" "}
                  <select value={currency}
                          onChange={(e) => setCurrency(e.target.value)}
                          style={{ ...inputStyle, width: 80 }}>
                    <option value="MVR">MVR</option>
                    <option value="USD">USD</option>
                  </select></label>
                <span style={{ marginLeft: "auto", fontWeight: 600,
                               color: "var(--sp-navy)" }}>
                  {chosen.length} selected · total {currency}{" "}
                  {total.toLocaleString()}</span>
              </div>
              {error && <p style={{ color: "#c0392b", fontSize: 13,
                                    margin: "8px 0 0" }}>{error}</p>}
              <div style={{ marginTop: 12 }}>
                <button onClick={submit} disabled={busy || !chosen.length}
                        style={buttonStyle}>
                  {busy ? "Raising PYR…" : "Renew + raise PYR"}</button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function EmployeeProfile({ employee, categories, seesPay, isHr, onClose,
                          onSaved, onChanged }) {
  const [f, setF] = useState({
    full_name: employee.full_name || "",
    date_of_birth: employee.date_of_birth || "",
    nationality: employee.nationality || "",
    job_category: employee.job_category || "",
    basic_pay: employee.basic_pay ?? "",
    currency: employee.currency || "MVR",
    ot_applies: employee.ot_applies,   // true | false | null
    passport_no: employee.passport_no || "",
    employment_type: employee.employment_type || "PERMANENT",
    work_permit_no: employee.work_permit_no || "",
    work_permit_expiry: employee.work_permit_expiry || "",
    emergency_contact: employee.emergency_contact || "",
    join_date: employee.join_date || "",
    is_active: employee.is_active,
  });
  const [photo, setPhoto] = useState(null);
  const [photoUrl, setPhotoUrl] = useState(employee.photo_url);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState(null);

  const set = (patch) => setF((s) => ({ ...s, ...patch }));
  const otChoice = f.ot_applies === true ? "on"
                 : f.ot_applies === false ? "off" : "inherit";

  useEffect(() => {
    if (isHr) {
      api(`/employees/${employee.id}/permit-renewals`)
        .then(setHistory).catch(() => setHistory([]));
    }
  }, [employee.id, isHr]);

  async function save() {
    setBusy(true); setError(null);
    try {
      const body = { ...f };
      if (body.basic_pay === "") body.basic_pay = null;
      if (!body.job_category) body.job_category = null;
      ["date_of_birth", "work_permit_expiry", "join_date"].forEach((k) => {
        if (!body[k]) body[k] = null;
      });
      await api(`/employees/${employee.id}`, { method: "PATCH", body });
      if (photo) {
        const fd = new FormData();
        fd.append("photo", photo);
        await apiUpload(`/employees/${employee.id}`, fd, "PATCH");
      }
      onSaved();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const L = ({ label, children }) => (
    <label style={{ fontSize: 12.5, display: "block" }}>
      <span style={{ color: "#5a6b78" }}>{label}</span>
      {children}
    </label>
  );

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)",
                  display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 60, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 640, width: "100%", maxHeight: "88vh",
                    overflow: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {photoUrl ? (
            <img src={photoUrl} alt="" style={{ width: 56, height: 56,
                 borderRadius: "50%", objectFit: "cover",
                 border: "1px solid var(--sp-border)" }} />
          ) : (
            <span style={{ display: "inline-flex", width: 56, height: 56,
                 borderRadius: "50%", background: "#eef2f5", color: "#9fb0bc",
                 alignItems: "center", justifyContent: "center",
                 fontSize: 22 }}>{f.full_name?.[0] || "?"}</span>
          )}
          <div style={{ flex: 1 }}>
            <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 16 }}>
              {employee.emp_no}</h2>
            <label style={{ fontSize: 12, color: "#3f6f9f", cursor: "pointer" }}>
              {photoUrl ? "Change photo" : "Add photo"}
              <input type="file" accept="image/*" style={{ display: "none" }}
                     onChange={(e) => {
                       const file = e.target.files[0];
                       setPhoto(file);
                       if (file) setPhotoUrl(URL.createObjectURL(file));
                     }} />
            </label>
          </div>
          <button onClick={onClose} style={ghostButton}>Close</button>
        </div>

        {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                      gap: 10, marginTop: 14 }}>
          <L label="Full name">
            <input value={f.full_name}
                   onChange={(e) => set({ full_name: e.target.value })}
                   style={inputStyle} /></L>
          <L label="Date of birth">
            <input type="date" value={f.date_of_birth || ""}
                   onChange={(e) => set({ date_of_birth: e.target.value })}
                   style={inputStyle} /></L>
          <L label="Nationality">
            <SelectOrOther value={f.nationality} options={NATIONALITIES}
                           placeholder="Nationality…"
                           onChange={(v) => set({ nationality: v })} /></L>
          <L label="Job category">
            <select value={f.job_category || ""}
                    onChange={(e) => set({ job_category: e.target.value })}
                    style={inputStyle}>
              <option value="">—</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select></L>
          {seesPay && (
            <L label="Basic salary (monthly)">
              <input type="number" value={f.basic_pay}
                     onChange={(e) => set({ basic_pay: e.target.value })}
                     style={inputStyle} /></L>
          )}
          {seesPay && (
            <L label="Salary currency">
              <select value={f.currency}
                      onChange={(e) => set({ currency: e.target.value })}
                      style={inputStyle}>
                <option value="MVR">MVR</option>
                <option value="USD">USD (middle management +)</option>
              </select></L>
          )}
          {seesPay && (
            <L label="Overtime">
              <select value={otChoice}
                      onChange={(e) => set({ ot_applies:
                        e.target.value === "on" ? true
                        : e.target.value === "off" ? false : null })}
                      style={inputStyle}>
                <option value="inherit">Inherit category default
                  {employee.ot_effective ? "" : ""}</option>
                <option value="on">Always applies</option>
                <option value="off">Never applies</option>
              </select>
              <span style={{ fontSize: 11, color: "#5a6b78" }}>
                {employee.ot_effective
                  ? `Currently: ${employee.ot_rate}/${employee.currency} per hr`
                  : "Currently: no overtime"}
              </span></L>
          )}
          <L label="Passport no.">
            <input value={f.passport_no}
                   onChange={(e) => set({ passport_no: e.target.value })}
                   style={inputStyle} /></L>
          <L label="Employment type">
            <select value={f.employment_type}
                    onChange={(e) => set({ employment_type: e.target.value })}
                    style={inputStyle}>
              {EMPLOYMENT.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
            <span style={{ fontSize: 11, color: "#5a6b78" }}>
              {f.employment_type === "CONTRACT"
                ? "Temporary hire — not on the company work permit"
                : "On the company work permit (expiry tracked)"}
            </span></L>
          <L label="Work permit no.">
            <input value={f.work_permit_no}
                   onChange={(e) => set({ work_permit_no: e.target.value })}
                   style={inputStyle} /></L>
          <L label="Work permit expiry">
            <input type="date" value={f.work_permit_expiry || ""}
                   onChange={(e) => set({ work_permit_expiry: e.target.value })}
                   style={inputStyle} /></L>
          <L label="Join date">
            <input type="date" value={f.join_date || ""}
                   onChange={(e) => set({ join_date: e.target.value })}
                   style={inputStyle} /></L>
          <L label="Emergency contact">
            <input value={f.emergency_contact}
                   onChange={(e) => set({ emergency_contact: e.target.value })}
                   style={inputStyle} /></L>
        </div>

        {isHr && f.employment_type === "PERMANENT" && history
          && history.length > 0 && (
          <div style={{ marginTop: 16, borderTop: "1px solid var(--sp-border)",
                        paddingTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600,
                          color: "var(--sp-navy)" }}>
              Work-permit renewals</div>
            <p style={{ fontSize: 11.5, color: "#5a6b78", margin: "2px 0 8px" }}>
              Renew from the People page (raises a PYR); each extends when
              Finance pays it.
            </p>
            <div style={{ fontSize: 12, color: "#5a6b78" }}>
              {history.map((h, i) => (
                <div key={i}>
                  {String(h.at).slice(0, 10)} · +{h.months}m ·{" "}
                  {h.applied
                    ? <>→ <strong>{h.new_expiry}</strong></>
                    : <span style={{ color: "#b35900" }}>
                        pending payment{h.pyr ? ` (${h.pyr})` : ""}</span>}
                  {h.fee ? ` · fee ${h.fee}` : ""} · {h.by}
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 10, marginTop: 16,
                      alignItems: "center" }}>
          <button onClick={save} disabled={busy || !f.full_name}
                  style={buttonStyle}>
            {busy ? "Saving…" : "Save profile"}</button>
          <label style={{ fontSize: 12.5, marginLeft: "auto" }}>
            <input type="checkbox" checked={f.is_active}
                   onChange={(e) => set({ is_active: e.target.checked })} />{" "}
            Active
          </label>
        </div>
      </div>
    </div>
  );
}
