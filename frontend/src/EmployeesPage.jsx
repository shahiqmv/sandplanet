import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { NATIONALITIES } from "./constants.js";
import { SelectOrOther, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const EMPTY = { full_name: "", nationality: "", job_category: "",
                basic_pay: "", currency: "MVR", passport_no: "",
                join_date: "" };

export default function EmployeesPage({ me, sites }) {
  const [employees, setEmployees] = useState([]);
  const [categories, setCategories] = useState([]);
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);   // employee being edited

  const isHr = ["HO_HR", "ADMIN"].includes(me.role);
  const seesPay = ["HO_HR", "FINANCE", "ADMIN"].includes(me.role);

  function load() {
    api("/employees").then(setEmployees);
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
        </div>

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
              <tr><td style={td} colSpan={9}>No employees yet.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      {editing && (
        <EmployeeProfile employee={editing} categories={categories}
          seesPay={seesPay}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
    </>
  );
}

function EmployeeProfile({ employee, categories, seesPay, onClose, onSaved }) {
  const [f, setF] = useState({
    full_name: employee.full_name || "",
    date_of_birth: employee.date_of_birth || "",
    nationality: employee.nationality || "",
    job_category: employee.job_category || "",
    basic_pay: employee.basic_pay ?? "",
    currency: employee.currency || "MVR",
    ot_applies: employee.ot_applies,   // true | false | null
    passport_no: employee.passport_no || "",
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

  const set = (patch) => setF((s) => ({ ...s, ...patch }));
  const otChoice = f.ot_applies === true ? "on"
                 : f.ot_applies === false ? "off" : "inherit";

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
