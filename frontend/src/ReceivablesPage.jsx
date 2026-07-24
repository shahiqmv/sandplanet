import { useEffect, useState } from "react";
import { api } from "./api.js";
import { card, th, td, Btn, Chip } from "./ui.jsx";

const RECEIPT_ROLES = ["FINANCE", "ADMIN"];
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

const TABS = [["aging", "Aging analysis"], ["statement", "Statement of account"],
  ["receipts", "Official receipts"]];

// Client receivables — invoice due dates, aging buckets, per-client statements
// and official receipts over the certified claims (IPCs). Finance / QS /
// Director.
export default function ReceivablesPage({ me }) {
  const [tab, setTab] = useState("aging");
  const canReceipt = RECEIPT_ROLES.includes(me.role);
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
      {tab === "aging" && <Aging />}
      {tab === "statement" && <Statement />}
      {tab === "receipts" && <Receipts canReceipt={canReceipt} />}
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
        a[inv.claim_id] = { on: false, amount: Number(inv.outstanding).toFixed(2) };
      });
      setAlloc(a);
    }).catch((e) => setError(e.message));
  }, [siteId]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const setLine = (id, patch) =>
    setAlloc((a) => ({ ...a, [id]: { ...a[id], ...patch } }));
  const total = invoices.reduce((s, inv) =>
    s + (alloc[inv.claim_id]?.on ? Number(alloc[inv.claim_id].amount) || 0 : 0), 0);

  async function save() {
    setError(null);
    const allocations = invoices
      .filter((inv) => alloc[inv.claim_id]?.on)
      .map((inv) => ({ claim_id: inv.claim_id,
                       amount: alloc[inv.claim_id].amount }));
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
                const a = alloc[inv.claim_id] || {};
                return (
                  <tr key={inv.claim_id}>
                    <td style={{ ...td, textAlign: "center" }}>
                      <input type="checkbox" checked={!!a.on}
                        onChange={(e) => setLine(inv.claim_id,
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
                        onChange={(e) => setLine(inv.claim_id,
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
            {money(total)} USD</strong></div>
        <Btn variant="primary" onClick={save}
             disabled={saving || total <= 0}>
          {saving ? "Generating…" : "Generate receipt"}</Btn>
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
