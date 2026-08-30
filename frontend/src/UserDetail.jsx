import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, StatusChip, card, inputStyle } from "./ui.jsx";

const ROLE_LABEL = (r) => (r || "").replace(/_/g, " ");

// One place to open a user. Email and phone used to be settable only at
// creation and invisible ever after — while "resend invite" went to whatever
// address had been typed that day, with no way to see or correct it
// (owner 2026-08-30).
export default function UserDetail({ user, me, onSaved, onClose }) {
  const [f, setF] = useState({
    username: user.username, full_name: user.full_name,
    email: user.email || "", phone: user.phone || "",
    designation: user.designation || "", role: user.role,
    notify_external: user.notify_external,
    employee: user.employee || null,
  });
  const [options, setOptions] = useState([]);
  const [q, setQ] = useState("");
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const isSelf = user.id === me.id;

  useEffect(() => {
    if (!picking) return;
    const t = setTimeout(() => {
      api(`/users/${user.id}/employee-options`
          + (q ? `?q=${encodeURIComponent(q)}` : ""))
        .then(setOptions).catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [picking, q, user.id]);

  const set = (k) => (e) => setF({ ...f,
    [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function save(extra) {
    setBusy(true); setError(null);
    try {
      const saved = await api(`/users/${user.id}`,
                              { method: "PATCH", body: { ...f, ...extra } });
      // Fold the result back into the form. Linking saves immediately, so
      // without this the form still held the employee it opened with —
      // null — and the next "Save changes" quietly unlinked what had just
      // been linked.
      setF((prev) => ({ ...prev, employee: saved.employee ?? null }));
      onSaved(saved);
      setPicking(false);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const linked = user.employee_detail;

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)",
                  display: "flex", alignItems: "flex-start",
                  justifyContent: "center", zIndex: 300, padding: 24,
                  overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 620, width: "100%", margin: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                      flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
            {user.username}
          </h2>
          <StatusChip status={user.is_active ? "ACTIVE" : "INACTIVE"} />
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
            {ROLE_LABEL(user.role)}
            {user.last_login
              ? ` · last signed in ${new Date(user.last_login)
                  .toLocaleDateString()}`
              : " · never signed in"}
          </span>
          <button onClick={onClose}
                  style={{ marginLeft: "auto", background: "transparent",
                           border: "1px solid #BFD6E6", borderRadius: 8,
                           padding: "5px 13px", cursor: "pointer",
                           fontFamily: "inherit", color: "var(--navy)" }}>
            Close
          </button>
        </div>

        {error && (
          <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>
        )}

        <div style={{ display: "grid", gap: 10, marginTop: 14,
                      gridTemplateColumns: "1fr 1fr" }}>
          <L k="Username"><input style={inputStyle} value={f.username}
            onChange={set("username")} /></L>
          <L k="Full name"><input style={inputStyle} value={f.full_name}
            onChange={set("full_name")} /></L>
          <L k="Email"><input style={inputStyle} type="email" value={f.email}
            onChange={set("email")}
            placeholder="where login details are sent" /></L>
          <L k="Phone"><input style={inputStyle} value={f.phone}
            onChange={set("phone")} /></L>
          <L k="Signature title" wide>
            <input style={inputStyle} value={f.designation}
              onChange={set("designation")}
              placeholder="printed under this signature on letters" /></L>
          <label style={{ ...fld, gridColumn: "1 / -1" }}>
            <span style={{ fontSize: 13, color: "var(--ink, inherit)" }}>
              <input type="checkbox" checked={!!f.notify_external}
                     onChange={set("notify_external")} />{" "}
              Send this user email notifications
            </span>
          </label>
        </div>

        {/* The person behind the login. Kept as a link rather than retyping
            the name, so the account and the payroll record cannot drift. */}
        <div style={{ marginTop: 16, paddingTop: 14,
                      borderTop: "1px solid var(--line)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10,
                        flexWrap: "wrap" }}>
            <b style={{ fontSize: 12.5, color: "var(--sp-navy)" }}>
              Employee record
            </b>
            {linked ? (
              <span style={{ fontSize: 13 }}>
                {linked.emp_no} · {linked.full_name}
                <span style={{ color: "var(--muted)" }}>
                  {linked.job_category ? ` · ${linked.job_category}` : ""}
                  {" · "}{linked.employment_type}
                </span>
                {!linked.is_active && (
                  <b style={{ color: "var(--amber-fg)" }}>
                    {" "}· left{linked.left_on ? ` ${linked.left_on}` : ""}
                  </b>
                )}
              </span>
            ) : (
              <span style={{ fontSize: 13, color: "var(--muted)" }}>
                Not linked — this login isn&rsquo;t tied to anyone on the
                payroll
              </span>
            )}
            <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
              <Btn variant="ghost" style={{ fontSize: 12, padding: "3px 10px" }}
                   onClick={() => { setPicking(!picking); setQ(""); }}>
                {picking ? "Cancel" : linked ? "Change" : "Link"}</Btn>
              {linked && !picking && (
                <Btn variant="ghost" disabled={busy}
                     style={{ fontSize: 12, padding: "3px 10px",
                              color: "var(--red-fg)" }}
                     onClick={() => save({ employee: null })}>
                  Unlink</Btn>
              )}
            </span>
          </div>

          {picking && (
            <div style={{ marginTop: 10 }}>
              <input value={q} onChange={(e) => setQ(e.target.value)}
                     placeholder="Search by name or employee number…"
                     style={{ ...inputStyle, width: "100%" }} />
              <div style={{ maxHeight: 210, overflowY: "auto", marginTop: 8,
                            border: "1px solid var(--line)",
                            borderRadius: 8 }}>
                {options.map((o) => (
                  <button key={o.id} disabled={busy}
                          onClick={() => save({ employee: o.id })}
                          style={{ display: "flex", gap: 10, width: "100%",
                                   textAlign: "left", padding: "7px 11px",
                                   background: o.suggested
                                     ? "var(--sky-soft, #E8F1F8)"
                                     : "transparent",
                                   border: 0, borderBottom:
                                     "1px solid var(--line)",
                                   cursor: "pointer", fontFamily: "inherit",
                                   fontSize: 13 }}>
                    <span style={{ width: 84 }}>{o.emp_no}</span>
                    <span style={{ flex: 1 }}>{o.full_name}</span>
                    <span style={{ fontSize: 11.5, color: "var(--muted)" }}>
                      {o.suggested ? "name matches" : o.employment_type}
                    </span>
                  </button>
                ))}
                {options.length === 0 && (
                  <p style={{ fontSize: 13, color: "var(--muted)",
                              margin: 10 }}>
                    {q ? `Nobody matches “${q}”.` : "No employees to link."}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
          <Btn variant="primary" disabled={busy} onClick={() => save({})}>
            Save changes</Btn>
          <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
          {isSelf && (
            <span style={{ alignSelf: "center", fontSize: 12,
                           color: "var(--muted)" }}>
              This is your own account
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function L({ k, wide, children }) {
  return (
    <label style={{ ...fld, gridColumn: wide ? "1 / -1" : undefined }}>
      {k}{children}
    </label>
  );
}

const fld = { display: "flex", flexDirection: "column", gap: 3, fontSize: 12,
  color: "var(--muted)" };
