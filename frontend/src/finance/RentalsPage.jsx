// Rentals: what the company rents and pays for period after period — offices,
// staff accommodation, warehouses, vehicles on hire. Each period's rent is
// raised by itself as it comes up and lands on Payables, ready for a payment
// voucher. (owner 2026-10-02 — core/rent.py)
import { useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "../api.js";
import { Btn, Chip, card, ghostButton, inputStyle } from "../ui.jsx";
import { fmtDate, money, today } from "./shared.jsx";
import { field, lab } from "./forms.jsx";

const BLANK = { title: "", kind: "OFFICE", landlord: "", landlord_tin: "", landlord_contact: "", payee_account: "", site: "",
  cost_head: "", currency: "MVR", amount: "", gst_applicable: false, frequency: "MONTHLY", in_advance: true, due_day: "",
  start_date: "", end_date: "", dues_from: "", lead_days: 7, deposit_amount: "", notes: "", steps: [], status: "ACTIVE" };
const PER = { MONTHLY: "a month", QUARTERLY: "a quarter", HALF_YEARLY: "a half-year", YEARLY: "a year" };

function DueChip({ d }) {
  if (d.status === "PAID") return <Chip tone="ok">Paid</Chip>;
  if (d.status === "CANCELLED") return <Chip tone="info">Cancelled</Chip>;
  return d.overdue ? <Chip tone="alert">Overdue</Chip> : <Chip tone="warn">Due</Chip>;
}

function List({ go }) {
  const [data, setData] = useState(null);
  const [all, setAll] = useState(false);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => api(`/rent/contracts${all ? "?status=all" : ""}`).then(setData).catch((e) => setError(e.message)), [all]);
  useEffect(() => { load(); }, [load]);
  async function raiseNow() {
    setError(null); setMsg(null);
    try { const r = await api("/rent/raise", { method: "POST", body: {} }); setMsg(r.raised ? `${r.raised} due${r.raised === 1 ? "" : "s"} raised — they are on Payables.` : "Nothing new has come up."); load(); }
    catch (e) { setError(e.message); }
  }
  if (!data) return <div style={card}>{error || "Loading…"}</div>;
  const rows = data.contracts;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Rentals</h1>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          {rows.length} rental{rows.length === 1 ? "" : "s"}{data.open_count ? <> · {data.open_count} due{data.open_count === 1 ? "" : "s"} to pay
            {data.overdue_count ? <> · <span className="f-bad">{data.overdue_count} overdue</span></> : null}</> : null}</span>
        <span className="spacer" />
        <label style={{ fontSize: 13 }}><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> show ended</label>
        {data.can_edit && <>
          <Btn variant="secondary" onClick={raiseNow} title="What the daily job does: raise every period that has come up">Raise dues now</Btn>
          <Btn onClick={() => go("rentals", "new")}>+ Rental</Btn>
        </>}
      </div>
      <p style={{ fontSize: 13.5, color: "var(--muted)", marginTop: -4, maxWidth: 860 }}>
        What the company rents and pays for period after period. As each period comes up, its rent is raised by itself and
        appears on <button className="f-link" onClick={() => go("payables")}>Payables</button>, ready to go on a payment voucher.</p>
      {msg && <p className="f-ok" style={{ fontSize: 13.5 }}>{msg}</p>}
      {error && <p className="f-bad" style={{ fontSize: 13.5 }}>{error}</p>}
      {rows.length === 0 ? <div style={card}>No rentals yet.{data.can_edit && <> Add each thing the company rents with <b>+ Rental</b> — its dues then raise themselves.</>}</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Ref</th><th>What is rented</th><th>Landlord</th><th>Site</th><th style={{ textAlign: "right" }}>Rent</th><th>Next due</th>
              <th style={{ textAlign: "right" }}>To pay</th><th /></tr></thead>
            <tbody>{rows.map((c) => (
              <tr key={c.id} className="f-click" onClick={() => go("rentals", c.ref)} style={c.status === "ENDED" ? { opacity: .55 } : undefined}>
                <td style={{ fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{c.ref}</td>
                <td><div style={{ fontWeight: 600 }}>{c.title}</div><div style={{ fontSize: 12, color: "var(--muted)" }}>{c.kind_label}</div></td>
                <td>{c.landlord}</td><td>{c.site_code}</td>
                <td className="f-num" style={{ whiteSpace: "nowrap" }}>{c.currency} {money(c.current_amount)}<div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 400 }}>{PER[c.frequency]}{c.gst_applicable ? " + GST" : ""}</div></td>
                <td style={{ whiteSpace: "nowrap" }}>{c.next ? <>{fmtDate(c.next.due_date)}<div style={{ fontSize: 12, color: "var(--muted)" }}>{c.next.period}</div></> : "—"}</td>
                <td className="f-num">{c.open_count ? <>{c.currency} {money(c.open_total)}<div style={{ fontSize: 12, fontWeight: 400 }} className={c.overdue_count ? "f-bad" : ""}>{c.open_count} due{c.open_count === 1 ? "" : "s"}{c.overdue_count ? `, ${c.overdue_count} overdue` : ""}</div></> : ""}</td>
                <td>{c.status === "ENDED" && <Chip tone="info">Ended</Chip>}</td>
              </tr>))}</tbody>
          </table>
        </div>)}
    </div>
  );
}

