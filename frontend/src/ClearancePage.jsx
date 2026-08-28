import { useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// The cargo-clearance board (owner 2026-08-26): the day's work first — what
// is at the port, what is arriving, what is cleared but not yet counted into
// the store — each row with its NEXT ACTION; the agent + share-email setup
// lives below, locked behind explicit Edit buttons.
const fmtD = (d) => (d ? new Date(d).toLocaleDateString("en-GB") : "—");

export default function ClearancePage({ me, onOpenIpr }) {
  const [data, setData] = useState(null);
  const [cc, setCc] = useState("");
  const [agentForm, setAgentForm] = useState(null);
  const [editingAgent, setEditingAgent] = useState(false);
  const [editingCc, setEditingCc] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => api("/clearance/setup").then((d) => {
    setData(d);
    setCc(d.share_cc);
    setAgentForm(d.agent ? { contact_person: d.agent.contact_person,
                             phone: d.agent.phone, email: d.agent.email,
                             address: d.agent.address,
                             notes: d.agent.notes } : null);
  }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const canEdit = data?.can_edit;

  async function saveCc() {
    setBusy(true); setError(null); setNotice(null);
    try {
      await api("/clearance/setup", { method: "POST",
                                      body: { share_cc: cc } });
      setNotice("CC list saved — future shares copy these addresses.");
      setEditingCc(false);
      load();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function saveAgent() {
    setBusy(true); setError(null); setNotice(null);
    try {
      await api(`/suppliers/${data.agent.id}`, { method: "PATCH",
                                                 body: agentForm });
      setNotice("Agent details saved.");
      setEditingAgent(false);
      load();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function makeAgent(id) {
    const pick = data.candidates.find((c) => String(c.id) === String(id));
    if (!pick || pick.is_agent) return;
    if (data.agent && !window.confirm(
        `${data.agent.name} is the clearing agent now. Move it to `
        + `${pick.name}? All shipping-document emails will go to `
        + `${pick.name} from here on.`)) return;
    setBusy(true); setError(null);
    try {
      await api(`/suppliers/${id}/clearing-agent`,
                { method: "POST", body: { set: true } });
      load();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  if (!data) return <section style={card}>{error || "Loading…"}</section>;

  const tile = (label, n, hot) => (
    <div style={{ border: "1px solid #dde5ea", borderRadius: 8,
                  padding: "10px 16px", minWidth: 130,
                  background: hot && n > 0 ? "#fdf6ec" : "#fafcfd" }}>
      <div style={{ fontSize: 24, fontWeight: 700,
                    color: hot && n > 0 ? "#b35900" : "var(--sp-navy)" }}>
        {n}</div>
      <div style={{ fontSize: 11.5, color: "#5a6b78" }}>{label}</div>
    </div>
  );

  // Row click lands ON the shipment's card, ready to work; the ref itself
  // is a separate link to the full order, just in case (owner 2026-08-26).
  const openRow = (r) => onOpenIpr?.(r.ipr_ref, r.shipment_seq);

  const shipRows = (rows, atPort) => rows.map((r, i) => (
    <tr key={i} onClick={() => openRow(r)}
        title="Open this shipment's clearing card"
        style={{ cursor: onOpenIpr ? "pointer" : "default" }}>
      <td style={{ ...td, fontWeight: 600, color: "var(--sp-navy)",
                   whiteSpace: "nowrap" }}>
        {r.shipment_ref}
        <div style={{ fontSize: 11, fontWeight: 400 }}>
          {(r.orders || []).map((o) => o.ref).join(" + ")}
          {(r.orders || []).length > 1 && (
            <b style={{ color: "#8a6d00" }}> · consolidated</b>)}
        </div>
      </td>
      <td style={td}>{r.supplier}</td>
      <td style={td}>{r.mode}</td>
      <td style={td}><StatusChip status={r.status} /></td>
      {atPort ? (
        <td style={{ ...td, color: (r.days_at_port ?? 0) >= 5
                       ? "#c0392b" : undefined,
                     fontWeight: (r.days_at_port ?? 0) >= 5 ? 700 : 400 }}>
          {r.arrived_on
            ? `${fmtD(r.arrived_on)} · ${r.days_at_port}d`
            : "—"}
        </td>
      ) : (
        <td style={td}>{fmtD(r.eta)}</td>
      )}
      <td style={td}>
        {r.shared_at
          ? fmtD(r.shared_at)
          : <span style={{ color: atPort ? "#c0392b" : "#8a97a1" }}>
              not shared</span>}
      </td>
      <td style={td}>
        {r.documents}
        {r.missing_docs.length > 0 && (
          <span style={{ fontSize: 11, color: "#b35900" }}>
            {" "}· missing {r.missing_docs.length}</span>)}
      </td>
      <td style={{ ...td, fontSize: 12 }}>
        {r.charges.paid > 0 && <span style={{ color: "#1a7f37" }}>
          {r.charges.paid}✓ </span>}
        {r.charges.raised > 0 && <span style={{ color: "#b35900" }}>
          {r.charges.raised}⏳ </span>}
        {r.charges.entered > 0 && <span style={{ color: "#5a6b78" }}>
          {r.charges.entered}·raise</span>}
        {r.charges.paid + r.charges.raised + r.charges.entered === 0 && "—"}
      </td>
      <td style={{ ...td, fontSize: 12, color: "#41525f" }}>
        {r.next_action}</td>
      <td style={{ ...td, whiteSpace: "nowrap" }}>
        <a href="#" title="Open the full order — details, schedule, all shipments"
           onClick={(e) => { e.preventDefault(); e.stopPropagation();
                             onOpenIpr?.(r.ipr_ref); }}
           style={{ fontSize: 12 }}>order ↗</a></td>
    </tr>
  ));

  const head = (dateCol) => (
    <thead><tr>
      <th style={th}>Shipment</th><th style={th}>Supplier</th>
      <th style={th}>Mode</th><th style={th}>Status</th>
      <th style={th}>{dateCol}</th>
      <th style={th}>Shared</th><th style={th}>Docs</th>
      <th style={th}>Charges</th><th style={th}>Next action</th>
      <th style={th} />
    </tr></thead>
  );

  const section = (title, hint) => (
    <h3 style={{ color: "var(--sp-navy)", fontSize: 14, marginTop: 22,
                 borderBottom: "1px solid #dde5ea", paddingBottom: 4 }}>
      {title}{hint && <span style={{ fontWeight: 400, fontSize: 11.5,
                                     color: "#8a97a1", marginLeft: 8 }}>
        {hint}</span>}
    </h3>
  );

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Cargo Clearance
        </h2>
        <span style={{ fontSize: 12.5, color: "#5a6b78" }}>
          Agent: <strong>{data.agent?.name || "not set"}</strong>
          {data.agent && !data.agent.email && (
            <span style={{ color: "#c0392b" }}> — no email!</span>)}
        </span>
      </div>
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <div style={{ display: "flex", gap: 10, marginTop: 12,
                    flexWrap: "wrap" }}>
        {tile("at sea", data.tiles.at_sea, false)}
        {tile("arriving ≤ 7 days", data.tiles.arriving_week, true)}
        {tile("at the port", data.tiles.at_port, true)}
        {tile("cleared, to receive", data.tiles.to_receive, true)}
      </div>

      {section("At the port — clear these now",
               "days at port in red past 5 — demurrage territory")}
      {data.at_port.length === 0
        ? <p style={{ color: "#5a6b78", fontSize: 13 }}>
            Nothing at the port.</p>
        : <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
              {head("Arrived · days")}
              <tbody>{shipRows(data.at_port, true)}</tbody>
            </table>
          </div>}

      {section("Arriving", "get documents in and shared before the vessel")}
      {data.incoming.length === 0
        ? <p style={{ color: "#5a6b78", fontSize: 13 }}>
            Nothing on the water.</p>
        : <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
              {head("ETA")}
              <tbody>{shipRows(data.incoming, false)}</tbody>
            </table>
          </div>}

      {section("Cleared — waiting to enter the store")}
      {data.to_receive.length === 0
        ? <p style={{ color: "#5a6b78", fontSize: 13 }}>
            Nothing waiting — every cleared shipment is counted in.</p>
        : <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Shipment</th><th style={th}>Supplier</th>
              <th style={th}>Mode</th><th style={th}>IRN</th>
              <th style={th}>Next action</th><th style={th} />
            </tr></thead>
            <tbody>
              {data.to_receive.map((r, i) => (
                <tr key={i} onClick={() => openRow(r)}
                    style={{ cursor: onOpenIpr ? "pointer" : "default" }}>
                  <td style={{ ...td, fontWeight: 600,
                               color: "var(--sp-navy)" }}>
                    {r.shipment_ref}
                    <div style={{ fontSize: 11, fontWeight: 400 }}>
                      {(r.orders || []).map((o) => o.ref).join(" + ")}</div>
                  </td>
                  <td style={td}>{r.supplier}</td>
                  <td style={td}>{r.mode}</td>
                  <td style={td}>{r.irn_ref
                    ? <>{r.irn_ref} <StatusChip status={r.irn_status} /></>
                    : "—"}</td>
                  <td style={{ ...td, fontSize: 12, color: "#41525f" }}>
                    {r.next_action}</td>
                  <td style={td}>
                    <a href="#" title="Open the full order"
                       onClick={(e) => { e.preventDefault();
                                         e.stopPropagation();
                                         onOpenIpr?.(r.ipr_ref); }}
                       style={{ fontSize: 12 }}>order ↗</a></td>
                </tr>
              ))}
            </tbody>
          </table>}

      {section("Clearing agent")}
      {data.agent ? (
        <>
          <div style={{ display: "flex", gap: 10, alignItems: "baseline",
                        flexWrap: "wrap" }}>
            <strong style={{ color: "var(--sp-navy)", fontSize: 15 }}>
              {data.agent.name}</strong>
            <span style={{ fontSize: 11, fontWeight: 600, color: "#fff",
                           background: "var(--sp-navy)", borderRadius: 4,
                           padding: "1px 6px" }}>CLEARING AGENT</span>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                        marginTop: 8 }}>
            {[["contact_person", "Contact person", false],
              ["phone", "Phone", false],
              ["email", "Email (documents are sent here)", true],
              ["address", "Address", true],
              ["notes", "Notes (licence no, who to call…)", true]]
              .map(([key, label, wide]) => (
              <label key={key} style={{ fontSize: 12, color: "#5a6b78",
                                        flex: wide ? 2 : 1,
                                        minWidth: wide ? 260 : 170,
                                        display: "flex",
                                        flexDirection: "column", gap: 3 }}>
                {label}
                <input value={agentForm?.[key] ?? ""}
                       disabled={!canEdit || !editingAgent || busy}
                       onChange={(e) => setAgentForm({ ...agentForm,
                                                       [key]: e.target.value })}
                       style={{ ...inputStyle,
                                background: editingAgent ? undefined
                                                         : "#f4f7f9" }} />
              </label>
            ))}
          </div>
          {canEdit && !editingAgent && (
            <button onClick={() => setEditingAgent(true)}
                    style={{ ...ghostButton, marginTop: 10,
                             padding: "6px 16px" }}>
              ✏️ Edit agent details</button>
          )}
          {canEdit && editingAgent && (
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <button onClick={saveAgent} disabled={busy}
                      style={buttonStyle}>Save agent details</button>
              <button onClick={() => { setEditingAgent(false);
                  setAgentForm({ contact_person: data.agent.contact_person,
                                 phone: data.agent.phone,
                                 email: data.agent.email,
                                 address: data.agent.address,
                                 notes: data.agent.notes }); }}
                      style={ghostButton}>Cancel</button>
            </div>
          )}
        </>
      ) : (
        <p style={{ color: "#c0392b", fontSize: 13 }}>
          No clearing agent is set — document shares are blocked until one is.
        </p>
      )}
      {canEdit && data.candidates.filter((c) => !c.is_agent).length > 0 && (
        <div style={{ marginTop: 10, fontSize: 13 }}>
          <span style={{ color: "#5a6b78" }}>Change agent: </span>
          <select value="" disabled={busy}
                  onChange={(e) => makeAgent(e.target.value)}
                  style={{ ...inputStyle, width: 260 }}>
            <option value="">— pick a clearing-agent supplier —</option>
            {data.candidates.filter((c) => !c.is_agent).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>))}
          </select>
          <div style={{ fontSize: 11.5, color: "#8a97a1", marginTop: 3 }}>
            The company has ONE clearing agent. Suppliers appear here when
            their category is "Clearing agent" (set on the Suppliers page).
          </div>
        </div>
      )}

      {section("Share email")}
      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "6px 0" }}>
        "Share with clearing agent" on a shipment emails every uploaded
        shipping document to the agent, sent in your name with replies coming
        back to you. Copied on every share:
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center",
                    flexWrap: "wrap" }}>
        {editingCc ? (
          <>
            <input value={cc} disabled={busy}
                   placeholder="cargoclearance@sandplanet.mv"
                   onChange={(e) => setCc(e.target.value)}
                   style={{ ...inputStyle, width: 380 }} />
            <button onClick={saveCc} disabled={busy} style={buttonStyle}>
              Save CC list</button>
            <button onClick={() => { setEditingCc(false);
                                     setCc(data.share_cc); }}
                    style={ghostButton}>Cancel</button>
            <span style={{ fontSize: 11.5, color: "#8a97a1" }}>
              comma-separated for more than one</span>
          </>
        ) : (
          <>
            <strong style={{ fontSize: 13.5, color: "var(--sp-navy)" }}>
              {data.share_cc || "— nobody copied —"}</strong>
            {canEdit && (
              <button onClick={() => setEditingCc(true)}
                      style={{ ...ghostButton, padding: "3px 12px",
                               fontSize: 12 }}>✏️ Edit</button>)}
          </>
        )}
      </div>
    </section>
  );
}
