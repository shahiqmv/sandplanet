// Journals: the register of entries, the entry form, and one entry opened.
// An entry posts only when it balances; a posted entry is never changed —
// it is reversed, and both stay on the record (FINANCE_BUILD_BRIEF.md).
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { Btn, Chip, card, ghostButton, inputStyle } from "../ui.jsx";
import { KIND_TONE, amt, fmtDate, money, today, tree } from "./shared.jsx";

const blankLine = () => ({ account: "", text: "", description: "", debit: "", credit: "",
                           amount_fc: "", fx_rate: "", party: "", site: "" });
const num = (v) => Number(String(v || "").replace(/,/g, "")) || 0;

// ---- the entry form -----------------------------------------------------------

function Editor({ id, kind, go, settings }) {
  const [accounts, setAccounts] = useState([]);
  const [sites, setSites] = useState([]);
  const [fx, setFx] = useState("");
  const [head, setHead] = useState({ date: today(), memo: "" });
  const [lines, setLines] = useState([blankLine(), blankLine()]);
  const [entryId, setEntryId] = useState(id || null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);          // party / site columns
  const [k, setK] = useState(kind || "MANUAL");    // a draft keeps its kind
  const opening = k === "OPENING";

  useEffect(() => {
    api("/ledger/accounts").then((d) => setAccounts(tree(d.accounts).filter((a) => !a.is_group && a.is_active)));
    api("/sites").then((s) => setSites(Array.isArray(s) ? s : s.results || [])).catch(() => {});
    api("/fx/usd-rate").then((r) => setFx(String(r.rate))).catch(() => {});
  }, []);
  const byLabel = useMemo(() => Object.fromEntries(accounts.map((a) => [`${a.code} ${a.name}`, a])), [accounts]);
  const byId = useMemo(() => Object.fromEntries(accounts.map((a) => [a.id, a])), [accounts]);

  useEffect(() => {
    if (!id || !accounts.length) return;
    api(`/ledger/journals/${id}`).then((e) => {
      setHead({ date: e.date, memo: e.memo });
      setK(e.kind);
      setLines(e.lines.map((l) => ({
        account: l.account, text: `${l.account_code} ${l.account_name}`, description: l.description,
        debit: Number(l.debit) ? String(l.debit) : "", credit: Number(l.credit) ? String(l.credit) : "",
        amount_fc: l.amount_fc || "", fx_rate: l.fx_rate || "", party: l.party, site: l.site || "" })));
      if (e.lines.some((l) => l.party || l.site)) setMore(true);
    }).catch((e) => setError(e.message));
  }, [id, accounts.length]);

  const setLine = (i, patch) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  function pickAccount(i, text) {
    const a = byLabel[text];
    setLine(i, { text, account: a ? a.id : "", fx_rate: a?.currency ? (lines[i].fx_rate || fx) : "" });
  }
  // On a dollar account the bookkeeper types dollars and the rate; the
  // rufiyaa follows, on whichever side already holds a figure (debit first).
  function setFc(i, patch) {
    const l = { ...lines[i], ...patch };
    const mvr = num(l.amount_fc) * num(l.fx_rate);
    const v = mvr ? mvr.toFixed(2) : "";
    setLine(i, { ...patch, ...(num(l.credit) && !num(l.debit) ? { credit: v } : { debit: v }) });
  }

  const dr = lines.reduce((s, l) => s + num(l.debit), 0);
  const cr = lines.reduce((s, l) => s + num(l.credit), 0);
  const diff = Math.round((dr - cr) * 100) / 100;
  const hasUsd = lines.some((l) => byId[l.account]?.currency);

  const body = () => ({
    kind: opening ? "OPENING" : "MANUAL", date: head.date, memo: head.memo,
    lines: lines.filter((l) => l.account || num(l.debit) || num(l.credit)).map((l) => ({
      account: l.account || null, description: l.description, debit: num(l.debit), credit: num(l.credit),
      amount_fc: byId[l.account]?.currency ? num(l.amount_fc) : null,
      fx_rate: byId[l.account]?.currency ? l.fx_rate : null,
      currency: byId[l.account]?.currency || "MVR",
      party: l.party, site: l.site ? Number(l.site) : null })),
  });

  // Saved as a draft first, then posted as a second step — so an entry the
  // server refuses to post is still there, corrected and posted, not typed
  // again or saved twice.
  async function save(post) {
    setBusy(true); setError(null);
    try {
      const saved = entryId
        ? await api(`/ledger/journals/${entryId}`, { method: "PATCH", body: body() })
        : await api("/ledger/journals", { method: "POST", body: body() });
      setEntryId(saved.id);
      if (post) await api(`/ledger/journals/${saved.id}/post`, { method: "POST", body: {} });
      go("journals", saved.id);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>
          {opening ? "Opening balances" : entryId ? "Edit draft journal" : "New journal"}</h1>
        <span className="spacer" />
        <button style={ghostButton} onClick={() => go("journals")}>← Journals</button>
      </div>
      {opening && (
        <p className="t-note">
          The balances the books open with, dated {fmtDate(settings?.opening_date)} — the day before the books
          start. Enter each asset as a debit and each liability and equity balance as a credit, from the audited
          statements. They must balance; while you are still gathering figures, put the difference to
          <b> Opening balance equity</b> and clear it later. You can post more than one opening entry.
        </p>
      )}
      <div style={{ ...card, marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          {!opening && (
            <label style={{ fontSize: 13, display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontWeight: 600 }}>Date</span>
              <input type="date" style={{ ...inputStyle, width: 160 }} value={head.date}
                     onChange={(e) => setHead({ ...head, date: e.target.value })} /></label>
          )}
          <label style={{ fontSize: 13, display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 280 }}>
            <span style={{ fontWeight: 600 }}>What it is for</span>
            <input style={inputStyle} value={head.memo} onChange={(e) => setHead({ ...head, memo: e.target.value })}
                   placeholder={opening ? "Audited balances at 31 December 2025" : "e.g. Office rent, March 2026"} /></label>
        </div>
      </div>

      <div style={{ ...card, padding: 10, overflowX: "auto" }}>
        <datalist id="f-accounts">{accounts.map((a) => <option key={a.id} value={`${a.code} ${a.name}`} />)}</datalist>
        <table className="f-table f-lines" style={{ minWidth: more ? 1100 : 820 }}>
          <thead><tr>
            <th style={{ width: "28%" }}>Account</th><th>Description</th>
            {hasUsd && <><th style={{ width: 110, textAlign: "right" }}>USD</th><th style={{ width: 90, textAlign: "right" }}>Rate</th></>}
            <th style={{ width: 140, textAlign: "right" }}>Debit (MVR)</th>
            <th style={{ width: 140, textAlign: "right" }}>Credit (MVR)</th>
            {more && <><th style={{ width: 150 }}>Party</th><th style={{ width: 110 }}>Site</th></>}
            <th style={{ width: 28 }} />
          </tr></thead>
          <tbody>
            {lines.map((l, i) => {
              const usd = byId[l.account]?.currency;
              return (
                <tr key={i}>
                  <td><input list="f-accounts" value={l.text} placeholder="Code or name…"
                             onChange={(e) => pickAccount(i, e.target.value)}
                             style={l.text && !l.account ? { borderColor: "var(--red-fg, #b3261e)" } : undefined} /></td>
                  <td><input value={l.description} onChange={(e) => setLine(i, { description: e.target.value })} /></td>
                  {hasUsd && (usd ? <>
                    <td><input className="f-amt" value={l.amount_fc} onChange={(e) => setFc(i, { amount_fc: e.target.value })} /></td>
                    <td><input className="f-amt" value={l.fx_rate} onChange={(e) => setFc(i, { fx_rate: e.target.value })} /></td>
                  </> : <><td /><td /></>)}
                  <td><input className="f-amt" value={l.debit} onChange={(e) => setLine(i, { debit: e.target.value, credit: e.target.value ? "" : l.credit })} /></td>
                  <td><input className="f-amt" value={l.credit} onChange={(e) => setLine(i, { credit: e.target.value, debit: e.target.value ? "" : l.debit })} /></td>
                  {more && <>
                    <td><input value={l.party} placeholder="Customer, supplier…" onChange={(e) => setLine(i, { party: e.target.value })} /></td>
                    <td><select value={l.site} onChange={(e) => setLine(i, { site: e.target.value })}>
                      <option value="">—</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}</select></td>
                  </>}
                  <td><button title="Remove line" className="f-link" style={{ textDecoration: "none", color: "var(--muted)" }}
                              onClick={() => setLines((ls) => (ls.length > 2 ? ls.filter((_, j) => j !== i) : ls))}>✕</button></td>
                </tr>
              );
            })}
          </tbody>
          <tfoot><tr>
            <td colSpan={hasUsd ? 4 : 2} style={{ paddingTop: 10 }}>
              <button style={{ ...ghostButton, padding: "4px 12px", fontSize: 13 }}
                      onClick={() => setLines((ls) => [...ls, blankLine()])}>+ Add line</button>
              <button style={{ ...ghostButton, padding: "4px 12px", fontSize: 13, marginLeft: 8 }}
                      onClick={() => setMore(!more)}>{more ? "Hide" : "Show"} party and site</button>
            </td>
            <td className="f-num" style={{ fontWeight: 800, paddingTop: 10 }}>{money(dr)}</td>
            <td className="f-num" style={{ fontWeight: 800, paddingTop: 10 }}>{money(cr)}</td>
            <td colSpan={more ? 3 : 1} />
          </tr></tfoot>
        </table>
      </div>

      <div className="f-bar" style={{ marginTop: 12 }}>
        {dr === 0 && cr === 0 ? <span style={{ color: "var(--muted)" }}>Enter the lines.</span>
          : diff === 0 ? <span className="f-ok">✓ Balanced — MVR {money(dr)}</span>
          : <span className="f-bad">Out by MVR {money(Math.abs(diff))} — {diff > 0 ? "credits" : "debits"} are short</span>}
        <span className="spacer" />
        {error && <span className="f-bad" style={{ fontSize: 13, maxWidth: 520 }}>{error}</span>}
        <Btn variant="secondary" disabled={busy} onClick={() => save(false)}>Save as draft</Btn>
        <Btn disabled={busy || diff !== 0 || dr === 0} onClick={() => save(true)}>{busy ? "Posting…" : "Post entry"}</Btn>
      </div>
    </div>
  );
}

// ---- one entry, opened ----------------------------------------------------------

function EntryView({ id, go, canEdit, planetUrl }) {
  const [e, setE] = useState(null);
  const [error, setError] = useState(null);
  const [rev, setRev] = useState(null);             // {reason}
  const load = useCallback(() => api(`/ledger/journals/${id}`).then(setE).catch((x) => setError(x.message)), [id]);
  useEffect(() => { load(); }, [load]);

  async function act(action, body) {
    setError(null);
    try {
      const r = await api(`/ledger/journals/${id}/${action}`, { method: "POST", body: body || {} });
      if (action === "reverse") go("journals", r.id); else load();
    } catch (x) { setError(x.message); }
  }
  async function del() {
    if (!window.confirm("Delete this draft?")) return;
    try { await api(`/ledger/journals/${id}`, { method: "DELETE" }); go("journals"); }
    catch (x) { setError(x.message); }
  }
  if (!e) return <div style={card}>{error || "Loading…"}</div>;
  const draft = e.status === "DRAFT";
  const usd = e.lines.some((l) => l.currency !== "MVR");
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0, fontFamily: "var(--font-mono)" }}>{e.ref || "Draft"}</h1>
        <Chip tone={draft ? "warn" : KIND_TONE[e.kind]}>{draft ? "Draft — not in the books yet" : e.kind_label}</Chip>
        {e.reversed_by && <Chip tone="alert">reversed by {e.reversed_by}</Chip>}
        {e.reversal_of && <Chip tone="warn">reverses {e.reversal_of}</Chip>}
        <span className="spacer" />
        <button style={ghostButton} onClick={() => go("journals")}>← Journals</button>
      </div>
      <div style={{ ...card, marginBottom: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 600 }}>{e.memo || <span style={{ color: "var(--muted)" }}>No description</span>}</div>
        <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
          Dated {fmtDate(e.date)} · entered by {e.created_by || "—"}
          {e.posted_by && ` · posted by ${e.posted_by} on ${fmtDate(e.posted_at)}`}
          {e.source_ref && <> · from <a href={`${planetUrl}#/open/${e.source_ref}`} target="_blank" rel="noreferrer">{e.source_ref}</a></>}
        </div>
      </div>
      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <table className="f-table">
          <thead><tr><th>Account</th><th>Description</th><th>Party</th><th>Site</th>
            {usd && <th style={{ textAlign: "right" }}>Foreign</th>}
            <th style={{ textAlign: "right" }}>Debit</th><th style={{ textAlign: "right" }}>Credit</th></tr></thead>
          <tbody>
            {e.lines.map((l) => (
              <tr key={l.id}>
                <td><button className="f-link" onClick={() => go("ledger", l.account)}>{l.account_code}</button> {l.account_name}</td>
                <td>{l.description}</td><td>{l.party}</td><td>{l.site_code}</td>
                {usd && <td className="f-num">{l.currency !== "MVR" ? `${l.currency} ${money(l.amount_fc)} @ ${Number(l.fx_rate)}` : ""}</td>}
                <td className="f-num">{amt(l.debit)}</td><td className="f-num">{amt(l.credit)}</td>
              </tr>
            ))}
            <tr className="f-total"><td colSpan={usd ? 5 : 4}>Total (MVR)</td>
              <td className="f-num">{money(e.total)}</td><td className="f-num">{money(e.total)}</td></tr>
          </tbody>
        </table>
      </div>
      {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}
      {canEdit && (
        <div className="f-bar" style={{ marginTop: 12 }}>
          {draft && <>
            <Btn onClick={() => act("post")}>Post entry</Btn>
            <Btn variant="secondary" onClick={() => go("journals", `edit-${e.id}`)}>Edit</Btn>
            <Btn variant="secondary" onClick={del}>Delete draft</Btn>
          </>}
          {!draft && !e.reversed_by && e.kind !== "REVERSAL" && (rev === null
            ? <Btn variant="secondary" onClick={() => setRev({ reason: "" })}>Reverse this entry…</Btn>
            : <>
              <input style={{ ...inputStyle, flex: 1, minWidth: 260 }} placeholder="Why is it being reversed?"
                     value={rev.reason} onChange={(x) => setRev({ reason: x.target.value })} />
              <Btn onClick={() => act("reverse", rev)}>Reverse</Btn>
              <Btn variant="secondary" onClick={() => setRev(null)}>Cancel</Btn>
            </>)}
          {!draft && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
            A posted entry can't be edited. Reversing posts its mirror image; both stay on the record.</span>}
        </div>
      )}
    </div>
  );
}

