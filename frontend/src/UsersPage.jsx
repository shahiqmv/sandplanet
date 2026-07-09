import { useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const ROLES = [
  ["SITE_ENGINEER", "Site Engineer — prepares DPR/TWS, submits IR & MAR"],
  ["SITE_ADMIN", "Site Admin / Storekeeper — DPR, MR, GRN, attendance, petty cash"],
  ["PM", "Project Manager — approves site documents, OT, month sign-off"],
  ["HO_PURCHASING", "HO Purchasing — PR, LM, PO, item & supplier masters"],
  ["DIRECTOR", "Sr PM / Director — approves PRs & payment requests"],
  ["SIGNATORY", "Signatory (Executive Director) — authorises Payment Vouchers"],
  ["FINANCE", "Finance — builds payment vouchers, records payments & slips"],
  ["HO_HR", "HO HR / Payroll — employees, timesheet reopen, payroll export"],
  ["ADMIN", "Admin — user management, site configuration, full access"],
];
const SITE_ROLES = ["SITE_ENGINEER", "SITE_ADMIN", "PM"];

const EMPTY = { username: "", full_name: "", role: "", password: "" };

export default function UsersPage({ me, sites }) {
  const [users, setUsers] = useState([]);
  const [draft, setDraft] = useState(EMPTY);
  const [draftSite, setDraftSite] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const projectSites = sites.filter((s) => !s.is_head_office);

  function load() {
    api("/users").then(setUsers).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function add() {
    setError(null);
    setNotice(null);
    try {
      const user = await api("/users", { method: "POST", body: draft });
      if (draftSite && SITE_ROLES.includes(draft.role)) {
        await api(`/users/${user.id}/allocate`,
                  { method: "POST", body: { site_id: +draftSite } });
        if (draft.role === "PM" && window.confirm(
              "Also make this PM the assigned Project PM for the site " +
              "(drives approval routing)?")) {
          await api(`/sites/${draftSite}/assign-pm`,
                    { method: "POST", body: { pm_user_id: user.id } });
        }
      }
      setNotice(`User ${user.username} created.`);
      setDraft(EMPTY);
      setDraftSite("");
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function allocate(user, siteId) {
    if (!siteId) return;
    await api(`/users/${user.id}/allocate`,
              { method: "POST", body: { site_id: +siteId } });
    load();
  }

  async function assignPm(user, siteId) {
    if (!siteId) return;
    await api(`/sites/${siteId}/assign-pm`,
              { method: "POST", body: { pm_user_id: user.id } });
    setNotice(`${user.full_name} is now the Project PM there.`);
    load();
  }

  async function deactivate(user) {
    if (!window.confirm(`Deactivate ${user.username}? Their history is `
                        + "preserved; the account can no longer sign in.")) {
      return;
    }
    await api(`/users/${user.id}/deactivate`, { method: "POST" });
    load();
  }

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Users &amp; roles
      </h2>
      <p style={{ fontSize: 13, color: "#5a6b78" }}>
        One role per user. Site Engineers and Site Admins work on exactly one
        site; PMs may cover several. All permissions are enforced on the
        server — the role decides what each person can create and approve.
      </p>

      <div style={{ display: "flex", gap: 8, margin: "12px 0",
                    flexWrap: "wrap" }}>
        <input placeholder="Username" value={draft.username}
               onChange={(e) => setDraft({ ...draft,
                                           username: e.target.value })}
               style={{ ...inputStyle, width: 130 }} />
        <input placeholder="Full name" value={draft.full_name}
               onChange={(e) => setDraft({ ...draft,
                                           full_name: e.target.value })}
               style={{ ...inputStyle, flex: 1, minWidth: 150 }} />
        <select value={draft.role}
                onChange={(e) => setDraft({ ...draft, role: e.target.value })}
                style={{ ...inputStyle, flex: 2, minWidth: 260 }}>
          <option value="">Role…</option>
          {ROLES.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        {SITE_ROLES.includes(draft.role) && (
          <select value={draftSite}
                  onChange={(e) => setDraftSite(e.target.value)}
                  style={{ ...inputStyle, width: 120 }}>
            <option value="">Site…</option>
            {projectSites.map((s) => (
              <option key={s.id} value={s.id}>{s.code}</option>
            ))}
          </select>
        )}
        <input placeholder="Initial password" type="text"
               value={draft.password}
               onChange={(e) => setDraft({ ...draft,
                                           password: e.target.value })}
               style={{ ...inputStyle, width: 140 }} />
        <button onClick={add} style={buttonStyle}
                disabled={!draft.username || !draft.full_name || !draft.role ||
                          !draft.password ||
                          (SITE_ROLES.includes(draft.role) && !draftSite &&
                           draft.role !== "PM")}>
          Create user
        </button>
      </div>
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Username</th><th style={th}>Name</th>
          <th style={th}>Role</th><th style={th}>Sites</th>
          <th style={th}>Allocate</th><th style={th}>PM of…</th>
          <th style={th} />
        </tr></thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id} style={user.is_active ? {} : { opacity: 0.5 }}>
              <td style={{ ...td, fontWeight: 600,
                           color: "var(--sp-navy)" }}>{user.username}</td>
              <td style={td}>{user.full_name}</td>
              <td style={td}>{user.role.replace(/_/g, " ")}</td>
              <td style={td}>
                {user.allocations.map((a) => a.site_code).join(", ") || "—"}
              </td>
              <td style={td}>
                {SITE_ROLES.includes(user.role) && user.is_active ? (
                  <select value="" style={{ ...inputStyle, width: 110,
                                            padding: "3px 6px" }}
                          onChange={(e) => allocate(user, e.target.value)}>
                    <option value="">Site…</option>
                    {projectSites.map((s) => (
                      <option key={s.id} value={s.id}>{s.code}</option>
                    ))}
                  </select>
                ) : "—"}
              </td>
              <td style={td}>
                {user.role === "PM" && user.is_active ? (
                  <select value="" style={{ ...inputStyle, width: 110,
                                            padding: "3px 6px" }}
                          onChange={(e) => assignPm(user, e.target.value)}>
                    <option value="">Assign…</option>
                    {projectSites.map((s) => (
                      <option key={s.id} value={s.id}>{s.code}</option>
                    ))}
                  </select>
                ) : "—"}
              </td>
              <td style={td}>
                {user.is_active && user.id !== me.id && (
                  <button onClick={() => deactivate(user)}
                          style={{ ...ghostButton, padding: "2px 10px",
                                   fontSize: 12, color: "#c0392b" }}>
                    Deactivate
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
