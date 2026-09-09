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

  // A tender holds a full bill of quantities. It gets the page, not a modal
  // floated over the register (owner 2026-09-09).
  if (open) {
    return <TenderDetail id={open} me={me}
                         onClose={() => { setOpen(null); load(); }} />;
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 4 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Tenders &amp; offers</h2>
        {/* "Only live" meant nothing to the person reading it — say what it
            hides (owner 2026-09-09). */}
        <label style={{ fontSize: 12.5, display: "flex", gap: 5,
                        alignItems: "center", marginLeft: "auto" }}
               title="Show only tenders still being priced or waiting on the
                      client's decision, hiding those already awarded, lost
                      or withdrawn.">
          <input type="checkbox" checked={onlyOpen}
                 onChange={(e) => setOnlyOpen(e.target.checked)} />
          Hide awarded, lost &amp; withdrawn
        </label>
        {can && !adding && (
          <button style={buttonStyle} onClick={() => setAdding(true)}>
            ➕ Open an enquiry</button>)}
      </div>
      <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "0 0 12px" }}>
        {live.length} still open · {outstanding} awaiting the client's
        decision. A revision is internal until it is issued — issuing one is
        the submission, and it stays on the record whatever is priced after
        it.
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {adding && can && (
        <NewTender sites={sites} onDone={(ok) => {
          setAdding(false); if (ok) load(); }} />)}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Reference</th>
            <th style={th}>Works / client</th>
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
                <td style={{ ...td, minWidth: 260 }}>
                  {/* The title is the thing being read, so it leads and gets
                      the room; the client sits under it (owner 2026-09-09). */}
                  <strong>{r.title}</strong>
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                    {r.client_name}
                    {r.assigned_to ? ` · ${r.assigned_to}` : ""}</div></td>
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

    </section>
  );
}

