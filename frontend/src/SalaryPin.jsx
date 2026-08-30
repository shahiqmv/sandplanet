import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { Btn, card, inputStyle } from "./ui.jsx";

// The PIN in front of a person's own pay, and the window that closes itself.
//
// The countdown here is a courtesy, not the control: the server holds the
// expiry and refuses the data on its own clock, so a paused tab or a fiddled
// timer buys nothing (owner 2026-08-30).
export function useSalaryLock() {
  const [pin, setPin] = useState(null);      // {has_pin, seconds_left, ...}
  const [left, setLeft] = useState(0);
  const tick = useRef(null);

  const refresh = useCallback(() => api("/me/pin").then((s) => {
    setPin(s);
    setLeft(s.seconds_left || 0);
    return s;
  }).catch(() => null), []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    clearInterval(tick.current);
    if (left <= 0) return undefined;
    tick.current = setInterval(() => setLeft((n) => Math.max(n - 1, 0)), 1000);
    return () => clearInterval(tick.current);
  }, [left > 0]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Pay is hidden by default, so "locked" no longer depends on whether a
  // PIN exists — only on whether the window is open (owner 2026-08-30).
  const locked = left <= 0;
  return { pin, left, locked, refresh, setLeft };
}

export function PinGate({ lock, onOpened }) {
  const has = !!lock.pin?.has_pin;
  const [entry, setEntry] = useState("");
  const [confirm, setConfirm] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const mins = Math.round((lock.pin?.window_seconds || 180) / 60);

  async function submit(e) {
    e?.preventDefault();
    setError(null);
    if (!has && entry !== confirm) {
      setError("The two PINs don't match."); return;
    }
    setBusy(true);
    try {
      if (has) {
        const r = await api("/me/pin/unlock",
                            { method: "POST", body: { pin: entry } });
        lock.setLeft(r.seconds_left);
      } else {
        const r = await api("/me/pin/set",
                            { method: "POST",
                              body: { pin: entry, password } });
        await lock.refresh();
        lock.setLeft(r.window_seconds);
      }
      setEntry(""); setConfirm(""); setPassword("");
      onOpened?.();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} style={{ padding: "18px 0", maxWidth: 340 }}>
      <p style={{ fontSize: 13.5, margin: "0 0 4px", fontWeight: 600,
                  color: "var(--sp-navy)" }}>
        {has ? "Your pay is hidden" : "Create a PIN to see your pay"}
      </p>
      <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 12px" }}>
        {has
          ? `Enter your PIN to show it for ${mins} minutes.`
          : "Your pay stays hidden until you set a PIN. It stops anyone who "
            + "picks up this device while you are signed in — it is not your "
            + "sign-in password. 4 to 6 digits."}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8,
                    maxWidth: 220 }}>
        <input value={entry} onChange={(e) => setEntry(e.target.value)}
               inputMode="numeric" type="password" maxLength={6}
               autoComplete={has ? "off" : "new-password"}
               placeholder={has ? "PIN" : "Choose a PIN"}
               style={{ ...inputStyle, letterSpacing: 4, fontSize: 17 }} />
        {!has && (
          <>
            <input value={confirm}
                   onChange={(e) => setConfirm(e.target.value)}
                   inputMode="numeric" type="password" maxLength={6}
                   autoComplete="new-password" placeholder="Repeat the PIN"
                   style={{ ...inputStyle, letterSpacing: 4, fontSize: 17 }} />
            <input value={password}
                   onChange={(e) => setPassword(e.target.value)}
                   type="password" autoComplete="current-password"
                   placeholder="Your sign-in password" style={inputStyle} />
          </>
        )}
      </div>
      <div style={{ marginTop: 12 }}>
        <Btn variant="primary" type="submit"
             disabled={busy || entry.length < 4 || (!has && !password)}>
          {has ? "Show my pay" : "Create PIN and show my pay"}</Btn>
      </div>
      {error && (
        <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>
      )}
    </form>
  );
}

export function LockBar({ lock, onLocked }) {
  if (!lock.pin?.has_pin || lock.left <= 0) return null;
  const m = Math.floor(lock.left / 60);
  const s = String(lock.left % 60).padStart(2, "0");
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10,
                  padding: "6px 12px", borderRadius: 8, marginBottom: 12,
                  background: "var(--sky-soft, #E8F1F8)", fontSize: 12.5 }}>
      <span>Your pay hides again in <b>{m}:{s}</b></span>
      <Btn variant="ghost" style={{ marginLeft: "auto", fontSize: 12,
                                    padding: "2px 10px" }}
           onClick={() => api("/me/pin/lock", { method: "POST" })
             .then(() => { lock.setLeft(0); onLocked?.(); })}>
        Hide now</Btn>
    </div>
  );
}

export function PinSettings({ lock, onChanged }) {
  const [open, setOpen] = useState(false);
  const [pin, setPin] = useState("");
  const [confirm, setConfirm] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    if (pin !== confirm) { setError("The two PINs don't match."); return; }
    setBusy(true); setError(null);
    try {
      await api("/me/pin/set", { method: "POST", body: { pin, password } });
      setOpen(false); setPin(""); setConfirm(""); setPassword("");
      await lock.refresh();
      onChanged?.();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  if (!open) {
    return (
      <div style={{ marginTop: 18, paddingTop: 12,
                    borderTop: "1px solid var(--line)" }}>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          A PIN hides your pay whenever this page is left open.
        </span>
        <Btn variant="ghost" style={{ fontSize: 12, padding: "3px 10px",
                                      marginLeft: 8 }}
             onClick={() => setOpen(true)}>Change PIN</Btn>
      </div>
    );
  }

  return (
    <div style={{ ...card, marginTop: 16, maxWidth: 360 }}>
      <b style={{ fontSize: 13.5, color: "var(--sp-navy)" }}>Change your PIN</b>
      {/* The account password, not the old PIN — so forgetting the PIN does
          not need an admin. */}
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "6px 0 10px" }}>
        Forgotten it? Setting a new one needs your sign-in password, not the
        old PIN.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <input value={pin} onChange={(e) => setPin(e.target.value)}
               type="password" inputMode="numeric" maxLength={6}
               placeholder="New PIN" autoComplete="new-password"
               style={inputStyle} />
        <input value={confirm} onChange={(e) => setConfirm(e.target.value)}
               type="password" inputMode="numeric" maxLength={6}
               placeholder="Repeat the PIN" autoComplete="new-password"
               style={inputStyle} />
        <input value={password} onChange={(e) => setPassword(e.target.value)}
               type="password" placeholder="Your sign-in password"
               autoComplete="current-password" style={inputStyle} />
      </div>
      {error && (
        <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <Btn variant="primary" disabled={busy || !password || pin.length < 4}
             onClick={save}>Save PIN</Btn>
        <Btn variant="ghost" onClick={() => { setOpen(false);
                                              setError(null); }}>
          Cancel</Btn>
      </div>
    </div>
  );
}
