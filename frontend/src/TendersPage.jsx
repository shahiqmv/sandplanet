import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import BoqPanel from "./BoqPanel.jsx";
import { Btn, Chip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

/* Tenders & offers — the work before there is a project (owner 2026-09-08).
 *
 * BOQs are priced outside the system and used to arrive only once won, so
 * there was no record of what was submitted, under what reference, or what
 * came of it. The rule this screen exists to show: a revision is internal
 * working until it is ISSUED, and an issued one is a submission that stays on
 * the record whatever is priced after it.
 */
const MANAGE = ["QS", "DIRECTOR", "ADMIN"];
const TONE = { DRAFT: "info", SUBMITTED: "warn", AWARDED: "ok",
               LOST: "alert", WITHDRAWN: "info", CANCELLED: "info" };
const LABEL = { DRAFT: "Pricing", SUBMITTED: "Submitted", AWARDED: "Awarded",
                LOST: "Lost", WITHDRAWN: "Withdrawn" };
const money = (v, ccy) => (v == null ? "—"
  : `${ccy} ${Number(v).toLocaleString(undefined,
      { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const day = (d) => (d ? String(d).slice(0, 10) : "—");

export default function TendersPage({ me, sites }) {
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);      // tender id being viewed
  const [adding, setAdding] = useState(false);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [error, setError] = useState(null);
  const can = MANAGE.includes(me.role);

  const load = () => { api(`/tenders${onlyOpen ? "?open=1" : ""}`)
    .then(setRows).catch((e) => setError(e.message)); };
  // NOT useEffect(load, …) when load returns a promise: React treats an
  // effect's return value as the cleanup function and calls it on unmount,
  // so closing the page threw "n is not a function" and took the whole app
  // down with it (owner 2026-09-09). Same trap as AgreementsPanel.
  useEffect(load, [onlyOpen]);

  const live = (rows || []).filter((r) =>
    ["DRAFT", "SUBMITTED"].includes(r.status));
  const outstanding = live.reduce((n, r) =>
    n + (r.status === "SUBMITTED" ? 1 : 0), 0);

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 4 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Tenders &amp; offers</h2>
        <label style={{ fontSize: 12.5, display: "flex", gap: 5,
                        alignItems: "center", marginLeft: "auto" }}>
          <input type="checkbox" checked={onlyOpen}
                 onChange={(e) => setOnlyOpen(e.target.checked)} />
          Only live
        </label>
        {can && !adding && (
          <button style={buttonStyle} onClick={() => setAdding(true)}>
            ➕ Open an enquiry</button>)}
      </div>
      <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "0 0 12px" }}>
        {live.length} live · {outstanding} awaiting the client's decision. A
        revision is internal until it is issued — issuing one is the
        submission, and it stays on the record whatever is priced after it.
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {adding && can && (
        <NewTender sites={sites} onDone={(ok) => {
          setAdding(false); if (ok) load(); }} />)}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Reference</th><th style={th}>Client / scope</th>
            <th style={th}>Site</th><th style={th}>Due</th>
            <th style={{ ...th, textAlign: "right" }}>Submitted</th>
            <th style={{ ...th, textAlign: "right" }}>Awarded</th>
            <th style={th}>State</th>
          </tr></thead>
          <tbody>
            {(rows || []).map((r) => (
              <tr key={r.id} onClick={() => setOpen(r.id)}
                  style={{ cursor: "pointer" }}>
                <td style={{ ...td, fontFamily: "var(--font-mono)",
                             fontSize: 12, whiteSpace: "nowrap" }}>
                  {r.ref}
                  <div style={{ color: "var(--muted)" }}>
                    {r.rev_label}{r.submit_our_format ? "" : " · their bill"}</div>
                </td>
                <td style={td}><strong>{r.client_name}</strong>
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                    {r.title}</div></td>
                <td style={td}>{r.site_code}</td>
                <td style={td}>{day(r.due_date)}</td>
                <td style={{ ...td, textAlign: "right",
                             fontVariantNumeric: "tabular-nums" }}>
                  {money(r.value_submitted, r.currency)}</td>
                <td style={{ ...td, textAlign: "right",
                             fontVariantNumeric: "tabular-nums" }}>
                  {money(r.value_awarded, r.currency)}</td>
                <td style={td}>
                  <Chip tone={TONE[r.status] || "info"}>
                    {LABEL[r.status] || r.status}</Chip>
                  {r.awarded_project && (
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>
                      {r.awarded_project}</div>)}
                </td>
              </tr>))}
            {rows && rows.length === 0 && (
              <tr><td style={td} colSpan={7}>
                No tenders yet.{can ? " Open an enquiry above." : ""}</td></tr>)}
          </tbody>
        </table>
      </div>

      {open && <TenderDetail id={open} me={me}
                             onClose={() => { setOpen(null); load(); }} />}
    </section>
  );
}

function NewTender({ sites, onDone }) {
  const [f, setF] = useState({ site_id: "", client_name: "", title: "",
                               enquiry_date: "", due_date: "",
                               submit_our_format: true, currency: "USD",
                               scope: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f,
    [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function save() {
    setBusy(true); setErr(null);
    try { await api("/tenders", { method: "POST", body: f }); onDone(true); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div style={{ border: "1px solid var(--sp-border, #d8e1e8)",
                  borderRadius: 8, padding: 12, marginBottom: 14,
                  display: "flex", gap: 8, flexWrap: "wrap",
                  alignItems: "flex-end" }}>
      <select value={f.site_id} onChange={set("site_id")}
              style={{ ...inputStyle, width: 150 }}>
        <option value="">Site…</option>
        {(sites || []).map((s) => (
          <option key={s.id} value={s.id}>{s.code} — {s.name}</option>))}
      </select>
      <input placeholder="Client" value={f.client_name}
             onChange={set("client_name")}
             style={{ ...inputStyle, width: 190 }} />
      <input placeholder="Title, e.g. Jetty extension — civil"
             value={f.title} onChange={set("title")}
             style={{ ...inputStyle, flex: "1 1 220px" }} />
      <label style={{ fontSize: 12 }}>Enquiry
        <input type="date" value={f.enquiry_date}
               onChange={set("enquiry_date")} style={inputStyle} /></label>
      <label style={{ fontSize: 12 }}>Due
        <input type="date" value={f.due_date} onChange={set("due_date")}
               style={inputStyle} /></label>
      <select value={f.currency} onChange={set("currency")}
              style={{ ...inputStyle, width: 90 }}>
        <option>USD</option><option>MVR</option>
      </select>
      {/* Only the document that goes out. The priced lines are captured
          either way — this picks whether the client receives our rendered
          bill or the file they issued. */}
      <label style={{ fontSize: 12.5 }}>Submit on
        <select value={f.submit_our_format ? "ours" : "theirs"}
                onChange={(e) => setF({ ...f,
                  submit_our_format: e.target.value === "ours" })}
                style={{ ...inputStyle, width: 170 }}>
          <option value="ours">our BOQ format</option>
          <option value="theirs">the client's own bill</option>
        </select>
      </label>
      <Btn onClick={save}
           disabled={busy || !f.site_id || !f.client_name.trim()
                     || !f.title.trim()}>
        {busy ? "Saving…" : "Open"}</Btn>
      <Btn variant="secondary" onClick={() => onDone(false)}>Cancel</Btn>
      {err && <div style={{ color: "#c0392b", fontSize: 12.5, width: "100%" }}>
        {err}</div>}
    </div>
  );
}

function TenderDetail({ id, me, onClose }) {
  const [t, setT] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [ref, setRef] = useState("");
  const can = MANAGE.includes(me.role);

  const load = () => { api(`/tenders/${id}`).then(setT)
    .catch((e) => setErr(e.message)); };
  useEffect(load, [id]);

  async function act(action, body) {
    setBusy(true); setErr(null);
    try {
      const d = await api(`/tenders/${id}/${action}`,
                          { method: "POST", body: body || {} });
      setT(d); setValue(""); setNote(""); setRef("");
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }
  if (!t) return null;
  const live = ["DRAFT", "SUBMITTED"].includes(t.status);
  const current = (t.revisions || []).slice(-1)[0];

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.45)",
                  display: "flex", alignItems: "flex-start",
                  justifyContent: "center", zIndex: 60, padding: 24,
                  overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 720, width: "100%", marginTop: 24 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "baseline",
                      flexWrap: "wrap" }}>
          <h3 style={{ margin: 0, color: "var(--sp-navy)",
                       fontFamily: "var(--font-mono)" }}>{t.ref}</h3>
          <Chip tone={TONE[t.status] || "info"}>
            {LABEL[t.status] || t.status}</Chip>
          <button style={{ ...ghostButton, marginLeft: "auto" }}
                  onClick={onClose}>Close</button>
        </div>
        <p style={{ margin: "6px 0 2px", fontWeight: 600 }}>{t.client_name}</p>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
          {t.title} · {t.site_code} · enquiry {day(t.enquiry_date)} · due{" "}
          {day(t.due_date)} · {t.submit_our_format ? "submitted on our bill"
                                     : "submitted on the client's bill"}</p>
        {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}

        <h4 style={{ margin: "16px 0 4px", fontSize: 13.5,
                     color: "var(--sp-navy)" }}>Revisions</h4>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Rev</th><th style={th}>Priced by</th>
            <th style={{ ...th, textAlign: "right" }}>Value</th>
            <th style={th}>State</th><th style={th}>Note</th>
          </tr></thead>
          <tbody>
            {(t.revisions || []).map((r) => (
              <tr key={r.id}>
                <td style={{ ...td, fontFamily: "var(--font-mono)" }}>
                  {r.rev_label}</td>
                <td style={td}>{r.created_by || "—"}
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {day(r.created_at)}</div></td>
                <td style={{ ...td, textAlign: "right",
                             fontVariantNumeric: "tabular-nums" }}>
                  {r.value ? money(r.value, t.currency) : "—"}</td>
                <td style={td}>
                  {r.issued
                    ? <Chip tone="ok">Issued {day(r.issued_at)}</Chip>
                    : <Chip tone="info">Internal</Chip>}</td>
                <td style={{ ...td, color: "var(--muted)" }}>
                  {r.note || "—"}</td>
              </tr>))}
          </tbody>
        </table>

        <p style={{ margin: "10px 0 0" }}>
          <a href={`/api/v1/tenders/${t.id}/submission.pdf`} target="_blank"
             rel="noreferrer" style={{ fontSize: 13 }}>
            ⬇ Submission pack ({current?.rev_label || "R0"}) — covering letter,
            summary{t.submit_our_format ? " and bill" : ""}</a>
        </p>

        <div style={{ marginTop: 18 }}>
          <BoqPanel base={`/tenders/${t.id}`} me={me} />
        </div>

        <Docs t={t} can={can} onChanged={setT} />
        <Trail t={t} can={can && live} busy={busy} act={act} />

        {!t.submit_our_format && (
          <p style={{ fontSize: 12.5, color: "#b35900", margin: "8px 0 0" }}>
            This is submitted on the client's own bill, so their file must be
            attached before the offer can be issued. The priced lines are
            captured here either way.
          </p>)}

        {can && live && (
          <div style={{ marginTop: 16, display: "flex", flexDirection:
                        "column", gap: 10 }}>
            {current && !current.issued && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                            alignItems: "center" }}>
                <input placeholder={`Value (${t.currency})`} type="number"
                       value={value} onChange={(e) => setValue(e.target.value)}
                       style={{ ...inputStyle, width: 160 }} />
                <Btn disabled={busy || !value}
                     onClick={() => act("issue", { value })}>
                  Issue {current.rev_label} to the client</Btn>
              </div>)}
            {current && current.issued && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                            alignItems: "center" }}>
                <input placeholder="Why a new price?" value={note}
                       onChange={(e) => setNote(e.target.value)}
                       style={{ ...inputStyle, flex: "1 1 220px" }} />
                <Btn variant="secondary" disabled={busy}
                     onClick={() => act("revision", { note })}>
                  Start a new revision</Btn>
              </div>)}
            {t.status === "SUBMITTED" && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                            alignItems: "center" }}>
                <input placeholder="Their reference (LOA no.)" value={ref}
                       onChange={(e) => setRef(e.target.value)}
                       style={{ ...inputStyle, width: 200 }} />
                <Btn disabled={busy}
                     onClick={() => act("awarded", { outcome_ref: ref })}>
                  Awarded</Btn>
                <Btn variant="secondary" disabled={busy}
                     onClick={() => act("lost", { lost_reason: note })}>
                  Lost</Btn>
              </div>)}
            <Btn variant="secondary" disabled={busy}
                 onClick={() => act("withdrawn", {})}>Withdraw</Btn>
          </div>)}

        {!live && (
          <p style={{ marginTop: 14, fontSize: 13 }}>
            {t.status === "AWARDED"
              ? `Awarded ${day(t.outcome_date)}${t.outcome_ref
                  ? ` under ${t.outcome_ref}` : ""} at ${money(
                  t.value_awarded, t.currency)}.`
              : t.status === "LOST"
                ? `Lost ${day(t.outcome_date)}${t.lost_to
                    ? ` to ${t.lost_to}` : ""}${t.lost_reason
                    ? ` — ${t.lost_reason}` : ""}.`
                : `Withdrawn ${day(t.outcome_date)}.`}
          </p>)}
      </div>
    </div>
  );
}


/* What the price rested on: the visit, and the questions the client answered.
 * Without the RFI trail a later revision reads as a change of mind rather
 * than a response to what the client told us (owner 2026-09-08).
 */
function Trail({ t, can, busy, act }) {
  const [q, setQ] = useState("");
  const [visit, setVisit] = useState({ visited_on: "", attendees: "",
                                       notes: "" });
  const [answering, setAnswering] = useState(null);
  const [ans, setAns] = useState("");

  return (
    <div style={{ marginTop: 18 }}>
      <h4 style={{ margin: "0 0 4px", fontSize: 13.5,
                   color: "var(--sp-navy)" }}>
        Questions to the client</h4>
      {(t.rfis || []).length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: 0 }}>
          None raised.</p>)}
      {(t.rfis || []).map((r) => (
        <div key={r.id} style={{ borderTop: "1px solid var(--sp-border)",
                                 padding: "6px 0", fontSize: 13 }}>
          <div><strong>RFI {r.number}</strong>
            <span style={{ color: "var(--muted)", marginLeft: 8 }}>
              raised {day(r.raised_on)}</span>
            {r.answered
              ? <Chip tone="ok">answered {day(r.answered_on)}</Chip>
              : <Chip tone="warn">awaiting the client</Chip>}
          </div>
          <div style={{ marginTop: 2 }}>{r.question}</div>
          {r.answer && (
            <div style={{ marginTop: 2, color: "var(--muted)" }}>
              ↳ {r.answer}</div>)}
          {can && !r.answered && (
            answering === r.id ? (
              <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                <input value={ans} onChange={(e) => setAns(e.target.value)}
                       placeholder="What the client said" autoFocus
                       style={{ ...inputStyle, flex: "1 1 200px" }} />
                <Btn disabled={busy || !ans.trim()}
                     onClick={() => { act("rfi-answer",
                       { rfi_id: r.id, answer: ans }); setAnswering(null);
                       setAns(""); }}>Save</Btn>
              </div>
            ) : (
              <button style={{ ...ghostButton, padding: "1px 6px",
                               fontSize: 11, marginTop: 3 }}
                      onClick={() => setAnswering(r.id)}>
                Record the answer</button>))}
        </div>))}
      {can && (
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Ask the client…"
                 style={{ ...inputStyle, flex: "1 1 220px" }} />
          <Btn variant="secondary" disabled={busy || !q.trim()}
               onClick={() => { act("rfi", { question: q }); setQ(""); }}>
            Raise RFI</Btn>
        </div>)}

      <h4 style={{ margin: "16px 0 4px", fontSize: 13.5,
                   color: "var(--sp-navy)" }}>Site visits</h4>
      {(t.visits || []).length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: 0 }}>
          None recorded.</p>)}
      {(t.visits || []).map((v) => (
        <div key={v.id} style={{ borderTop: "1px solid var(--sp-border)",
                                 padding: "6px 0", fontSize: 13 }}>
          <strong>{day(v.visited_on)}</strong>
          {v.attendees && <span style={{ color: "var(--muted)",
                                         marginLeft: 8 }}>{v.attendees}</span>}
          {v.notes && <div style={{ marginTop: 2 }}>{v.notes}</div>}
        </div>))}
      {can && (
        <div style={{ display: "flex", gap: 6, marginTop: 8,
                      flexWrap: "wrap" }}>
          <input type="date" value={visit.visited_on}
                 onChange={(e) => setVisit({ ...visit,
                   visited_on: e.target.value })} style={inputStyle} />
          <input value={visit.attendees} placeholder="Who went"
                 onChange={(e) => setVisit({ ...visit,
                   attendees: e.target.value })}
                 style={{ ...inputStyle, width: 160 }} />
          <input value={visit.notes} placeholder="What was seen"
                 onChange={(e) => setVisit({ ...visit,
                   notes: e.target.value })}
                 style={{ ...inputStyle, flex: "1 1 200px" }} />
          <Btn variant="secondary" disabled={busy || !visit.visited_on}
               onClick={() => { act("visit", visit);
                 setVisit({ visited_on: "", attendees: "", notes: "" }); }}>
            Log visit</Btn>
        </div>)}
    </div>
  );
}


/* Everything the enquiry arrived with and everything it produces. The
 * client's own bill is the one that matters: where we submit on their form
 * that file IS the submission, so the offer cannot be issued until it is
 * here (owner 2026-09-09).
 */
const DOC_KINDS = [
  ["TENDER_ENQUIRY", "Enquiry document"],
  ["TENDER_BILL", "Their bill (the form we submit on)"],
  ["TENDER_ADDENDUM", "Addendum / clarification"],
  ["TENDER_AWARD", "Award letter"],
  ["ENCLOSURE", "Other enclosure"],
];

function Docs({ t, can, onChanged }) {
  const [kind, setKind] = useState("TENDER_ENQUIRY");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const fileRef = useRef(null);

  async function upload(file) {
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("kind", kind);
      onChanged(await apiUpload(`/tenders/${t.id}/documents`, fd));
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  }
  async function remove(a) {
    setBusy(true); setErr(null);
    try {
      onChanged(await api(`/tenders/${t.id}/documents/${a.id}`,
                          { method: "DELETE" }));
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }
  const docs = t.attachments || [];
  const needsBill = !t.submit_our_format
    && !docs.some((a) => a.kind === "TENDER_BILL");

  return (
    <div style={{ marginTop: 18 }}>
      <h4 style={{ margin: "0 0 4px", fontSize: 13.5,
                   color: "var(--sp-navy)" }}>Documents</h4>
      {needsBill && (
        <p style={{ fontSize: 12.5, color: "#b35900", margin: "0 0 6px" }}>
          This offer is submitted on the client's own bill — upload that file
          here before issuing it.
        </p>)}
      {docs.length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: 0 }}>
          Nothing filed yet.</p>)}
      {docs.map((a) => (
        <div key={a.id} style={{ borderTop: "1px solid var(--sp-border)",
                                 padding: "5px 0", fontSize: 13,
                                 display: "flex", gap: 8,
                                 alignItems: "baseline", flexWrap: "wrap" }}>
          <a href={a.url} target="_blank" rel="noreferrer">{a.file_name}</a>
          <span style={{ color: "var(--muted)", fontSize: 11.5 }}>
            {a.kind_label}</span>
          {a.issued && <Chip tone="ok">sent to the client</Chip>}
          {can && !a.issued && (
            <button style={{ ...ghostButton, padding: "1px 6px", fontSize: 11,
                             marginLeft: "auto", color: "#c0392b" }}
                    disabled={busy} onClick={() => remove(a)}>Remove</button>)}
        </div>))}
      {can && (
        <div style={{ display: "flex", gap: 6, marginTop: 8,
                      flexWrap: "wrap", alignItems: "center" }}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}
                  style={{ ...inputStyle, width: 230 }}>
            {DOC_KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <Btn variant="secondary" disabled={busy}
               onClick={() => fileRef.current?.click()}>
            {busy ? "Uploading…" : "⬆ Upload"}</Btn>
          <input ref={fileRef} type="file" style={{ display: "none" }}
                 onChange={(e) => upload(e.target.files[0])} />
        </div>)}
      {err && <div style={{ color: "#c0392b", fontSize: 12.5 }}>{err}</div>}
    </div>
  );
}
