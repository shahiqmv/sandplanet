import { useEffect, useState } from "react";
import { api } from "./api.js";
import { card, th, td, Btn, Chip } from "./ui.jsx";

const money = (v) =>
  v == null ? "—"
    : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2,
        maximumFractionDigits: 2 });
const dash = (v) => (Number(v) ? money(v) : "—");
const mono = { fontFamily: "var(--font-mono)" };
const fmtDate = (s) => (s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—");

const TABS = [["aging", "Aging analysis"], ["statement", "Statement of account"]];

// Client receivables — invoice due dates, aging buckets and per-client
// statements over the certified claims (IPCs). Finance / QS / Director.
export default function ReceivablesPage({ me }) {
  const [tab, setTab] = useState("aging");
  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    marginBottom: 4 }}>
        <h1 style={{ margin: 0 }}>Receivables</h1>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          Client billing, due dates &amp; collections — all figures USD</span>
      </div>
      <div style={{ display: "flex", gap: 6, margin: "10px 0 14px" }}>
        {TABS.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            style={{ padding: "6px 14px", border: "1px solid var(--line)",
              borderRadius: 6, cursor: "pointer", fontSize: 13,
              background: tab === k ? "var(--navy)" : "#fff",
              color: tab === k ? "#fff" : "var(--navy)" }}>{label}</button>
        ))}
      </div>
      {tab === "aging" ? <Aging /> : <Statement />}
    </div>
  );
}

