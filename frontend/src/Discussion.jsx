import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, SectionTitle, ghostButton, inputStyle } from "./ui.jsx";

/* The discussion on a document (owner 2026-10-07): notes for the record,
 * and follow-ups put to people, which sit on their My Tasks until someone
 * answers in the thread or the person asked marks it answered. A thread
 * never blocks the workflow. Rules live in core/discussion.py.
 *
 * `threadKey` is "doc:<id>", "claim:<id>" or "payroll:<id>".
 */
const when = (iso) => {
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  const t = d.toLocaleString(undefined, { day: "2-digit", month: "short",
                                          hour: "2-digit", minute: "2-digit" });
  return days >= 1 ? `${t} · ${days} day${days === 1 ? "" : "s"} ago` : t;
};

export default function Discussion({ threadKey, me, compact, focus }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [body, setBody] = useState("");
  const [to, setTo] = useState([]);            // [{id, name, role}]
  const [q, setQ] = useState("");
  const [people, setPeople] = useState([]);
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(!compact);
  const boxRef = useRef(null);

  const load = useCallback(() => api(`/discussion/${threadKey}`)
    .then(setD).catch((e) => setError(e.message)), [threadKey]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (focus && boxRef.current) boxRef.current.scrollIntoView({ block: "center" });
  }, [focus, d]);

  // the picker: the document's own people first, then anyone by name
  useEffect(() => {
    const h = setTimeout(() => {
      api(`/discussion/${threadKey}/people?q=${encodeURIComponent(q)}`)
        .then((r) => setPeople(r.people || [])).catch(() => setPeople([]));
    }, 180);
    return () => clearTimeout(h);
  }, [threadKey, q]);

  async function send() {
    if (!body.trim()) return;
    setBusy(true); setError(null);
    try {
      setD(await api(`/discussion/${threadKey}`, { method: "POST",
        body: { body, to: to.map((p) => p.id) } }));
      setBody(""); setTo([]); setQ("");
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  async function answered(recipientId) {
    setError(null);
    try { setD(await api(`/discussion/recipients/${recipientId}/answered`,
                         { method: "POST" })); }
    catch (e) { setError(e.message); }
  }

  if (!d) return error ? <p style={{ color: "#c0392b", fontSize: 12.5 }}>{error}</p> : null;
  const rows = showAll ? d.comments : d.comments.slice(-3);
  const chosen = new Set(to.map((p) => p.id));

  return (
    <div ref={boxRef} style={{ marginTop: 14 }}>
      <SectionTitle>
        Discussion{d.comments.length ? ` · ${d.comments.length}` : ""}
        {d.open_count > 0 && (
          <span style={{ marginLeft: 8 }}>
            <Chip tone={d.open_for_me ? "alert" : "warn"}>
              {d.open_for_me ? `${d.open_for_me} waiting on you`
                : `${d.open_count} unanswered`}</Chip></span>)}
      </SectionTitle>
      {error && <p style={{ color: "#c0392b", fontSize: 12.5 }}>{error}</p>}

      {d.comments.length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "2px 0 8px" }}>
          Nothing yet. A note is for the record; put it to someone and it
          sits on their My Tasks until it is answered.</p>)}
      {!showAll && d.comments.length > 3 && (
        <button style={{ ...ghostButton, padding: "2px 10px", fontSize: 12,
                         marginBottom: 6 }} onClick={() => setShowAll(true)}>
          Show all {d.comments.length}</button>)}

      {rows.map((c) => (
        <div key={c.id}
             style={{ borderLeft: `3px solid ${c.open ? "#b45309"
                        : c.kind === "FOLLOWUP" ? "#1a7f37" : "#c9d3da"}`,
                      padding: "4px 10px", margin: "4px 0 8px",
                      background: c.open ? "#fff8ec" : "transparent" }}>
          <div style={{ fontSize: 12, color: "#3a4750" }}>
            <strong style={{ color: "var(--sp-navy)" }}>{c.author}</strong>
            {" "}· {when(c.created_at)}
            {c.status_at && <span style={{ color: "var(--muted)" }}>
              {" "}· {c.status_at.replace(/_/g, " ").toLowerCase()}</span>}
            {c.to.length > 0 && (
              <span> · to {c.to.map((r) => r.name).join(", ")}</span>)}
          </div>
          <div style={{ fontSize: 13.5, whiteSpace: "pre-wrap", margin: "2px 0" }}>
            {c.body}</div>
          {c.to.length > 0 && (
            <div style={{ fontSize: 11.5, display: "flex", gap: 10,
                          flexWrap: "wrap" }}>
              {c.to.map((r) => r.answered ? (
                <span key={r.recipient_id} style={{ color: "#1a7f37" }}>
                  ✓ {r.name}{r.answered_by && r.answered_by !== r.name
                    ? ` (answered by ${r.answered_by})` : ""}</span>
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

      {/* write */}
      <div style={{ border: "1px solid var(--sp-border, #d5dde3)",
                    borderRadius: 8, padding: 8, marginTop: 6 }}>
        <textarea value={body} onChange={(e) => setBody(e.target.value)}
          placeholder={to.length ? "Your question or request…"
            : "A note for the record — or pick who to ask below"}
          style={{ ...inputStyle, width: "100%", minHeight: 56,
                   fontFamily: "inherit", resize: "vertical" }} />
        <div style={{ display: "flex", gap: 6, alignItems: "center",
                      flexWrap: "wrap", marginTop: 6 }}>
          <span style={{ fontSize: 12, color: "var(--muted)" }}>Put to:</span>
          {to.map((p) => (
            <span key={p.id} style={{ fontSize: 12, background: "#e8eef3",
                                      borderRadius: 12, padding: "2px 8px" }}>
              {p.name}
              <button style={{ border: "none", background: "none",
                               cursor: "pointer", padding: "0 0 0 4px" }}
                      onClick={() => setTo(to.filter((x) => x.id !== p.id))}>
                ✕</button></span>))}
          <input list={`ppl-${threadKey}`} value={q} placeholder="name…"
            onChange={(e) => {
              const v = e.target.value;
              const hit = people.find((p) => p.name === v);
              if (hit && !chosen.has(hit.id)) { setTo([...to, hit]); setQ(""); }
              else setQ(v);
            }}
            style={{ ...inputStyle, width: 180, padding: "3px 8px",
                     fontSize: 12.5 }} />
          <datalist id={`ppl-${threadKey}`}>
            {people.filter((p) => !chosen.has(p.id)).map((p) => (
              <option key={p.id} value={p.name}>{p.role}</option>))}
          </datalist>
          <Btn disabled={busy || !body.trim()} onClick={send}
               style={{ marginLeft: "auto" }}>
            {to.length ? "Ask" : "Add note"}</Btn>
        </div>
      </div>
    </div>
  );
}