function NewTender({ sites, onDone }) {
  const [f, setF] = useState({ site_id: "", client_name: "",
                               client_contact: "", title: "",
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
  // Laid out in rows rather than one long line of boxes: a tender title is a
  // sentence ("Construction of Host Accommodation Building — Phase 2"), and
  // it was sharing a row with five other fields (owner 2026-09-09).
  const row = { display: "flex", gap: 10, flexWrap: "wrap",
                alignItems: "flex-end" };
  const lab = { fontSize: 11.5, color: "var(--muted)", display: "block",
                marginBottom: 2, letterSpacing: ".02em" };

  return (
    <div style={{ border: "1px solid var(--sp-border, #d8e1e8)",
                  borderRadius: 8, padding: 14, marginBottom: 14,
                  display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={row}>
        <label style={{ flex: "0 0 190px" }}>
          <span style={lab}>Site</span>
          {/* Picking the site fills the client in: the site record already
              knows who it is (owner 2026-09-09). Still editable — a few
              sites carry no client, and the party inviting a tender is not
              always the one on the site record. */}
          <select value={f.site_id}
                  onChange={(e) => {
                    const picked = (sites || []).find(
                      (s) => String(s.id) === e.target.value);
                    setF({ ...f, site_id: e.target.value,
                           client_name: picked?.client_name || f.client_name,
                           client_contact: picked?.client_contact
                                           || f.client_contact || "" });
                  }}
                  style={{ ...inputStyle, width: "100%" }}>
            <option value="">Choose a site…</option>
            {(sites || []).map((s) => (
              <option key={s.id} value={s.id}>{s.code} — {s.name}</option>))}
          </select>
        </label>
        <label style={{ flex: "1 1 260px" }}>
          <span style={lab}>Client — from the site record, edit if it differs</span>
          <input value={f.client_name} onChange={set("client_name")}
                 placeholder="Who the enquiry came from"
                 style={{ ...inputStyle, width: "100%" }} />
        </label>
      </div>

      {/* Its own row: these run long. */}
      <label>
        <span style={lab}>Title of the works</span>
        <input value={f.title} onChange={set("title")}
               placeholder="e.g. Construction of Host Accommodation Building"
               style={{ ...inputStyle, width: "100%", fontSize: 14 }} />
      </label>

      <div style={row}>
        <label style={{ flex: "0 0 150px" }}>
          <span style={lab}>Enquiry received</span>
          <input type="date" value={f.enquiry_date}
                 onChange={set("enquiry_date")}
                 style={{ ...inputStyle, width: "100%" }} />
        </label>
        <label style={{ flex: "0 0 150px" }}>
          <span style={lab}>Submission due</span>
          <input type="date" value={f.due_date} onChange={set("due_date")}
                 style={{ ...inputStyle, width: "100%" }} />
        </label>
        <label style={{ flex: "0 0 110px" }}>
          <span style={lab}>Currency</span>
          <select value={f.currency} onChange={set("currency")}
                  style={{ ...inputStyle, width: "100%" }}>
            <option>USD</option><option>MVR</option>
          </select>
        </label>
        {/* Only the document that goes out. The priced lines are captured
            either way — this picks whether the client receives our rendered
            bill or the file they issued. */}
        <label style={{ flex: "1 1 220px" }}>
          <span style={lab}>Submit on</span>
          <select value={f.submit_our_format ? "ours" : "theirs"}
                  onChange={(e) => setF({ ...f,
                    submit_our_format: e.target.value === "ours" })}
                  style={{ ...inputStyle, width: "100%" }}>
            <option value="ours">our BOQ format</option>
            <option value="theirs">the client's own bill</option>
          </select>
        </label>
      </div>

      <label>
        <span style={lab}>Scope (optional)</span>
        <textarea value={f.scope} onChange={set("scope")} rows={2}
                  placeholder="What the enquiry covers, in a line or two"
                  style={{ ...inputStyle, width: "100%",
                           fontFamily: "inherit" }} />
      </label>

      <div style={{ display: "flex", gap: 8 }}>
        <Btn onClick={save}
             disabled={busy || !f.site_id || !f.client_name.trim()
                       || !f.title.trim()}>
          {busy ? "Saving…" : "Open the enquiry"}</Btn>
        <Btn variant="secondary" onClick={() => onDone(false)}>Cancel</Btn>
      </div>
      {err && <div style={{ color: "#c0392b", fontSize: 12.5 }}>{err}</div>}
    </div>
  );
}

const TABS = [
  ["offer", "Offer"],
  ["documents", "Documents"],
  ["visits", "Site visits"],
  ["queries", "Queries (TQ)"],
  ["proposal", "Proposal terms"],
  ["boq", "Bill of quantities"],
];

function TenderDetail({ id, me, onClose }) {
  const [t, setT] = useState(null);
  const [tab, setTab] = useState("offer");
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
      return d;
    } catch (e) { setErr(e.message); return null; }
    finally { setBusy(false); }
  }
  if (!t) return null;
  const live = ["DRAFT", "SUBMITTED"].includes(t.status);
  const current = (t.revisions || []).slice(-1)[0];
  // What each tab is carrying, so the work left is visible without opening
  // every one of them (owner 2026-09-09).
  const counts = {
    documents: (t.attachments || []).length,
    visits: (t.visits || []).length,
    queries: (t.queries || []).length,
  };
  const openQuestions = (t.queries || []).reduce(
    (n, q) => n + (q.items || []).filter((i) => !i.is_answered).length, 0);

  return (
    <div>
      <div style={card}>
        <div style={{ display: "flex", gap: 10, alignItems: "baseline",
                      flexWrap: "wrap" }}>
          <button style={ghostButton} onClick={onClose}>
            ← All tenders</button>
          <h3 style={{ margin: 0, color: "var(--sp-navy)",
                       fontFamily: "var(--font-mono)" }}>{t.ref}</h3>
          <Chip tone={TONE[t.status] || "info"}>
            {LABEL[t.status] || t.status}</Chip>
          {t.assigned_to && (
            <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
              with {t.assigned_to}</span>)}
        </div>
        <p style={{ margin: "8px 0 2px", fontWeight: 600, fontSize: 16,
                    lineHeight: 1.3 }}>{t.title}</p>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
          {t.client_name} · {t.site_code} · enquiry {day(t.enquiry_date)} ·
          due {day(t.due_date)} · {t.submit_our_format
            ? "submitted on our bill" : "submitted on the client's bill"}</p>
        {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}

        <div style={{ display: "flex", gap: 6, marginTop: 12,
                      flexWrap: "wrap" }}>
          {TABS.map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)}
                    style={tab === k ? buttonStyle : ghostButton}>
              {label}
              {counts[k] > 0 && (
                <span style={{ marginLeft: 5, opacity: .75 }}>
                  {counts[k]}</span>)}
              {k === "queries" && openQuestions > 0 && (
                <span style={{ marginLeft: 5, color: "#b35900",
                               fontWeight: 700 }}>
                  · {openQuestions} unanswered</span>)}
            </button>))}
        </div>
      </div>

      {tab === "offer" && (
        <div style={{ ...card, marginTop: 12 }}>
          <Offer t={t} can={can} live={live} current={current} busy={busy}
                 act={act} value={value} setValue={setValue} note={note}
                 setNote={setNote} refText={ref} setRef={setRef} me={me} />
        </div>)}

      {tab === "documents" && (
        <div style={{ ...card, marginTop: 12 }}>
          <Docs t={t} can={can} onChanged={setT} />
        </div>)}

      {tab === "visits" && (
        <div style={{ ...card, marginTop: 12 }}>
          <Visits t={t} can={can && live} busy={busy} act={act}
                  onChanged={setT} />
        </div>)}

      {tab === "queries" && (
        <div style={{ ...card, marginTop: 12 }}>
          <Queries t={t} can={can && live} busy={busy} act={act} />
        </div>)}

      {tab === "proposal" && (
        <div style={{ ...card, marginTop: 12 }}>
          <Proposal t={t} can={can && live} busy={busy} save={
            async (body) => {
              try { setT(await api(`/tenders/${t.id}`,
                                   { method: "PATCH", body })); }
              catch (e) { alert(e.message); }
            }} />
        </div>)}

      {tab === "boq" && (
        <div style={{ marginTop: 12 }}>
          <BoqPanel base={`/tenders/${t.id}`} me={me} />
        </div>)}
    </div>
  );
}

