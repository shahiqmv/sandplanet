import { useEffect, useState } from "react";
import { api } from "./api.js";
import UserDetail from "./UserDetail.jsx";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const ROLES = [
  ["SITE_ENGINEER", "Site Engineer — full site tasks: DPR/TWS, IR & MAR, "
   + "MR, GRN, attendance, petty cash"],
  ["SITE_ADMIN", "Site Admin / Storekeeper — DPR, MR, GRN, attendance, petty cash"],
  ["PM", "Project Manager — approves site documents, OT, month sign-off"],
  ["HO_PURCHASING", "HO Purchasing — PR, LM, PO, item & supplier masters"],
  ["DIRECTOR", "Sr PM / Director — approves PRs & payment requests"],
  ["SIGNATORY", "Signatory (Executive Director) — authorises Payment Vouchers"],
  ["FINANCE", "Finance — builds payment vouchers, records payments & slips"],
  ["HO_HR", "HO HR / Payroll — employees, timesheet reopen, payroll export"],
  ["QS", "Quantity Surveyor — tenders, contracts, project financials (USD)"],
  ["PA", "Personal Assistant (Director's Office) — meetings, onboarding entry, "
   + "company profile; read-only projects, commercials & receivables"],
  ["ADMIN", "Admin — user management, site configuration, full access"],
];
const SITE_ROLES = ["SITE_ENGINEER", "SITE_ADMIN", "PM"];

const EMPTY = { username: "", full_name: "", email: "", phone: "", role: "",
                password: "" };

