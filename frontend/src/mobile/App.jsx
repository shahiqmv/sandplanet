// Planet Mobile — app shell: auth gate, role-based tabs, detail navigation,
// action stamp + toast, install/notify prompts, offline awareness.
import React, { useEffect, useMemo, useState } from "react";
import { api, getToken, setToken } from "./api.js";
import {
  disablePush,
  enablePush,
  isSubscribed,
  pushPermission,
  pushSupported,
} from "./push.js";
import {
  Alerts,
  DocumentDetail,
  MyRequests,
  PendingInbox,
  Timeline,
} from "./screens.jsx";
import { RingMark, Spinner, Stamp, Toast } from "./ui.jsx";

const APPROVER_ROLES = new Set(["PM", "ADMIN", "DIRECTOR", "SIGNATORY"]);

// A push tap deep-links to /m/track/<ref>; pull the ref back out.
function parseTrack(path) {
  const m = /^\/m\/track\/(.+)$/.exec(path || "");
  return m ? decodeURIComponent(m[1]) : null;
}

function isIos() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}
function isStandalone() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(true);
  const [tab, setTab] = useState(null);
  // Navigation stack of {mode:'doc'|'timeline', ref}; last entry is on screen.
  // A stack (not a single value) lets a tapped voucher line drill into its
  // source doc and Back return to the voucher.
  const [nav, setNav] = useState([]);
  const detail = nav[nav.length - 1] || null;
  const openDetail = (d) => setNav((n) => [...n, d]);
  const goBack = () => setNav((n) => n.slice(0, -1));
  const [toast, setToast] = useState(null);
  const [stamp, setStamp] = useState(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [refreshKey, setRefreshKey] = useState(0);
  const [counts, setCounts] = useState({ pending: 0, alerts: 0 });

  // Restore session from the stored device token.
  useEffect(() => {
    (async () => {
      if (getToken()) {
        try {
          setUser(await api.me());
        } catch {
          setToken("");
        }
      }
      setBooting(false);
    })();
  }, []);

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  // Cold-open from a push tap (/m/track/<ref>): jump straight to that timeline.
  useEffect(() => {
    if (!user) return;
    const ref = parseTrack(window.location.pathname);
    if (ref) {
      setNav([{ mode: "timeline", ref }]);
      window.history.replaceState({}, "", "/m/");
    }
  }, [user]);

  // Warm app: the service worker relays a notification tap.
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const onMsg = (e) => {
      const url = e.data && e.data.url;
      if (!url) return;
      const ref = parseTrack(new URL(url, window.location.origin).pathname);
      if (ref) setNav([{ mode: "timeline", ref }]);
    };
    navigator.serviceWorker.addEventListener("message", onMsg);
    return () => navigator.serviceWorker.removeEventListener("message", onMsg);
  }, []);

  const tabs = useMemo(() => {
    if (!user) return [];
    const t = [];
    if (APPROVER_ROLES.has(user.role)) {
      t.push({ key: "pending", label: "Pending" });
    }
    t.push({ key: "requests", label: "Requests" });
    t.push({ key: "alerts", label: "Alerts" });
    return t;
  }, [user]);

  useEffect(() => {
    if (tabs.length && !tabs.find((t) => t.key === tab))
      setTab(tabs[0].key);
  }, [tabs]); // eslint-disable-line react-hooks/exhaustive-deps

  function showToast(t) {
    setToast(t);
    setTimeout(() => setToast(null), 2600);
  }

  function afterAction({ text, tone }) {
    setStamp({ text, tone });
    setTimeout(() => {
      setStamp(null);
      setNav([]);
      setRefreshKey((k) => k + 1);
      showToast({ msg: `${text} — done.`, tone: tone || "ok" });
    }, 900);
  }

  async function onSignedIn(u) {
    setUser(u);
    setBooting(false);
  }

  async function onLogout() {
    try {
      await disablePush();
      await api.logout();
    } catch {
      /* best effort */
    }
    setToken("");
    setUser(null);
    setNav([]);
    setTab(null);
  }

  if (booting) {
    return (
      <div className="app">
        <Spinner />
      </div>
    );
  }
  if (!user) return <SignIn onSignedIn={onSignedIn} />;

  return (
    <div className="app">
      {detail ? (
        <div className="topbar">
          <button className="back" onClick={goBack}>
            ← Back
          </button>
          <div className="topbar-row">
            <span className="brand">
              {detail.mode === "timeline" ? "Tracking" : "Review"}
            </span>
          </div>
        </div>
      ) : (
        <div className="topbar">
          <div className="topbar-row">
            <span className="brand">
              Planet <small>Mobile</small>
            </span>
            <span className="whoami">
              {user.full_name}
              <br />
              {user.role_label}
              {" · "}
              <button
                className="btn ghost"
                style={{ color: "#cfe6f5", padding: 0 }}
                onClick={onLogout}
              >
                Sign out
              </button>
            </span>
          </div>
          <div className="tabs">
            {tabs.map((t) => (
              <button
                key={t.key}
                className={`tab ${tab === t.key ? "active" : ""}`}
                onClick={() => setTab(t.key)}
              >
                {t.label}
                {t.key === "pending" && counts.pending > 0 && (
                  <span className="count">{counts.pending}</span>
                )}
                {t.key === "alerts" && counts.alerts > 0 && (
                  <span className="count">{counts.alerts}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {detail ? (
        detail.mode === "timeline" ? (
          <Timeline key={detail.ref} docRef={detail.ref} />
        ) : (
          <DocumentDetail
            key={detail.ref}
            docRef={detail.ref}
            online={online}
            onActioned={afterAction}
            onToast={showToast}
            onOpen={openDetail}
          />
        )
      ) : (
        <div className="scroll">
          {!online && (
            <div className="stale-bar">You're offline — showing last update.</div>
          )}
          <NotifyPrompt onToast={showToast} />
          {tab === "pending" && (
            <PendingInbox
              key={`pending-${refreshKey}`}
              onOpen={openDetail}
              onCount={(n) => setCounts((c) => ({ ...c, pending: n }))}
            />
          )}
          {tab === "requests" && (
            <MyRequests key={`requests-${refreshKey}`} onOpen={openDetail} />
          )}
          {tab === "alerts" && (
            <Alerts
              key={`alerts-${refreshKey}`}
              onOpen={openDetail}
              onCount={(n) => setCounts((c) => ({ ...c, alerts: n }))}
            />
          )}
        </div>
      )}

      {stamp && <Stamp text={stamp.text} tone={stamp.tone} />}
      <Toast toast={toast} />
    </div>
  );
}

// ---- Sign in ------------------------------------------------------------
function SignIn({ onSignedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const { token, user } = await api.login(username.trim(), password);
      setToken(token);
      onSignedIn(user);
    } catch (e2) {
      setErr(e2.message);
      setBusy(false);
    }
  }

  return (
    <form className="signin" onSubmit={submit}>
      <div className="mark">
        <RingMark size={72} />
      </div>
      <h1>Planet</h1>
      <p className="tag">Approvals &amp; request tracking</p>
      {err && <div className="err">{err}</div>}
      <div className="field">
        <label>Username</label>
        <input
          autoCapitalize="none"
          autoCorrect="off"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
        />
      </div>
      <div className="field">
        <label>Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
      </div>
      <button className="btn" type="submit" disabled={busy || !username || !password}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
      {isIos() && !isStandalone() && (
        <p className="tag" style={{ marginTop: 22 }}>
          On iPhone: tap <strong>Share → Add to Home Screen</strong> to install
          Planet and receive notifications.
        </p>
      )}
    </form>
  );
}

// ---- Enable-notifications prompt (dismissible) --------------------------
const NOTIFY_ENABLED = "planet.mobile.notify.enabled";
const NOTIFY_DISMISSED = "planet.mobile.notify.dismissed";

function NotifyPrompt({ onToast }) {
  // Start hidden; only reveal after confirming (a) the server actually has web
  // push configured, and (b) this device is NOT already subscribed. Gating on
  // the server's vapid-key means we never nag when push isn't set up, and
  // basing "already on" on a real subscription (not the flaky
  // Notification.permission read) stops it re-appearing once enabled.
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      if (
        !pushSupported() ||
        localStorage.getItem(NOTIFY_ENABLED) === "1" ||
        localStorage.getItem(NOTIFY_DISMISSED) === "1" ||
        pushPermission() === "denied" ||
        (isIos() && !isStandalone()) // iOS push only works installed
      ) {
        return;
      }
      if (await isSubscribed()) {
        localStorage.setItem(NOTIFY_ENABLED, "1"); // already on — never nag
        return;
      }
      // Don't prompt at all unless the server can actually deliver push.
      const vk = await api.vapidKey().catch(() => ({ enabled: false }));
      if (!vk || !vk.enabled) return;
      if (alive) setShow(true);
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (!show) return null;

  // Any outcome except a transient one stops the auto-prompt for good, so the
  // card never nags on every launch.
  async function enable() {
    setBusy(true);
    try {
      const { ok, reason } = await enablePush();
      if (ok) {
        localStorage.setItem(NOTIFY_ENABLED, "1");
        setShow(false);
        onToast && onToast({ msg: "Notifications on.", tone: "ok" });
      } else if (reason === "default") {
        // They dismissed the OS dialog without choosing — let them retry.
        setBusy(false);
      } else {
        // denied / server-off / unsupported — won't succeed by re-asking.
        localStorage.setItem(NOTIFY_DISMISSED, "1");
        setShow(false);
        onToast &&
          onToast({
            msg:
              reason === "denied"
                ? "Blocked — turn on notifications for Planet in your phone settings."
                : "Notifications aren't available on this device yet.",
            tone: "alert",
          });
      }
    } catch {
      setBusy(false);
    }
  }
  function dismiss() {
    localStorage.setItem(NOTIFY_DISMISSED, "1");
    setShow(false);
  }

  return (
    <div className="prompt">
      <h4>Turn on notifications</h4>
      <p>Get a push when something needs you, or a document you raised moves.</p>
      <div className="row">
        <button className="btn secondary" onClick={dismiss} disabled={busy}>
          Not now
        </button>
        <button className="btn" onClick={enable} disabled={busy}>
          {busy ? "Enabling…" : "Enable"}
        </button>
      </div>
    </div>
  );
}