// ---- the register -----------------------------------------------------------------

export default function JournalsPage({ sub, go, settings, planetUrl }) {
  const [data, setData] = useState(null);
  const [f, setF] = useState({ status: "", kind: "", from: "", to: "", q: "" });
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    api(`/ledger/journals?${p}`).then(setData).catch((e) => setError(e.message));
  }, [f]);
  useEffect(() => { if (!sub) load(); }, [sub, load]);

  if (sub === "new") return <Editor go={go} settings={settings} />;
  if (sub === "opening") return <Editor kind="OPENING" go={go} settings={settings} />;
  if (String(sub || "").startsWith("edit-")) return <Editor id={Number(String(sub).slice(5))} go={go} settings={settings} />;
  if (sub) return <EntryView id={Number(sub)} go={go} canEdit={data ? data.can_edit : true} planetUrl={planetUrl} />;

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Journals</h1>
        {data?.drafts > 0 && <Chip tone="warn">{data.drafts} draft{data.drafts === 1 ? "" : "s"} not posted</Chip>}
        <span className="spacer" />
        {data?.can_edit && <>
          <Btn variant="secondary" onClick={() => go("journals", "opening")}>Opening balances</Btn>
          <Btn onClick={() => go("journals", "new")}>+ New journal</Btn>
        </>}
      </div>
      <div className="f-bar">
        <select style={{ ...inputStyle, width: 130 }} value={f.status} onChange={set("status")}>
          <option value="">All</option><option value="POSTED">Posted</option><option value="DRAFT">Drafts</option></select>
        <select style={{ ...inputStyle, width: 190 }} value={f.kind} onChange={set("kind")}>
          <option value="">Every kind</option><option value="MANUAL">Journals</option>
          <option value="OPENING">Opening balances</option><option value="REVERSAL">Reversals</option>
          <option value="AUTO">Posted from operations</option></select>
        <input type="date" style={{ ...inputStyle, width: 150 }} value={f.from} onChange={set("from")} aria-label="From" />
        <span style={{ color: "var(--muted)" }}>to</span>
        <input type="date" style={{ ...inputStyle, width: 150 }} value={f.to} onChange={set("to")} aria-label="To" />
        <input style={{ ...inputStyle, width: 240 }} placeholder="Number, description, party…" value={f.q} onChange={set("q")} />
      </div>
      {error && <p className="f-bad">{error}</p>}
      {!data ? <div style={card}>Loading…</div> : data.journals.length === 0 ? (
        <div style={card}>No entries{Object.values(f).some(Boolean) ? " match" : " yet. Start with the opening balances."}</div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Number</th><th>Date</th><th>Description</th><th>Kind</th>
              <th style={{ textAlign: "right" }}>Amount (MVR)</th><th>By</th></tr></thead>
            <tbody>
              {data.journals.map((e) => (
                <tr key={e.id} className="f-click" onClick={() => go("journals", e.id)}>
                  <td style={{ fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{e.ref || <Chip tone="warn">draft</Chip>}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{fmtDate(e.date)}</td>
                  <td>{e.memo}{e.reversed_by && <span style={{ color: "var(--red-fg)" }}> · reversed by {e.reversed_by}</span>}</td>
                  <td>{e.kind_label}</td>
                  <td className="f-num">{money(e.total)}</td>
                  <td>{e.posted_by || e.created_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data?.has_more && <p style={{ fontSize: 12.5, color: "var(--muted)" }}>Showing the latest {data.journals.length} of {data.total} — narrow the dates or search to see older ones.</p>}
    </div>
  );
}
