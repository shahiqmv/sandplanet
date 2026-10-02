// Import from Excel: bring a spreadsheet of transactions into the books — how
// the months before PLANET held the operations are caught up. The file is
// checked first and nothing is saved; then it goes in whole, or not at all.
// (FINANCE_BUILD_BRIEF.md, stage 2)
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiDownload, apiUpload } from "../api.js";
import { Btn, Chip, card, inputStyle } from "../ui.jsx";
import { fmtDate, money } from "./shared.jsx";

export default function ImportPage({ canEdit }) {
  const [file, setFile] = useState(null);
  const [res, setRes] = useState(null);             // the check, or the import
  const [history, setHistory] = useState(null);
  const [undoing, setUndoing] = useState(null);     // {id, reason}
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);
  const load = useCallback(() => api("/ledger/imports").then((d) => setHistory(d.imports)).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  async function send(commit) {
    setBusy(true); setError(null);
    const fd = new FormData(); fd.append("file", file); fd.append("commit", commit ? "1" : "0");
    try {
      const r = await apiUpload("/ledger/imports", fd, "POST");
      setRes(r);
      if (r.imported) { setFile(null); if (inputRef.current) inputRef.current.value = ""; load(); }
    } catch (e) { setError(e.message); setRes(null); } finally { setBusy(false); }
  }
  async function undo() {
    setError(null);
    try { const d = await api(`/ledger/imports/${undoing.id}/undo`, { method: "POST", body: { reason: undoing.reason } }); setHistory(d.imports); setUndoing(null); }
    catch (e) { setError(e.message); }
  }
  const bad = res ? res.rows.filter((r) => r.error) : [];
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Import from Excel</h1>
        <span className="spacer" />
        <Btn variant="secondary" onClick={() => apiDownload("/ledger/import/template").catch((e) => setError(e.message))}>⬇ Download the template</Btn>
      </div>
      <p style={{ fontSize: 13.5, color: "var(--muted)", marginTop: -4, maxWidth: 820 }}>
        For catching up the months before PLANET held the operations. Fill the template — one row per expense, deposit, transfer,
        bill or invoice — and bring it in a month or two at a time. Each row goes through the same rules as its form. The file is
        checked first; nothing is saved until every row is right.</p>

      {canEdit && (
        <div style={{ ...card, marginBottom: 12 }}>
          <div className="f-bar" style={{ margin: 0 }}>
            <input ref={inputRef} type="file" accept=".xlsx,.xlsm" onChange={(e) => { setFile(e.target.files[0] || null); setRes(null); setError(null); }} />
            <Btn disabled={!file || busy} onClick={() => send(false)}>{busy ? "Working…" : "Check the file"}</Btn>
            {res && !res.imported && res.errors === 0 && file &&
              <Btn disabled={busy} onClick={() => send(true)}>Import {res.count} transaction{res.count === 1 ? "" : "s"}</Btn>}
          </div>
        </div>)}
      {error && <p className="f-bad" style={{ fontSize: 13.5 }}>{error}</p>}

      {res && (
        <>
          <p style={{ fontSize: 14 }} className={res.errors ? "f-bad" : "f-ok"}>
            {res.imported ? `✓ Imported ${res.count} transactions, MVR ${money(res.total_mvr)} in all.`
              : res.errors ? `${res.errors} of ${res.count} transactions can't go in. Correct the file and check it again — nothing has been saved.`
                : `✓ All ${res.count} transactions are in order (MVR ${money(res.total_mvr)}). Nothing is saved yet — press Import.`}</p>
          <div style={{ ...card, padding: 0, overflowX: "auto", marginBottom: 16 }}>
            <table className="f-table">
              <thead><tr><th>Row</th><th>Type</th><th>Date</th><th>Name</th><th>Reference</th><th style={{ textAlign: "right" }}>Amount</th>
                <th>{res.imported ? "Number" : "Result"}</th></tr></thead>
              <tbody>{(bad.length ? [...bad, ...res.rows.filter((r) => !r.error)] : res.rows).map((r) => (
                <tr key={r.row}>
                  <td>{r.row}{r.lines > 1 ? `–${r.row + r.lines - 1}` : ""}</td><td>{r.type}</td><td style={{ whiteSpace: "nowrap" }}>{r.date ? fmtDate(r.date) : ""}</td>
                  <td>{r.party}</td><td>{r.reference}</td>
                  <td className="f-num">{r.amount != null ? `${r.currency || ""} ${money(r.amount)}` : ""}</td>
                  <td>{r.error ? <span className="f-bad" style={{ fontWeight: 500 }}>{r.error}</span>
                    : res.imported ? <span style={{ fontFamily: "var(--font-mono)" }}>{r.number}</span>
                      : res.errors ? <span style={{ color: "var(--muted)" }}>in order</span> : <span className="f-ok">✓</span>}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </>)}

      <h3 style={{ margin: "8px 0 8px" }}>Files imported</h3>
      {!history ? <div style={card}>Loading…</div> : history.length === 0 ? <div style={card}>None yet.</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Imported</th><th>File</th><th>By</th><th style={{ textAlign: "right" }}>Transactions</th>
              <th style={{ textAlign: "right" }}>MVR</th><th /></tr></thead>
            <tbody>{history.map((b) => (
              <tr key={b.id} style={b.undone ? { opacity: .55 } : undefined}>
                <td style={{ whiteSpace: "nowrap" }}>{fmtDate(b.at)}</td>
                <td>{b.file_url ? <a href={b.file_url} target="_blank" rel="noreferrer">{b.filename}</a> : b.filename}</td>
                <td>{b.by}</td><td className="f-num">{b.count}</td><td className="f-num">{money(b.total_mvr)}</td>
                <td>{b.undone ? <Chip tone="alert">Undone</Chip>
                  : canEdit && (undoing?.id === b.id ? (
                    <span className="f-bar" style={{ margin: 0 }}>
                      <input style={{ ...inputStyle, width: 220 }} placeholder="Why is it being undone?" value={undoing.reason}
                             onChange={(e) => setUndoing({ ...undoing, reason: e.target.value })} />
                      <Btn variant="secondary" onClick={undo}>Void all {b.count}</Btn>
                      <button className="f-link" onClick={() => setUndoing(null)}>cancel</button></span>
                  ) : <button className="f-link" onClick={() => setUndoing({ id: b.id, reason: "" })}>Undo…</button>)}</td>
              </tr>))}</tbody>
          </table>
        </div>)}
    </div>
  );
}
