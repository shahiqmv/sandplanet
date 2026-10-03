// Phone and utility bills: every account the company is billed on — mobile
// numbers, internet lines, meters — a sheet to enter a month's bills in one
// go, and the unpaid ones by provider so a provider's batch goes on one
// voucher. A phone has a person and an allowance; what a bill runs over it
// comes off that person's salary. (owner 2026-10-03 — core/bills.py)
import { useCallback, useEffect, useState } from "react";
import { api, apiDownload } from "../api.js";
import { Btn, Chip, card, ghostButton, inputStyle } from "../ui.jsx";
import { fmtDate, money, today } from "./shared.jsx";
import { field, lab } from "./forms.jsx";

const TABS = [[null, "Accounts"], ["enter", "Enter a month's bills"], ["pay", "Bills to pay"], ["recoveries", "Salary recoveries"]];
const month = (d) => new Date(`${String(d).slice(0, 7)}-01T00:00`).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
const lastMonth = () => { const t = new Date(); const d = new Date(t.getFullYear(), t.getMonth() - 1, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

function Tabs({ sub, go }) {
  const cur = TABS.some(([k]) => k === sub) ? sub : null;
  return (
    <div className="f-bar">
      <h1 className="t-h1" style={{ margin: 0 }}>Phone and utility bills</h1>
      <span className="spacer" />
      {TABS.map(([k, l]) => (
        <button key={l} className={"f-sub-item" + (cur === k ? " is-active" : "")} onClick={() => go("utilities", k)}>{l}</button>))}
    </div>
  );
}

function Recovery({ r }) {
  if (!r) return null;
  return <div style={{ fontSize: 12 }} className={r.deducted ? "f-ok" : "f-bad"}>
    MVR {money(r.amount)} from {r.from} — {r.note}</div>;
}

// ---- the register -----------------------------------------------------------------

function Accounts({ go }) {
  const [data, setData] = useState(null);
  const [all, setAll] = useState(false);
  const [q, setQ] = useState("");
  const [error, setError] = useState(null);
  useEffect(() => { api(`/bills/accounts${all ? "?all=1" : ""}`).then(setData).catch((e) => setError(e.message)); }, [all]);
  if (!data) return <div style={card}>{error || "Loading…"}</div>;
  const rows = data.accounts.filter((a) => !q.trim() || `${a.provider} ${a.account_no} ${a.label} ${a.employee_name}`.toLowerCase().includes(q.trim().toLowerCase()));
  const groups = {};
  rows.forEach((a) => { (groups[a.provider] = groups[a.provider] || []).push(a); });
  return (
    <>
      <div className="f-bar">
        <span style={{ color: "var(--muted)", fontSize: 13 }}>{data.accounts.length} account{data.accounts.length === 1 ? "" : "s"} with {Object.keys(groups).length} provider{Object.keys(groups).length === 1 ? "" : "s"}</span>
        <span className="spacer" />
        <input style={{ ...inputStyle, width: 220 }} placeholder="Find a number or a name…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label style={{ fontSize: 13 }}><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> show closed</label>
        {data.can_edit && <>
          <Btn variant="secondary" onClick={() => go("utilities", "many")}>+ Several at once</Btn>
          <Btn onClick={() => go("utilities", "new")}>+ Account</Btn>
        </>}
      </div>
      {data.accounts.length === 0 ? (
        <div style={card}>No accounts yet. Add each mobile number, internet line and meter the company pays for — <b>+ Several at once</b> takes a pasted list.
          Each month the bills are then entered on one sheet and paid provider by provider.</div>
      ) : Object.entries(groups).map(([provider, list]) => (
        <div key={provider} style={{ ...card, padding: 0, overflowX: "auto", marginBottom: 12 }}>
          <table className="f-table">
            <thead><tr><th style={{ width: "22%" }}>{provider} · {list.length}</th><th>Whose / where</th><th>Kind</th><th>Site</th>
              <th style={{ textAlign: "right" }}>Allowance / recharge</th><th style={{ textAlign: "right" }}>Last bill</th></tr></thead>
            <tbody>{list.map((a) => (
              <tr key={a.id} className="f-click" onClick={() => go("utilities", a.ref)} style={a.is_active ? undefined : { opacity: .55 }}>
                <td style={{ fontFamily: "var(--font-mono)" }}>{a.account_no}{!a.is_active && <> <Chip tone="info">closed</Chip></>}</td>
                <td>{a.label}{a.employee_name && a.employee_name.split(" · ")[1] !== a.label && <span style={{ color: "var(--muted)" }}> · {a.employee_name}</span>}
                  {a.employee && <div style={{ fontSize: 12, color: "var(--muted)" }}>{a.employee_name.split(" · ")[0]}</div>}</td>
                <td>{a.kind_label}</td><td>{a.site_code}</td>
                <td className="f-num">{a.prepaid ? <span style={{ fontWeight: 400 }}>prepaid{a.fixed_amount != null ? ` · ${money(a.fixed_amount)}` : ""}</span>
                  : a.monthly_limit != null ? money(a.monthly_limit) : ""}</td>
                <td className="f-num">{a.last ? <>{money(a.last.total)}<div style={{ fontSize: 12, fontWeight: 400, color: "var(--muted)" }}>{month(a.last.period)}</div></> : ""}</td>
              </tr>))}</tbody>
          </table>
        </div>))}
    </>
  );
}

const BLANK = { provider: "", kind: "MOBILE", account_no: "", label: "", provider_tin: "", site: "", cost_head: "", currency: "MVR",
  gst_applicable: true, monthly_limit: "", due_day: "", notes: "", is_active: true, employee: null, employee_name: "",
  prepaid: false, fixed_amount: "" };

function PersonPicker({ f, setF, disabled }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState([]);
  useEffect(() => {
    if (q.trim().length < 2) { setFound([]); return undefined; }
    const t = setTimeout(() => api(`/bills/people?q=${encodeURIComponent(q.trim())}`).then((d) => setFound(d.people)).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q]);
  if (f.employee) {
    return <span style={{ ...inputStyle, display: "flex", justifyContent: "space-between", gap: 8 }}>{f.employee_name}
      {!disabled && <button className="f-link" onClick={() => setF({ ...f, employee: null, employee_name: "" })}>change</button>}</span>;
  }
  return (
    <span style={{ position: "relative" }}>
      <input style={{ ...inputStyle, width: "100%" }} value={q} disabled={disabled} placeholder="Type a name or employee no." onChange={(e) => setQ(e.target.value)} />
      {found.length > 0 && (
        <div style={{ position: "absolute", zIndex: 5, left: 0, right: 0, background: "#fff", border: "1px solid var(--line)", borderRadius: 6, maxHeight: 220, overflowY: "auto" }}>
          {found.map((p) => (
            <button key={p.id} style={{ display: "block", width: "100%", textAlign: "left", padding: "6px 10px", border: 0, background: "none", cursor: "pointer", font: "inherit" }}
                    onClick={() => { setF({ ...f, employee: p.id, employee_name: `${p.emp_no} · ${p.name}`, label: f.label || p.name }); setQ(""); setFound([]); }}>
              {p.emp_no} · {p.name}</button>))}
        </div>)}
    </span>
  );
}

function Account({ ident, go }) {
  const isNew = ident === "new";
  const [a, setA] = useState(null);
  const [f, setF] = useState(BLANK);
  const [meta, setMeta] = useState(null);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const take = useCallback((x) => { setA(x); setMeta(x.meta); setF({ ...BLANK, ...x, site: String(x.site), cost_head: String(x.cost_head), monthly_limit: x.monthly_limit ?? "", due_day: x.due_day ?? "", fixed_amount: x.fixed_amount ?? "" }); }, []);
  useEffect(() => {
    if (isNew) api("/bills/accounts").then((d) => setMeta(d.meta)).catch((e) => setError(e.message));
    else api(`/bills/accounts/${ident}`).then(take).catch((e) => setError(e.message));
  }, [ident, isNew, take]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  // a new account takes its kind's usual head and GST until told otherwise
  const setKind = (kind) => {
    const tel = meta.kinds.find((k) => k.value === kind)?.telecom;
    setF({ ...f, kind, ...(isNew ? { gst_applicable: !!tel, cost_head: "" } : {}) });
  };
  async function save() {
    setBusy(true); setError(null); setMsg(null);
    const body = { provider: f.provider, kind: f.kind, account_no: f.account_no, label: f.label, provider_tin: f.provider_tin,
      site: f.site ? Number(f.site) : null, cost_head: f.cost_head ? Number(f.cost_head) : null, currency: f.currency,
      gst_applicable: f.gst_applicable, monthly_limit: f.prepaid ? "" : f.monthly_limit, due_day: f.due_day, notes: f.notes,
      is_active: f.is_active, employee: f.employee || null, prepaid: f.prepaid, fixed_amount: f.prepaid ? f.fixed_amount : "" };
    try {
      if (isNew) { const x = await api("/bills/accounts", { method: "POST", body }); go("utilities", x.ref); }
      else { take(await api(`/bills/accounts/${ident}`, { method: "PATCH", body })); setMsg("Saved."); }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  if (!meta) return <div style={card}>{error || "Loading…"}</div>;
  const ro = !isNew && !a?.can_edit;
  const usual = meta.kinds.find((k) => k.value === f.kind)?.telecom ? meta.head_telecom : meta.head_utilities;
  return (
    <>
      <div className="f-bar">
        <h2 style={{ margin: 0 }}>{isNew ? "New account" : `${a.ref} · ${a.provider} ${a.account_no}`}</h2>
        <span className="spacer" /><button style={ghostButton} onClick={() => go("utilities")}>← Accounts</button>
      </div>
      <div style={{ ...card, marginBottom: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "10px 16px" }}>
          <label style={field}>{lab("Provider")}
            <input list="u-prov" style={inputStyle} value={f.provider} disabled={ro} onChange={set("provider")} placeholder="Dhiraagu, Ooredoo, STELCO…" />
            <datalist id="u-prov">{meta.providers.map((p) => <option key={p} value={p} />)}</datalist></label>
          <label style={field}>{lab("Kind")}
            <select style={inputStyle} value={f.kind} disabled={ro} onChange={(e) => setKind(e.target.value)}>{meta.kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}</select></label>
          <label style={field}>{lab("Number / account / meter")}
            <input style={inputStyle} value={f.account_no} disabled={ro} onChange={set("account_no")} /></label>
          <label style={field}>{lab("Site that bears the cost")}
            <select style={inputStyle} value={f.site} disabled={ro} onChange={set("site")}><option value="">— pick —</option>
              {meta.sites.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}</select></label>
          <label style={field}>{lab("Billing")}
            <select style={inputStyle} value={f.prepaid ? "1" : "0"} disabled={ro} onChange={(e) => setF({ ...f, prepaid: e.target.value === "1" })}>
              <option value="0">Postpaid — a bill each month</option><option value="1">Prepaid — a recharge each month</option></select></label>
          <label style={{ ...field, gridColumn: "span 2" }}>{lab("Person it is assigned to (a phone)")}
            <PersonPicker f={f} setF={setF} disabled={ro} /></label>
          {f.prepaid ? (
            <label style={field}>{lab("Monthly recharge")}
              <input style={{ ...inputStyle, textAlign: "right" }} value={f.fixed_amount} disabled={ro} onChange={set("fixed_amount")} placeholder="the usual top-up" /></label>
          ) : (
            <label style={field}>{lab("Monthly allowance the company bears")}
              <input style={{ ...inputStyle, textAlign: "right" }} value={f.monthly_limit} disabled={ro} onChange={set("monthly_limit")} placeholder="blank = the whole bill" /></label>)}
          <label style={{ ...field, gridColumn: "span 2" }}>{lab("Whose / where (shown on lists)")}
            <input style={inputStyle} value={f.label} disabled={ro} onChange={set("label")} placeholder="Project Director · Head office meter" /></label>
          <label style={field}>{lab("Cost head")}
            <select style={inputStyle} value={f.cost_head || String(usual || "")} disabled={ro} onChange={set("cost_head")}>
              {meta.cost_heads.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}</select></label>
          <label style={field}>{lab("Usually due on day (of the next month)")}
            <input style={inputStyle} value={f.due_day} disabled={ro} onChange={set("due_day")} placeholder="1–28; blank = month end" /></label>
          <label style={field}>{lab("Provider TIN")}
            <input style={inputStyle} value={f.provider_tin} disabled={ro} onChange={set("provider_tin")} /></label>
          <label style={{ ...field, gridColumn: "span 2" }}>{lab("Notes")}
            <input style={inputStyle} value={f.notes} disabled={ro} onChange={set("notes")} /></label>
        </div>
        <div className="f-bar" style={{ marginTop: 10, marginBottom: 0, fontSize: 13.5 }}>
          <label><input type="checkbox" checked={f.gst_applicable} disabled={ro} onChange={set("gst_applicable")} /> Its bills include GST ({meta.gst_rate}%)</label>
          {!isNew && <label><input type="checkbox" checked={f.is_active} disabled={ro} onChange={set("is_active")} /> In use</label>}
        </div>
        {f.prepaid && <p style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 0 }}>
          A prepaid number has no bill and nothing to run over: the recharge is the company's cost and nothing is recovered from anyone's salary.</p>}
        {!f.prepaid && f.employee && f.monthly_limit !== "" && <p style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 0 }}>
          The company bears up to {f.currency} {money(f.monthly_limit)} a month. What a bill runs over that is recovered from {f.employee_name.split(" · ")[1]}'s salary.</p>}
      </div>
      {error && <p className="f-bad" style={{ fontSize: 13.5 }}>{error}</p>}
      {msg && <p className="f-ok" style={{ fontSize: 13.5 }}>{msg}</p>}
      {!ro && <div className="f-bar"><Btn disabled={busy || !f.provider.trim() || !f.account_no.trim() || !f.site} onClick={save}>{busy ? "Saving…" : isNew ? "Save account" : "Save changes"}</Btn></div>}
      {!isNew && (
        <>
          <h3 style={{ margin: "16px 0 8px" }}>Its bills</h3>
          {a.history.length === 0 ? <div style={card}>None entered yet.</div> : (
            <div style={{ ...card, padding: 0, overflowX: "auto" }}>
              <table className="f-table">
                <thead><tr><th>Month</th><th>Bill no.</th><th>Due</th><th style={{ textAlign: "right" }}>Amount</th><th /><th>Recovered from salary</th></tr></thead>
                <tbody>{a.history.map((h) => (
                  <tr key={h.id} style={h.status === "CANCELLED" ? { opacity: .55 } : undefined}>
                    <td>{h.period_label}</td><td>{h.bill_no}</td><td>{fmtDate(h.due_date)}</td>
                    <td className="f-num">{h.currency} {money(h.total)}</td>
                    <td>{h.status === "PAID" ? <Chip tone="ok">Paid {fmtDate(h.paid_on)}</Chip> : h.status === "CANCELLED" ? <Chip tone="info">Cancelled</Chip>
                      : <Chip tone={h.overdue ? "alert" : "warn"}>{h.overdue ? "Overdue" : "To pay"}</Chip>}
                      {h.voucher && <span style={{ fontSize: 12, marginLeft: 6 }}>{h.voucher}</span>}</td>
                    <td><Recovery r={h.status === "CANCELLED" ? null : h.recovery} /></td>
                  </tr>))}</tbody>
              </table>
            </div>)}
        </>)}
    </>
  );
}

function Many({ go }) {
  const [meta, setMeta] = useState(null);
  const [f, setF] = useState({ provider: "", kind: "MOBILE", site: "", lines: "", prepaid: false });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/bills/accounts").then((d) => setMeta(d.meta)).catch((e) => setError(e.message)); }, []);
  async function save() {
    setBusy(true); setError(null);
    try { await api("/bills/accounts", { method: "POST", body: { ...f, site: Number(f.site) } }); go("utilities"); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  if (!meta) return <div style={card}>{error || "Loading…"}</div>;
  const n = f.lines.split("\n").filter((l) => l.trim()).length;
  return (
    <>
      <div className="f-bar"><h2 style={{ margin: 0 }}>Add several accounts</h2><span className="spacer" />
        <button style={ghostButton} onClick={() => go("utilities")}>← Accounts</button></div>
      <div style={card}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "10px 16px" }}>
          <label style={field}>{lab("Provider")}
            <input list="u-prov2" style={inputStyle} value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })} />
            <datalist id="u-prov2">{meta.providers.map((p) => <option key={p} value={p} />)}</datalist></label>
          <label style={field}>{lab("Kind")}
            <select style={inputStyle} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{meta.kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}</select></label>
          <label style={field}>{lab("Site that bears the cost")}
            <select style={inputStyle} value={f.site} onChange={(e) => setF({ ...f, site: e.target.value })}><option value="">— pick —</option>
              {meta.sites.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}</select></label>
        </div>
        <label style={{ display: "block", fontSize: 13.5, marginTop: 10 }}>
          <input type="checkbox" checked={f.prepaid} onChange={(e) => setF({ ...f, prepaid: e.target.checked })} /> These are <b>prepaid</b> numbers — the third column is the monthly recharge, and nothing is recovered from salaries</label>
        <label style={{ ...field, marginTop: 10 }}>{lab(f.prepaid ? "One account to a line: number, person, monthly recharge" : "One account to a line: number, person, monthly allowance")}
          <textarea rows={10} style={{ ...inputStyle, fontFamily: "var(--font-mono)", fontSize: 13 }} value={f.lines}
                    onChange={(e) => setF({ ...f, lines: e.target.value })}
                    placeholder={"7771234, EMP-0060, 500\n7775678, EMP-0112, 300\n7779012, Site office phone"} /></label>
        <p style={{ fontSize: 12.5, color: "var(--muted)" }}>Paste from Excel if you like — columns become commas. For the person give the <b>employee number</b> (EMP-0060): the phone is
          then tied to that person, and anything over the allowance is recovered from their salary. A plain name is kept as a label only. The site can be changed per account afterwards.</p>
        {error && <p className="f-bad" style={{ fontSize: 13.5 }}>{error}</p>}
        <Btn disabled={busy || !f.provider.trim() || !f.site || n === 0} onClick={save}>{busy ? "Adding…" : `Add ${n} account${n === 1 ? "" : "s"}`}</Btn>
      </div>
    </>
  );
}