/* The offer itself: its revisions, what has been issued, and how it ends. */
function Offer({ t, can, live, current, busy, act, value, setValue, note,
                 setNote, refText, setRef, me }) {
  const [people, setPeople] = useState([]);
  useEffect(() => {
    if (!can) return;
    // Its own endpoint: the user list is admin-only, and a QS assigning a
    // tender has no business reading the whole staff register.
    api("/tenders/assignees").then(setPeople).catch(() => {});
  }, [can]);

  return (
    <>
      <h4 style={{ margin: "0 0 4px", fontSize: 13.5,
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

      {can && (
        <div style={{ marginTop: 12, display: "flex", gap: 8,
                      alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ fontSize: 12.5 }}>Carried by
            <select value={t.assigned_to_id || ""} disabled={busy}
                    onChange={(e) => act("assign",
                      { user_id: e.target.value || null })}
                    style={{ ...inputStyle, width: 190 }}>
              <option value="">— unassigned —</option>
              {people.map((u) => (
                <option key={u.id} value={u.id}>{u.full_name}</option>))}
            </select>
          </label>
        </div>)}

      {can && live && (
        <div style={{ marginTop: 14, display: "flex", flexDirection: "column",
                      gap: 10 }}>
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
            <Outcome t={t} busy={busy} act={act} refText={refText}
                     setRef={setRef} note={note} setNote={setNote} />)}
          <Btn variant="secondary" disabled={busy}
               onClick={() => act("withdrawn", {})}>Withdraw</Btn>
        </div>)}

      {!live && (
        <p style={{ marginTop: 14, fontSize: 13 }}>
          {t.status === "AWARDED"
            ? `Awarded ${day(t.outcome_date)}${t.outcome_ref
                ? ` under ${t.outcome_ref}` : ""} at ${money(
                t.value_awarded, t.currency)}${t.awarded_project
                ? ` — project ${t.awarded_project}` : ""}.`
            : t.status === "LOST"
              ? `Lost ${day(t.outcome_date)}${t.lost_to
                  ? ` to ${t.lost_to}` : ""}${t.lost_reason
                  ? ` — ${t.lost_reason}` : ""}.`
              : `Withdrawn ${day(t.outcome_date)}.`}
        </p>)}
    </>
  );
}

