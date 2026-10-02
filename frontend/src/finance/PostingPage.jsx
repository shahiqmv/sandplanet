// Posting from Planet: which of Planet's own events post to the books, what
// each one posts, a preview of exactly what it would do over the history, and
// the switch. Costs land in the account mapped to each cost head.
// (FINANCE_BUILD_BRIEF.md, stage 3 — core/posting.py)
import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { Btn, Chip, card, inputStyle } from "../ui.jsx";
import { amt, fmtDate, money, tree } from "./shared.jsx";

function Report({ report, saved }) {
  const [open, setOpen] = useState(null);
  return (
    <div style={{ ...card, padding: 0, marginBottom: 14 }}>
      <table className="f-table">
        <thead><tr><th>{saved ? "Posted" : "Preview — nothing has been saved"}</th>
          <th style={{ textAlign: "right" }}>{saved ? "Entries posted" : "Entries to post"}</th>
          <th style={{ textAlign: "right" }}>MVR</th><th style={{ textAlign: "right" }}>Reversed</th>
          <th style={{ textAlign: "right" }}>Already right</th><th style={{ textAlign: "right" }}>Held back</th></tr></thead>
        <tbody>{report.map((r) => {
          // the reasons, each once, with how many it holds
          const why = {};
          r.held.forEach((h) => { (why[h.why] = why[h.why] || []).push(h.what); });
          return (
            <Fragment key={r.rule}>
              <tr className="f-click" onClick={() => setOpen(open === r.rule ? null : r.rule)}>
                <td style={{ fontWeight: 600 }}>{open === r.rule ? "▾ " : "▸ "}{r.name}</td>
                <td className="f-num">{r.post || ""}</td><td className="f-num">{amt(r.post_mvr)}</td>
                <td className="f-num">{r.reverse || ""}</td><td className="f-num">{r.same || ""}</td>
                <td className={"f-num" + (r.held.length ? " f-bad" : "")}>{r.held.length || ""}</td>
              </tr>
              {open === r.rule && (
                <tr><td colSpan={6} style={{ background: "#fbfaf6", padding: "10px 16px" }}>
                  {Object.keys(why).length > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <b>Held back — nothing is guessed:</b>
                      {Object.entries(why).map(([reason, whats]) => (
                        <div key={reason} style={{ fontSize: 13, margin: "3px 0" }}>
                          <span className="f-bad" style={{ fontWeight: 500 }}>{whats.length} ×</span> {reason}
                          <span style={{ color: "var(--muted)" }}> — {whats.slice(0, 4).join(", ")}{whats.length > 4 ? ` and ${whats.length - 4} more` : ""}</span>
                        </div>))}
                    </div>)}
                  {r.sample.length === 0 ? <span style={{ color: "var(--muted)", fontSize: 13 }}>Nothing new to post.</span> : (
                    <>
                      <b>{saved ? "Posted" : "Would post"}{r.post > r.sample.length ? ` — the first ${r.sample.length} of ${r.post}` : ""}:</b>
                      {r.sample.map((s, i) => (
                        <div key={i} style={{ fontSize: 13, margin: "8px 0 0" }}>
                          <div>{fmtDate(s.date)} · {s.memo}</div>
                          <table style={{ marginLeft: 14, fontSize: 12.5, borderCollapse: "collapse" }}><tbody>
                            {s.lines.map((l, j) => (
                              <tr key={j}>
                                <td style={{ padding: "1px 14px 1px 0", paddingLeft: Number(l.credit) ? 22 : 0 }}>{l.account}{l.site ? ` · ${l.site}` : ""}</td>
                                <td className="f-num" style={{ padding: "1px 12px", minWidth: 96 }}>{amt(l.debit)}</td>
                                <td className="f-num" style={{ padding: "1px 0", minWidth: 96 }}>{amt(l.credit)}</td>
                              </tr>))}
                          </tbody></table>
                        </div>))}
                    </>)}
                </td></tr>)}
            </Fragment>);
        })}</tbody>
      </table>
    </div>
  );
}