// ---- a month's bills ----------------------------------------------------------------

function Enter({ go }) {
  const [period, setPeriod] = useState(lastMonth());
  const [provider, setProvider] = useState("");
  const [d, setD] = useState(null);
  const [v, setV] = useState({});                   // account id → {total, bill_no, due_date}
  const [billDate, setBillDate] = useState(today());
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    setD(null);
    api(`/bills/sheet?period=${period}${provider ? `&provider=${encodeURIComponent(provider)}` : ""}`).then((x) => { setD(x); setV({}); }).catch((e) => setError(e.message));
  }, [period, provider]);
  useEffect(() => { load(); }, [load]);
  const setRow = (id, patch) => setV((x) => ({ ...x, [id]: { ...(x[id] || {}), ...patch } }));
  const num = (s) => Number(String(s ?? "").replace(/,/g, "")) || 0;
  const filled = Object.entries(v).filter(([, r]) => r.total !== undefined && r.total !== "");
  // prepaid numbers take the same recharge each month: fill the blanks
  const prepaidBlank = (d?.rows || []).filter((a) => a.prepaid && a.fixed_amount != null && !a.charge && !(v[a.id]?.total));
  const fillPrepaid = () => setV((x) => { const y = { ...x }; prepaidBlank.forEach((a) => { y[a.id] = { ...(y[a.id] || {}), total: String(a.fixed_amount) }; }); return y; });
  const sum = filled.reduce((s, [, r]) => s + num(r.total), 0);
  async function save() {
    setBusy(true); setError(null); setMsg(null);
    try {
      const r = await api("/bills/sheet", { method: "POST", body: { period, rows: filled.map(([id, r]) => ({ account: Number(id), total: r.total, bill_no: r.bill_no || "", due_date: r.due_date || null, bill_date: billDate })) } });
      setMsg(`${r.entered} bill${r.entered === 1 ? "" : "s"} entered, ${money(r.total)} in all — they are under Bills to pay.`); load();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const cancel = async (c) => {
    const reason = window.prompt(`Cancel the ${c.period_label} bill of ${c.provider} ${c.account_no}? Say why:`);
    if (!reason) return;
    try { await api(`/bills/charges/${c.id}/cancel`, { method: "POST", body: { reason } }); load(); } catch (e) { setError(e.message); }
  };
  return (
    <>
      <div className="f-bar">
        <label style={{ fontSize: 13 }}>Bills for <input type="month" style={{ ...inputStyle, width: 160 }} value={period} onChange={(e) => setPeriod(e.target.value)} /></label>
        <select style={{ ...inputStyle, width: 200 }} value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="">Every provider</option>{(d?.providers || []).map((p) => <option key={p} value={p}>{p}</option>)}</select>
        <label style={{ fontSize: 13 }}>Bill date <input type="date" style={{ ...inputStyle, width: 150 }} value={billDate} max={today()} onChange={(e) => setBillDate(e.target.value)} /></label>
        <span className="spacer" />
        {d?.can_edit && prepaidBlank.length > 0 && <Btn variant="secondary" onClick={fillPrepaid}>Fill {prepaidBlank.length} prepaid recharge{prepaidBlank.length === 1 ? "" : "s"}</Btn>}
        {d?.can_edit && <Btn disabled={busy || filled.length === 0} onClick={save}>{busy ? "Saving…" : filled.length ? `Save ${filled.length} bill${filled.length === 1 ? "" : "s"} · ${money(sum)}` : "Save"}</Btn>}
      </div>
      <p style={{ fontSize: 13, color: "var(--muted)", marginTop: -4 }}>Type each bill's total as printed (GST included); for a prepaid number, the recharge bought for the month. Leave a row blank if there is nothing for it. They are saved together, or not at all.</p>
      {error && <p className="f-bad" style={{ fontSize: 13.5 }}>{error}</p>}
      {msg && <p className="f-ok" style={{ fontSize: 13.5 }}>{msg}</p>}
      {!d ? <div style={card}>Loading…</div> : d.rows.length === 0 ? <div style={card}>No accounts{provider ? ` with ${provider}` : ""} yet — add them under Accounts.</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table f-lines">
            <thead><tr><th>Provider</th><th>Number</th><th>Whose / where</th><th style={{ textAlign: "right" }}>Allowance</th><th style={{ textAlign: "right" }}>Last month</th>
              <th style={{ width: 130, textAlign: "right" }}>Bill total</th><th style={{ width: 130 }}>Bill no.</th><th style={{ width: 150 }}>Due</th><th /></tr></thead>
            <tbody>{d.rows.map((a) => {
              const c = a.charge, r = v[a.id] || {};
              const over = !c && !a.prepaid && a.monthly_limit != null && num(r.total) > Number(a.monthly_limit) ? num(r.total) - Number(a.monthly_limit) : 0;
              return (
                <tr key={a.id} style={c ? { background: "#f3faf4" } : undefined}>
                  <td>{a.provider}</td><td style={{ fontFamily: "var(--font-mono)" }}>{a.account_no}</td>
                  <td>{a.label}</td>
                  <td className="f-num">{a.prepaid ? <span style={{ color: "var(--muted)" }}>prepaid</span> : a.monthly_limit != null ? money(a.monthly_limit) : ""}</td>
                  <td className="f-num" style={{ color: "var(--muted)" }}>{a.previous != null ? money(a.previous) : ""}</td>
                  {c ? <>
                    <td className="f-num" style={{ fontWeight: 700 }}>{money(c.total)}</td><td>{c.bill_no}</td><td>{fmtDate(c.due_date)}</td>
                    <td style={{ fontSize: 12.5 }}>{c.status === "PAID" ? <span className="f-ok">paid</span> : c.voucher ? c.voucher : d.can_edit ? <button className="f-link" onClick={() => cancel(c)}>cancel</button> : "entered"}
                      <Recovery r={c.recovery} /></td>
                  </> : <>
                    <td><input className="f-amt" value={r.total ?? ""} disabled={!d.can_edit} placeholder={a.prepaid && a.fixed_amount != null ? money(a.fixed_amount) : ""}
                               onChange={(e) => setRow(a.id, { total: e.target.value })} /></td>
                    <td><input value={r.bill_no ?? ""} disabled={!d.can_edit} onChange={(e) => setRow(a.id, { bill_no: e.target.value })} /></td>
                    <td><input type="date" value={r.due_date ?? a.usual_due} disabled={!d.can_edit} onChange={(e) => setRow(a.id, { due_date: e.target.value })} /></td>
                    <td style={{ fontSize: 12 }}>{over > 0 && (a.employee ? <span className="f-bad" style={{ fontWeight: 500 }}>{money(over)} over — from {a.employee_name.split(" · ")[1]}'s salary</span>
                      : <span className="f-bad" style={{ fontWeight: 500 }}>{money(over)} over the allowance; nobody is assigned</span>)}</td>
                  </>}
                </tr>);
            })}</tbody>
          </table>
        </div>)}
    </>
  );
}