export default function UsersPage({ me, sites }) {
  const [openUser, setOpenUser] = useState(null);
  const [users, setUsers] = useState([]);
  const [draft, setDraft] = useState(EMPTY);
  const [draftSite, setDraftSite] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [roleEdit, setRoleEdit] = useState(null);   // { id, role, assignSite }

  const projectSites = sites.filter((s) => !s.is_head_office);

  function load() {
    api("/users").then(setUsers).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function add() {
    setError(null);
    setNotice(null);
    try {
      const body = { ...draft };
      if (!body.password) delete body.password;  // triggers the invite flow
      const user = await api("/users", { method: "POST", body });
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
      setNotice(user.invite_sent
        ? `User ${user.username} created — login details emailed to ${draft.email}.`
        : user.invite_error
          ? `User ${user.username} created, but the email failed: `
            + `${user.invite_error}`
          : `User ${user.username} created.`);
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

  async function changeRole(user, role, assignSiteId) {
    setError(null); setNotice(null);
    try {
      const body = { role };
      if (assignSiteId) body.assign_site_id = +assignSiteId;
      const r = await api(`/users/${user.id}/change-role`,
                          { method: "POST", body });
      setNotice(`${user.full_name} is now ${role.replace(/_/g, " ")}`
        + (r.assigned_pm_site ? `, and PM of ${r.assigned_pm_site}.` : "."));
      setRoleEdit(null);
      load();
    } catch (e) { setError(e.message); }
  }

  async function resendInvite(user) {
    setError(null); setNotice(null);
    try {
      await api(`/users/${user.id}/resend_invite`, { method: "POST" });
      setNotice(`Login details re-sent to ${user.email}.`);
    } catch (e) { setError(e.message); }
  }

  async function editDesignation(user) {
    const t = window.prompt(
      "Title printed under this user's signature on official letters "
      + "(e.g. Managing Director):", user.designation || "");
    if (t === null) return;
    setError(null);
    try {
      await api(`/users/${user.id}`,
                { method: "PATCH", body: { designation: t.trim() } });
      setNotice(`Signature title ${t.trim() ? "set" : "cleared"} for `
                + user.full_name + ".");
      load();
    } catch (e) { setError(e.message); }
  }

  async function resetPassword(user) {
    const pw = window.prompt(
      `Set a new password for ${user.username} (min 8 characters). `
      + "You'll need to tell them the new password.");
    if (pw === null) return;
    if (pw.length < 8) { setError("Password must be at least 8 characters."); return; }
    setError(null); setNotice(null);
    try {
      await api(`/users/${user.id}`, { method: "PATCH", body: { password: pw } });
      setNotice(`Password reset for ${user.username}.`);
    } catch (e) { setError(e.message); }
  }

  async function remove(user) {
    if (!window.confirm(`Permanently delete ${user.username}? This can't be `
                        + "undone. (Users with history can't be deleted — "
                        + "deactivate those instead.)")) return;
    setError(null); setNotice(null);
    try {
      await api(`/users/${user.id}`, { method: "DELETE" });
      setNotice(`${user.username} deleted.`);
      load();
    } catch (e) { setError(e.message); }
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
               style={{ ...inputStyle, flex: 1, minWidth: 130 }} />
        <input placeholder="Email (for login details)" type="email"
               value={draft.email}
               onChange={(e) => setDraft({ ...draft, email: e.target.value })}
               style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
        <input placeholder="Mobile (+960…) — contact"
               value={draft.phone}
               onChange={(e) => setDraft({ ...draft, phone: e.target.value })}
               style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
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
        <input placeholder="Password (blank = email a temp one)" type="text"
               value={draft.password}
               onChange={(e) => setDraft({ ...draft,
                                           password: e.target.value })}
               style={{ ...inputStyle, width: 220 }} />
        <button onClick={add} style={buttonStyle}
                disabled={!draft.username || !draft.full_name || !draft.role ||
                          (!draft.password && !draft.email) ||
                          (SITE_ROLES.includes(draft.role) && !draftSite &&
                           draft.role !== "PM")}>
          Create user
        </button>
      </div>
      <p style={{ fontSize: 12, color: "#5a6b78", margin: "0 0 4px" }}>
        Leave the password blank and give an email — the app generates a
        temporary password and emails the login details; the user sets their
        own password on first sign-in.
      </p>
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Username</th><th style={th}>Name</th>
          <th style={th}>Email</th>
          <th style={th}>Role</th>
          <th style={th}>Sites</th>
          <th style={th}>Allocate</th><th style={th}>PM of…</th>
          <th style={th} />
        </tr></thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id} style={user.is_active ? {} : { opacity: 0.5 }}>
              <td style={{ ...td, fontWeight: 600 }}>
                {/* The page had no way in: four separate prompts edited four
                    fields, and email was not among them (owner 2026-08-30). */}
                <a href="#" onClick={(e) => { e.preventDefault();
                                              setOpenUser(user); }}
                   style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                  {user.username}
                </a>
              </td>
              <td style={td}>{user.full_name}
                {(user.designation || ["SIGNATORY", "DIRECTOR", "ADMIN"]
                    .includes(user.role)) && (
                  <div style={{ fontSize: 11, color: "#5a6b78" }}>
                    {user.designation || "no signature title"}
                    {me.role === "ADMIN" && (
                      <button title={"Title printed under this user's "
                          + "signature on official letters"}
                        onClick={() => editDesignation(user)}
                        style={{ border: "none", background: "none",
                          cursor: "pointer", color: "#2b7bb9",
                          fontSize: 11, padding: "0 0 0 6px" }}>edit</button>
                    )}
                  </div>
                )}</td>
              <td style={{ ...td, fontSize: 12.5 }}>
                {user.email || (
                  <span style={{ color: "var(--amber-fg)" }}>
                    none on file</span>
                )}
                {user.employee_detail && (
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {user.employee_detail.emp_no}
                  </div>
                )}
              </td>
              <td style={td}>
                {roleEdit?.id === user.id ? (
                  <div style={{ display: "flex", flexDirection: "column",
                    gap: 4, minWidth: 170 }}>
                    <select value={roleEdit.role}
                      onChange={(e) => setRoleEdit({ ...roleEdit,
                        role: e.target.value })}
                      style={{ ...inputStyle, padding: "3px 6px" }}>
                      {ROLES.map(([v]) => (
                        <option key={v} value={v}>
                          {v.replace(/_/g, " ")}</option>
                      ))}
                    </select>
                    {roleEdit.role === "PM" && user.allocations[0] && (
                      <label style={{ fontSize: 11, color: "#5a6b78",
                        display: "flex", gap: 4, alignItems: "center" }}>
                        <input type="checkbox" checked={roleEdit.assignSite}
                          onChange={(e) => setRoleEdit({ ...roleEdit,
                            assignSite: e.target.checked })} />
                        Assign as PM of {user.allocations[0].site_code}
                      </label>
                    )}
                    <div style={{ display: "flex", gap: 4 }}>
                      <button onClick={() => changeRole(user, roleEdit.role,
                        (roleEdit.role === "PM" && roleEdit.assignSite
                          && user.allocations[0])
                          ? user.allocations[0].site : null)}
                        style={{ ...buttonStyle, padding: "2px 12px",
                          fontSize: 12 }}>Save</button>
                      <button onClick={() => setRoleEdit(null)}
                        style={{ ...ghostButton, padding: "2px 10px",
                          fontSize: 12 }}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <span style={{ display: "flex", gap: 6,
                    alignItems: "baseline" }}>
                    {user.role.replace(/_/g, " ")}
                    {me.role === "ADMIN" && user.is_active
                      && user.id !== me.id && (
                      <button title="Change this user's role"
                        onClick={() => setRoleEdit({ id: user.id,
                          role: user.role, assignSite: true })}
                        style={{ border: "none", background: "none",
                          cursor: "pointer", color: "#2b7bb9", fontSize: 11,
                          padding: 0 }}>change</button>
                    )}
                  </span>
                )}
              </td>
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
              <td style={{ ...td, whiteSpace: "nowrap" }}>
                <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <button onClick={() => resetPassword(user)}
                          style={{ ...ghostButton, padding: "2px 10px",
                                   fontSize: 12 }}>Reset password</button>
                  {user.is_active && user.email && (
                    <button onClick={() => resendInvite(user)}
                            title={`Re-send login details to ${user.email}`}
                            style={{ ...ghostButton, padding: "2px 10px",
                                     fontSize: 12 }}>Resend invite</button>
                  )}
                  {user.is_active && user.id !== me.id && (
                    <button onClick={() => deactivate(user)}
                            style={{ ...ghostButton, padding: "2px 10px",
                                     fontSize: 12, color: "#b35900" }}>
                      Deactivate</button>
                  )}
                  {user.id !== me.id && (
                    <button onClick={() => remove(user)}
                            style={{ ...ghostButton, padding: "2px 8px",
                                     fontSize: 12, color: "#c0392b" }}>
                      Delete</button>
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {openUser && (
        <UserDetail user={openUser} me={me} onClose={() => setOpenUser(null)}
          onSaved={(saved) => { setOpenUser(saved); load(); }} />
      )}
    </section>
  );
}
