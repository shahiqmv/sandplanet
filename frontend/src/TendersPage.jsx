import { useEffect, useState } from "react";
import { api } from "./api.js";
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

  const load = () => api(`/tenders${onlyOpen ? "?open=1" : ""}`)
    .then(setRows).catch((e) => setError(e.message));
  useEffect(load, [onlyOpen]); // eslint-disable-line

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
                    {r.rev_label}{r.our_format ? "" : " · their format"}</div>
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
                               our_format: true, currency: "USD",
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
      {/* Their format means their file is what goes out, so the system will
          ask for it before letting the offer be issued. */}
      <label style={{ fontSize: 12.5, display: "flex", gap: 5,
                      alignItems: "center" }}>
        <input type="checkbox" checked={f.our_format}
               onChange={set("our_format")} />
        Our BOQ format
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

  const load = () => api(`/tenders/${id}`).then(setT)
    .catch((e) => setErr(e.message));
  useEffect(load, [id]); // eslint-disable-line

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
          {day(t.due_date)} · {t.our_format ? "our format"
                                            : "the client's format"}</p>
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

        {!t.our_format && (
          <p style={{ fontSize: 12.5, color: "#b35900", margin: "8px 0 0" }}>
            This goes out in the client's format — their bill must be attached
            to the document before the offer can be issued.
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