// ---- to pay, by provider --------------------------------------------------------------

function ToPay({ go }) {
  const [d, setD] = useState(null);
  const [picked, setPicked] = useState({});
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api("/bills/to-pay").then((x) => { setD(x); setPicked({}); }).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  async function voucher(g) {
    const ids = g.bills.filter((b) => !b.voucher && picked[b.id] !== false).map((b) => b.payable);
    if (!ids.length) return;
    setBusy(true); setError(null); setMsg(null);
    try {
      const pv = await api("/payment-vouchers", { method: "POST", body: { payable_ids: ids } });
      setMsg(`Voucher ${pv.ref} raised for ${ids.length} ${g.provider} bill${ids.length === 1 ? "" : "s"} — submit it under Payment vouchers.`); load();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  if (!d) return <div style={card}>{error || "Loading…"}</div>;
  return (
    <>
      <div className="f-bar">
        <span style={{ color: "var(--muted)", fontSize: 13 }}>Unpaid bills by provider. A provider's batch goes on one voucher; untick any to leave out.</span>
        <span className="spacer" />
        <Btn variant="secondary" onClick={() => apiDownload("/bills/to-pay?export=xlsx").catch((e) => setError(e.message))}>⬇ Excel</Btn>
      </div>
      {error && <p className="f-bad" style={{ fontSize: 13.5 }}>{error}</p>}
      {msg && <p className="f-ok" style={{ fontSize: 13.5 }}>{msg} <button className="f-link" onClick={() => go("vouchers")}>Open Payment vouchers</button></p>}
      {d.groups.length === 0 ? <div style={card}>Nothing to pay. Bills appear here once a month's figures are entered.</div> : d.groups.map((g) => {
        const free = g.bills.filter((b) => !b.voucher);
        const chosen = free.filter((b) => picked[b.id] !== false);
        const total = chosen.reduce((s, b) => s + Number(b.total), 0);
        return (
          <div key={g.provider + g.currency} style={{ ...card, padding: 0, overflowX: "auto", marginBottom: 14 }}>
            <div className="f-bar" style={{ margin: 0, padding: "10px 14px" }}>
              <b style={{ fontSize: 15 }}>{g.provider}</b>
              <span style={{ fontSize: 13, color: "var(--muted)" }}>{g.count} bill{g.count === 1 ? "" : "s"} · {g.currency} {money(g.total)} · earliest due {fmtDate(g.earliest_due)}
                {g.overdue ? <span className="f-bad"> · {g.overdue} overdue</span> : null}</span>
              <span className="spacer" />
              {d.can_edit && free.length > 0 && <Btn disabled={busy || chosen.length === 0} onClick={() => voucher(g)}>Create voucher · {chosen.length} bill{chosen.length === 1 ? "" : "s"} · {g.currency} {money(total)}</Btn>}
              <Btn variant="secondary" onClick={() => apiDownload(`/bills/to-pay?export=xlsx&provider=${encodeURIComponent(g.provider)}`).catch((e) => setError(e.message))}>⬇ List</Btn>
            </div>
            <table className="f-table">
              <thead><tr><th style={{ width: 30 }} /><th>Number</th><th>Whose / where</th><th>Month</th><th>Bill no.</th><th>Due</th><th style={{ textAlign: "right" }}>Amount</th><th>Voucher</th></tr></thead>
              <tbody>{g.bills.map((b) => (
                <tr key={b.id}>
                  <td>{!b.voucher && d.can_edit && <input type="checkbox" checked={picked[b.id] !== false} aria-label={`Pay ${b.account_no}`} onChange={(e) => setPicked({ ...picked, [b.id]: e.target.checked })} />}</td>
                  <td style={{ fontFamily: "var(--font-mono)" }}><button className="f-link" style={{ fontFamily: "inherit" }} onClick={() => go("utilities", b.ref)}>{b.account_no}</button></td>
                  <td>{b.label}<Recovery r={b.recovery} /></td><td>{b.period_label}</td><td>{b.bill_no}</td>
                  <td style={{ whiteSpace: "nowrap" }} className={b.overdue ? "f-bad" : ""}>{fmtDate(b.due_date)}</td>
                  <td className="f-num">{money(b.total)}</td>
                  <td>{b.voucher ? <button className="f-link" onClick={() => go("vouchers", b.voucher)}>{b.voucher}</button> : ""}</td>
                </tr>))}</tbody>
            </table>
          </div>);
      })}
    </>
  );
}