/* Awarding creates the project, so it asks for the code the register will
   read by (SOUT JT, NORTH JT) rather than inventing a serial. */
function Outcome({ t, busy, act, refText, setRef, note, setNote }) {
  const [code, setCode] = useState("");
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                  alignItems: "center" }}>
      <input placeholder="Their reference (LOA no.)" value={refText}
             onChange={(e) => setRef(e.target.value)}
             style={{ ...inputStyle, width: 180 }} />
      <input placeholder="New project code" value={code}
             onChange={(e) => setCode(e.target.value)}
             style={{ ...inputStyle, width: 150 }} />
      <Btn disabled={busy || !code.trim()}
           onClick={() => act("awarded", { outcome_ref: refText,
                                           project_code: code })}>
        Awarded</Btn>
      <Btn variant="secondary" disabled={busy}
           onClick={() => act("lost", { lost_reason: note })}>Lost</Btn>
      <input placeholder="Why lost?" value={note}
             onChange={(e) => setNote(e.target.value)}
             style={{ ...inputStyle, flex: "1 1 160px" }} />
    </div>
  );
}

/* A visit is asked for, then held. Both dates matter: one requested and not
 * yet given is a live reason pricing has not started. The photos are as much
 * of the price as the notes (owner 2026-09-09).
 */
