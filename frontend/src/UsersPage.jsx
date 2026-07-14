import { useEffect, useState } from "react";
import { api } from "./api.js";
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
  ["ADMIN", "Admin — user management, site configuration, full access"],
];
const SITE_ROLES = ["SITE_ENGINEER", "SITE_ADMIN", "PM"];

const EMPTY = { username: "", full_name: "", email: "", phone: "", role: "",
                password: "" };

export default function UsersPage({ me, sites }) {
  const [users, setUsers] = useState([]);
  const [draft, setDraft] = useState(EMPTY);
  const [draftSite, setDraftSite] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [cfg, setCfg] = useState(null);          // SMS/WhatsApp delivery config
  const [testPhone, setTestPhone] = useState("");

  const projectSites = sites.filter((s) => !s.is_head_office);

  function load() {
    api("/users").then(setUsers).catch((e) => setError(e.message));
  }
  useEffect(load, []);
  useEffect(() => { api("/notify/config").then(setCfg).catch(() => {}); }, []);

  async function saveUserField(user, patch) {
    setError(null);
    try {
      await api(`/users/${user.id}`, { method: "PATCH", body: patch });
      load();
    } catch (e) { setError(e.message); }
  }

  async function sendTest() {
    setError(null); setNotice(null);
    try {
      const r = await api("/notify/test", { method: "POST",
        body: { phone: testPhone } });
      setNotice(r.detail);
    } catch (e) { setError(e.message); }
  }

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

  async function resendInvite(user) {
    setError(null); setNotice(null);
    try {
      await api(`/users/${user.id}/resend_invite`, { method: "POST" });
      setNotice(`Login details re-sent to ${user.email}.`);
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
        <input placeholder="Mobile (+960…) for SMS/WhatsApp alerts"
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

      <div style={{ display: "flex", gap: 10, alignItems: "center",
                    flexWrap: "wrap", padding: "10px 12px", borderRadius: 8,
                    background: "var(--sp-tint, #f5f8fb)", margin: "6px 0 12px" }}>
        <strong style={{ fontSize: 13, color: "var(--sp-navy)" }}>
          📱 SMS / WhatsApp alerts</strong>
        {cfg && (cfg.configured ? (
          <span style={{ fontSize: 12.5, color: "#1a7f37" }}>
            ✓ configured — {cfg.channel} via {cfg.sender}</span>
        ) : (
          <span style={{ fontSize: 12.5, color: "#8a5a00" }}>
            not configured — set TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
            TWILIO_FROM in the server .env, then redeploy</span>
        ))}
        <span style={{ marginLeft: "auto", display: "flex", gap: 6,
                       alignItems: "center" }}>
          <input placeholder="Test to +960…" value={testPhone}
                 onChange={(e) => setTestPhone(e.target.value)}
                 style={{ ...inputStyle, width: 150, padding: "4px 8px" }} />
          <button onClick={sendTest} disabled={!cfg?.configured}
                  style={{ ...ghostButton, padding: "4px 12px", fontSize: 12.5 }}>
            Send test</button>
        </span>
        <span style={{ fontSize: 11.5, color: "var(--muted)", flexBasis: "100%" }}>
          A user with a mobile number and <em>SMS</em> ticked below gets an
          alert whenever a document is waiting on them.</span>
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Username</th><th style={th}>Name</th>
          <th style={th}>Role</th><th style={th}>Mobile · SMS</th>
          <th style={th}>Sites</th>
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
              <td style={{ ...td, whiteSpace: "nowrap" }}>
                <input key={`ph-${user.id}-${user.phone || ""}`}
                       defaultValue={user.phone || ""} placeholder="+960…"
                       onBlur={(e) => {
                         const v = e.target.value.trim();
                         if (v !== (user.phone || "")) {
                           saveUserField(user, { phone: v });
                         }
                       }}
                       style={{ ...inputStyle, width: 110, padding: "3px 6px" }} />
                <label style={{ fontSize: 11, marginLeft: 6,
                                color: user.notify_external ? "var(--sp-navy)"
                                  : "#8a97a1" }}>
                  <input type="checkbox" checked={!!user.notify_external}
                         onChange={(e) => saveUserField(user,
                           { notify_external: e.target.checked })} /> SMS
                </label>
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
    </section>
  );
}
