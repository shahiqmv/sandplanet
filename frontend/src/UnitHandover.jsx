import { useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

/* Handing one unit — a villa, a pool — to the client on its own, as it is
 * finished (owner 2026-10-05). Offered → inspected jointly → handed over on a
 * signed certificate, with minor snags still open if need be; a major one
 * holds it. The unit's defects period runs from its own handover date.
 * Rules live in core/unit_handover.py.
 */
export const HANDOVER_TONE = { NONE: "info", OFFERED: "warn", INSPECTED: "warn",
                               HANDED_OVER: "ok" };
const SNAG_TONE = { OPEN: "alert", IN_PROGRESS: "warn", FIXED: "warn",
                    CLOSED: "ok", REJECTED: "info" };
const SNAG_LABEL = { OPEN: "Open", IN_PROGRESS: "In progress",
                     FIXED: "Fixed — to check", CLOSED: "Closed",
                     REJECTED: "Not a defect" };
const today = () => new Date().toLocaleDateString("en-CA");
const lab = { fontSize: 12, fontWeight: 600, color: "#3a4750",
              display: "flex", flexDirection: "column", gap: 3 };

/** The chip a unit board shows: where its handover stands. */
export function HandoverChip({ h }) {
  if (!h) return null;
  return (
    <span>
      <Chip tone={HANDOVER_TONE[h.status] || "info"}>
        {h.status === "HANDED_OVER" ? `Handed over ${h.handed_over_on}`
          : h.status_label}</Chip>
      {h.snags_open > 0 && (
        <div style={{ fontSize: 11, marginTop: 2,
                      color: h.snags_major_open ? "#a3271b" : "var(--muted)" }}>
          {h.snags_open} snag{h.snags_open === 1 ? "" : "s"} open
          {h.snags_major_open ? ` · ${h.snags_major_open} major` : ""}</div>)}
    </span>);
}

export default function UnitHandover({ unitId, onClose }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [offer, setOffer] = useState({ proposed_inspection: "" });
  const [insp, setInsp] = useState({ inspected_on: today(),
    client_attendees: "", our_attendees: "", inspection_notes: "" });
  const [ho, setHo] = useState({ handed_over_on: today(),
    client_signatory: "", client_position: "", file: null });
  const [snag, setSnag] = useState({ description: "", location: "",
    severity: "MINOR", due_date: "", photo: null });

  const load = useCallback(() => api(`/units/${unitId}/handover`)
    .then(setD).catch((e) => setError(e.message)), [unitId]);
  useEffect(() => { load(); }, [load]);

  async function run(fn) {
    setBusy(true); setError(null);
    try { setD(await fn()); } catch (e) { setError(e.message); }
    setBusy(false);
  }
  const post = (action, body) => run(() =>
    api(`/units/${unitId}/handover/${action}`, { method: "POST", body }));

  function handOver() {
    if (!ho.file) {
      return post("hand-over", { handed_over_on: ho.handed_over_on,
        client_signatory: ho.client_signatory,
        client_position: ho.client_position });
    }
    const fd = new FormData();
    fd.append("handed_over_on", ho.handed_over_on);
    fd.append("client_signatory", ho.client_signatory);
    fd.append("client_position", ho.client_position);
    fd.append("signed_copy", ho.file);
    return run(() => apiUpload(`/units/${unitId}/handover/hand-over`, fd));
  }
  function signedCopy(file) {
    if (!file) return;
    const fd = new FormData();
    fd.append("signed_copy", file);
    run(() => apiUpload(`/units/${unitId}/handover/signed-copy`, fd));
  }
  function addSnag() {
    const fd = new FormData();
    fd.append("description", snag.description);
    fd.append("location", snag.location);
    fd.append("severity", snag.severity);
    if (snag.due_date) fd.append("due_date", snag.due_date);
    if (snag.photo) fd.append("photo", snag.photo);
    run(async () => {
      const x = await apiUpload(`/units/${unitId}/handover/snags`, fd);
      setSnag({ description: "", location: "", severity: "MINOR",
                due_date: "", photo: null });
      return x;
    });
  }
  const patchSnag = (s, body) => run(async () => {
    await api(`/handover/snags/${s.id}`, { method: "PATCH", body });
    return api(`/units/${unitId}/handover`);
  });
  function stepBack() {
    const reason = window.prompt(
      d.status === "HANDED_OVER" ? "Take the handover back — why?"
        : d.status === "INSPECTED" ? "Take the inspection back — why?"
        : "Withdraw the offer — why?");
    if (reason === null) return;
    post("step-back", { reason });
  }

  const shell = (body) => (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,30,45,.45)",
                  zIndex: 60, overflowY: "auto", padding: "4vh 12px" }}
         onClick={onClose}>
      <section style={{ ...card, maxWidth: 860, margin: "0 auto" }}
               onClick={(e) => e.stopPropagation()}>{body}</section>
    </div>);
  if (!d) return shell(<p style={{ fontSize: 13 }}>{error || "Loading…"}</p>);

  const can = d.can_record;
  const openSnags = d.snags.filter((s) =>
    ["OPEN", "IN_PROGRESS", "FIXED"].includes(s.status));
  const box = { border: "1px solid var(--sp-border, #d5dde3)", borderRadius: 8,
                padding: "10px 12px", marginTop: 10 };
  const row = { display: "flex", gap: 10, flexWrap: "wrap",
                alignItems: "flex-end" };
  const step = (n, title, done, sub) => (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
      <span style={{ color: done ? "#1a7f37" : "#b6c2cc", fontSize: 15 }}>
        {done ? "●" : "○"}</span>
      <strong style={{ fontSize: 13.5, color: "var(--sp-navy)" }}>
        {n}. {title}</strong>
      {sub && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{sub}</span>}
    </div>);

  return shell(<>
    <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                  flexWrap: "wrap" }}>
      <h2 style={{ margin: 0, fontSize: 17, color: "var(--sp-navy)" }}>
        Handover — {d.unit.ref}{d.unit.name ? ` · ${d.unit.name}` : ""}</h2>
      <Chip tone={HANDOVER_TONE[d.status]}>{d.status_label}</Chip>
      <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
        {d.unit.project_code} · {Math.round(Number(d.unit.percent))}% complete</span>
      <Btn variant="ghost" style={{ marginLeft: "auto" }} onClick={onClose}>
        Close</Btn>
    </div>
    {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

    {/* 1 — offered */}
    <div style={box}>
      {step(1, "Offered for inspection", d.status !== "NONE",
            d.offered_on ? `${d.offered_on} by ${d.offered_by}`
              + (d.proposed_inspection
                ? ` · inspection proposed ${d.proposed_inspection}` : "") : "")}
      {d.status === "NONE" && can && (
        <div style={{ ...row, marginTop: 8 }}>
          <label style={lab}>Proposed inspection date
            <input type="date" style={{ ...inputStyle, width: 160 }}
              value={offer.proposed_inspection}
              onChange={(e) => setOffer({ proposed_inspection: e.target.value })} />
          </label>
          <Btn disabled={busy} onClick={() => post("offer", offer)}>
            Offer for inspection</Btn>
          {Number(d.unit.percent) < 100 && (
            <span style={{ fontSize: 12, color: "#b45309" }}>
              The board shows this unit at {Math.round(Number(d.unit.percent))}%.
            </span>)}
        </div>)}
    </div>

    {/* 2 — inspected */}
    <div style={box}>
      {step(2, "Joint inspection with the client",
            ["INSPECTED", "HANDED_OVER"].includes(d.status),
            d.inspected_on ? `${d.inspected_on} · ${d.client_attendees}` : "")}
      {d.status === "OFFERED" && can && (
        <div style={{ ...row, marginTop: 8 }}>
          <label style={lab}>Inspected on
            <input type="date" style={{ ...inputStyle, width: 150 }}
              value={insp.inspected_on} max={today()}
              onChange={(e) => setInsp({ ...insp, inspected_on: e.target.value })} />
          </label>
          <label style={{ ...lab, flex: "1 1 200px" }}>Who attended for the client
            <input style={inputStyle} value={insp.client_attendees}
              placeholder="Name, position"
              onChange={(e) => setInsp({ ...insp, client_attendees: e.target.value })} />
          </label>
          <label style={{ ...lab, flex: "1 1 200px" }}>Who attended for us
            <input style={inputStyle} value={insp.our_attendees}
              onChange={(e) => setInsp({ ...insp, our_attendees: e.target.value })} />
          </label>
          <label style={{ ...lab, flex: "1 1 100%" }}>Notes
            <input style={inputStyle} value={insp.inspection_notes}
              onChange={(e) => setInsp({ ...insp, inspection_notes: e.target.value })} />
          </label>
          <Btn disabled={busy} onClick={() => post("inspect", insp)}>
            Record the inspection</Btn>
        </div>)}
      {d.inspection_notes && d.status !== "OFFERED" && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "6px 0 0 22px" }}>
          {d.inspection_notes}</p>)}
    </div>

    {/* snags */}
    {d.status !== "NONE" && (
      <div style={box}>
        <strong style={{ fontSize: 13.5, color: "var(--sp-navy)" }}>
          Snags in this unit</strong>
        <span style={{ fontSize: 12.5, color: "var(--muted)", marginLeft: 8 }}>
          {openSnags.length} open of {d.snags.length} · a unit can be handed
          over with minor snags open; a major one holds it</span>
        {d.snags.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 12.5, marginTop: 6 }}>
            <thead><tr><th style={th}>Ref</th><th style={th}>Item</th>
              <th style={th}>Class</th><th style={th}>Status</th>
              <th style={th} /></tr></thead>
            <tbody>{d.snags.map((s) => (
              <tr key={s.id}>
                <td style={{ ...td, whiteSpace: "nowrap" }}>{s.ref_no}</td>
                <td style={td}>{s.description}
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {s.location}{s.due_date ? ` · due ${s.due_date}` : ""}
                    {s.in_dlp ? " · found in the defects period" : ""}
                    {s.photo_url && <> · <a href={s.photo_url} target="_blank"
                      rel="noreferrer">photo</a></>}</div></td>
                <td style={td}>
                  {can && ["OPEN", "IN_PROGRESS", "FIXED"].includes(s.status) ? (
                    <select value={s.severity} disabled={busy}
                      style={{ ...inputStyle, width: 86, padding: "2px 4px",
                               fontSize: 12 }}
                      onChange={(e) => patchSnag(s, { severity: e.target.value })}>
                      <option value="MINOR">Minor</option>
                      <option value="MAJOR">Major</option></select>
                  ) : (s.severity === "MAJOR" ? "Major" : "Minor")}</td>
                <td style={td}><Chip tone={SNAG_TONE[s.status]}>
                  {SNAG_LABEL[s.status] || s.status}</Chip></td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  {can && ["OPEN", "IN_PROGRESS"].includes(s.status) && (
                    <button style={{ ...ghostButton, padding: "2px 8px",
                                     fontSize: 12 }} disabled={busy}
                      onClick={() => patchSnag(s, { status: "FIXED" })}>
                      Mark fixed</button>)}
                  {d.can_close_snag && s.status === "FIXED" && (
                    <button style={{ ...ghostButton, padding: "2px 8px",
                                     fontSize: 12 }} disabled={busy}
                      onClick={() => patchSnag(s, { status: "CLOSED" })}>
                      Checked — close</button>)}
                </td>
              </tr>))}</tbody>
          </table>)}
        {can && (
          <div style={{ ...row, marginTop: 8 }}>
            <label style={{ ...lab, flex: "2 1 240px" }}>New snag
              <input style={inputStyle} value={snag.description}
                placeholder="What is the defect?"
                onChange={(e) => setSnag({ ...snag, description: e.target.value })} />
            </label>
            <label style={{ ...lab, flex: "1 1 140px" }}>Where in the unit
              <input style={inputStyle} value={snag.location}
                placeholder={d.unit.ref}
                onChange={(e) => setSnag({ ...snag, location: e.target.value })} />
            </label>
            <label style={lab}>Class
              <select style={{ ...inputStyle, width: 96 }} value={snag.severity}
                onChange={(e) => setSnag({ ...snag, severity: e.target.value })}>
                <option value="MINOR">Minor</option>
                <option value="MAJOR">Major</option></select></label>
            <label style={lab}>Fix by
              <input type="date" style={{ ...inputStyle, width: 150 }}
                value={snag.due_date}
                onChange={(e) => setSnag({ ...snag, due_date: e.target.value })} />
            </label>
            <label style={lab}>Photo
              <input type="file" accept="image/*" key={d.snags.length}
                onChange={(e) => setSnag({ ...snag,
                  photo: e.target.files[0] || null })} /></label>
            <Btn variant="secondary" disabled={busy || !snag.description.trim()}
                 onClick={addSnag}>Add snag</Btn>
          </div>)}
      </div>)}

    {/* 3 — handed over */}
    <div style={box}>
      {step(3, "Handed over", d.status === "HANDED_OVER",
            d.handed_over_on
              ? `${d.handed_over_on} · signed by ${d.client_signatory}`
                + (d.client_position ? `, ${d.client_position}` : "") : "")}
      {d.certificate_no && (
        <div style={{ ...row, margin: "8px 0 0 22px", alignItems: "center" }}>
          <a href={`/api/v1/units/${unitId}/handover/certificate.pdf`}
             target="_blank" rel="noreferrer"
             style={{ ...ghostButton, textDecoration: "none", fontSize: 12.5 }}>
            ⬇ Certificate {d.certificate_no} (PDF)</a>
          {d.signed_copy_url
            ? <a href={d.signed_copy_url} target="_blank" rel="noreferrer"
                 style={{ fontSize: 12.5 }}>signed copy</a>
            : d.status === "HANDED_OVER" && can && (
              <label style={{ fontSize: 12.5 }}>Upload the signed copy{" "}
                <input type="file" onChange={(e) => signedCopy(e.target.files[0])} />
              </label>)}
        </div>)}
      {d.status === "INSPECTED" && can && (<>
        {d.handover_block && (
          <p style={{ fontSize: 12.5, color: "#a3271b", margin: "8px 0 0 22px" }}>
            {d.handover_block}</p>)}
        <div style={{ ...row, marginTop: 8 }}>
          <label style={lab}>Handed over on
            <input type="date" style={{ ...inputStyle, width: 150 }}
              value={ho.handed_over_on} max={today()}
              onChange={(e) => setHo({ ...ho, handed_over_on: e.target.value })} />
          </label>
          <label style={{ ...lab, flex: "1 1 180px" }}>Signed for the client by
            <input style={inputStyle} value={ho.client_signatory}
              onChange={(e) => setHo({ ...ho, client_signatory: e.target.value })} />
          </label>
          <label style={{ ...lab, flex: "1 1 150px" }}>Position
            <input style={inputStyle} value={ho.client_position}
              onChange={(e) => setHo({ ...ho, client_position: e.target.value })} />
          </label>
          <label style={lab}>Signed certificate (optional now)
            <input type="file"
              onChange={(e) => setHo({ ...ho, file: e.target.files[0] || null })} />
          </label>
          <Btn disabled={busy || !!d.handover_block} onClick={handOver}>
            Record the handover</Btn>
        </div>
      </>)}
      {d.status === "HANDED_OVER" && (
        <p style={{ fontSize: 12.5, margin: "8px 0 0 22px" }}>
          {d.dlp_ends
            ? <>Defects liability for this unit runs to <strong>{d.dlp_ends}</strong>
                {" "}({d.dlp_months} months from its handover).</>
            : <span style={{ color: "#b45309" }}>No defects liability period is
                set on the project, so this unit has no end date for it.</span>}
        </p>)}
    </div>

    {d.can_undo && d.status !== "NONE" && (
      <div style={{ marginTop: 10, textAlign: "right" }}>
        <button style={{ ...ghostButton, fontSize: 12, color: "#a3271b" }}
                disabled={busy} onClick={stepBack}>
          ↩ {d.status === "HANDED_OVER" ? "Take the handover back"
            : d.status === "INSPECTED" ? "Take the inspection back"
            : "Withdraw the offer"}</button>
      </div>)}
  </>);
}