function Visits({ t, can, busy, act, onChanged }) {
  const [req, setReq] = useState({ requested_on: "", notes: "" });
  const [holding, setHolding] = useState(null);
  const [held, setHeld] = useState({ visited_on: "", attendees: "",
                                     notes: "" });
  const [err, setErr] = useState(null);
  const fileRef = useRef(null);
  const [forVisit, setForVisit] = useState(null);

  async function addPhoto(file) {
    if (!file || !forVisit) return;
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      onChanged(await apiUpload(`/tenders/${t.id}/visits/${forVisit}/photo`,
                                fd));
    } catch (e) { setErr(e.message); }
    finally { if (fileRef.current) fileRef.current.value = ""; }
  }

  return (
    <div>
      <h4 style={{ margin: "0 0 4px", fontSize: 13.5,
                   color: "var(--sp-navy)" }}>Site visits</h4>
      <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 8px" }}>
        What the estimator saw — access, existing conditions, what the drawings
        do not show. Pricing rests on it as much as on the documents.
      </p>
      {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
      {(t.visits || []).length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: 0 }}>
          None requested yet.</p>)}

      {(t.visits || []).map((v) => (
        <div key={v.id} style={{ borderTop: "1px solid var(--sp-border)",
                                 padding: "8px 0", fontSize: 13 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "baseline",
                        flexWrap: "wrap" }}>
            {v.held
              ? <><strong>Held {day(v.visited_on)}</strong>
                  <Chip tone="ok">done</Chip></>
              : <><strong>Requested {day(v.requested_on)}</strong>
                  <Chip tone="warn">awaiting the client</Chip></>}
            {v.attendees && <span style={{ color: "var(--muted)" }}>
              {v.attendees}</span>}
          </div>
          {v.notes && <div style={{ marginTop: 3, whiteSpace: "pre-line" }}>
            {v.notes}</div>}

          {v.photos?.length > 0 && (
            <div style={{ display: "flex", gap: 6, marginTop: 6,
                          flexWrap: "wrap" }}>
              {v.photos.map((ph) => (
                <a key={ph.id} href={ph.url} target="_blank" rel="noreferrer">
                  <img src={ph.url} alt={ph.caption || ph.file_name}
                       style={{ height: 84, width: 112, objectFit: "cover",
                                borderRadius: 5,
                                border: "1px solid var(--sp-border)" }} />
                </a>))}
            </div>)}

          {can && !v.held && (
            holding === v.id ? (
              <div style={{ display: "flex", gap: 6, marginTop: 6,
                            flexWrap: "wrap" }}>
                <input type="date" value={held.visited_on}
                       onChange={(e) => setHeld({ ...held,
                         visited_on: e.target.value })} style={inputStyle} />
                <input placeholder="Who went" value={held.attendees}
                       onChange={(e) => setHeld({ ...held,
                         attendees: e.target.value })}
                       style={{ ...inputStyle, width: 150 }} />
                <input placeholder="What was seen" value={held.notes}
                       onChange={(e) => setHeld({ ...held,
                         notes: e.target.value })}
                       style={{ ...inputStyle, flex: "1 1 200px" }} />
                <Btn disabled={busy || !held.visited_on}
                     onClick={() => { act("visit-held",
                       { visit_id: v.id, ...held }); setHolding(null);
                       setHeld({ visited_on: "", attendees: "", notes: "" });
                     }}>Save</Btn>
              </div>
            ) : (
              <button style={{ ...ghostButton, padding: "1px 6px",
                               fontSize: 11, marginTop: 5 }}
                      onClick={() => setHolding(v.id)}>
                Record the visit</button>))}

          {can && v.held && (
            <button style={{ ...ghostButton, padding: "1px 6px", fontSize: 11,
                             marginTop: 5 }}
                    onClick={() => { setForVisit(v.id);
                                     fileRef.current?.click(); }}>
              ＋ Add a photo</button>)}
        </div>))}

      <input ref={fileRef} type="file" accept="image/*"
             style={{ display: "none" }}
             onChange={(e) => addPhoto(e.target.files[0])} />

      {can && (
        <div style={{ display: "flex", gap: 6, marginTop: 10,
                      flexWrap: "wrap" }}>
          <input type="date" value={req.requested_on}
                 onChange={(e) => setReq({ ...req,
                   requested_on: e.target.value })} style={inputStyle} />
          <input placeholder="What we asked for" value={req.notes}
                 onChange={(e) => setReq({ ...req, notes: e.target.value })}
                 style={{ ...inputStyle, flex: "1 1 220px" }} />
          <Btn variant="secondary" disabled={busy}
               onClick={() => { act("visit-request", req);
                 setReq({ requested_on: "", notes: "" }); }}>
            Request a visit</Btn>
        </div>)}
    </div>
  );
}

/* Tender Queries. NOT an RFI — that name is taken by the contract-stage
 * request for information and by the inspection request. A TQ carries several
 * numbered questions on one sheet, goes to the client under its own reference
 * in our format, and the answers come back against each question, because a
 * client commonly answers three of five (owner 2026-09-09).
 */