function Recoveries() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api("/bills/recoveries").then(setD).catch((e) => setError(e.message)); }, []);
  if (!d) return <div style={card}>{error || "Loading…"}</div>;
  return (
    <>
      <p style={{ fontSize: 13, color: "var(--muted)" }}>What phones ran over their allowance. Each amount is taken with the person's advances on the payroll month shown —
        the bill's own month, or the next one not yet drawn up.</p>
      {d.recoveries.length === 0 ? <div style={card}>No bill has run over its allowance.</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Person</th><th>Number</th><th>Bill month</th><th style={{ textAlign: "right" }}>Bill</th><th style={{ textAlign: "right" }}>Recovered</th><th>Payroll month</th><th /></tr></thead>
            <tbody>{d.recoveries.map((c) => (
              <tr key={c.id}>
                <td>{c.recovery.from}<div style={{ fontSize: 12, color: "var(--muted)" }}>{c.recovery.emp_no}</div></td>
                <td style={{ fontFamily: "var(--font-mono)" }}>{c.account_no}</td><td>{c.period_label}</td>
                <td className="f-num">{money(c.total)}</td><td className="f-num" style={{ fontWeight: 700 }}>MVR {money(c.recovery.amount)}</td>
                <td>{c.recovery.month}</td>
                <td className={c.recovery.deducted ? "f-ok" : ""} style={{ fontSize: 13, fontWeight: 500 }}>{c.recovery.note}</td>
              </tr>))}</tbody>
          </table>
        </div>)}
    </>
  );
}

// sub: null | new | many | enter | pay | recoveries | <UTL-ref>
export default function UtilitiesPage({ sub, go }) {
  return (
    <div className="t-page">
      <Tabs sub={sub} go={go} />
      {!sub && <Accounts go={go} />}
      {sub === "enter" && <Enter go={go} />}
      {sub === "pay" && <ToPay go={go} />}
      {sub === "recoveries" && <Recoveries />}
      {sub === "many" && <Many go={go} />}
      {sub && !["enter", "pay", "recoveries", "many"].includes(sub) && <Account ident={sub} go={go} key={sub} />}
    </div>
  );
}
