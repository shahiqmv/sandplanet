import { Fragment, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { card, th, td, Btn, Chip, ghostButton } from "./ui.jsx";
import { InvoiceModal, InvoiceRef, InvoicesTab } from "./ReceivableInvoice.jsx";

const RECEIPT_ROLES = ["FINANCE", "ADMIN"];
// Who may record a manual client invoice (mirrors manual_invoices.CREATE_ROLES).
const MANUAL_ROLES = ["QS", "FINANCE", "DIRECTOR", "ADMIN"];
const METHODS = [["TT", "Telegraphic transfer"], ["CHEQUE", "Cheque"],
  ["CASH", "Cash"], ["CARD", "Card"], ["OTHER", "Other"]];

const money = (v) =>
  v == null ? "—"
    : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2,
        maximumFractionDigits: 2 });
const dash = (v) => (Number(v) ? money(v) : "—");
const mono = { fontFamily: "var(--font-mono)" };
const fmtDate = (s) => (s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—");

const TABS = [["aging", "Aging analysis"], ["invoices", "Invoices"],
  ["statement", "Statement of account"],
  ["manual", "Manual invoices"], ["receipts", "Official receipts"]];

// Client receivables — invoice due dates, aging buckets, per-client statements
// and official receipts over the certified claims (IPCs). Finance / QS /
// Director.
export default function ReceivablesPage({ me }) {
  const [tab, setTab] = useState("aging");
  // The invoice opened from any tab: {source: "claim" | "manual", id}
  const [openInv, setOpenInv] = useState(null);
  const canReceipt = RECEIPT_ROLES.includes(me.role);
  const canManual = MANUAL_ROLES.includes(me.role);
  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    marginBottom: 4 }}>
        <h1 style={{ margin: 0 }}>Receivables</h1>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          Client billing, due dates &amp; collections — figures in each
          contract's currency (USD unless marked MVR)</span>
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
      {tab === "aging" && <Aging onOpen={setOpenInv} />}
      {tab === "invoices" && <InvoicesTab onOpen={setOpenInv} />}
      {tab === "statement" && <Statement onOpen={setOpenInv} />}
      {openInv && <InvoiceModal invoice={openInv}
                                onClose={() => setOpenInv(null)} />}
      {tab === "manual" && <ManualInvoices canManual={canManual} />}
      {tab === "receipts" && <Receipts canReceipt={canReceipt} />}
    </div>
  );
}

