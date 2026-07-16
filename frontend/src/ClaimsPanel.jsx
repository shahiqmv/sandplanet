import { Fragment, useEffect, useState } from "react";
import { api } from "./api.js";
import { Chip, Eyebrow, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const EDIT_ROLES = ["PM", "ADMIN", "DIRECTOR", "QS"];
const fmt = (v) =>
  Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2,
    maximumFractionDigits: 2 });
const signed = (v) => (Number(v) < 0 ? `(${fmt(-v)})` : fmt(v));
const STATUS_TONE = { DRAFT: "info", SUBMITTED: "info", CERTIFIED: "ok",
  PAID: "ok", REJECTED: "alert" };
const TYPE_LABEL = { ADVANCE: "Advance", INTERIM: "Interim",
  RELEASE: "Retention release", FINAL: "Final account" };

// Progress claims (interim payment applications / IPCs) — the QS values work
// done to date against the BOQ + approved variations and claims the balance,
// applying advance recovery, retention and output GST (the Soneva IPA layout).
export default function ClaimsPanel({ projectId, me }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [receiptForm, setReceiptForm] = useState(null);   // null = closed
  const canEdit = EDIT_ROLES.includes(me.role);

  function load() {
    setError(null);
    api(`/projects/${projectId}/claims`).then(setData)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function raise() {
    setError(null); setBusy(true);
    try {
      const d = await api(`/projects/${projectId}/claims/create`,
        { method: "POST", body: {} });
      setData(d);
      setOpenId(d.claims[d.claims.length - 1].id);
    } catch (e) { setError(e.message); }
    setBusy(false);
  }

  async function recordReceipt() {
    setError(null); setBusy(true);
    try {
      setData(await api(`/projects/${projectId}/receipts`,
        { method: "POST", body: receiptForm }));
      setReceiptForm(null);
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  async function delReceipt(id) {
    if (!window.confirm("Delete this receipt?")) return;
    setError(null);
    try { setData(await api(`/receipts/${id}/delete`, { method: "DELETE" })); }
    catch (e) { setError(e.message); }
  }

  if (error && !data) return <section style={card}>{error}</section>;
  if (!data) return <section style={card}>Loading…</section>;
  const ccy = data.currency;
  const rev = data.revenue || {};

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    marginBottom: 8 }}>
        <Eyebrow meta={`${data.claims.length}`}>Progress claims</Eyebrow>
        {canEdit && data.can_raise && (
          <button style={{ ...ghostButton, marginLeft: "auto",
                           padding: "4px 12px" }}
                  disabled={busy} onClick={raise}>
            {busy ? "…" : "+ New claim"}</button>
        )}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {!data.can_raise && (
        <p style={{ color: "var(--muted)", fontSize: 13 }}>
          Enter the BOQ first — claims are valued against it.</p>
      )}

      {/* Money-in position (P4) */}
      {data.claims.length > 0 && (
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 13,
                      margin: "4px 0 14px", padding: "10px 12px",
                      background: "var(--sp-tint,#f5f8fb)", borderRadius: 8 }}>
          <Fig label="Revised contract"
               v={`${ccy} ${fmt(rev.contract_revised)}`} />
          <Fig label="Certified revenue"
               v={`${ccy} ${fmt(rev.certified_revenue)}`}
               sub={`${fmt(rev.pct_complete)}% complete · ex-GST`} strong />
          <Fig label="Retention held" v={`${ccy} ${fmt(rev.retention_held)}`} />
          <Fig label="Billed (incl GST)" v={`${ccy} ${fmt(rev.billed)}`} />
          <Fig label="Received" v={`${ccy} ${fmt(rev.received)}`} />
          <Fig label="Outstanding" v={`${ccy} ${fmt(rev.outstanding)}`}
               tone={Number(rev.outstanding) > 0 ? "#b0402f" : undefined}
               strong />
        </div>
      )}

      {data.claims.length === 0 && data.can_raise ? (
        <p style={{ color: "var(--muted)", fontSize: 13 }}>
          No claims yet. Raise the first interim application when work is
          ready to certify.</p>
      ) : data.claims.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Ref</th><th style={th}>Type</th>
              <th style={th}>Up to</th><th style={th}>Status</th>
              <th style={{ ...th, textAlign: "right" }}>Net due</th>
              <th style={{ ...th, textAlign: "right" }}>GST</th>
              <th style={{ ...th, textAlign: "right" }}>Total {ccy}</th>
            </tr></thead>
            <tbody>
              {data.claims.map((c) => (
                <Fragment key={c.id}>
                  <tr style={{ cursor: "pointer" }}
                      onClick={() => setOpenId(openId === c.id ? null : c.id)}>
                    <td style={{ ...td, fontWeight: 600, color: "var(--navy)" }}>
                      {openId === c.id ? "▾ " : "▸ "}{c.ref}</td>
                    <td style={td}>{TYPE_LABEL[c.claim_type] || c.claim_type}</td>
                    <td style={td}>{c.work_done_upto || "—"}</td>
                    <td style={td}>
                      <Chip tone={STATUS_TONE[c.status] || "info"}>
                        {c.status}</Chip></td>
                    <td style={{ ...td, textAlign: "right" }}>
                      {fmt(c.net_due)}</td>
                    <td style={{ ...td, textAlign: "right" }}>{fmt(c.gst)}</td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 700 }}>
                      {fmt(c.total)}</td>
                  </tr>
                  {openId === c.id && (
                    <tr><td colSpan={7} style={{ padding: 0 }}>
                      <ClaimEditor claimId={c.id} ccy={ccy} canEdit={canEdit}
                                   onChange={(d) => d && setData(d)}
                                   reloadList={load} />
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Client receipts (P4) */}
      {data.claims.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Eyebrow meta={`${data.receipts.length}`}>Client receipts</Eyebrow>
            {canEdit && !receiptForm && (
              <button style={{ ...ghostButton, marginLeft: "auto",
                               padding: "4px 12px" }}
                      onClick={() => setReceiptForm({ amount: "",
                        received_on: "", claim_id: "", reference: "",
                        note: "" })}>+ Record receipt</button>
            )}
          </div>
          {receiptForm && (
            <ReceiptForm form={receiptForm} setForm={setReceiptForm} ccy={ccy}
                         claims={data.claims} busy={busy}
                         onSave={recordReceipt} />
          )}
          {data.receipts.length === 0 ? (
            <p style={{ color: "var(--muted)", fontSize: 13, margin: "6px 0 0" }}>
              No client receipts recorded yet.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse",
                              fontSize: 13, marginTop: 6 }}>
                <thead><tr>
                  <th style={th}>Date</th><th style={th}>Against</th>
                  <th style={th}>Reference</th>
                  <th style={{ ...th, textAlign: "right" }}>Amount {ccy}</th>
                  <th style={th} />
                </tr></thead>
                <tbody>
                  {data.receipts.map((r) => (
                    <tr key={r.id}>
                      <td style={td}>{r.received_on}</td>
                      <td style={td}>{r.claim_ref || "—"}</td>
                      <td style={td}>{r.reference || "—"}</td>
                      <td style={{ ...td, textAlign: "right",
                                   fontWeight: 600 }}>{fmt(r.amount)}</td>
                      <td style={{ ...td, textAlign: "right" }}>
                        {canEdit && (
                          <button style={{ ...ghostButton, padding: "2px 8px",
                            fontSize: 12, color: "#c0392b" }}
                            onClick={() => delReceipt(r.id)}>delete</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function Fig({ label, v, sub, strong, tone }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--muted)",
                    textTransform: "uppercase", letterSpacing: ".04em" }}>
        {label}</div>
      <div style={{ fontWeight: strong ? 700 : 500, fontSize: strong ? 15 : 13,
                    color: tone || (strong ? "var(--navy)" : "inherit") }}>
        {v}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--muted)" }}>{sub}</div>}
    </div>
  );
}

function ReceiptForm({ form, setForm, ccy, claims, busy, onSave }) {
  const set = (k, v) => setForm({ ...form, [k]: v });
  const billable = claims.filter(
    (c) => ["CERTIFIED", "PAID"].includes(c.status));
  return (
    <div style={{ ...card, margin: "8px 0",
                  background: "var(--sp-tint,#f5f8fb)", display: "flex",
                  gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <input type="number" placeholder={`Amount (${ccy})`} value={form.amount}
             onChange={(e) => set("amount", e.target.value)}
             style={{ ...inputStyle, width: 140 }} />
      <input type="date" value={form.received_on}
             onChange={(e) => set("received_on", e.target.value)}
             style={{ ...inputStyle, width: 150 }} />
      <select value={form.claim_id}
              onChange={(e) => set("claim_id", e.target.value)}
              style={{ ...inputStyle, width: 180 }}>
        <option value="">Against claim… (optional)</option>
        {billable.map((c) => (
          <option key={c.id} value={c.id}>{c.ref}</option>
        ))}
      </select>
      <input placeholder="Bank / TT ref" value={form.reference}
             onChange={(e) => set("reference", e.target.value)}
             style={{ ...inputStyle, width: 160 }} />
      <button style={{ ...buttonStyle, padding: "4px 14px" }} disabled={busy}
              onClick={onSave}>Save receipt</button>
      <button style={ghostButton}
              onClick={() => setForm(null)}>Cancel</button>
    </div>
  );
}

const numCell = { ...inputStyle, width: 84, padding: "3px 5px", fontSize: 12,
  textAlign: "right" };

function ClaimEditor({ claimId, ccy, canEdit, onChange, reloadList }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  // local editable copies
  const [meta, setMeta] = useState(null);
  const [vals, setVals] = useState({});   // line id -> {pct, qty}

  function hydrate(detail) {
    setD(detail);
    const c = detail.claim;
    setMeta({ claim_type: c.claim_type, basis: c.basis,
      work_done_upto: c.work_done_upto || "",
      material_on_site: c.material_on_site, material_off_site: c.material_off_site,
      retention_released: c.retention_released });
    const v = {};
    detail.lines.forEach((ln) => {
      v[ln.id] = { pct: ln.cumulative_pct ?? "", qty: ln.cumulative_qty ?? "" };
    });
    setVals(v);
  }
  useEffect(() => {
    api(`/claims/${claimId}`).then(hydrate).catch((e) => setError(e.message));
  }, [claimId]);

  if (error && !d) return <div style={{ padding: 12,
    color: "#c0392b" }}>{error}</div>;
  if (!d) return <div style={{ padding: 12, color: "var(--muted)" }}>Loading…</div>;

  const c = d.claim;
  const w = d.waterfall;
  const editable = canEdit && c.status === "DRAFT";
  const measured = meta.basis === "MEASURED";

  async function save() {
    setError(null); setBusy(true);
    try {
      await api(`/claims/${claimId}/meta`, { method: "POST", body: {
        claim_type: meta.claim_type, basis: meta.basis,
        work_done_upto: meta.work_done_upto || null,
        material_on_site: meta.material_on_site || 0,
        material_off_site: meta.material_off_site || 0,
        retention_released: meta.retention_released || 0 } });
      const rows = d.lines.map((ln) => ({ id: ln.id,
        cumulative_pct: vals[ln.id]?.pct === "" ? null : vals[ln.id]?.pct,
        cumulative_qty: vals[ln.id]?.qty === "" ? null : vals[ln.id]?.qty }));
      const fresh = await api(`/claims/${claimId}/items`,
        { method: "POST", body: { rows } });
      hydrate(fresh);
      reloadList();
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  async function status(s) {
    setError(null); setBusy(true);
    try {
      const fresh = await api(`/claims/${claimId}/status`,
        { method: "POST", body: { status: s } });
      hydrate(fresh);
      reloadList();
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  async function del() {
    setError(null); setBusy(true);
    try {
      const list = await api(`/claims/${claimId}/delete`, { method: "DELETE" });
      onChange(list);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  const setV = (id, k, val) =>
    setVals({ ...vals, [id]: { ...vals[id], [k]: val } });
  const setM = (k, val) => setMeta({ ...meta, [k]: val });

  return (
    <div style={{ ...card, margin: "6px 0", background: "var(--sp-tint,#f5f8fb)" }}>
      {/* Header meta */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                    alignItems: "center", marginBottom: 10, fontSize: 13 }}>
        <strong style={{ color: "var(--navy)" }}>{c.ref}</strong>
        <label>Type{" "}
          <select value={meta.claim_type} disabled={!editable}
                  onChange={(e) => setM("claim_type", e.target.value)}
                  style={{ ...inputStyle, width: 150 }}>
            {Object.entries(TYPE_LABEL).map(([k, v]) =>
              <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>Basis{" "}
          <select value={meta.basis} disabled={!editable}
                  onChange={(e) => setM("basis", e.target.value)}
                  style={{ ...inputStyle, width: 140 }}>
            <option value="PERCENT">% complete</option>
            <option value="MEASURED">Measured qty</option>
          </select>
        </label>
        <label>Work done up to{" "}
          <input type="date" value={meta.work_done_upto} disabled={!editable}
                 onChange={(e) => setM("work_done_upto", e.target.value)}
                 style={{ ...inputStyle, width: 150 }} />
        </label>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {/* Line valuation */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 12 }}>
          <thead><tr>
            <th style={th}>Code</th><th style={th}>Description</th>
            <th style={{ ...th, textAlign: "right" }}>Contract {ccy}</th>
            <th style={{ ...th, textAlign: "right" }}>
              {measured ? "Qty done" : "% done"}</th>
            <th style={{ ...th, textAlign: "right" }}>Previous</th>
            <th style={{ ...th, textAlign: "right" }}>This claim</th>
            <th style={{ ...th, textAlign: "right" }}>Cumulative</th>
          </tr></thead>
          <tbody>
            {d.lines.map((ln) => (
              <tr key={ln.id}>
                <td style={td}>{ln.item_code}
                  {ln.source === "VO" && (
                    <span style={{ marginLeft: 4, fontSize: 10,
                      color: "#8a6d00", background: "#fff4e0",
                      padding: "0 5px", borderRadius: 8 }}>VO</span>)}
                </td>
                <td style={{ ...td, maxWidth: 260 }}>{ln.description}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {fmt(ln.contract_amount)}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {editable ? (
                    <input type="number" style={numCell}
                      value={measured ? (vals[ln.id]?.qty ?? "")
                        : (vals[ln.id]?.pct ?? "")}
                      onChange={(e) => setV(ln.id, measured ? "qty" : "pct",
                        e.target.value)} />
                  ) : (measured ? fmt(ln.cumulative_qty)
                    : `${fmt(ln.cumulative_pct)}%`)}
                </td>
                <td style={{ ...td, textAlign: "right", color: "var(--muted)" }}>
                  {fmt(ln.previous_value)}</td>
                <td style={{ ...td, textAlign: "right", fontWeight: 600 }}>
                  {fmt(ln.current_value)}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {fmt(ln.cumulative_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Manual header figures + save */}
      {editable && (
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap",
                      alignItems: "center", margin: "10px 0", fontSize: 12 }}>
          <label>Material on site{" "}
            <input type="number" style={numCell} value={meta.material_on_site}
              onChange={(e) => setM("material_on_site", e.target.value)} /></label>
          <label>Material off site{" "}
            <input type="number" style={numCell} value={meta.material_off_site}
              onChange={(e) => setM("material_off_site", e.target.value)} /></label>
          <label>Retention released{" "}
            <input type="number" style={numCell} value={meta.retention_released}
              onChange={(e) => setM("retention_released", e.target.value)} /></label>
          <button style={{ ...buttonStyle, padding: "4px 16px" }}
                  disabled={busy} onClick={save}>
            {busy ? "Saving…" : "Save & recalc"}</button>
        </div>
      )}

      {/* Waterfall */}
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap",
                    marginTop: 8 }}>
        <div style={{ flex: "1 1 320px", maxWidth: 420 }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <tbody>
              <W label="Value of work done (BOQ)" v={w.k1_work_done} ccy={ccy} />
              {Number(w.k4_variations) !== 0 &&
                <W label="Variations" v={w.k4_variations} ccy={ccy} />}
              {Number(w.k2_material_on_site) !== 0 &&
                <W label="Material on site" v={w.k2_material_on_site} ccy={ccy} />}
              {Number(w.k3_material_off_site) !== 0 &&
                <W label="Material off site" v={w.k3_material_off_site}
                   ccy={ccy} />}
              <W label="Gross cumulative" v={w.k_gross} ccy={ccy} strong />
              <W label="Less advance recovery" v={-w.advance_recovered}
                 ccy={ccy} neg />
              <W label="Less retention" v={-w.retention_held} ccy={ccy} neg />
              {Number(w.retention_released) !== 0 &&
                <W label="Add retention released" v={w.retention_released}
                   ccy={ccy} />}
              <W label="Net cumulative certified" v={w.net_cumulative}
                 ccy={ccy} strong />
              <W label="Less previously certified" v={-w.previously_certified}
                 ccy={ccy} neg />
              <W label="Net now due (ex-GST)" v={w.net_due} ccy={ccy} strong />
              <W label={`Output GST @ ${fmt(c.gst_pct)}%`} v={w.gst}
                 ccy={ccy} />
              <W label="Total due incl. GST" v={w.total} ccy={ccy} big />
            </tbody>
          </table>
        </div>
        <div style={{ flex: "1 1 240px" }}>
          <div style={{ fontSize: 11, color: "var(--muted)",
                        textTransform: "uppercase", letterSpacing: ".04em",
                        marginBottom: 4 }}>By bill / section</div>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 12 }}>
            <thead><tr>
              <th style={th}>Section</th>
              <th style={{ ...th, textAlign: "right" }}>This claim</th>
              <th style={{ ...th, textAlign: "right" }}>Cumulative</th>
            </tr></thead>
            <tbody>
              {d.section_summary.map((s) => (
                <tr key={s.section}>
                  <td style={td}>{s.section}</td>
                  <td style={{ ...td, textAlign: "right" }}>{fmt(s.current)}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {fmt(s.cumulative)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Documents (P5) */}
      {c.status !== "DRAFT" && (
        <div style={{ display: "flex", gap: 14, marginTop: 12,
                      flexWrap: "wrap", alignItems: "center" }}>
          <a href={`/api/v1/claims/${claimId}/ipa.pdf`} target="_blank"
             rel="noreferrer" style={{ fontSize: 13, color: "var(--navy)",
                                       fontWeight: 600 }}>
            ⬇ Payment application (IPA)</a>
          {["CERTIFIED", "PAID"].includes(c.status) && (
            <a href={`/api/v1/claims/${claimId}/invoice.pdf`} target="_blank"
               rel="noreferrer" style={{ fontSize: 13, color: "var(--navy)",
                                         fontWeight: 600 }}>
              ⬇ Tax invoice{c.invoice_no ? ` · ${c.invoice_no}` : ""}</a>
          )}
        </div>
      )}

      {/* Workflow */}
      {canEdit && (
        <div style={{ display: "flex", gap: 8, marginTop: 12,
                      flexWrap: "wrap" }}>
          {c.status === "DRAFT" && (<>
            <button style={{ ...buttonStyle, padding: "4px 14px" }}
                    disabled={busy} onClick={() => status("SUBMITTED")}>
              Submit</button>
            <button style={{ ...ghostButton, color: "#c0392b" }}
                    disabled={busy} onClick={del}>Delete</button>
          </>)}
          {c.status === "SUBMITTED" && (<>
            <button style={{ ...buttonStyle, padding: "4px 14px" }}
                    disabled={busy} onClick={() => status("CERTIFIED")}>
              Certify</button>
            <button style={{ ...ghostButton, color: "#c0392b" }}
                    disabled={busy} onClick={() => status("REJECTED")}>
              Reject</button>
            <button style={ghostButton} disabled={busy}
                    onClick={() => status("DRAFT")}>Reopen</button>
          </>)}
          {c.status === "CERTIFIED" && (
            <button style={{ ...buttonStyle, padding: "4px 14px" }}
                    disabled={busy} onClick={() => status("PAID")}>
              Mark paid</button>
          )}
          {c.status === "REJECTED" && (
            <button style={ghostButton} disabled={busy}
                    onClick={() => status("DRAFT")}>Reopen</button>
          )}
        </div>
      )}
    </div>
  );
}

function W({ label, v, ccy, strong, big, neg }) {
  return (
    <tr style={{ borderTop: (strong || big) ? "1px solid var(--line,#dce3ea)"
                 : "none" }}>
      <td style={{ padding: "3px 6px", fontWeight: (strong || big) ? 700 : 400,
                   fontSize: big ? 14 : 13 }}>{label}</td>
      <td style={{ padding: "3px 6px", textAlign: "right",
                   fontWeight: (strong || big) ? 700 : 400,
                   fontSize: big ? 15 : 13,
                   color: neg ? "#b0402f" : (big ? "var(--navy)" : "inherit") }}>
        {ccy} {signed(v)}</td>
    </tr>
  );
}