function Rental({ ident, go }) {
  const isNew = ident === "new";
  const [c, setC] = useState(null);                  // as saved
  const [f, setF] = useState(BLANK);
  const [meta, setMeta] = useState(null);
  const [file, setFile] = useState(null);
  const [cancel, setCancel] = useState(null);        // {id, reason}
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const take = useCallback((x) => {
    setC(x); setMeta(x.meta);
    setF({ ...BLANK, ...x, site: String(x.site), cost_head: String(x.cost_head), amount: String(x.amount), due_day: x.due_day ?? "",
           end_date: x.end_date || "", deposit_amount: x.deposit_amount ?? "", steps: x.steps || [] });
  }, []);
  useEffect(() => {
    if (isNew) {
      api("/rent/contracts").then((d) => { setMeta(d.meta); setF((x) => ({ ...x, cost_head: String(d.meta.default_head || "") })); }).catch((e) => setError(e.message));
    } else api(`/rent/contracts/${ident}`).then(take).catch((e) => setError(e.message));
  }, [ident, isNew, take]);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const setStep = (i, patch) => setF({ ...f, steps: f.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  async function save() {
    setBusy(true); setError(null); setMsg(null);
    const body = { ...f, site: f.site ? Number(f.site) : null, cost_head: f.cost_head ? Number(f.cost_head) : null,
      due_day: f.due_day === "" ? null : Number(f.due_day), lead_days: Number(f.lead_days || 0),
      steps: f.steps.filter((s) => s.from || s.amount) };
    ["dues", "meta", "next", "can_edit", "id", "ref"].forEach((k) => delete body[k]);
    if (isNew && !body.dues_from) delete body.dues_from;
    try {
      const path = isNew ? "/rent/contracts" : `/rent/contracts/${ident}`;
      let saved;
      if (file) {
        const fd = new FormData(); fd.append("payload", JSON.stringify(body)); fd.append("agreement", file);
        saved = await apiUpload(path, fd, isNew ? "POST" : "PATCH");
      } else saved = await api(path, { method: isNew ? "POST" : "PATCH", body });
      if (isNew) go("rentals", saved.ref); else { take({ ...saved, meta: saved.meta || meta }); setMsg("Saved."); setFile(null); }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function act(path, body, done) {
    setError(null); setMsg(null);
    try { const x = await api(path, { method: "POST", body }); take(x); if (done) setMsg(done(x)); }
    catch (e) { setError(e.message); }
  }
  if (!meta) return <div style={card}>{error || "Loading…"}</div>;
  const canEdit = isNew ? true : c?.can_edit;
  const ro = !canEdit;
  const grid = { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "10px 16px" };
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{isNew ? "New rental" : `${c.ref} · ${c.title}`}</h1>
        {c?.status === "ENDED" && <Chip tone="info">Ended</Chip>}
        <span className="spacer" />
        <button style={ghostButton} onClick={() => go("rentals")}>← Rentals</button>
      </div>

      <div style={{ ...card, marginBottom: 12 }}>
        <div style={grid}>
          <label style={{ ...field, gridColumn: "span 2" }}>{lab("What is rented")}
            <input style={inputStyle} value={f.title} disabled={ro} onChange={set("title")} placeholder="Head office, H. Sunny Villa, 3rd floor" /></label>
          <label style={field}>{lab("Kind")}
            <select style={inputStyle} value={f.kind} disabled={ro} onChange={set("kind")}>{meta.kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}</select></label>
          <label style={field}>{lab("Site that bears the cost")}
            <select style={inputStyle} value={f.site} disabled={ro} onChange={set("site")}><option value="">— pick —</option>
              {meta.sites.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}</select></label>
          <label style={{ ...field, gridColumn: "span 2" }}>{lab("Landlord / owner")}
            <input style={inputStyle} value={f.landlord} disabled={ro} onChange={set("landlord")} /></label>
          <label style={field}>{lab("Landlord TIN")}
            <input style={inputStyle} value={f.landlord_tin} disabled={ro} onChange={set("landlord_tin")} /></label>
          <label style={field}>{lab("Phone / email")}
            <input style={inputStyle} value={f.landlord_contact} disabled={ro} onChange={set("landlord_contact")} /></label>
          <label style={{ ...field, gridColumn: "span 2" }}>{lab("Pay to (bank and account)")}
            <input style={inputStyle} value={f.payee_account} disabled={ro} onChange={set("payee_account")} placeholder="BML 7730000012345 — Ahmed Ali" /></label>
          <label style={field}>{lab("Cost head")}
            <select style={inputStyle} value={f.cost_head} disabled={ro} onChange={set("cost_head")}>
              {meta.cost_heads.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}</select></label>
        </div>
      </div>

      <div style={{ ...card, marginBottom: 12 }}>
        <div style={grid}>
          <label style={field}>{lab(`Rent ${PER[f.frequency]}, before GST`)}
            <input style={{ ...inputStyle, textAlign: "right" }} value={f.amount} disabled={ro} onChange={set("amount")} /></label>
          <label style={field}>{lab("Currency")}
            <select style={inputStyle} value={f.currency} disabled={ro} onChange={set("currency")}><option>MVR</option><option>USD</option></select></label>
          <label style={field}>{lab("Paid")}
            <select style={inputStyle} value={f.frequency} disabled={ro} onChange={set("frequency")}>{meta.frequencies.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}</select></label>
          <label style={field}>{lab("Falls due")}
            <select style={inputStyle} value={f.in_advance ? "1" : "0"} disabled={ro} onChange={(e) => setF({ ...f, in_advance: e.target.value === "1" })}>
              <option value="1">In advance — as the period starts</option><option value="0">In arrears — as the period ends</option></select></label>
          <label style={field}>{lab("On day of the month (optional)")}
            <input style={inputStyle} value={f.due_day} disabled={ro} onChange={set("due_day")} placeholder="1–28" /></label>
          <label style={field}>{lab("Rental starts")}
            <input type="date" style={inputStyle} value={f.start_date} disabled={ro} onChange={set("start_date")} /></label>
          <label style={field}>{lab("Ends (blank = open)")}
            <input type="date" style={inputStyle} value={f.end_date} disabled={ro} onChange={set("end_date")} /></label>
          <label style={field}>{lab("Raise dues from")}
            <input type="date" style={inputStyle} value={f.dues_from} disabled={ro} onChange={set("dues_from")} />
            <span style={{ fontSize: 12, color: "var(--muted)" }}>{isNew ? `Blank = from today (${fmtDate(today())}). ` : ""}Earlier periods are taken as paid outside Planet.</span></label>
          <label style={field}>{lab("Raise each due … days ahead")}
            <input style={inputStyle} value={f.lead_days} disabled={ro} onChange={set("lead_days")} /></label>
          <label style={field}>{lab("Deposit held by landlord")}
            <input style={{ ...inputStyle, textAlign: "right" }} value={f.deposit_amount} disabled={ro} onChange={set("deposit_amount")} /></label>
        </div>
        <label style={{ display: "block", fontSize: 13.5, marginTop: 10 }}>
          <input type="checkbox" checked={f.gst_applicable} disabled={ro} onChange={set("gst_applicable")} /> The landlord charges GST
          {f.gst_applicable && <span style={{ color: "var(--muted)" }}> — {meta.gst_rate}% is added to each due and goes to the recoverable input tax</span>}</label>

        <div style={{ marginTop: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 4 }}>Agreed changes of rent</div>
          {f.steps.length === 0 && <span style={{ fontSize: 13, color: "var(--muted)" }}>None — the rent above applies throughout. </span>}
          {f.steps.map((s, i) => (
            <div key={i} className="f-bar" style={{ margin: "4px 0" }}>
              <span style={{ fontSize: 13 }}>From</span>
              <input type="date" style={{ ...inputStyle, width: 160 }} value={s.from || ""} disabled={ro} onChange={(e) => setStep(i, { from: e.target.value })} />
              <span style={{ fontSize: 13 }}>the rent is {f.currency}</span>
              <input style={{ ...inputStyle, width: 130, textAlign: "right" }} value={s.amount || ""} disabled={ro} onChange={(e) => setStep(i, { amount: e.target.value })} />
              {!ro && <button className="f-link" onClick={() => setF({ ...f, steps: f.steps.filter((_, j) => j !== i) })}>remove</button>}
            </div>))}
          {!ro && <button className="f-link" onClick={() => setF({ ...f, steps: [...f.steps, { from: "", amount: "" }] })}>+ Add a change</button>}
        </div>
      </div>

      <div style={{ ...card, marginBottom: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 16 }}>
          <label style={field}>{lab("Notes")}
            <input style={inputStyle} value={f.notes} disabled={ro} onChange={set("notes")} /></label>
          <label style={field}>{lab("Agreement (scan)")}
            {!ro && <input type="file" accept="image/*,.pdf" style={{ fontSize: 12 }} onChange={(e) => setFile(e.target.files[0] || null)} />}
            {c?.agreement_url && <a href={c.agreement_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>Open the agreement</a>}</label>
          {!isNew && <label style={field}>{lab("Status")}
            <select style={inputStyle} value={f.status} disabled={ro} onChange={set("status")}><option value="ACTIVE">Active</option><option value="ENDED">Ended — raise no more dues</option></select></label>}
        </div>
      </div>

      {error && <p className="f-bad" style={{ fontSize: 13.5 }}>{error}</p>}
      {msg && <p className="f-ok" style={{ fontSize: 13.5 }}>{msg}</p>}
      {canEdit && (
        <div className="f-bar">
          <Btn disabled={busy || !f.title.trim() || !f.landlord.trim() || !f.site || !f.amount || !f.start_date} onClick={save}>
            {busy ? "Saving…" : isNew ? "Save rental" : "Save changes"}</Btn>
          {!isNew && c.status === "ACTIVE" && c.next && (
            <Btn variant="secondary" onClick={() => act(`/rent/contracts/${c.ref}/raise`, { ahead: true }, (x) => `${x.raised} due${x.raised === 1 ? "" : "s"} raised.`)}
                 title="Raise the next period now, before its time">Raise {c.next.period} now</Btn>)}
          {!isNew && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>Changing the terms does not touch dues already raised.</span>}
        </div>)}

      {!isNew && (
        <>
          <h3 style={{ margin: "18px 0 8px" }}>Dues{c.next ? <span style={{ fontWeight: 400, fontSize: 13, color: "var(--muted)" }}> · next: {c.next.period}, due {fmtDate(c.next.due_date)}</span> : null}</h3>
          {c.dues.length === 0 ? <div style={card}>None raised yet.</div> : (
            <div style={{ ...card, padding: 0, overflowX: "auto" }}>
              <table className="f-table">
                <thead><tr><th>Period</th><th>Due</th><th style={{ textAlign: "right" }}>Rent</th><th style={{ textAlign: "right" }}>GST</th>
                  <th style={{ textAlign: "right" }}>To pay</th><th /><th>Voucher / payment</th><th /></tr></thead>
                <tbody>{c.dues.map((d) => (
                  <tr key={d.id} style={d.status === "CANCELLED" ? { opacity: .6 } : undefined}>
                    <td>{d.period}</td><td style={{ whiteSpace: "nowrap" }}>{fmtDate(d.due_date)}</td>
                    <td className="f-num">{money(d.amount)}</td><td className="f-num">{Number(d.gst) ? money(d.gst) : ""}</td>
                    <td className="f-num" style={{ fontWeight: 700 }}>{d.currency} {money(d.total)}</td>
                    <td><DueChip d={d} /></td>
                    <td style={{ fontSize: 13 }}>
                      {d.voucher && <button className="f-link" onClick={() => go("vouchers", d.voucher)}>{d.voucher}</button>}
                      {d.status === "PAID" && <span style={{ color: "var(--muted)" }}> paid {fmtDate(d.paid_on)}{d.paid_ref ? ` · ${d.paid_ref}` : ""}</span>}
                      {d.status === "RAISED" && !d.voucher && <button className="f-link" onClick={() => go("payables")}>on Payables</button>}
                      {d.status === "CANCELLED" && <span style={{ color: "var(--muted)" }}>{d.cancel_reason}</span>}</td>
                    <td style={{ whiteSpace: "nowrap" }}>{canEdit && d.status === "RAISED" && (cancel?.id === d.id ? (
                      <span className="f-bar" style={{ margin: 0 }}>
                        <input style={{ ...inputStyle, width: 190 }} placeholder="Why?" value={cancel.reason} onChange={(e) => setCancel({ ...cancel, reason: e.target.value })} />
                        <button className="f-link" onClick={() => { act(`/rent/dues/${d.id}/cancel`, { reason: cancel.reason }); setCancel(null); }}>Cancel it</button>
                        <button className="f-link" onClick={() => setCancel(null)}>keep</button></span>
                    ) : <button className="f-link" onClick={() => setCancel({ id: d.id, reason: "" })}>Cancel…</button>)}
                      {canEdit && d.status === "CANCELLED" && <button className="f-link" onClick={() => act(`/rent/dues/${d.id}/raise-again`, {})}>Raise again</button>}</td>
                  </tr>))}</tbody>
              </table>
            </div>)}
        </>)}
    </div>
  );
}

// sub: null | new | <ref or id>
export default function RentalsPage({ sub, go }) {
  return sub ? <Rental ident={sub} go={go} key={sub} /> : <List go={go} />;
}