function Queries({ t, can, busy, act }) {
  const [openQ, setOpenQ] = useState(null);
  const [subject, setSubject] = useState("");
  const [q, setQ] = useState({ question: "", reference: "" });
  const [answering, setAnswering] = useState(null);
  const [ans, setAns] = useState("");

  return (
    <div>
      <h4 style={{ margin: "0 0 4px", fontSize: 13.5,
                   color: "var(--sp-navy)" }}>Tender queries</h4>
      <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 8px" }}>
        Questions put to the client during the tender period, several to a
        sheet, issued under our own reference. Their answers are what explain
        why a later revision is priced differently.
      </p>
      {(t.queries || []).length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: 0 }}>
          None raised.</p>)}

      {(t.queries || []).map((qq) => (
        <div key={qq.id} style={{ borderTop: "1px solid var(--sp-border)",
                                  padding: "8px 0" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "baseline",
                        flexWrap: "wrap" }}>
            <strong style={{ fontFamily: "var(--font-mono)" }}>{qq.ref}</strong>
            {qq.subject && <span>{qq.subject}</span>}
            {qq.issued
              ? <Chip tone="ok">issued {day(qq.issued_at)}</Chip>
              : <Chip tone="info">drafting</Chip>}
            <span style={{ fontSize: 12, color: "var(--muted)" }}>
              {qq.answered}/{(qq.items || []).length} answered</span>
            {qq.client_ref && (
              <span style={{ fontSize: 12, color: "var(--muted)" }}>
                their ref {qq.client_ref}</span>)}
            <a href={`/api/v1/tenders/${t.id}/queries/${qq.id}.pdf`}
               target="_blank" rel="noreferrer"
               style={{ fontSize: 12, marginLeft: "auto" }}>⬇ Sheet</a>
          </div>

          {(qq.items || []).map((it) => (
            <div key={it.id} style={{ marginTop: 5, paddingLeft: 10,
                                      borderLeft: "2px solid var(--sp-border)",
                                      fontSize: 13 }}>
              <div><strong>{it.number}.</strong> {it.question}
                {it.reference && (
                  <span style={{ color: "var(--muted)", fontSize: 11.5 }}>
                    {" "}(ref {it.reference})</span>)}</div>
              {it.answer
                ? <div style={{ color: "var(--muted)", marginTop: 2 }}>
                    ↳ {it.answer} · {day(it.answered_on)}</div>
                : can && (answering === it.id ? (
                    <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                      <input value={ans} autoFocus
                             onChange={(e) => setAns(e.target.value)}
                             placeholder="What the client answered"
                             style={{ ...inputStyle, flex: "1 1 200px" }} />
                      <Btn disabled={busy || !ans.trim()}
                           onClick={() => { act("query-answer",
                             { query_id: qq.id, item_id: it.id,
                               answer: ans }); setAnswering(null);
                             setAns(""); }}>Save</Btn>
                    </div>
                  ) : (
                    <button style={{ ...ghostButton, padding: "1px 6px",
                                     fontSize: 11, marginTop: 3 }}
                            onClick={() => setAnswering(it.id)}>
                      Record the answer</button>))}
            </div>))}

          {can && !qq.issued && (
            <div style={{ marginTop: 8, display: "flex", gap: 6,
                          flexWrap: "wrap" }}>
              <input placeholder="Another question" value={
                openQ === qq.id ? q.question : ""}
                     onChange={(e) => { setOpenQ(qq.id);
                       setQ({ ...q, question: e.target.value }); }}
                     style={{ ...inputStyle, flex: "1 1 220px" }} />
              <input placeholder="Drawing / clause" value={
                openQ === qq.id ? q.reference : ""}
                     onChange={(e) => { setOpenQ(qq.id);
                       setQ({ ...q, reference: e.target.value }); }}
                     style={{ ...inputStyle, width: 140 }} />
              <Btn variant="secondary"
                   disabled={busy || openQ !== qq.id || !q.question.trim()}
                   onClick={() => { act("query-question",
                     { query_id: qq.id, ...q });
                     setQ({ question: "", reference: "" }); }}>Add</Btn>
              <Btn disabled={busy || !(qq.items || []).length}
                   onClick={() => act("query-issue", { query_id: qq.id })}>
                Issue to the client</Btn>
            </div>)}
        </div>))}

      {can && (
        <div style={{ display: "flex", gap: 6, marginTop: 12,
                      flexWrap: "wrap" }}>
          <input placeholder="Subject of a new query sheet" value={subject}
                 onChange={(e) => setSubject(e.target.value)}
                 style={{ ...inputStyle, flex: "1 1 240px" }} />
          <Btn variant="secondary" disabled={busy}
               onClick={() => { act("query", { subject }); setSubject(""); }}>
            Start a query</Btn>
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


/* What the cover and the summary print. Taken from the owner's own SJR
 * Operation Office workbook, which is the format these proposals already
 * follow — it was retyped into Excel for every tender (owner 2026-09-09).
 */
function Proposal({ t, can, busy, save }) {
  const [f, setF] = useState({
    doc_ref: t.doc_ref || "", validity_days: t.validity_days ?? 30,
    duration_days: t.duration_days ?? "", provisional_sum:
      t.provisional_sum ?? "", gst_percent: t.gst_percent ?? 8,
    payment_terms: t.payment_terms || "",
    client_provides: t.client_provides || "",
    exclusions: t.exclusions || "", variations: t.variations || "",
    warranty_terms: t.warranty_terms || "",
    prepared_by: t.prepared_by || "", reviewed_by: t.reviewed_by || "",
    approved_by: t.approved_by || "",
  });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const lab = { fontSize: 11.5, color: "var(--muted)", display: "block",
                marginBottom: 2 };
  const area = { ...inputStyle, width: "100%", fontFamily: "inherit" };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <h4 style={{ margin: 0, fontSize: 13.5, color: "var(--sp-navy)" }}>
        Cover and summary</h4>
      <p style={{ fontSize: 12.5, color: "var(--muted)", margin: 0 }}>
        These print on the submission pack. The sums build on the value you
        issue: sub total, provisional sum, GST, grand total.
      </p>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <label style={{ flex: "1 1 220px" }}>
          <span style={lab}>Document reference — yours, if you keep one</span>
          <input value={f.doc_ref} onChange={set("doc_ref")} disabled={!can}
                 placeholder={t.ref} style={{ ...inputStyle, width: "100%" }} />
        </label>
        <label style={{ flex: "0 0 120px" }}>
          <span style={lab}>Validity (days)</span>
          <input type="number" value={f.validity_days} disabled={!can}
                 onChange={set("validity_days")}
                 style={{ ...inputStyle, width: "100%" }} />
        </label>
        <label style={{ flex: "0 0 140px" }}>
          <span style={lab}>Duration (days)</span>
          <input type="number" value={f.duration_days} disabled={!can}
                 onChange={set("duration_days")}
                 style={{ ...inputStyle, width: "100%" }} />
        </label>
        <label style={{ flex: "0 0 150px" }}>
          <span style={lab}>Provisional sum</span>
          <input type="number" value={f.provisional_sum} disabled={!can}
                 onChange={set("provisional_sum")}
                 style={{ ...inputStyle, width: "100%" }} />
        </label>
        <label style={{ flex: "0 0 110px" }}>
          <span style={lab}>GST %</span>
          <input type="number" value={f.gst_percent} disabled={!can}
                 onChange={set("gst_percent")}
                 style={{ ...inputStyle, width: "100%" }} />
        </label>
      </div>

      {[["payment_terms", "Payment terms"],
        ["client_provides", "By client"],
        ["exclusions", "Exclusions"],
        ["variations", "Variations"],
        ["warranty_terms", "Warranty / DLP"]].map(([k, label]) => (
        <label key={k}>
          <span style={lab}>{label}</span>
          <textarea value={f[k]} onChange={set(k)} rows={2} disabled={!can}
                    style={area} />
        </label>))}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {[["prepared_by", "Prepared by (QS)"], ["reviewed_by", "Reviewed by"],
          ["approved_by", "Approved by"]].map(([k, label]) => (
          <label key={k} style={{ flex: "1 1 170px" }}>
            <span style={lab}>{label}</span>
            <input value={f[k]} onChange={set(k)} disabled={!can}
                   style={{ ...inputStyle, width: "100%" }} />
          </label>))}
      </div>

      {can && (
        <div>
          <Btn disabled={busy} onClick={() => save(f)}>Save these terms</Btn>
        </div>)}
    </div>
  );
}