export default function PostingPage() {
  const [d, setD] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [result, setResult] = useState(null);       // {report, saved}
  const [from, setFrom] = useState("");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  // every reply carries the whole state; keep what an older reply lacked
  const take = useCallback((x) => { setD((cur) => ({ ...(cur || {}), ...x })); setFrom(x.from || ""); }, []);
  useEffect(() => {
    api("/ledger/posting").then(take).catch((e) => setError(e.message));
    api("/ledger/accounts").then((x) => setAccounts(tree(x.accounts).filter((a) => !a.is_group && a.is_active))).catch(() => {});
  }, [take]);

  async function call(label, fn) {
    setBusy(label); setError(null);
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(null); }
  }
  const preview = (rules) => call("preview", async () => setResult(await api("/ledger/posting/preview", { method: "POST", body: { rules } })));
  const postNow = (rules) => call("run", async () => {
    setResult(await api("/ledger/posting/run", { method: "POST", body: rules ? { rules } : {} }));
    take(await api("/ledger/posting"));
  });
  async function toggle(rule) {
    const on = d.rules.filter((r) => r.on).map((r) => r.key);
    if (rule.on) {
      if (!window.confirm(`Switch “${rule.name}” off? Its entries stay in the books; new events will no longer be posted.`)) return;
      await call("switch", async () => take(await api("/ledger/posting", { method: "POST", body: { on: on.filter((k) => k !== rule.key) } })));
    } else {
      if (!window.confirm(`Switch “${rule.name}” on? Everything it covers from ${fmtDate(d.from)} is posted to the books now, and kept in step from here on.`)) return;
      await call("switch", async () => {
        take(await api("/ledger/posting", { method: "POST", body: { on: [...on, rule.key] } }));
        setResult(await api("/ledger/posting/run", { method: "POST", body: { rules: [rule.key] } }));
        take(await api("/ledger/posting"));
      });
    }
  }
  const takeOut = (rule) => {
    if (!window.confirm(`Take every “${rule.name}” entry out of the books? Each is reversed; nothing is deleted.`)) return;
    call("out", async () => take(await api("/ledger/posting/take-out", { method: "POST", body: { rule: rule.key } })));
  };
  const saveFrom = () => call("from", async () => take(await api("/ledger/posting", { method: "POST", body: { from } })));
  const mapHead = (h, account) => call("head", async () => {
    const x = await api(`/ledger/posting/heads/${h.id}`, { method: "PATCH", body: { account: account || null } });
    setD((cur) => ({ ...cur, heads: x.heads }));
  });

  if (!d) return <div style={card}>{error || "Loading…"}</div>;
  const anyOn = d.rules.some((r) => r.on);
  // only a head Planet has actually posted costs under needs an account now
  const unmapped = d.heads.filter((h) => !h.account && h.used);
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Posting from Planet</h1>
        <span className="spacer" />
        {d.can_edit && <>
          <Btn variant="secondary" disabled={!!busy} onClick={() => preview(d.rules.map((r) => r.key))}>{busy === "preview" ? "Working…" : "Preview all"}</Btn>
          <Btn disabled={!!busy || !anyOn} onClick={() => postNow()}>{busy === "run" ? "Posting…" : "Post now"}</Btn>
        </>}
      </div>
      <p style={{ fontSize: 13.5, color: "var(--muted)", marginTop: -4, maxWidth: 900 }}>
        Each rule takes something Planet already records and gives it one entry in the books. A rule posts nothing until it is
        switched on; once on, the books are kept in step every twenty minutes — a new event is posted, a changed one re-posted,
        a deleted one reversed. Preview shows exactly what a rule would do, and saves nothing. While a rule is on, the
        forms that could enter the same thing by hand ask for a tick confirming it is not in Planet.</p>
      {error && <p className="f-bad" style={{ fontSize: 13.5 }}>{error}</p>}
      {result && <Report report={result.report} saved={result.saved} />}

      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <table className="f-table">
          <thead><tr><th style={{ width: 200 }}>Rule</th><th>What it posts</th><th style={{ textAlign: "right" }}>In the books</th><th style={{ width: 250 }} /></tr></thead>
          <tbody>{d.rules.map((r) => (
            <tr key={r.key}>
              <td style={{ fontWeight: 600, verticalAlign: "top" }}>{r.name}<div style={{ marginTop: 4 }}><Chip tone={r.on ? "ok" : "info"}>{r.on ? "On" : "Off"}</Chip></div></td>
              <td style={{ fontSize: 13, verticalAlign: "top" }}>{r.what}</td>
              <td className="f-num" style={{ verticalAlign: "top" }}>{r.entries || ""}</td>
              <td style={{ verticalAlign: "top", whiteSpace: "nowrap" }}>{d.can_edit && <>
                <button className="f-link" disabled={!!busy} onClick={() => preview([r.key])}>Preview</button>{" · "}
                <button className="f-link" disabled={!!busy} onClick={() => toggle(r)}>{r.on ? "Switch off" : "Switch on"}</button>
                {!r.on && r.entries > 0 && <>{" · "}<button className="f-link" disabled={!!busy} onClick={() => takeOut(r)}>Take its entries out</button></>}
              </>}</td>
            </tr>))}</tbody>
        </table>
      </div>

      <div style={{ ...card, marginTop: 14, display: "flex", flexWrap: "wrap", gap: "10px 18px", alignItems: "flex-end" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
          <span style={{ fontWeight: 600 }}>Post events dated from</span>
          <input type="date" style={{ ...inputStyle, width: 170 }} value={from} disabled={!d.can_edit} min={d.books_start}
                 onChange={(e) => setFrom(e.target.value)} /></label>
        {d.can_edit && from !== (d.from || "") && <Btn disabled={!!busy} onClick={saveFrom}>Save</Btn>}
        <span style={{ fontSize: 12.5, color: "var(--muted)", maxWidth: 620 }}>
          Anything earlier is left to the opening balances and to hand entry. Dollar invoices and receipts are taken at the
          company rate, MVR {d.usd_rate} to the dollar — the same rate Planet's own reports use.</span>
      </div>

      <h3 style={{ margin: "20px 0 6px" }}>Where each cost head lands</h3>
      <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 0, maxWidth: 820 }}>
        A cost in Planet carries a cost head; the books need an account. Each head has a usual account; choose another where
        the consultant wants it elsewhere. {unmapped.length > 0 && <span className="f-bad">{unmapped.length} head{unmapped.length === 1 ? " has" : "s have"} no account yet — costs under {unmapped.length === 1 ? "it" : "them"} are held back.</span>}</p>
      <div style={{ ...card, padding: 0, overflowX: "auto", maxWidth: 820 }}>
        <table className="f-table">
          <thead><tr><th>Cost head</th><th>Account in the books</th></tr></thead>
          <tbody>{d.heads.map((h) => (
            <tr key={h.id}>
              <td>{h.name}</td>
              <td>{d.can_edit ? (
                <select style={{ ...inputStyle, width: 380, borderColor: h.account || !h.used ? undefined : "var(--red-fg, #b3261e)" }} value={h.account || ""}
                        disabled={!!busy} onChange={(e) => mapHead(h, e.target.value)}>
                  <option value="">{h.mapped ? "— back to the usual account —" : "— none yet —"}</option>
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}
                </select>) : (h.account_label || <span className="f-bad">none yet</span>)}
                {!h.mapped && h.account && <span style={{ fontSize: 12, color: "var(--muted)", marginLeft: 8 }}>usual</span>}
                {!h.account && !h.used && <span style={{ fontSize: 12, color: "var(--muted)", marginLeft: 8 }}>not used yet</span>}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </div>
  );
}
