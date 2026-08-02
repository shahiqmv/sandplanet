import { useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// HO-admin management of Client Portal logins (the client realm itself is a
// separate app at /portal/). Create an account, assign the client's site(s),
// hand over the one-time temp password.
export default function ClientUsersPage({ sites }) {
  const [list, setList] = useState([]);
  const [draft, setDraft] = useState({ org_name: "", full_name: "",
    email: "", site_ids: [] });
  const [temp, setTemp] = useState(null);      // {email, password} to hand over
  const [error, setError] = useState(null);
  const projectSites = (sites || []).filter((s) => !s.is_head_office);

  const load = () => api("/client-users").then(setList).catch(() => {});
  useEffect(() => { load(); }, []);

  async function create() {
    setError(null); setTemp(null);
    try {
      const r = await api("/client-users", { method: "POST", body: draft });
      setTemp({ email: r.email, password: r.temp_password });
      setDraft({ org_name: "", full_name: "", email: "", site_ids: [] });
      load();
    } catch (e) { setError(e.message); }
  }
  async function resetPw(u) {
    if (!window.confirm(`Reset ${u.email}'s password? Their current login `
      + "stops working.")) return;
    const r = await api(`/client-users/${u.id}/password`, { method: "POST" });
    setTemp({ email: u.email, password: r.temp_password }); load();
  }
  async function deactivate(u) {
    if (!window.confirm(`Deactivate ${u.email}? They can no longer sign in.`))
      return;
    await api(`/client-users/${u.id}`, { method: "DELETE" }); load();
  }
  const toggleSite = (id) => setDraft((d) => ({ ...d,
    site_ids: d.site_ids.includes(id)
      ? d.site_ids.filter((x) => x !== id) : [...d.site_ids, id] }));

  return (
    <>
      <section style={card}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Client Portal accounts</h2>
        <p style={{ color: "#5a6b78", fontSize: 12.5, marginTop: 0 }}>
          External read-only logins to <b>/portal/</b>. A client sees only the
          site(s) you assign — daily progress, works and workforce total; no
          costs, rates or internal data.</p>

        {temp && (
          <div style={{ border: "1px solid #b7e0c5", background: "#eefaf1",
            borderRadius: 8, padding: "10px 12px", margin: "8px 0",
            fontSize: 13.5 }}>
            <b>Account ready.</b> Give the client these credentials — the
            password is shown only once:<br />
            <span style={{ fontFamily: "var(--font-mono)" }}>
              {temp.email}</span> · password{" "}
            <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700 }}>
              {temp.password}</span>
          </div>)}
        {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
          alignItems: "flex-start" }}>
          <input placeholder="Organisation" value={draft.org_name}
            onChange={(e) => setDraft({ ...draft, org_name: e.target.value })}
            style={{ ...inputStyle, width: 180 }} />
          <input placeholder="Contact name" value={draft.full_name}
            onChange={(e) => setDraft({ ...draft, full_name: e.target.value })}
            style={{ ...inputStyle, width: 160 }} />
          <input placeholder="Email *" type="email" value={draft.email}
            onChange={(e) => setDraft({ ...draft, email: e.target.value })}
            style={{ ...inputStyle, width: 200 }} />
          <button onClick={create}
            disabled={!draft.email || !draft.site_ids.length}
            style={buttonStyle}>Create account</button>
        </div>
        <div style={{ marginTop: 8, fontSize: 12, color: "#5a6b78" }}>
          Assign site(s):
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
            marginTop: 4 }}>
            {projectSites.map((s) => (
              <label key={s.id} style={{ display: "inline-flex", gap: 4,
                alignItems: "center", border: "1px solid var(--line)",
                borderRadius: 6, padding: "3px 8px", cursor: "pointer",
                background: draft.site_ids.includes(s.id)
                  ? "var(--sky-soft)" : "#fff" }}>
                <input type="checkbox" checked={draft.site_ids.includes(s.id)}
                  onChange={() => toggleSite(s.id)} />{s.code}</label>))}
          </div>
        </div>
      </section>

      <section style={card}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Organisation</th><th style={th}>Contact</th>
            <th style={th}>Email</th><th style={th}>Sites</th>
            <th style={th}>Status</th><th style={th}></th>
          </tr></thead>
          <tbody>
            {list.map((u) => (
              <tr key={u.id} style={{ opacity: u.is_active ? 1 : 0.5 }}>
                <td style={td}>{u.org_name}</td>
                <td style={td}>{u.full_name}</td>
                <td style={td}>{u.email}</td>
                <td style={td}>{u.sites.map((s) => s.code).join(", ") || "—"}</td>
                <td style={td}>{u.is_active
                  ? (u.last_login ? "Active" : "Invited") : "Off"}</td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  {u.is_active && <>
                    <button onClick={() => resetPw(u)}
                      style={{ ...ghostButton, padding: "2px 8px",
                        fontSize: 12 }}>Reset pw</button>{" "}
                    <button onClick={() => deactivate(u)}
                      style={{ border: "none", background: "none",
                        color: "var(--red-fg)", cursor: "pointer",
                        fontSize: 12 }}>Deactivate</button></>}</td>
              </tr>
            ))}
            {!list.length && <tr><td style={td} colSpan={6}>
              No client accounts yet.</td></tr>}
          </tbody>
        </table>
      </section>
    </>
  );
}
