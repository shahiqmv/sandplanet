import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, ghostButton, inputStyle } from "./ui.jsx";

/* The discussion on a document (owner 2026-10-07): notes for the record,
 * and follow-ups put to people, which sit on their My Tasks until someone
 * answers in the thread or the person asked marks it answered. A thread
 * never blocks the workflow. Rules live in core/discussion.py.
 *
 * People are tagged in the text with @ — type "@" and pick from the list
 * (the document's own people first, then anyone by name). Whoever is tagged
 * is asked. It docks on the right as a panel, where most documents have
 * nothing (owner 2026-10-07); on a narrow screen it sits below.
 *
 * `threadKey` is "doc:<id>", "claim:<id>" or "payroll:<id>".
 */
const when = (iso) => {
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  const t = d.toLocaleString(undefined, { day: "2-digit", month: "short",
                                          hour: "2-digit", minute: "2-digit" });
  return days >= 1 ? `${t} · ${days}d ago` : t;
};

/** The body with its @names picked out. */
function Body({ text, names }) {
  if (!names.length) return <>{text}</>;
  const re = new RegExp(`(@(?:${names.map((n) =>
    n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")}))`, "g");
  return <>{text.split(re).map((part, i) => part.startsWith("@")
    && names.includes(part.slice(1))
    ? <span key={i} style={{ color: "var(--sp-navy)", fontWeight: 600,
                             background: "#e8eef3", borderRadius: 4,
                             padding: "0 3px" }}>{part}</span>
    : <span key={i}>{part}</span>)}</>;
}

/** Composer with @mentions: "@" opens the people list; a pick inserts the
 *  name and the person is asked when the message is sent. */
function Composer({ threadKey, onSent, busy, setBusy, setError }) {
  const [body, setBody] = useState("");
  const [tagged, setTagged] = useState([]);       // [{id, name}]
  const [people, setPeople] = useState([]);
  const [mention, setMention] = useState(null);   // {start, q} while typing
  const [cursor, setCursor] = useState(0);
  const taRef = useRef(null);

  // What is being typed after the last "@" before the caret.
  function readMention(text, caret) {
    const before = text.slice(0, caret);
    const at = before.lastIndexOf("@");
    if (at < 0 || (at > 0 && !/[\s(]/.test(before[at - 1]))) return null;
    const q = before.slice(at + 1);
    if (/\n/.test(q) || q.length > 40) return null;
    return { start: at, q };
  }
  function onChange(e) {
    const text = e.target.value;
    setBody(text);
    setMention(readMention(text, e.target.selectionStart));
  }
  useEffect(() => {
    if (!mention) { setPeople([]); return undefined; }
    const h = setTimeout(() => {
      api(`/discussion/${threadKey}/people?q=${encodeURIComponent(mention.q)}`)
        .then((r) => { setPeople(r.people || []); setCursor(0); })
        .catch(() => setPeople([]));
    }, 120);
    return () => clearTimeout(h);
  }, [threadKey, mention?.q]); // eslint-disable-line react-hooks/exhaustive-deps

  function pick(p) {
    const ta = taRef.current;
    const caret = ta ? ta.selectionStart : body.length;
    const next = body.slice(0, mention.start) + "@" + p.name + " "
      + body.slice(caret);
    setBody(next);
    setTagged((t) => t.some((x) => x.id === p.id) ? t : [...t, p]);
    setMention(null);
    const pos = mention.start + p.name.length + 2;
    requestAnimationFrame(() => { ta?.focus(); ta?.setSelectionRange(pos, pos); });
  }
  function onKeyDown(e) {
    if (mention && people.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => (c + 1) % people.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => (c - 1 + people.length) % people.length); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pick(people[cursor]); return; }
      if (e.key === "Escape") { setMention(null); return; }
    }
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
  }
  // only the people whose @name is still in the text are asked
  const asked = tagged.filter((p) => body.includes("@" + p.name));

  async function send() {
    if (!body.trim() || busy) return;
    setBusy(true); setError(null);
    try {
      const d = await api(`/discussion/${threadKey}`, { method: "POST",
        body: { body, to: asked.map((p) => p.id) } });
      setBody(""); setTagged([]); setMention(null);
      onSent(d);
    } catch (e) { setError(e.message); }
    setBusy(false);
  }

  return (
    <div style={{ borderTop: "1px solid var(--sp-border, #d5dde3)",
                  padding: "8px 10px 10px" }}>
      <div style={{ position: "relative" }}>
      <textarea ref={taRef} value={body} onChange={onChange} onKeyDown={onKeyDown}
        onClick={(e) => setMention(readMention(body, e.target.selectionStart))}
        placeholder="Write a note — or @name someone to ask them"
        style={{ ...inputStyle, width: "100%", minHeight: 64,
                 fontFamily: "inherit", resize: "vertical", display: "block" }} />
      {/* the list drops down under the box, never over the words being
          typed (owner 2026-10-07) */}
      {mention && people.length > 0 && (
        <div style={{ position: "absolute", left: 0, right: 0, top: "100%",
                      marginTop: 2,
                      background: "#fff", border: "1px solid var(--sp-border, #d5dde3)",
                      borderRadius: 8, boxShadow: "0 6px 20px rgba(15,30,45,.15)",
                      zIndex: 5, maxHeight: 200, overflowY: "auto" }}>
          {people.map((p, i) => (
            <div key={p.id} onMouseDown={(e) => { e.preventDefault(); pick(p); }}
                 style={{ padding: "6px 10px", cursor: "pointer", fontSize: 13,
                          background: i === cursor ? "#e8eef3" : "transparent" }}>
              <strong>{p.name}</strong>
              <span style={{ color: "var(--muted)", marginLeft: 6, fontSize: 12 }}>
                {p.role}</span>
            </div>))}
        </div>)}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
        <span style={{ fontSize: 12, color: asked.length ? "var(--sp-navy)" : "var(--muted)" }}>
          {asked.length
            ? `Asking ${asked.map((p) => p.name).join(", ")}`
            : "Type @ to tag someone · ⌘↵ sends"}</span>
        <Btn disabled={busy || !body.trim()} onClick={send}
             style={{ marginLeft: "auto" }}>
          {asked.length ? "Ask" : "Add note"}</Btn>
      </div>
    </div>
  );
}

