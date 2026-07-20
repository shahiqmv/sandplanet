import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const SITE_MANAGE = ["SITE_ADMIN", "SITE_ENGINEER", "ADMIN"];
const STATUS_TONE = {
  DRAFT: "info", PM_APPROVED: "warn", APPROVED: "ok", ACTIVE: "ok",
  SUSPENDED: "warn", CLOSED: "alert",
};
const WORKER_TONE = { ACTIVE: "ok", PENDING: "warn", REMOVED: "alert" };

// Subcontractor register + site team management (subcontractor module, R? P2).
// Given a `site`, it scopes to that site and lets the SA/SE create/staff a
// subcontractor. Without one, it is the read/approve register for PM+/Director.
export default function SubcontractorsPanel({ me, site }) {
  const [subs, setSubs] = useState(null);
  const [sel, setSel] = useState(null);          // open detail
  const [cats, setCats] = useState([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);

  const canCreate = site && SITE_MANAGE.includes(me.role);
  const path = site ? `/subcontractors?site_id=${site.id}` : "/subcontractors";

  function load() {
    api(path).then(setSubs).catch((e) => setError(e.message));
  }
  useEffect(load, [site?.id]);
  useEffect(() => {
    api("/manpower-categories")
      .then((all) => setCats(all.filter((c) => c.list_type === "DPR")))
      .catch(() => setCats([]));
  }, []);

  async function reopen(id) {
    try { setSel(await api(`/subcontractors/${id}`)); }
    catch (e) { setError(e.message); }
  }

  if (sel) {
    return <Detail sub={sel} me={me} cats={cats}
                   onBack={() => { setSel(null); load(); }}
                   onChanged={(s) => setSel(s)} />;
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 10 }}>
        <h3 style={{ margin: 0, color: "var(--navy)" }}>
          Subcontractors{site ? ` · ${site.code}` : ""}</h3>
        {canCreate && (
          <Btn variant="navy" onClick={() => setCreating(true)}>
            + New subcontractor</Btn>
        )}
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {creating && (
        <CreateForm site={site} onCancel={() => setCreating(false)}
                    onDone={() => { setCreating(false); load(); }} />
      )}
      {subs === null ? <p style={{ color: "var(--muted)" }}>Loading…</p>
       : subs.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>No subcontractors yet.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Name</th>
            {!site && <th style={th}>Site</th>}
            <th style={th}>Status</th>
            <th style={{ ...th, textAlign: "right" }}>Workers</th>
            <th style={th}></th>
          </tr></thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.id}>
                <td style={td}>{s.name}
                  {s.contact_person && (
                    <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                      {s.contact_person}{s.phone ? ` · ${s.phone}` : ""}</div>
                  )}</td>
                {!site && <td style={td}>{s.site_code}</td>}
                <td style={td}>
                  <Chip tone={STATUS_TONE[s.status] || "info"}>
                    {s.status_label}</Chip>
                  {s.pending_count > 0 && (
                    <Chip tone="warn">{s.pending_count} pending</Chip>)}
                </td>
                <td style={{ ...td, textAlign: "right" }}>{s.worker_count}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  <Btn variant="secondary"
                       onClick={() => reopen(s.id)}>Open</Btn></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function CreateForm({ site, onCancel, onDone }) {
  const [f, setF] = useState({ name: "", registration_no: "",
    contact_person: "", phone: "", bank_details: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api("/subcontractors",
                { method: "POST", body: { ...f, site_id: site.id } });
      onDone();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} style={{ ...card, background: "var(--paper)",
                                     marginBottom: 12 }}>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      <div style={{ display: "grid", gap: 8,
                    gridTemplateColumns: "1fr 1fr" }}>
        <input style={inputStyle} placeholder="Company / gang name *"
               value={f.name} onChange={set("name")} autoFocus />
        <input style={inputStyle} placeholder="Registration no."
               value={f.registration_no} onChange={set("registration_no")} />
        <input style={inputStyle} placeholder="Contact person"
               value={f.contact_person} onChange={set("contact_person")} />
        <input style={inputStyle} placeholder="Phone"
               value={f.phone} onChange={set("phone")} />
        <input style={{ ...inputStyle, gridColumn: "1 / -1" }}
               placeholder="Bank details (for payment)"
               value={f.bank_details} onChange={set("bank_details")} />
        <input style={{ ...inputStyle, gridColumn: "1 / -1" }}
               placeholder="Notes" value={f.notes} onChange={set("notes")} />
      </div>
      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <Btn variant="navy" disabled={busy || !f.name.trim()}>Create draft</Btn>
        <Btn type="button" variant="ghost" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

function Detail({ sub, me, cats, onBack, onChanged }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);

  const canSiteManage = SITE_MANAGE.includes(me.role);
  const isPM = ["PM", "ADMIN"].includes(me.role);
  const isDirector = ["DIRECTOR", "ADMIN"].includes(me.role);
  const canSuspend = ["PM", "DIRECTOR", "ADMIN"].includes(me.role);

  async function act(action, body = {}) {
    setBusy(true); setError(null);
    try { onChanged(await api(`/subcontractors/${sub.id}/action`,
                              { method: "POST", body: { action, ...body } })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function workerAct(emp, action) {
    setBusy(true); setError(null);
    try {
      await api(`/subcontract-workers/${emp.id}/action`,
                { method: "POST", body: { action } });
      onChanged(await api(`/subcontractors/${sub.id}`));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  const actions = [];
  if (sub.status === "DRAFT" && isPM)
    actions.push(<Btn key="pm" variant="navy" disabled={busy}
                      onClick={() => act("approve")}>Approve (PM)</Btn>);
  if (sub.status === "PM_APPROVED" && isDirector)
    actions.push(<Btn key="dir" variant="navy" disabled={busy}
                      onClick={() => act("approve")}>Activate (Director)</Btn>);
  if (sub.status === "PM_APPROVED" && (isPM || isDirector))
    actions.push(<Btn key="ret" variant="secondary" disabled={busy}
                      onClick={() => act("return")}>Return to draft</Btn>);
  if (["APPROVED", "ACTIVE"].includes(sub.status) && canSuspend)
    actions.push(<Btn key="sus" variant="danger" disabled={busy}
                      onClick={() => act("suspend")}>Suspend</Btn>);
  if (sub.status === "SUSPENDED" && canSuspend)
    actions.push(<Btn key="re" variant="secondary" disabled={busy}
                      onClick={() => act("reactivate")}>Reactivate</Btn>);
  if (["APPROVED", "ACTIVE", "SUSPENDED"].includes(sub.status) && canSuspend)
    actions.push(<Btn key="cl" variant="danger" disabled={busy}
                      onClick={() => act("close")}>Close</Btn>);

  return (
    <section style={card}>
      <Btn variant="ghost" onClick={onBack}>← Back</Btn>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginTop: 6 }}>
        <h3 style={{ margin: 0, color: "var(--navy)" }}>
          {sub.name} <Chip tone={STATUS_TONE[sub.status] || "info"}>
            {sub.status_label}</Chip></h3>
      </div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
        {sub.site_code}
        {sub.registration_no ? ` · Reg ${sub.registration_no}` : ""}
        {sub.contact_person ? ` · ${sub.contact_person}` : ""}
        {sub.phone ? ` · ${sub.phone}` : ""}
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {actions.length > 0 && (
        <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>{actions}</div>
      )}

      <h4 style={{ marginBottom: 6, color: "var(--navy)" }}>
        Team ({(sub.workers || []).filter((w) => w.state === "ACTIVE").length}
        {" "}active)</h4>
      {!sub.can_raise_sca && (
        <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
          Workers can be added once the subcontractor is approved.</p>
      )}
      {canSiteManage && sub.can_raise_sca && !adding && (
        <Btn variant="secondary"
             onClick={() => setAdding(true)}>+ Add worker</Btn>
      )}
      {adding && (
        <WorkerForm sub={sub} cats={cats} onCancel={() => setAdding(false)}
                    onDone={async () => { setAdding(false);
                      onChanged(await api(`/subcontractors/${sub.id}`)); }} />
      )}
      {(sub.workers || []).length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse",
                        marginTop: 8 }}>
          <thead><tr>
            <th style={th}>Worker</th><th style={th}>Trade</th>
            <th style={th}>Status</th><th style={th}></th>
          </tr></thead>
          <tbody>
            {sub.workers.map((w) => (
              <tr key={w.id}>
                <td style={td}>{w.full_name}
                  <span style={{ color: "var(--muted)" }}>
                    {" "}· {w.emp_no}</span></td>
                <td style={td}>{w.job_title || "—"}</td>
                <td style={td}><Chip tone={WORKER_TONE[w.state]}>
                  {w.state}</Chip></td>
                <td style={{ ...td, textAlign: "right" }}>
                  {w.state === "PENDING" && isPM && (
                    <Btn variant="navy" disabled={busy}
                         onClick={() => workerAct(w, "approve")}>Approve</Btn>)}
                  {w.state !== "REMOVED" && canSiteManage && (
                    <Btn variant="danger" disabled={busy}
                         onClick={() => workerAct(w, "remove")}>Remove</Btn>)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function WorkerForm({ sub, cats, onCancel, onDone }) {
  const [f, setF] = useState({ full_name: "", nationality: "",
    passport_no: "", job_category_id: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const body = { ...f };
      if (!body.job_category_id) delete body.job_category_id;
      await api(`/subcontractors/${sub.id}/workers`,
                { method: "POST", body });
      onDone();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} style={{ ...card, background: "var(--paper)",
                                     margin: "8px 0" }}>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      <div style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr" }}>
        <input style={inputStyle} placeholder="Full name *"
               value={f.full_name} onChange={set("full_name")} autoFocus />
        <select style={inputStyle} value={f.job_category_id}
                onChange={set("job_category_id")}>
          <option value="">Trade / category…</option>
          {cats.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>))}
        </select>
        <input style={inputStyle} placeholder="Nationality"
               value={f.nationality} onChange={set("nationality")} />
        <input style={inputStyle} placeholder="Passport no."
               value={f.passport_no} onChange={set("passport_no")} />
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "8px 0 0" }}>
        Added workers wait for PM approval before they appear on the site
        attendance register.</p>
      <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
        <Btn variant="navy" disabled={busy || !f.full_name.trim()}>
          Add worker</Btn>
        <Btn type="button" variant="ghost" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}
