import { useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Cargo clearance in one place (owner 2026-08-26): who the clearing agent
// is, who gets copied on every document share, and what has been shared.
// The share email itself: all uploaded shipping documents attached, sent in
// the purchasing user's name with reply-to them, 20 MB cap.
export default function ClearancePage({ me, onOpenIpr }) {
  const [data, setData] = useState(null);
  const [cc, setCc] = useState("");
  const [agentForm, setAgentForm] = useState(null);
  // Fields stay locked until an explicit Edit (owner 2026-08-26) — this is
  // a reference page first, a form second.
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

  const field = (key, label, wide) => (
    <label key={key} style={{ fontSize: 12, color: "#5a6b78",
                              flex: wide ? 2 : 1, minWidth: wide ? 260 : 170,
                              display: "flex", flexDirection: "column",
                              gap: 3 }}>
      {label}
      <input value={agentForm?.[key] ?? ""}
             disabled={!canEdit || !editingAgent || busy}
             onChange={(e) => setAgentForm({ ...agentForm,
                                             [key]: e.target.value })}
             style={{ ...inputStyle,
                      background: editingAgent ? undefined : "#f4f7f9" }} />
    </label>
  );

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Cargo Clearance
      </h2>
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <h3 style={{ color: "var(--sp-navy)", fontSize: 14,
                   borderBottom: "1px solid #dde5ea", paddingBottom: 4 }}>
        Clearing agent
      </h3>
      {data.agent ? (
        <>
          <div style={{ display: "flex", gap: 10, alignItems: "baseline",
                        flexWrap: "wrap" }}>
            <strong style={{ color: "var(--sp-navy)", fontSize: 15 }}>
              {data.agent.name}</strong>
            <span style={{ fontSize: 11, fontWeight: 600, color: "#fff",
                           background: "var(--sp-navy)", borderRadius: 4,
                           padding: "1px 6px" }}>CLEARING AGENT</span>
            {!data.agent.email && (
              <span style={{ color: "#c0392b", fontSize: 12.5 }}>
                ⚠ no email — document shares will fail</span>)}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                        marginTop: 8 }}>
            {field("contact_person", "Contact person")}
            {field("phone", "Phone")}
            {field("email", "Email (documents are sent here — commas for more than one)", true)}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                        marginTop: 8 }}>
            {field("address", "Address", true)}
            {field("notes", "Notes (licence no, opening hours, who to call…)", true)}
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
      {canEdit && data.candidates.length > 0 && (
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

      <h3 style={{ color: "var(--sp-navy)", fontSize: 14, marginTop: 22,
                   borderBottom: "1px solid #dde5ea", paddingBottom: 4 }}>
        Share email
      </h3>
      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "6px 0" }}>
        "Share with clearing agent" on a shipment emails every uploaded
        shipping document to the agent, sent in your name with replies coming
        back to you. These addresses are copied on every share:
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

      <h3 style={{ color: "var(--sp-navy)", fontSize: 14, marginTop: 22,
                   borderBottom: "1px solid #dde5ea", paddingBottom: 4 }}>
        Pending clearances
      </h3>
      {data.pending.length === 0 ? (
        <p style={{ color: "#5a6b78", fontSize: 13 }}>
          Nothing in the clearance pipeline — every booked shipment is
          cleared.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Order</th><th style={th}>Supplier</th>
            <th style={th}>Mode</th><th style={th}>Status</th>
            <th style={th}>ETA</th><th style={th}>Shared with agent</th>
            <th style={th}>Documents</th><th style={th}>Charges</th>
          </tr></thead>
          <tbody>
            {data.pending.map((r, i) => {
              const ch = r.charges;
              return (
              <tr key={i} onClick={() => onOpenIpr?.(r.ipr_ref)}
                  title="Open the order's clearing window"
                  style={{ cursor: onOpenIpr ? "pointer" : "default" }}>
                <td style={{ ...td, fontWeight: 600,
                             color: "var(--sp-navy)" }}>
                  {r.ipr_ref} · S{r.shipment_seq}</td>
                <td style={td}>{r.supplier}</td>
                <td style={td}>{r.mode}</td>
                <td style={td}><StatusChip status={r.status} /></td>
                <td style={td}>{r.eta || "—"}</td>
                <td style={td}>
                  {r.shared_at
                    ? new Date(r.shared_at).toLocaleDateString("en-GB")
                    : <span style={{ color: ["ARRIVED", "UNDER_CLEARING"]
                        .includes(r.status) ? "#c0392b" : "#8a97a1" }}>
                        not shared</span>}
                </td>
                <td style={td}>
                  {r.documents} uploaded
                  {r.missing_docs.length > 0 && (
                    <div style={{ fontSize: 11, color: "#b35900" }}>
                      for clearing: {r.missing_docs.join(", ")}</div>)}
                </td>
                <td style={td}>
                  {ch.paid + ch.raised + ch.entered === 0
                    ? <span style={{ color: "#8a97a1" }}>none entered</span>
                    : <>
                        {ch.paid > 0 && <span style={{ color: "#1a7f37" }}>
                          {ch.paid} paid</span>}
                        {ch.raised > 0 && <span style={{ color: "#b35900" }}>
                          {ch.paid > 0 ? " · " : ""}{ch.raised} awaiting
                          {" "}payment</span>}
                        {ch.entered > 0 && <span style={{ color: "#5a6b78" }}>
                          {ch.paid + ch.raised > 0 ? " · " : ""}{ch.entered}
                          {" "}to raise</span>}
                      </>}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      )}
      <p style={{ fontSize: 11.5, color: "#8a97a1", marginTop: 6 }}>
        Every shipment not yet cleared, the ones being cleared first. Click a
        row to open the order's clearing window.
      </p>
    </section>
  );
}
