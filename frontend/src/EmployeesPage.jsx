import { useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const EMPTY = { full_name: "", nationality: "", job_category: "",
                basic_pay: "", passport_no: "", join_date: "" };

export default function EmployeesPage({ me, sites }) {
  const [employees, setEmployees] = useState([]);
  const [categories, setCategories] = useState([]);
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);

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
            <input placeholder="Nationality" value={draft.nationality}
                   onChange={(e) => setDraft({ ...draft,
                                               nationality: e.target.value })}
                   style={{ ...inputStyle, width: 110 }} />
            <select value={draft.job_category}
                    onChange={(e) => setDraft({ ...draft,
                                                job_category: e.target.value })}
                    style={{ ...inputStyle, width: 160 }}>
              <option value="">Job category…</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <input placeholder="Passport no." value={draft.passport_no}
                   onChange={(e) => setDraft({ ...draft,
                                               passport_no: e.target.value })}
                   style={{ ...inputStyle, width: 120 }} />
            <input placeholder="Basic pay (MVR)" type="number"
                   value={draft.basic_pay}
                   onChange={(e) => setDraft({ ...draft,
                                               basic_pay: e.target.value })}
                   style={{ ...inputStyle, width: 130 }} />
            <input type="date" value={draft.join_date}
                   title="Join date"
                   onChange={(e) => setDraft({ ...draft,
                                               join_date: e.target.value })}
                   style={{ ...inputStyle, width: 140 }} />
            <button onClick={add} disabled={!draft.full_name}
                    style={buttonStyle}>Add employee</button>
          </div>
        )}
        {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Emp No</th><th style={th}>Name</th>
            <th style={th}>Category</th><th style={th}>Site</th>
            {seesPay && <th style={th}>Basic Pay</th>}
            {isHr && <th style={th}>Passport</th>}
            <th style={th}>Allocate</th>
          </tr></thead>
          <tbody>
            {employees.map((emp) => (
              <tr key={emp.id}>
                <td style={{ ...td, fontWeight: 600,
                             color: "var(--sp-navy)" }}>{emp.emp_no}</td>
                <td style={td}>{emp.full_name}</td>
                <td style={td}>{emp.job_category_name}</td>
                <td style={td}>{emp.site_code || "—"}</td>
                {seesPay && <td style={td}>{emp.basic_pay}</td>}
                {isHr && <td style={td}>{emp.passport_no}</td>}
                <td style={td}>
                  {isHr ? (
                    <select value="" style={{ ...inputStyle, width: 130,
                                              padding: "3px 6px" }}
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
              <tr><td style={td} colSpan={7}>No employees yet.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