function Aging() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api("/receivables/aging").then(setD).catch((e) => setError(e.message));
  }, []);
  if (error) return <div style={card}>{error}</div>;
  if (!d) return <div style={card}>Loading…</div>;
  const cols = d.buckets;
  const total = Number(d.totals.total);
  if (!d.clients.length)
    return <div style={card}>No outstanding client invoices. Everything is
      collected or nothing is certified yet.</div>;
  return (
    <>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                    marginBottom: 12 }}>
        <Kpi label="Total outstanding" value={money(total)} strong />
        {cols.map((b) => Number(d.totals[b]) > 0 && (
          <Kpi key={b} label={d.bucket_labels[b]} value={money(d.totals[b])}
               alert={b === "d61_90" || b === "d90p"} />
        ))}
      </div>
      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <thead><tr>
            <th style={{ ...th, textAlign: "left" }}>Client</th>
            <th style={{ ...th, textAlign: "right" }}>Inv.</th>
            {cols.map((b) => (
              <th key={b} style={{ ...th, textAlign: "right" }}>
                {d.bucket_labels[b]}</th>
            ))}
            <th style={{ ...th, textAlign: "right" }}>Total due</th>
          </tr></thead>
          <tbody>
            {d.clients.map((c) => (
              <tr key={c.site_id}>
                <td style={td}>
                  <div style={{ fontWeight: 600 }}>{c.client}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {c.site_code}</div>
                </td>
                <td style={{ ...td, textAlign: "right" }}>{c.invoices}</td>
                {cols.map((b) => (
                  <td key={b} style={{ ...td, textAlign: "right", ...mono,
                    color: (b === "d61_90" || b === "d90p") && Number(c[b])
                      ? "var(--red-fg)" : undefined }}>{dash(c[b])}</td>
                ))}
                <td style={{ ...td, textAlign: "right", ...mono,
                             fontWeight: 700 }}>{money(c.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr style={{ borderTop: "2px solid var(--line)" }}>
            <td style={{ ...td, fontWeight: 700 }}>All clients</td>
            <td style={{ ...td, textAlign: "right" }}>{d.invoice_count}</td>
            {cols.map((b) => (
              <td key={b} style={{ ...td, textAlign: "right", ...mono,
                fontWeight: 700 }}>{dash(d.totals[b])}</td>
            ))}
            <td style={{ ...td, textAlign: "right", ...mono, fontWeight: 800 }}>
              {money(total)}</td>
          </tr></tfoot>
        </table>
      </div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        Aged by invoice due date as at {fmtDate(d.as_of)}. Due date = invoice
        date + the client credit period set on each project's contract terms.
      </div>
    </>
  );
}

function Statement() {
  const [clients, setClients] = useState(null);
  const [siteId, setSiteId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [stmt, setStmt] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/receivables/clients").then((r) => {
      setClients(r.clients);
      if (r.clients.length) setSiteId(String(r.clients[0].site_id));
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!siteId) return;
    const qs = new URLSearchParams({ site: siteId });
    if (from) qs.set("from", from);
    if (to) qs.set("to", to);
    setStmt(null);
    api(`/receivables/statement?${qs}`).then(setStmt)
      .catch((e) => setError(e.message));
  }, [siteId, from, to]);

  if (error) return <div style={card}>{error}</div>;
  if (!clients) return <div style={card}>Loading…</div>;
  if (!clients.length)
    return <div style={card}>No client has been invoiced yet.</div>;

  const pdfUrl = () => {
    const qs = new URLSearchParams({ site: siteId });
    if (from) qs.set("from", from);
    if (to) qs.set("to", to);
    return `/api/v1/receivables/statement.pdf?${qs}`;
  };

  return (
    <>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                    alignItems: "flex-end", marginBottom: 12 }}>
        <Field label="Client">
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}
            style={sel}>
            {clients.map((c) => (
              <option key={c.site_id} value={c.site_id}>
                {c.client} ({c.site_code}) — {money(c.outstanding)} due</option>
            ))}
          </select>
        </Field>
        <Field label="From">
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
                 style={sel} /></Field>
        <Field label="To">
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)}
                 style={sel} /></Field>
        {siteId && (
          <a href={pdfUrl()} target="_blank" rel="noreferrer">
            <Btn variant="secondary">Download PDF</Btn></a>
        )}
      </div>

      {!stmt ? <div style={card}>Loading…</div> : (
        <>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                        marginBottom: 12 }}>
            <Kpi label="Invoiced" value={money(stmt.billed)} />
            <Kpi label="Received" value={money(stmt.received)} />
            <Kpi label="Balance due" value={money(stmt.closing)} strong
                 alert={Number(stmt.closing) > 0} />
          </div>
          <div style={{ ...card, padding: 0, overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
              <thead><tr>
                <th style={{ ...th, textAlign: "left" }}>Date</th>
                <th style={{ ...th, textAlign: "left" }}>Reference</th>
                <th style={{ ...th, textAlign: "left" }}>Project</th>
                <th style={{ ...th, textAlign: "left" }}>Description</th>
                <th style={{ ...th, textAlign: "left" }}>Due</th>
                <th style={{ ...th, textAlign: "right" }}>Invoiced</th>
                <th style={{ ...th, textAlign: "right" }}>Received</th>
                <th style={{ ...th, textAlign: "right" }}>Balance</th>
              </tr></thead>
              <tbody>
                <tr style={{ background: "var(--paper)" }}>
                  <td style={{ ...td, fontWeight: 600 }} colSpan={7}>
                    Opening balance{stmt.date_from
                      ? ` as at ${fmtDate(stmt.date_from)}` : ""}</td>
                  <td style={{ ...td, textAlign: "right", ...mono,
                    fontWeight: 600 }}>{money(stmt.opening)}</td>
                </tr>
                {stmt.rows.map((r, i) => (
                  <tr key={i}>
                    <td style={td}>{fmtDate(r.date)}</td>
                    <td style={{ ...td, ...mono }}>{r.ref || "—"}</td>
                    <td style={td}>{r.project_code}</td>
                    <td style={td}>{r.description}
                      {r.kind === "INVOICE" && <> <Chip tone="info">INV</Chip></>}
                      {r.kind === "RECEIPT" && <> <Chip tone="ok">RCPT</Chip></>}
                    </td>
                    <td style={td}>{r.due_date ? fmtDate(r.due_date) : "—"}</td>
                    <td style={{ ...td, textAlign: "right", ...mono }}>
                      {dash(r.debit)}</td>
                    <td style={{ ...td, textAlign: "right", ...mono,
                      color: Number(r.credit) ? "var(--green-fg)" : undefined }}>
                      {dash(r.credit)}</td>
                    <td style={{ ...td, textAlign: "right", ...mono }}>
                      {money(r.balance)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot><tr style={{ borderTop: "2px solid var(--line)" }}>
                <td style={{ ...td, fontWeight: 700 }} colSpan={5}>
                  Closing balance</td>
                <td style={{ ...td, textAlign: "right", ...mono,
                  fontWeight: 700 }}>{money(stmt.billed)}</td>
                <td style={{ ...td, textAlign: "right", ...mono,
                  fontWeight: 700 }}>{money(stmt.received)}</td>
                <td style={{ ...td, textAlign: "right", ...mono,
                  fontWeight: 800 }}>{money(stmt.closing)}</td>
              </tr></tfoot>
            </table>
          </div>
        </>
      )}
    </>
  );
}

function Kpi({ label, value, strong, alert }) {
  return (
    <div style={{ ...card, minWidth: 150, padding: "10px 14px" }}>
      <div style={{ fontSize: 11, color: "var(--muted)",
                    textTransform: "uppercase", letterSpacing: ".04em" }}>
        {label}</div>
      <div style={{ fontSize: strong ? 22 : 18, fontWeight: strong ? 800 : 600,
        ...mono, color: alert ? "var(--red-fg)" : "var(--navy)" }}>
        {value}</div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3,
                    fontSize: 12, color: "var(--muted)" }}>
      {label}{children}
    </label>
  );
}

const sel = { padding: "6px 8px", border: "1px solid var(--line)",
  borderRadius: 6, fontSize: 13, background: "#fff" };
