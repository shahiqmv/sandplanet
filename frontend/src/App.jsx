import { useEffect, useState } from "react";
import { api } from "./api.js";

const card = {
  background: "#fff",
  border: "1px solid var(--sp-border)",
  borderRadius: 8,
  padding: 24,
  marginBottom: 24,
};

const STATUS_COLORS = {
  ACTIVE: { bg: "#1a7f37", fg: "#fff" },
  AWARDED: { bg: "var(--sp-sky)", fg: "#fff" },
  ON_HOLD: { bg: "#b35900", fg: "#fff" },
  CLOSED: { bg: "#5a6b78", fg: "#fff" },
};

function StatusChip({ status }) {
  const c = STATUS_COLORS[status] || STATUS_COLORS.CLOSED;
  return (
    <span
      style={{
        fontSize: 12,
        padding: "2px 10px",
        borderRadius: 12,
        background: c.bg,
        color: c.fg,
        whiteSpace: "nowrap",
      }}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api("/auth/login", {
        method: "POST",
        body: { username, password },
      });
      onLogin(me);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 380, margin: "10vh auto", padding: "0 16px" }}>
      <form onSubmit={submit} style={card}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)" }}>Sign in</h2>
        <label style={{ display: "block", fontSize: 13, marginBottom: 4 }}>
          Username
        </label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
          style={inputStyle}
        />
        <label style={{ display: "block", fontSize: 13, margin: "12px 0 4px" }}>
          Password
        </label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={inputStyle}
        />
        {error && (
          <p style={{ color: "#c0392b", fontSize: 13, margin: "12px 0 0" }}>
            {error}
          </p>
        )}
        <button type="submit" disabled={busy} style={buttonStyle}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

const inputStyle = {
  width: "100%",
  padding: "8px 10px",
  border: "1px solid var(--sp-border)",
  borderRadius: 6,
  fontSize: 14,
};

const buttonStyle = {
  marginTop: 16,
  width: "100%",
  padding: "9px 0",
  background: "var(--sp-navy)",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  fontSize: 14,
  cursor: "pointer",
};

function Field({ label, value }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div style={{ padding: "6px 0", borderTop: "1px solid var(--sp-border)" }}>
      <span style={{ color: "#5a6b78", fontSize: 12, display: "block" }}>
        {label}
      </span>
      <span style={{ fontSize: 14 }}>{String(value)}</span>
    </div>
  );
}

function SiteDetail({ site, onBack, showBack }) {
  return (
    <div>
      {showBack && (
        <button
          onClick={onBack}
          style={{
            ...buttonStyle,
            width: "auto",
            padding: "6px 14px",
            marginTop: 0,
            marginBottom: 16,
            background: "#fff",
            color: "var(--sp-navy)",
            border: "1px solid var(--sp-border)",
          }}
        >
          ← All sites
        </button>
      )}
      <section style={card}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
          }}
        >
          <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
            {site.code} — {site.name}
          </h2>
          <StatusChip status={site.status} />
        </div>
        <div style={{ marginTop: 16 }}>
          <Field label="Scope" value={site.scope} />
          <Field
            label="Contract value"
            value={
              site.contract_value != null
                ? `${site.currency} ${Number(site.contract_value).toLocaleString()}`
                : undefined
            }
          />
          <Field label="Project PM" value={site.current_pm?.full_name} />
          <Field label="Client" value={site.client_name} />
          <Field label="Consultant" value={site.consultant_name} />
          <Field label="Start date" value={site.start_date} />
          <Field label="Planned completion" value={site.planned_completion} />
          <Field
            label="Working hours"
            value={`${site.working_hours_from} – ${site.working_hours_to}`}
          />
        </div>
      </section>
      <section style={{ ...card, color: "#5a6b78", fontSize: 13 }}>
        Site documents (DPR, TWS, IR, MAR, MR, GRN) arrive with milestone M2.
      </section>
    </div>
  );
}

function SiteList({ sites, onOpen }) {
  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Sites & projects
      </h2>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <tbody>
          {sites.map((s) => (
            <tr
              key={s.id}
              onClick={() => onOpen(s)}
              style={{
                borderTop: "1px solid var(--sp-border)",
                cursor: "pointer",
              }}
            >
              <td
                style={{
                  padding: "10px 8px 10px 0",
                  fontWeight: 600,
                  color: "var(--sp-navy)",
                  width: 56,
                }}
              >
                {s.code}
              </td>
              <td style={{ padding: 10 }}>
                {s.name}
                {s.is_head_office ? " (Head Office)" : ""}
              </td>
              <td style={{ padding: 10, textAlign: "right" }}>
                <StatusChip status={s.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function App() {
  const [me, setMe] = useState(null); // null = loading
  const [sites, setSites] = useState([]);
  const [openSite, setOpenSite] = useState(null);

  useEffect(() => {
    api("/auth/me").then(setMe).catch(() => setMe({ authenticated: false }));
  }, []);

  useEffect(() => {
    if (!me?.authenticated) return;
    api("/sites").then((list) => {
      setSites(list);
      if (me.landing_site_id) {
        setOpenSite(list.find((s) => s.id === me.landing_site_id) || null);
      }
    });
  }, [me]);

  async function logoutUser() {
    await api("/auth/logout", { method: "POST" });
    setMe({ authenticated: false });
    setSites([]);
    setOpenSite(null);
  }

  if (me === null) return null;

  return (
    <div>
      <header
        style={{
          background: "var(--sp-navy)",
          color: "#fff",
          padding: "14px 28px",
          borderBottom: "4px solid var(--sp-sky)",
          display: "flex",
          alignItems: "baseline",
          gap: 12,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 20, letterSpacing: 0.5 }}>
          SAND PLANET
        </h1>
        <span style={{ color: "var(--sp-sky)", fontSize: 14 }}>
          Site Documents
        </span>
        {me.authenticated && (
          <span style={{ marginLeft: "auto", fontSize: 13 }}>
            {me.full_name} · {me.role.replace(/_/g, " ")}
            <button
              onClick={logoutUser}
              style={{
                marginLeft: 14,
                background: "transparent",
                color: "var(--sp-sky)",
                border: "1px solid var(--sp-sky)",
                borderRadius: 6,
                padding: "3px 10px",
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              Sign out
            </button>
          </span>
        )}
      </header>

      {!me.authenticated ? (
        <Login onLogin={setMe} />
      ) : (
        <main style={{ maxWidth: 760, margin: "32px auto", padding: "0 16px" }}>
          {openSite ? (
            <SiteDetail
              site={openSite}
              onBack={() => setOpenSite(null)}
              showBack={!me.landing_site_id || sites.length > 1}
            />
          ) : (
            <SiteList sites={sites} onOpen={setOpenSite} />
          )}
        </main>
      )}
    </div>
  );
}
