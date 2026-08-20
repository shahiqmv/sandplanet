import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, buttonStyle, card, inputStyle, td, th } from "./ui.jsx";

// Worker leave. Granting moves the man to Head Office for the duration, so his
// site stops counting him and nobody has to mark him every morning; HR marks
// the return, which puts him back on his own site (owner 2026-08-20).
//
// Paid leave is pre-marked at Head Office and pays by itself. Leave without pay
// marks nothing AND stops the site marking him, so the days cannot be paid by
// accident.
export default function LeavePage({ me }) {
  const [rows, setRows] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const canGrant = ["HO_HR", "ADMIN", "PA"].includes(me.role);

  const load = () =>
    api(`/leaves${openOnly ? "?open=1" : ""}`).then(setRows).catch(() => {});

  useEffect(() => { load(); }, [openOnly]);
  useEffect(() => {
    if (canGrant) api("/employees").then(setEmployees).catch(() => {});
  }, [canGrant]);

  const blank = { employee_id: "", kind: "PAID", from_date: "", to_date: "",
                  reason: "" };

  async function grant() {
    setBusy(true); setErr("");
    try {
      await api("/leaves", { method: "POST", body: form });
      setForm(null);
      load();
    } catch (e) {
      setErr(e.message || "Could not grant the leave.");
    } finally { setBusy(false); }
  }

  async function markReturned(row) {
    // The date matters: he goes back on his site's register from the day
    // after, and men come back late as often as on time. Default to today,
    // let HR correct it.
    const on = window.prompt(
      `${row.full_name} is back — what date did he return?`,
      new Date().toISOString().slice(0, 10));
    if (!on) return;
    await run(row, "return", { on });
  }

  async function cancelLeave(row) {
    if (!window.confirm(`Cancel this leave for ${row.full_name}? He goes `
                        + "straight back to his site and any leave days "
                        + "recorded for him are removed.")) return;
    await run(row, "cancel", {});
  }

  async function run(row, what, body) {
    setErr("");
    try {
      await api(`/leaves/${row.id}/${what}`, { method: "POST", body });
      load();
    } catch (e) { setErr(e.message || "That did not go through."); }
  }

  const overdue = rows.filter((r) => r.overdue);

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", flexWrap: "wrap", gap: 10 }}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Worker leave</h2>
        {canGrant && !form && (
          <button style={buttonStyle} onClick={() => setForm(blank)}>
            ➕ Grant leave</button>)}
      </div>
      <p style={{ color: "#5a6b78", fontSize: 12, margin: "0 0 10px" }}>
        Granting leave transfers the worker to Head Office until he is back.
        Paid leave is recorded for him automatically; leave without pay blocks
        his attendance and his pay for those days.
      </p>

      {overdue.length > 0 && (
        <div style={{ background: "#FFF6E5", border: "1px solid #F0C36D",
                      borderRadius: 6, padding: "8px 12px", fontSize: 12.5,
                      marginBottom: 12 }}>
          <b>{overdue.length} worker{overdue.length > 1 ? "s are" : " is"}</b>{" "}
          past the end of their leave and still on the Head Office register.
          Mark them returned so they go back to their site.
        </div>)}

      {form && (
        <div style={{ border: "1px solid #dde5ea", borderRadius: 6,
                      padding: 12, marginBottom: 14 }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <select style={{ ...inputStyle, minWidth: 230 }}
              value={form.employee_id}
              onChange={(e) => setForm({ ...form,
                                         employee_id: e.target.value })}>
              <option value="">Choose a worker…</option>
              {employees.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.emp_no} — {e.full_name}
                  {e.site_code ? ` (${e.site_code})` : ""}</option>))}
            </select>
            <select style={inputStyle} value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="PAID">Paid leave</option>
              <option value="UNPAID">Leave without pay</option>
            </select>
            <label style={{ fontSize: 12, color: "#5a6b78" }}>From{" "}
              <input type="date" style={inputStyle} value={form.from_date}
                onChange={(e) => setForm({ ...form,
                                           from_date: e.target.value })} />
            </label>
            <label style={{ fontSize: 12, color: "#5a6b78" }}>To{" "}
              <input type="date" style={inputStyle} value={form.to_date}
                onChange={(e) => setForm({ ...form,
                                           to_date: e.target.value })} />
            </label>
            <input style={{ ...inputStyle, flex: 1, minWidth: 180 }}
              placeholder="Reason (optional)" value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          </div>
          {err && <div style={{ color: "#c0392b", fontSize: 12.5,
                                marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <Btn onClick={grant} disabled={busy}>
              {busy ? "Granting…" : "Grant leave"}</Btn>
            <Btn variant="secondary" onClick={() => { setForm(null);
                                                      setErr(""); }}>
              Cancel</Btn>
          </div>
        </div>)}

      {err && !form && <p style={{ color: "#c0392b", fontSize: 12.5 }}>
        {err}</p>}

      <label style={{ fontSize: 12, color: "#5a6b78" }}>
        <input type="checkbox" checked={openOnly}
          onChange={(e) => setOpenOnly(e.target.checked)} />{" "}
        Currently away only
      </label>

      <table style={{ width: "100%", borderCollapse: "collapse",
                      marginTop: 8 }}>
        <thead><tr>
          <th style={th}>Emp No</th><th style={th}>Name</th>
          <th style={th}>Type</th><th style={th}>From</th><th style={th}>To</th>
          <th style={{ ...th, textAlign: "right" }}>Days</th>
          <th style={th}>Back to</th><th style={th}>Status</th>
          {canGrant && <th style={th}></th>}
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={td}>{r.emp_no}</td>
              <td style={td}>{r.full_name}</td>
              <td style={td}>
                <Chip tone={r.kind === "PAID" ? "info" : "warn"}>
                  {r.kind === "PAID" ? "Paid" : "No pay"}</Chip></td>
              <td style={td}>{r.from_date}</td>
              <td style={td}>{r.to_date}</td>
              <td style={{ ...td, textAlign: "right" }}>{r.days}</td>
              <td style={td}>{r.from_site || "Head Office"}</td>
              <td style={td}>
                {r.cancelled ? "Cancelled"
                  : r.returned_on ? `Returned ${r.returned_on}`
                  : r.overdue ? <span style={{ color: "#b9770e" }}>
                      ⚠ Due back</span>
                  : "Away"}</td>
              {canGrant && (
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  {r.open && (<>
                    <Btn variant="secondary"
                      onClick={() => markReturned(r)}>Returned</Btn>{" "}
                    <Btn variant="secondary"
                      onClick={() => cancelLeave(r)}>Cancel</Btn>
                  </>)}
                </td>)}
            </tr>
          ))}
          {!rows.length && (
            <tr><td style={td} colSpan={canGrant ? 9 : 8}>
              {openOnly ? "Nobody is on leave right now."
                        : "No leave recorded yet."}</td></tr>)}
        </tbody>
      </table>
    </section>
  );
}