function Thread({ d, me, onChanged, setError }) {
  async function answered(recipientId) {
    setError(null);
    try { onChanged(await api(`/discussion/recipients/${recipientId}/answered`,
                              { method: "POST" })); }
    catch (e) { setError(e.message); }
  }
  if (d.comments.length === 0) {
    return <p style={{ fontSize: 12.5, color: "var(--muted)", padding: "10px 12px" }}>
      Nothing yet. A note is for the record; @name someone and it sits on
      their My Tasks until it is answered.</p>;
  }
  return (
    <div style={{ padding: "6px 10px", overflowY: "auto", flex: "1 1 auto" }}>
      {d.comments.map((c) => (
        <div key={c.id}
             style={{ borderLeft: `3px solid ${c.open ? "#b45309"
                        : c.kind === "FOLLOWUP" ? "#1a7f37" : "#c9d3da"}`,
                      padding: "4px 8px", margin: "4px 0 8px",
                      background: c.open ? "#fff8ec" : "transparent" }}>
          <div style={{ fontSize: 11.5, color: "#3a4750" }}>
            <strong style={{ color: "var(--sp-navy)" }}>{c.author}</strong>
            {" "}· {when(c.created_at)}
            {c.status_at && <span style={{ color: "var(--muted)" }}>
              {" "}· {c.status_at.replace(/_/g, " ").toLowerCase()}</span>}
          </div>
          <div style={{ fontSize: 13.5, whiteSpace: "pre-wrap", margin: "2px 0" }}>
            <Body text={c.body} names={c.to.map((r) => r.name)} /></div>
          {c.to.length > 0 && (
            <div style={{ fontSize: 11.5, display: "flex", gap: 10, flexWrap: "wrap" }}>
              {c.to.map((r) => r.answered ? (
                <span key={r.recipient_id} style={{ color: "#1a7f37" }}>
                  ✓ {r.name}{r.answered_by && r.answered_by !== r.name
                    ? ` (by ${r.answered_by})` : ""}</span>
              ) : (
                <span key={r.recipient_id} style={{ color: "#b45309" }}>
                  ⏳ {r.name} — not yet answered
                  {(r.me || c.mine) && (
                    <button style={{ ...ghostButton, padding: "0 6px",
                                     fontSize: 11, marginLeft: 6 }}
                            onClick={() => answered(r.recipient_id)}>
                      mark answered</button>)}
                </span>))}
            </div>)}
        </div>))}
    </div>
  );
}