function Aging({ onOpen }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  // A client row opens to the invoices that make up its total.
  const [openKey, setOpenKey] = useState(null);   // "siteId-currency"
  const [inv, setInv] = useState({});             // siteId -> invoices
  function toggle(c) {
    const key = `${c.site_id}-${c.currency}`;
    if (openKey === key) { setOpenKey(null); return; }
    setOpenKey(key);
    if (!inv[c.site_id])
      api(`/receivables/invoices?site=${c.site_id}&outstanding=1`)
        .then((r) => setInv((m) => ({ ...m, [c.site_id]: r.invoices })))
        .catch((e) => setError(e.message));
  }
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
        <Kpi label={`Total outstanding (${d.totals_currency || "USD"})`}
             value={money(total)} strong />
        {Object.entries(d.totals_by_currency || {})
          .filter(([cur]) => cur !== (d.totals_currency || "USD"))
          .map(([cur, t]) => (
          <Kpi key={cur} label={`Total outstanding (${cur})`}
               value={money(t.total)} strong />
        ))}
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
              <Fragment key={`${c.site_id}-${c.currency}`}>
              <tr style={{ cursor: "pointer" }} onClick={() => toggle(c)}
                  title="Show this client's outstanding invoices">
                <td style={td}>
                  <div style={{ fontWeight: 600 }}>
                    <span style={{ color: "var(--muted)", marginRight: 6 }}>
                      {openKey === `${c.site_id}-${c.currency}` ? "▾" : "▸"}</span>
                    {c.client}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {c.site_code}
                    {c.currency && c.currency !== "USD" && (
                      <b style={{ marginLeft: 6, color: "#8a6d00" }}>
                        {c.currency}</b>)}</div>
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
              {openKey === `${c.site_id}-${c.currency}` && (
                <tr>
                  <td colSpan={cols.length + 3}
                      style={{ ...td, background: "var(--paper)", padding: "6px 14px 10px 30px" }}>
                    {!inv[c.site_id] ? "Loading…" : (
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
                        <tbody>
                          {inv[c.site_id].filter((r) => r.currency === c.currency).map((r) => (
                            <tr key={`${r.source}-${r.claim_id || r.manual_invoice_id}`}>
                              <td style={{ padding: "3px 8px 3px 0" }}>
                                <InvoiceRef row={r} onOpen={onOpen} /></td>
                              <td style={{ padding: "3px 8px" }}>{r.project_code}</td>
                              <td style={{ padding: "3px 8px", whiteSpace: "nowrap" }}>
                                due {fmtDate(r.due_date)}</td>
                              <td style={{ padding: "3px 8px", color: r.days_overdue
                                ? "var(--red-fg)" : "var(--muted)" }}>
                                {r.days_overdue ? `${r.days_overdue} days overdue` : "not yet due"}</td>
                              <td style={{ padding: "3px 0", textAlign: "right", ...mono, fontWeight: 600 }}>
                                {money(r.outstanding)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
          <tfoot>
            {Object.entries(d.totals_by_currency || { USD: d.totals })
              .map(([cur, t]) => (
              <tr key={cur} style={{ borderTop: "2px solid var(--line)" }}>
                <td style={{ ...td, fontWeight: 700 }}>
                  All clients ({cur})</td>
                <td style={{ ...td, textAlign: "right" }} />
                {cols.map((b) => (
                  <td key={b} style={{ ...td, textAlign: "right", ...mono,
                    fontWeight: 700 }}>{dash(t[b])}</td>
                ))}
                <td style={{ ...td, textAlign: "right", ...mono,
                             fontWeight: 800 }}>{money(t.total)}</td>
              </tr>
            ))}
          </tfoot>
        </table>
      </div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        Aged by invoice due date as at {fmtDate(d.as_of)}. Due date = invoice
        date + the client credit period set on each project's contract terms.
      </div>
    </>
  );
}

function Statement({ onOpen }) {
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
              <option key={`${c.site_id}-${c.currency}`} value={c.site_id}>
                {c.client} ({c.site_code}) — {money(c.outstanding)}
                {" "}{c.currency || "USD"} due</option>
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
            <Kpi label={`Invoiced (${stmt.currency || "USD"})`}
                 value={money(stmt.billed)} />
            <Kpi label={`Received (${stmt.currency || "USD"})`}
                 value={money(stmt.received)} />
            <Kpi label={`Balance due (${stmt.currency || "USD"})`}
                 value={money(stmt.closing)} strong
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
                    <td style={{ ...td, ...mono }}>
                      {r.kind === "INVOICE"
                        ? <InvoiceRef row={r} label={r.ref} onOpen={onOpen} />
                        : (r.ref || "—")}</td>
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

function Receipts({ canReceipt }) {
  const [list, setList] = useState(null);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);

  const load = () => api("/receivables/receipts")
    .then((r) => setList(r.receipts)).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  if (error) return <div style={card}>{error}</div>;
  if (creating)
    return <NewReceipt onDone={() => { setCreating(false); load(); }}
                       onCancel={() => setCreating(false)} />;
  if (!list) return <div style={card}>Loading…</div>;

  async function voidReceipt(r) {
    if (!window.confirm(`Void receipt ${r.receipt_no}? This reverses the `
      + `money received against its invoices.`)) return;
    try { await api(`/receivables/receipts/${r.id}`, { method: "DELETE" }); load(); }
    catch (e) { setError(e.message); }
  }

  return (
    <>
      {canReceipt && (
        <div style={{ marginBottom: 12 }}>
          <Btn variant="primary" onClick={() => setCreating(true)}>
            + New official receipt</Btn>
        </div>
      )}
      {!list.length ? <div style={card}>No receipts issued yet.</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={{ ...th, textAlign: "left" }}>Receipt</th>
              <th style={{ ...th, textAlign: "left" }}>Date</th>
              <th style={{ ...th, textAlign: "left" }}>Client</th>
              <th style={{ ...th, textAlign: "left" }}>Method / ref</th>
              <th style={{ ...th, textAlign: "left" }}>Invoices</th>
              <th style={{ ...th, textAlign: "right" }}>Amount</th>
              <th style={th}></th>
            </tr></thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.id}>
                  <td style={{ ...td, ...mono, fontWeight: 600 }}>
                    {r.receipt_no}</td>
                  <td style={td}>{fmtDate(r.receipt_date)}</td>
                  <td style={td}>{r.client}</td>
                  <td style={td}>{r.method_label}
                    {r.reference && <span style={{ color: "var(--muted)" }}>
                      {" · "}{r.reference}</span>}</td>
                  <td style={td}>{r.lines.map((l) => l.invoice_no).join(", ")}</td>
                  <td style={{ ...td, textAlign: "right", ...mono,
                               fontWeight: 700 }}>{money(r.total)}</td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>
                    <a href={`/api/v1/receivables/receipts/${r.id}.pdf`}
                       target="_blank" rel="noreferrer"
                       style={{ marginRight: 10 }}>PDF</a>
                    {canReceipt && (
                      <button onClick={() => voidReceipt(r)}
                        style={{ border: "none", background: "none",
                          color: "var(--red-fg)", cursor: "pointer",
                          fontSize: 13 }}>Void</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// A stable per-invoice key: claims carry a claim_id, manual invoices carry a
// manual_invoice_id (claim_id is null for those) — keying by claim_id alone made
// every manual invoice share the null slot, so ticking one ticked them all.
const invKey = (inv) =>
  inv.claim_id ? `c${inv.claim_id}` : `m${inv.manual_invoice_id}`;

function NewReceipt({ onDone, onCancel }) {
  const [clients, setClients] = useState(null);
  const [banks, setBanks] = useState([]);
  const [siteId, setSiteId] = useState("");
  const [invoices, setInvoices] = useState([]);
  const [alloc, setAlloc] = useState({});    // claim_id -> {on, amount}
  const [form, setForm] = useState({
    receipt_date: new Date().toISOString().slice(0, 10),
    method: "TT", reference: "", bank_account: "", note: "" });
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api("/receivables/clients").then((r) => setClients(r.clients))
      .catch((e) => setError(e.message));
    api("/receivables/bank-accounts?active=1").then((r) => {
      setBanks(r.accounts);
      if (r.accounts.length) setForm((f) => ({ ...f,
        bank_account: String(r.accounts[0].id) }));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!siteId) { setInvoices([]); setAlloc({}); return; }
    api(`/receivables/invoices?site=${siteId}&outstanding=1`).then((r) => {
      setInvoices(r.invoices);
      const a = {};
      r.invoices.forEach((inv) => {
        a[invKey(inv)] = { on: false,
                           amount: Number(inv.outstanding).toFixed(2) };
      });
      setAlloc(a);
    }).catch((e) => setError(e.message));
  }, [siteId]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const setLine = (id, patch) =>
    setAlloc((a) => ({ ...a, [id]: { ...a[id], ...patch } }));
  const total = invoices.reduce((s, inv) => {
    const a = alloc[invKey(inv)];
    return s + (a?.on ? Number(a.amount) || 0 : 0);
  }, 0);

  async function save() {
    setError(null);
    const allocations = invoices
      .filter((inv) => alloc[invKey(inv)]?.on)
      .map((inv) => ({ claim_id: inv.claim_id,
                       manual_invoice_id: inv.manual_invoice_id,
                       amount: alloc[invKey(inv)].amount }));
    if (!allocations.length) { setError("Select at least one invoice."); return; }
    setSaving(true);
    try {
      const r = await api("/receivables/receipts", { method: "POST",
        body: { site: Number(siteId), ...form, allocations } });
      window.open(`/api/v1/receivables/receipts/${r.id}.pdf`, "_blank");
      onDone();
    } catch (e) { setError(e.message); }
    setSaving(false);
  }

  if (!clients) return <div style={card}>Loading…</div>;

  return (
    <div style={{ ...card, maxWidth: 820 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>New official receipt</h2>
        <button onClick={onCancel} style={{ border: "none", background: "none",
          cursor: "pointer", color: "var(--muted)", fontSize: 13 }}>Cancel</button>
      </div>
      {error && <div style={{ color: "var(--red-fg)", marginBottom: 10,
                              fontSize: 13 }}>{error}</div>}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                    marginBottom: 14 }}>
        <Field label="Client">
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}
            style={sel}>
            <option value="">Select client…</option>
            {clients.map((c) => (
              <option key={c.site_id} value={c.site_id}>
                {c.client} ({c.site_code}) — {money(c.outstanding)} due</option>
            ))}
          </select>
        </Field>
        <Field label="Receipt date">
          <input type="date" value={form.receipt_date}
                 onChange={set("receipt_date")} style={sel} /></Field>
        <Field label="Method">
          <select value={form.method} onChange={set("method")} style={sel}>
            {METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></Field>
        <Field label="TT / cheque reference">
          <input value={form.reference} onChange={set("reference")}
                 placeholder="bank ref" style={sel} /></Field>
        <Field label="Account credited">
          <select value={form.bank_account} onChange={set("bank_account")}
            style={sel}>
            <option value="">—</option>
            {banks.map((b) => (
              <option key={b.id} value={b.id}>
                {b.label}{b.currency ? ` (${b.currency})` : ""}</option>
            ))}
          </select></Field>
      </div>

      {siteId && (
        <div style={{ ...card, padding: 0, marginBottom: 12 }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}></th>
              <th style={{ ...th, textAlign: "left" }}>Invoice</th>
              <th style={{ ...th, textAlign: "left" }}>Project</th>
              <th style={{ ...th, textAlign: "left" }}>Due</th>
              <th style={{ ...th, textAlign: "right" }}>Outstanding</th>
              <th style={{ ...th, textAlign: "right" }}>Amount received</th>
            </tr></thead>
            <tbody>
              {!invoices.length && (
                <tr><td style={td} colSpan={6}>
                  No outstanding invoices for this client.</td></tr>
              )}
              {invoices.map((inv) => {
                const key = invKey(inv);
                const a = alloc[key] || {};
                return (
                  <tr key={key}>
                    <td style={{ ...td, textAlign: "center" }}>
                      <input type="checkbox" checked={!!a.on}
                        onChange={(e) => setLine(key,
                          { on: e.target.checked })} /></td>
                    <td style={{ ...td, ...mono }}>{inv.invoice_no}</td>
                    <td style={td}>{inv.project_code}</td>
                    <td style={td}>{fmtDate(inv.due_date)}
                      {inv.days_overdue > 0 && <> <Chip tone="alert">
                        {inv.days_overdue}d</Chip></>}</td>
                    <td style={{ ...td, textAlign: "right", ...mono }}>
                      {money(inv.outstanding)}</td>
                    <td style={{ ...td, textAlign: "right" }}>
                      <input type="number" step="0.01" value={a.amount || ""}
                        disabled={!a.on}
                        onChange={(e) => setLine(key,
                          { amount: e.target.value })}
                        style={{ ...sel, width: 110, textAlign: "right",
                          ...mono, opacity: a.on ? 1 : 0.5 }} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center" }}>
        <div style={{ fontSize: 15 }}>
          Total to receipt:{" "}
          <strong style={{ ...mono, color: "var(--navy)" }}>
            {money(total)} {invoices[0]?.currency || "USD"}</strong></div>
        <Btn variant="primary" onClick={save}
             disabled={saving || total <= 0}>
          {saving ? "Generating…" : "Generate receipt"}</Btn>
      </div>
    </div>
  );
}

const ORIGIN_LABEL = { HISTORICAL: "Historical", ISSUED: "Issued on Planet" };
// Draft → submitted → approved by a Director; only an approved invoice is
// owed (owner 2026-10-31).
const MI_STATUS = { DRAFT: ["Draft", "info"],
  SUBMITTED: ["Waiting for approval", "warn"], APPROVED: ["Approved", "ok"] };
const linkish = { border: "none", background: "none", cursor: "pointer",
  fontSize: 12, marginLeft: 8, padding: 0 };

// Manual client invoices — historical (recorded) + Planet-issued, for a project
// tracked mid-flight without rebuilding its BOQ / claims.
function ManualInvoices({ canManual }) {
  const [list, setList] = useState(null);
  const [presets, setPresets] = useState([]);
  const [error, setError] = useState(null);
  // null = the list; "new" = a new invoice; an invoice = editing that draft
  const [editing, setEditing] = useState(null);
  const load = () => api("/receivables/manual-invoices")
    .then((r) => { setList(r.invoices); setPresets(r.deduction_presets || []); })
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function step(mi, name, body) {
    setError(null);
    try {
      await api(`/receivables/manual-invoices/${mi.id}/${name}`,
                { method: "POST", body: body || {} });
      load();
    } catch (e) { setError(e.message); }
  }
  const approve = (mi) => {
    if (window.confirm(`Approve ${mi.label} for ${mi.currency} `
      + `${money(mi.amount)}? It becomes owed by the client`
      + (mi.invoice_no ? "." : " and takes the next invoice number."))) {
      step(mi, "approve");
    }
  };
  const sendBack = (mi) => {
    const note = window.prompt(`Return ${mi.label} to ${mi.submitted_by
      || "the QS"} — what needs changing?`);
    if (note && note.trim()) step(mi, "return", { note });
  };
  async function revise(mi) {
    const reason = window.prompt(`Reopen ${mi.label} as revision `
      + `${mi.revision + 1}? It keeps its number but is not owed until it is `
      + "approved again. Reason for the revision:");
    if (!reason || !reason.trim()) return;
    setError(null);
    try {
      const fresh = await api(`/receivables/manual-invoices/${mi.id}/reopen`,
                              { method: "POST", body: { reason } });
      setEditing(fresh);
    } catch (e) { setError(e.message); }
  }
  async function remove(mi) {
    if (!window.confirm(`Delete ${mi.label}? It was never approved, so `
      + "nothing else changes.")) return;
    try {
      await api(`/receivables/manual-invoices/${mi.id}`, { method: "DELETE" });
      load();
    } catch (e) { setError(e.message); }
  }

  // Tie an invoice to the claim that will take it over, or undo it. The
  // claim list is fetched per invoice because it is its project's claims,
  // and the invoice is where the QS is standing when they think of it.
  async function linkClaim(mi) {
    try {
      const claims = await api(`/receivables/manual-invoices/${mi.id}/claims`);
      if (!claims.length) {
        window.alert(`${mi.project_code} has no claims yet. Raise the advance `
          + "claim first, then link this invoice to it.");
        return;
      }
      if (mi.superseded_by) {
        if (!window.confirm(`Unlink ${mi.invoice_no} from `
          + `${mi.superseded_by}? It goes back to standing on its own.`)) return;
        await api(`/receivables/manual-invoices/${mi.id}/claim`,
                  { method: "DELETE" });
        load();
        return;
      }
      const pick = window.prompt(
        `Which claim will cover ${mi.invoice_no}?\n\n`
        + claims.map((c) => `${c.ref} — ${c.claim_type}, ${c.status}`)
            .join("\n") + "\n\nType the reference:");
      if (!pick) return;
      const c = claims.find((x) => x.ref.toLowerCase()
        === pick.trim().toLowerCase());
      if (!c) { window.alert(`No claim ${pick} on this project.`); return; }
      await api(`/receivables/manual-invoices/${mi.id}/claim`,
                { method: "POST", body: { claim_id: c.id } });
      load();
    } catch (e) { window.alert(e.message); }
  }

  async function voidInvoice(mi) {
    if (!window.confirm(`Void invoice ${mi.label}? It will drop off the `
      + "receivables. This can't be undone.")) return;
    try {
      await api(`/receivables/manual-invoices/${mi.id}/void`,
        { method: "POST" });
      load();
    } catch (e) { setError(e.message); }
  }

  if (editing) return <ManualInvoiceForm
    invoice={editing === "new" ? null : editing} presets={presets}
    onDone={() => { setEditing(null); load(); }}
    onCancel={() => { setEditing(null); load(); }} />;
  if (!list) return <div style={card}>Loading…</div>;

  const waiting = list.filter((mi) => mi.can_approve).length;
  return (
    <div>
      {error && <div style={{ color: "var(--red-fg)", marginBottom: 10,
        fontSize: 13 }}>{error}</div>}
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 10, gap: 12 }}>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          Invoices raised outside the claim flow. Drafted, submitted and
          approved by a Director — once approved they feed the same aging,
          statement &amp; receipts.
          {waiting > 0 && <b style={{ color: "var(--amber-fg)" }}>
            {" "}{waiting} waiting for your approval.</b>}</span>
        {canManual && <Btn variant="primary"
          onClick={() => setEditing("new")}>+ New invoice</Btn>}
      </div>
      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
          fontSize: 13 }}>
          <thead><tr>
            <th style={{ ...th, textAlign: "left" }}>Date</th>
            <th style={{ ...th, textAlign: "left" }}>Invoice</th>
            <th style={{ ...th, textAlign: "left" }}>Project</th>
            <th style={{ ...th, textAlign: "left" }}>Status</th>
            <th style={{ ...th, textAlign: "right" }}>Amount</th>
            <th style={{ ...th, textAlign: "right" }}>Received</th>
            <th style={{ ...th, textAlign: "right" }}>Outstanding</th>
            <th style={th}></th>
          </tr></thead>
          <tbody>
            {!list.length && <tr><td style={td} colSpan={8}>
              No manual invoices recorded.</td></tr>}
            {list.map((mi) => {
              const [stLabel, stTone] = MI_STATUS[mi.status] || [mi.status];
              const owed = mi.status === "APPROVED";
              return (
              <tr key={mi.id}>
                <td style={td}>{fmtDate(mi.invoice_date)}</td>
                <td style={{ ...td, minWidth: 170 }}>
                  {mi.invoice_no ? <span style={mono}>{mi.invoice_no}</span>
                    : <span style={{ color: "var(--muted)" }}>
                      No number yet</span>}
                  {mi.revision > 0 && <span style={{ color: "var(--muted)",
                    fontSize: 11 }}> Rev {mi.revision}</span>}
                  <div style={{ color: "var(--muted)", fontSize: 11 }}>
                    {ORIGIN_LABEL[mi.origin]}
                    {mi.description ? ` · ${mi.description}` : ""}</div>
                </td>
                <td style={td}>{mi.project_code}</td>
                <td style={td}>
                  <Chip tone={stTone}>{stLabel}</Chip>
                  {mi.status === "SUBMITTED" && mi.submitted_by && (
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>
                      from {mi.submitted_by}</div>)}
                  {mi.status === "APPROVED" && mi.approved_by && (
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>
                      by {mi.approved_by}</div>)}
                  {mi.status === "DRAFT" && mi.return_note && (
                    <div style={{ fontSize: 11, color: "var(--amber-fg)",
                      maxWidth: 220 }}>{mi.return_note}</div>)}
                </td>
                <td style={{ ...td, textAlign: "right", ...mono }}>
                  {money(mi.amount)}
                  <span style={{ fontSize: 10.5, color: "var(--muted)" }}>
                    {" "}{mi.currency}</span>
                  {Number(mi.deducted_before_gst) + Number(mi.deducted_after_gst)
                    > 0 && (
                    <div style={{ fontSize: 10.5, color: "var(--muted)" }}>
                      after {money(Number(mi.deducted_before_gst)
                        + Number(mi.deducted_after_gst))} deducted</div>)}
                </td>
                <td style={{ ...td, textAlign: "right", ...mono }}>
                  {owed ? dash(mi.received) : "—"}</td>
                <td style={{ ...td, textAlign: "right", ...mono }}>
                  {owed ? <>{money(mi.outstanding)}
                    <span style={{ fontSize: 10.5, color: "var(--muted)" }}>
                      {" "}{mi.currency}</span></> : "—"}</td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  {mi.can_edit && (
                    <button onClick={() => setEditing(mi)}
                      style={{ ...linkish, color: "var(--sky)", marginLeft: 0 }}>
                      Edit</button>)}
                  {mi.can_submit && (
                    <button onClick={() => step(mi, "submit")}
                      style={{ ...linkish, color: "var(--sky)" }}>
                      Submit</button>)}
                  {mi.can_approve && (<>
                    <button onClick={() => approve(mi)}
                      style={{ ...linkish, color: "var(--green-fg)",
                        fontWeight: 700, marginLeft: 0 }}>Approve</button>
                    <button onClick={() => sendBack(mi)}
                      style={{ ...linkish, color: "var(--amber-fg)" }}>
                      Return</button></>)}
                  {mi.can_pdf && <a href={`/api/v1/receivables/`
                    + `manual-invoices/${mi.id}.pdf`} target="_blank"
                    rel="noreferrer" style={{ color: "var(--sky)",
                      fontSize: 12, marginLeft: 8 }}>
                    {owed ? "PDF" : "Draft PDF"}</a>}
                  {mi.has_attachment && <span style={{ color: "var(--muted)",
                    fontSize: 11, marginLeft: 8 }}>📎</span>}
                  {mi.can_reopen && (
                    <button onClick={() => revise(mi)}
                      title="Correct it and send it for approval again"
                      style={{ ...linkish, color: "var(--sky)" }}>
                      Revise</button>)}
                  {mi.can_delete && (
                    <button onClick={() => remove(mi)}
                      style={{ ...linkish, color: "var(--red-fg)" }}>
                      Delete</button>)}
                  {canManual && owed && Number(mi.received) === 0 && (
                    <button onClick={() => voidInvoice(mi)}
                      style={{ ...linkish, color: "var(--red-fg)" }}>
                      Void</button>)}
                  {/* Billed ahead of the claim that covers it — an advance
                      against a signed LOA, say. Linking closes this invoice
                      when that claim is certified, so the same money is not
                      owed twice (owner 2026-09-01). */}
                  {canManual && owed && (mi.superseded_by ? (
                    <button onClick={() => linkClaim(mi)}
                      title={mi.superseded_at
                        ? `Closed by ${mi.superseded_by}`
                        : `Will close when ${mi.superseded_by} is certified`}
                      style={{ ...linkish, color: "var(--muted)" }}>
                      → {mi.superseded_by}</button>
                  ) : (
                    <button onClick={() => linkClaim(mi)}
                      title="Link this invoice to the claim that will cover it"
                      style={{ ...linkish, color: "var(--sky)" }}>
                      Link to claim</button>
                  ))}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const blankLine = (kind = "CHARGE") => ({ kind, description: "", quantity: "",
  unit_price: "", amount: "", before_gst: true });
// A saved line as the form edits it: a deduction is typed as a positive
// figure under "Less", whatever sign it is stored with.
const formLine = (ln) => ({
  kind: ln.kind || "CHARGE", description: ln.description || "",
  quantity: ln.quantity != null ? String(Number(ln.quantity)) : "",
  unit_price: ln.unit_price != null ? String(Math.abs(Number(ln.unit_price)))
    : "",
  amount: ln.amount != null ? String(Math.abs(Number(ln.amount))) : "",
  before_gst: ln.before_gst !== false });

// New invoice, or a draft being changed (its own, a returned one, or a
// revision). Charges, then deductions — advance recovery, retention, back
// charges — taken off before GST (the taxable net) or after it.
function ManualInvoiceForm({ invoice, presets, onDone, onCancel }) {
  const [sites, setSites] = useState(null);
  const [projects, setProjects] = useState([]);
  const [siteId, setSiteId] = useState(invoice ? String(invoice.site_id) : "");
  const [form, setForm] = useState(invoice ? {
    origin: invoice.origin, project_id: String(invoice.project_id),
    invoice_no: invoice.origin === "HISTORICAL" ? invoice.invoice_no : "",
    invoice_date: invoice.invoice_date,
    due_date: invoice.due_date && invoice.due_date !== invoice.invoice_date
      ? invoice.due_date : "",
    gst_pct: String(Number(invoice.gst_pct)), currency: invoice.currency,
    description: invoice.description || "", note: invoice.note || "",
  } : {
    origin: "HISTORICAL", project_id: "", invoice_no: "",
    invoice_date: new Date().toISOString().slice(0, 10), due_date: "",
    gst_pct: "8", currency: "USD", description: "", note: "" });
  const [lines, setLines] = useState(invoice && invoice.lines.length
    ? invoice.lines.map(formLine) : [blankLine()]);
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [firstSite, setFirstSite] = useState(true);

  useEffect(() => {
    api("/sites").then((r) => setSites(Array.isArray(r) ? r : (r.results || [])))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!siteId) { setProjects([]); return; }
    api(`/sites/${siteId}/projects`)
      .then((r) => setProjects(Array.isArray(r) ? r : (r.results || [])))
      .catch(() => setProjects([]));
    // an invoice being edited keeps its project and currency on first load
    if (firstSite && invoice) { setFirstSite(false); return; }
    setFirstSite(false);
    // The invoice follows the contract's currency — MVR for an MVR-based
    // project like MRA, USD otherwise (owner 2026-08-27). Still editable.
    const site = (sites || []).find((x) => String(x.id) === String(siteId));
    setForm((f) => ({ ...f, project_id: "",
                      currency: (site?.currency || "USD").toUpperCase() }));
  }, [siteId]);   // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const issued = form.origin === "ISSUED";
  const revision = invoice && invoice.approved_at;

  // Line edits: qty × unit price auto-fills the line amount.
  const setLine = (i, k, v) => setLines((ls) => ls.map((ln, j) => {
    if (j !== i) return ln;
    const next = { ...ln, [k]: v };
    if (k === "quantity" || k === "unit_price") {
      const q = parseFloat(k === "quantity" ? v : next.quantity);
      const u = parseFloat(k === "unit_price" ? v : next.unit_price);
      if (!isNaN(q) && !isNaN(u)) next.amount = (q * u).toFixed(2);
    }
    return next;
  }));
  const addLine = (kind) => setLines((ls) => [...ls, blankLine(kind)]);
  const removeLine = (i) => setLines((ls) => ls.filter((_, j) => j !== i));

  // Live totals, the order the server keeps: charges, less deductions before
  // GST = taxable net; GST on that; less deductions after GST = total.
  const amt = (ln) => Math.abs(Number(ln.amount) || 0);
  const charges = lines.filter((ln) => ln.kind === "CHARGE")
    .reduce((s, ln) => s + (Number(ln.amount) || 0), 0);
  const pre = lines.filter((ln) => ln.kind === "DEDUCTION" && ln.before_gst)
    .reduce((s, ln) => s + amt(ln), 0);
  const post = lines.filter((ln) => ln.kind === "DEDUCTION" && !ln.before_gst)
    .reduce((s, ln) => s + amt(ln), 0);
  const net = charges - pre;
  const gstPct = Number(form.gst_pct) || 0;
  const gst = Math.round(net * gstPct) / 100;
  const total = net + gst - post;

  async function save(submit) {
    setError(null);
    if (!form.project_id) { setError("Choose the project."); return; }
    if (!issued && !form.invoice_no.trim()) {
      setError("Enter the client's invoice number."); return; }
    const clean = lines
      .filter((ln) => ln.description.trim() && Number(ln.amount))
      .map((ln) => ({ kind: ln.kind, description: ln.description.trim(),
        quantity: ln.quantity || null, unit_price: ln.unit_price || null,
        amount: ln.amount, before_gst: ln.before_gst }));
    if (!clean.some((ln) => ln.kind === "CHARGE")) {
      setError("Add at least one charge with a description and amount.");
      return;
    }
    if (net <= 0 || total <= 0) {
      setError("The deductions take the invoice to nothing — check them.");
      return;
    }
    setSaving(true);
    try {
      const fd = new FormData();
      ["origin", "project_id", "invoice_date", "due_date", "gst_pct",
        "currency", "description", "note"].forEach((k) => {
        if (form[k] !== "" && form[k] != null) fd.append(k, form[k]);
      });
      if (!issued) fd.append("invoice_no", form.invoice_no);
      fd.append("lines", JSON.stringify(clean));
      if (submit) fd.append("submit", "true");
      if (file) fd.append("attachment", file);
      const mi = invoice
        ? await apiUpload(`/receivables/manual-invoices/${invoice.id}`, fd,
                          "PATCH")
        : await apiUpload("/receivables/manual-invoices", fd);
      if (mi && mi.detail) { setError(mi.detail); setSaving(false); return; }
      onDone();
    } catch (e) { setError(e.message); }
    setSaving(false);
  }

  if (!sites) return <div style={card}>Loading…</div>;

  const lineRow = (ln, i) => {
    const ded = ln.kind === "DEDUCTION";
    return (
      <tr key={i}>
        <td style={{ padding: 2 }}>
          <input value={ln.description} list={ded ? "mi-deductions" : undefined}
            onChange={(e) => setLine(i, "description", e.target.value)}
            placeholder={ded ? "e.g. Advance recovery"
              : "e.g. Excavator rental / Food provision"}
            style={{ ...sel, width: "100%" }} /></td>
        <td style={{ padding: 2 }}>
          <input type="number" step="0.01" value={ln.quantity}
            onChange={(e) => setLine(i, "quantity", e.target.value)}
            style={{ ...sel, width: "100%", textAlign: "right", ...mono }} />
        </td>
        <td style={{ padding: 2 }}>
          <input type="number" step="0.01" value={ln.unit_price}
            onChange={(e) => setLine(i, "unit_price", e.target.value)}
            style={{ ...sel, width: "100%", textAlign: "right", ...mono }} />
        </td>
        <td style={{ padding: 2 }}>
          <input type="number" step="0.01" min={ded ? "0" : undefined}
            value={ln.amount}
            onChange={(e) => setLine(i, "amount", e.target.value)}
            style={{ ...sel, width: "100%", textAlign: "right", ...mono,
                     color: ded ? "var(--red-fg)" : undefined }} />
        </td>
        <td style={{ padding: "2px 4px", fontSize: 11.5, whiteSpace: "nowrap",
                     color: "var(--muted)" }}>
          {ded && (
            <label title="Taken off before GST is worked out (advance
              recovery, retention), or after it">
              <input type="checkbox" checked={ln.before_gst}
                onChange={(e) => setLine(i, "before_gst", e.target.checked)} />
              {" "}before GST</label>)}
        </td>
        <td style={{ padding: 2, textAlign: "center" }}>
          <button type="button" onClick={() => removeLine(i)}
            title="Remove line" style={{ border: "none",
              background: "none", cursor: "pointer",
              color: "var(--muted)", fontSize: 16 }}>×</button>
        </td>
      </tr>
    );
  };
  const indexed = lines.map((ln, i) => [ln, i]);
  const tot = (labelText, value, opts = {}) => (
    <div style={{ display: "flex", justifyContent: "space-between",
      padding: "3px 0", alignItems: "center", ...(opts.style || {}) }}>
      <span style={{ color: opts.strong ? undefined : "var(--muted)" }}>
        {labelText}</span>
      <b style={{ ...mono, color: opts.red ? "var(--red-fg)"
        : opts.strong ? "var(--navy)" : undefined }}>{value}</b></div>);

  return (
    <div style={{ ...card, maxWidth: 880 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>
          {!invoice ? "New client invoice"
            : revision ? `Revise ${invoice.label} — revision ${invoice.revision}`
              : `Edit ${invoice.label}`}</h2>
        <button onClick={onCancel} style={{ border: "none", background: "none",
          cursor: "pointer", color: "var(--muted)", fontSize: 13 }}>
          {invoice ? "Close" : "Cancel"}</button>
      </div>
      {invoice && invoice.return_note && (
        <div style={{ background: "var(--amber-bg)", color: "var(--amber-fg)",
          padding: "8px 12px", borderRadius: 6, fontSize: 13,
          marginBottom: 10 }}>{invoice.return_note}</div>)}
      {error && <div style={{ color: "var(--red-fg)", marginBottom: 10,
        fontSize: 13 }}>{error}</div>}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
        marginBottom: 6 }}>
        <Field label="Invoice type">
          <select value={form.origin} onChange={set("origin")} style={sel}
                  disabled={!!revision}>
            <option value="HISTORICAL">Historical — record only</option>
            <option value="ISSUED">Issue on Planet — generate PDF</option>
          </select></Field>
        <Field label="Client">
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}
            style={sel}>
            <option value="">Select client…</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.client_name || s.name} ({s.code})</option>
            ))}
          </select></Field>
        <Field label="Project">
          <select value={form.project_id} onChange={set("project_id")}
            style={sel} disabled={!siteId}>
            <option value="">Select project…</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.code} — {p.title}</option>
            ))}
          </select></Field>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
        marginBottom: 6 }}>
        {issued ? (
          <Field label="Invoice number">
            <input value={invoice && invoice.invoice_no
              ? invoice.invoice_no : "Given on approval"} disabled
              style={{ ...sel, color: "var(--muted)", width: 170 }} /></Field>
        ) : (
          <Field label="Client's invoice number">
            <input value={form.invoice_no} onChange={set("invoice_no")}
              placeholder="e.g. INV/2024/07" style={sel} /></Field>
        )}
        <Field label="Invoice date">
          <input type="date" value={form.invoice_date}
            onChange={set("invoice_date")} style={sel} /></Field>
        <Field label="Due date (optional)">
          <input type="date" value={form.due_date} onChange={set("due_date")}
            style={sel} /></Field>
      </div>

      <datalist id="mi-deductions">
        {presets.map((p) => <option key={p} value={p} />)}
      </datalist>
      <table style={{ width: "100%", borderCollapse: "collapse",
        fontSize: 13, margin: "10px 0 6px" }}>
        <thead><tr>
          <th style={{ ...th, textAlign: "left" }}>Charges</th>
          <th style={{ ...th, textAlign: "right", width: 70 }}>Qty</th>
          <th style={{ ...th, textAlign: "right", width: 100 }}>Unit price</th>
          <th style={{ ...th, textAlign: "right", width: 120 }}>Amount</th>
          <th style={{ ...th, width: 90 }}></th>
          <th style={{ ...th, width: 28 }}></th>
        </tr></thead>
        <tbody>
          {indexed.filter(([ln]) => ln.kind === "CHARGE")
            .map(([ln, i]) => lineRow(ln, i))}
          <tr><td colSpan={6} style={{ padding: "4px 2px 10px" }}>
            <button type="button" onClick={() => addLine("CHARGE")}
              style={{ ...ghostButton, padding: "3px 12px", fontSize: 13 }}>
              + Add charge</button></td></tr>
          <tr><td colSpan={6} style={{ ...th, textAlign: "left" }}>
            Less — deductions
            <span style={{ fontWeight: 400, textTransform: "none",
              letterSpacing: 0, marginLeft: 8 }}>
              advance recovery, retention, back charges — type the amount
              to take off</span></td></tr>
          {indexed.filter(([ln]) => ln.kind === "DEDUCTION")
            .map(([ln, i]) => lineRow(ln, i))}
          <tr><td colSpan={6} style={{ padding: "4px 2px" }}>
            <button type="button" onClick={() => addLine("DEDUCTION")}
              style={{ ...ghostButton, padding: "3px 12px", fontSize: 13 }}>
              + Add deduction</button></td></tr>
        </tbody>
      </table>

      {/* System-computed totals, in the server's order */}
      <div style={{ display: "flex", justifyContent: "flex-end",
        margin: "6px 0 10px" }}>
        <div style={{ minWidth: 300, fontSize: 13 }}>
          {(pre > 0 || post > 0) && tot("Charges", money(charges))}
          {pre > 0 && tot("Less deductions before GST", `(${money(pre)})`,
                          { red: true })}
          {tot(pre > 0 ? "Net (taxable)" : "Net", money(net))}
          <div style={{ display: "flex", justifyContent: "space-between",
            padding: "3px 0", alignItems: "center" }}>
            <span style={{ color: "var(--muted)" }}>GST @{" "}
              <input type="number" step="0.01" value={form.gst_pct}
                onChange={set("gst_pct")}
                style={{ ...sel, width: 56, padding: "2px 6px",
                  textAlign: "right", ...mono }} /> %</span>
            <b style={mono}>{money(gst)}</b></div>
          {post > 0 && tot("Less deductions after GST", `(${money(post)})`,
                           { red: true })}
          <div style={{ display: "flex", justifyContent: "space-between",
            padding: "6px 0", borderTop: "1px solid var(--line)",
            fontSize: 15 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              Total
              <select value={form.currency} onChange={set("currency")}
                      style={{ ...sel, width: 74, padding: "2px 6px" }}>
                <option>USD</option><option>MVR</option>
              </select>
            </span>
            <b style={{ ...mono, color: "var(--navy)" }}>{money(total)}</b></div>
        </div>
      </div>

      <div style={{ marginBottom: 6 }}>
        <Field label="Invoice summary (optional — a heading for the statement)">
          <input value={form.description} onChange={set("description")}
            placeholder="e.g. Miscellaneous charges — July"
            style={{ ...sel, width: "100%" }} /></Field>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
        alignItems: "flex-end", marginBottom: 14 }}>
        <Field label={issued ? "Attach (optional)"
          : "Attach the actual invoice (optional)"}>
          <input type="file" accept="application/pdf,image/*"
            onChange={(e) => setFile(e.target.files[0] || null)}
            style={{ fontSize: 12 }} /></Field>
        <Field label="Internal note (optional)">
          <input value={form.note} onChange={set("note")}
            style={{ ...sel, width: 260 }} /></Field>
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8,
                    alignItems: "center" }}>
        <span style={{ fontSize: 12, color: "var(--muted)", marginRight: 6 }}>
          Not owed by the client until a Director approves it.</span>
        <Btn onClick={() => save(false)} disabled={saving}>Save draft</Btn>
        <Btn variant="primary" onClick={() => save(true)} disabled={saving}>
          {saving ? "Saving…" : "Submit for approval"}</Btn>
      </div>
    </div>
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