/** The panel: docked on the right on a wide screen, below on a narrow one,
 *  with a tab that shows the count and opens it. Remembers open/closed. */
export default function Discussion({ threadKey, me, inline = false }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem("planet:discussion") !== "closed"; }
    catch { return true; }
  });
  const [wide, setWide] = useState(() => window.innerWidth >= 1200);
  useEffect(() => {
    const onResize = () => setWide(window.innerWidth >= 1200);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const load = useCallback(() => api(`/discussion/${threadKey}`)
    .then(setD).catch((e) => setError(e.message)), [threadKey]);
  useEffect(() => { load(); }, [load]);
  function toggle() {
    const next = !open;
    setOpen(next);
    try { localStorage.setItem("planet:discussion", next ? "open" : "closed"); }
    catch { /* private mode */ }
  }
  if (!d) return null;

  const head = (
    <div style={{ display: "flex", alignItems: "center", gap: 8,
                  padding: "8px 10px", borderBottom: "1px solid var(--sp-border, #d5dde3)" }}>
      <strong style={{ color: "var(--sp-navy)", fontSize: 13.5 }}>
        💬 Discussion{d.comments.length ? ` · ${d.comments.length}` : ""}</strong>
      {d.open_count > 0 && (
        <Chip tone={d.open_for_me ? "alert" : "warn"}>
          {d.open_for_me ? `${d.open_for_me} waiting on you`
            : `${d.open_count} unanswered`}</Chip>)}
      <button onClick={toggle} title={wide ? "Hide the panel" : "Collapse"}
              style={{ ...ghostButton, marginLeft: "auto", padding: "1px 8px",
                       fontSize: 12 }}>{wide ? "✕" : "▾"}</button>
    </div>);
  const panelBody = (<>
    {head}
    {error && <p style={{ color: "#c0392b", fontSize: 12.5, padding: "4px 10px" }}>{error}</p>}
    <Thread d={d} me={me} onChanged={setD} setError={setError} />
    <Composer threadKey={threadKey} busy={busy} setBusy={setBusy}
              setError={setError} onSent={setD} />
  </>);

  if (wide && !inline) {
    // the tab on the right edge, and the panel it opens
    if (!open) {
      return (
        <button onClick={toggle} title="Open the discussion" data-discussion="tab"
          style={{ position: "fixed", right: 0, top: "40%", zIndex: 30,
                   writingMode: "vertical-rl", transform: "rotate(180deg)",
                   background: d.open_for_me ? "#b45309" : "var(--sp-navy)",
                   color: "#fff", border: "none", borderRadius: "0 8px 8px 0",
                   padding: "12px 6px", fontSize: 12.5, cursor: "pointer",
                   boxShadow: "0 2px 10px rgba(15,30,45,.25)" }}>
          💬 Discussion{d.comments.length ? ` · ${d.comments.length}` : ""}
          {d.open_for_me ? ` · ${d.open_for_me} for you` : ""}
        </button>);
    }
    return (
      <aside data-discussion="panel"
             style={{ position: "fixed", right: 0, top: 64, bottom: 0, width: 380,
                      zIndex: 30, background: "#fff",
                      borderLeft: "1px solid var(--sp-border, #d5dde3)",
                      boxShadow: "-4px 0 16px rgba(15,30,45,.08)",
                      display: "flex", flexDirection: "column" }}>
        {panelBody}
      </aside>);
  }
  // narrow: inline, collapsible, below the document
  return (
    <section data-discussion="inline"
             style={{ marginTop: 14, border: "1px solid var(--sp-border, #d5dde3)",
                      borderRadius: 8, display: "flex", flexDirection: "column" }}>
      {open ? panelBody : (
        <div onClick={toggle} style={{ padding: "8px 10px", cursor: "pointer",
                                       fontSize: 13.5, color: "var(--sp-navy)" }}>
          <strong>💬 Discussion{d.comments.length ? ` · ${d.comments.length}` : ""}</strong>
          {d.open_count > 0 && <span style={{ marginLeft: 8 }}>
            <Chip tone={d.open_for_me ? "alert" : "warn"}>
              {d.open_for_me ? `${d.open_for_me} waiting on you`
                : `${d.open_count} unanswered`}</Chip></span>}
          <span style={{ float: "right" }}>▸</span>
        </div>)}
    </section>
  );
}
