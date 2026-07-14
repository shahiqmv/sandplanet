// Planet Mobile screens — inbox, actioned, document detail, requests,
// timeline, alerts. All read the mobile API; no business logic lives here.
import React, { useState } from "react";
import { api } from "./api.js";
import { useAsync } from "./hooks.js";
import { Empty, Spinner, StatusChip, age, money, pretty } from "./ui.jsx";

function LastUpdated({ at, onReload, loading }) {
  if (!at) return null;
  return (
    <div className="metaline" style={{ justifyContent: "flex-end", margin: "0 2px 10px" }}>
      <span>Updated {age(new Date(at).toISOString())} ago</span>
      <button className="btn ghost" onClick={onReload} disabled={loading}>
        Refresh
      </button>
    </div>
  );
}

function ErrLine({ error, onRetry }) {
  return (
    <div className="err" style={{ marginTop: 12 }}>
      {error.message}{" "}
      {onRetry && (
        <button className="btn ghost" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

// ---- Approver: Pending inbox -------------------------------------------
export function PendingInbox({ onOpen, onCount }) {
  const { data, error, loading, at, reload } = useAsync(() => api.queue());
  React.useEffect(() => {
    if (data) onCount && onCount(data.count || 0);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading && !data) return <Spinner />;
  const items = (data && data.items) || [];
  return (
    <>
      <LastUpdated at={at} onReload={reload} loading={loading} />
      {error && <ErrLine error={error} onRetry={reload} />}
      {!items.length && !error ? (
        <Empty title="All clear">Nothing is waiting on you.</Empty>
      ) : (
        items.map((it) => (
          <div
            key={it.ref}
            className="card tap"
            onClick={() => onOpen({ mode: "doc", ref: it.ref })}
          >
            <div className="card-hd">
              <span className="ref">{it.ref}</span>
              <span className="dtype">{it.doc_type}</span>
            </div>
            <div className="card-bd">
              <div className="summary">{it.hint || "Awaiting your approval"}</div>
              <div className="metaline">
                <span className="chip">{it.site_code}</span>
                {it.project_code && <span className="chip">{it.project_code}</span>}
                <span style={{ marginLeft: "auto" }} />
                {it.amount != null && (
                  <span className="amount">{money(it.amount)}</span>
                )}
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}

// ---- Approver: Actioned -------------------------------------------------
export function ActionedList({ onOpen }) {
  const { data, error, loading, at, reload } = useAsync(() => api.actioned(30));
  if (loading && !data) return <Spinner />;
  const items = (data && data.items) || [];
  return (
    <>
      <LastUpdated at={at} onReload={reload} loading={loading} />
      {error && <ErrLine error={error} onRetry={reload} />}
      {!items.length && !error ? (
        <Empty title="Nothing yet">Documents you action appear here.</Empty>
      ) : (
        items.map((it) => (
          <div
            key={it.ref}
            className="card tap"
            onClick={() => onOpen({ mode: "doc", ref: it.ref })}
          >
            <div className="card-hd">
              <span className="ref">{it.ref}</span>
              <StatusChip status={it.result} label={pretty(it.result)} />
            </div>
            <div className="card-bd">
              <div className="metaline">
                <span className="dtype">{it.doc_type}</span>
                <span className="chip">{it.site_code}</span>
                <span style={{ marginLeft: "auto" }}>{age(it.acted_at)} ago</span>
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}

// ---- Approver: Document detail -----------------------------------------
// Only the signatory's Payment Voucher is an "authorisation"; PM/Director steps
// on a PYR (and everything else) read as "approve".
const AUTHORISE_TYPES = new Set(["PV"]);

export function DocumentDetail({ docRef, online, onActioned, onToast }) {
  const { data, error, loading } = useAsync(() => api.document(docRef), [docRef]);
  const [busy, setBusy] = useState(false);
  const [returning, setReturning] = useState(false);
  const [reason, setReason] = useState("");

  if (loading && !data) return <Spinner />;
  if (error) return <ErrLine error={error} />;
  const d = data || {};
  const actionable = new Set(["SUBMITTED", "PM_APPROVED"]).has(d.status);
  const verb = AUTHORISE_TYPES.has(d.doc_type) ? "Authorise" : "Approve";

  async function doApprove() {
    setBusy(true);
    try {
      await api.approve(docRef);
      onActioned({ text: verb === "Authorise" ? "Authorised" : "Approved", tone: "" });
    } catch (e) {
      onToast({ msg: e.message, tone: "alert" });
      setBusy(false);
    }
  }
  async function doReturn() {
    if (!reason.trim()) return;
    setBusy(true);
    try {
      await api.return(docRef, reason.trim());
      onActioned({ text: "Returned", tone: "alert" });
    } catch (e) {
      onToast({ msg: e.message, tone: "alert" });
      setBusy(false);
    }
  }

  return (
    <>
      <div className="scroll" style={{ paddingBottom: 8 }}>
        <div className="card">
          <div
            className="card-hd"
            style={{ background: "var(--navy)", borderColor: "var(--navy)" }}
          >
            <span className="ref" style={{ color: "#fff" }}>
              {d.ref}
            </span>
            <span className="dtype" style={{ color: "rgba(255,255,255,.8)" }}>
              {d.doc_type} {d.rev_label || ""}
            </span>
          </div>
          <div className="card-bd">
            <div className="metaline" style={{ marginTop: 0, marginBottom: 12 }}>
              <StatusChip status={d.status} />
              {d.site_code && <span className="chip">{d.site_code}</span>}
              {d.project_code && <span className="chip">{d.project_code}</span>}
            </div>
            <FieldsGrid d={d} />
          </div>
        </div>

        <PaymentBlock d={d} />
        <Lines d={d} />
        <Remarks d={d} />
        <Attachments d={d} />
        <ApprovalTrail d={d} />
      </div>

      {actionable && (
        <div className="actionbar">
          {!online ? (
            <span className="offline-note">
              You're offline — actions need a connection.
            </span>
          ) : returning ? (
            <ReturnSheet
              reason={reason}
              setReason={setReason}
              busy={busy}
              onCancel={() => setReturning(false)}
              onConfirm={doReturn}
            />
          ) : (
            <>
              <button
                className="btn danger secondary"
                disabled={busy}
                onClick={() => setReturning(true)}
              >
                Return
              </button>
              <button className="btn" disabled={busy} onClick={doApprove}>
                {verb} {d.ref}
              </button>
            </>
          )}
        </div>
      )}
    </>
  );
}

function ReturnSheet({ reason, setReason, busy, onCancel, onConfirm }) {
  return (
    <div style={{ flex: 1 }}>
      <div className="field" style={{ marginBottom: 8 }}>
        <label>Reason to return (required)</label>
        <input
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. spec unclear on item 3"
        />
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        <button className="btn secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button
          className="btn danger"
          disabled={busy || !reason.trim()}
          onClick={onConfirm}
        >
          Return document
        </button>
      </div>
    </div>
  );
}

function Row({ k, v }) {
  if (v == null || v === "" || v === "None") return null;
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  );
}

function FieldsGrid({ d }) {
  return (
    <dl className="detail-grid">
      <Row k="Raised by" v={d.created_by_name} />
      <Row k="Date" v={d.doc_date} />
      <Row k="Project" v={d.project_title || d.project_code} />
      <Row k="Supplier" v={d.supplier_name} />
    </dl>
  );
}

// PYR payment summary (the richest single-doc block on mobile).
function PaymentBlock({ d }) {
  const pr = d.payment_request;
  if (!pr) return null;
  return (
    <div className="card">
      <div className="card-hd">
        <span className="dtype">Payment</span>
        <span className="amount">
          {money(pr.amount_requested, pr.currency)}
        </span>
      </div>
      <div className="card-bd">
        <dl className="detail-grid">
          <Row k="Payee" v={pr.payee} />
          <Row k="Cost head" v={pr.cost_head} />
          <Row k="Method" v={pretty(pr.payment_method)} />
          <Row k="Purpose" v={pr.purpose} />
          <Row k="Required by" v={pr.required_by} />
          {pr.is_urgent && <Row k="Urgent" v={pr.urgent_reason || "Yes"} />}
        </dl>
      </div>
    </div>
  );
}

// PV lines come as {ref, amount, currency}; document lines as rich rows.
function Lines({ d }) {
  const lines = d.lines || [];
  if (!lines.length) return null;
  const isPV = d.doc_type === "PV";
  const total =
    d.amount != null
      ? d.amount
      : lines.reduce((s, l) => s + Number(l.amount || 0), 0);
  return (
    <div className="card">
      <div className="card-hd">
        <span className="dtype">{isPV ? "Vouchered" : "Line items"}</span>
        {total ? <span className="amount">{money(total)}</span> : null}
      </div>
      <div className="card-bd" style={{ padding: 0 }}>
        <table className="lines">
          <tbody>
            {lines.map((l, i) => (
              <tr key={l.id || i}>
                <td>
                  <div style={{ fontWeight: 500 }}>
                    {l.description || l.free_text_desc || l.ref || l.item_code || "—"}
                  </div>
                  <div style={{ color: "var(--muted)", fontSize: 12 }}>
                    {[
                      l.qty_required != null &&
                        `${l.qty_required}${l.unit ? " " + l.unit : ""}`,
                      l.item_code && !l.description ? null : l.item_code,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </td>
                <td className="num">
                  {money(l.amount, isPV ? l.currency : undefined)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Remarks({ d }) {
  const p = d.payload || {};
  const text = p.remarks || p.notes || p.justification || p.purpose;
  if (!text) return null;
  return (
    <div className="card">
      <div className="card-hd">
        <span className="dtype">Remarks</span>
      </div>
      <div className="card-bd">
        <div className="summary">{text}</div>
      </div>
    </div>
  );
}

function Attachments({ d }) {
  const atts = d.attachments || [];
  if (!atts.length) return null;
  return (
    <div className="card">
      <div className="card-hd">
        <span className="dtype">Attachments</span>
      </div>
      <div className="card-bd">
        {atts.map((a) => (
          <div key={a.id} style={{ marginBottom: 8 }}>
            <a
              href={a.file || a.url}
              target="_blank"
              rel="noreferrer"
              style={{ color: "var(--sky)", fontWeight: 600 }}
            >
              {a.label || a.kind || a.filename || "Open attachment"}
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}

function ApprovalTrail({ d }) {
  const a = d.approvals || [];
  if (!a.length) return null;
  return (
    <div className="card">
      <div className="card-hd">
        <span className="dtype">Trail</span>
      </div>
      <div className="card-bd">
        <ul className="timeline">
          {a.map((x, i) => (
            <li key={i} className="step done">
              <span className="node" />
              <div className="s-label">{pretty(x.result || x.action)}</div>
              <div className="s-ref">{x.actor_name || x.actor_role || ""}</div>
              <div className="s-when">{age(x.acted_at)} ago</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ---- Originator: My Requests -------------------------------------------
export function MyRequests({ onOpen }) {
  const { data, error, loading, at, reload } = useAsync(() => api.requests());
  if (loading && !data) return <Spinner />;
  const items = (data && data.items) || [];
  return (
    <>
      <LastUpdated at={at} onReload={reload} loading={loading} />
      {error && <ErrLine error={error} onRetry={reload} />}
      {!items.length && !error ? (
        <Empty title="Nothing raised">Documents you raise appear here.</Empty>
      ) : (
        items.map((it) => (
          <div
            key={it.ref}
            className="card tap"
            onClick={() => onOpen({ mode: "timeline", ref: it.ref })}
          >
            <div className="card-hd">
              <span className="ref">
                {it.unread && (
                  <span
                    style={{
                      display: "inline-block",
                      width: 8,
                      height: 8,
                      background: "var(--sky)",
                      borderRadius: "50%",
                      marginRight: 7,
                    }}
                  />
                )}
                {it.ref}
              </span>
              <StatusChip status={it.status} label={it.status_label} />
            </div>
            <div className="card-bd">
              <div className="metaline" style={{ marginTop: 0 }}>
                <span className="dtype">{it.doc_type}</span>
                <span>{it.line}</span>
                <span style={{ marginLeft: "auto" }}>{age(it.updated_at)} ago</span>
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}

// ---- Originator: tracking timeline -------------------------------------
export function Timeline({ docRef }) {
  const { data, error, loading } = useAsync(() => api.timeline(docRef), [docRef]);
  if (loading && !data) return <Spinner />;
  if (error) return <ErrLine error={error} />;
  const t = data || {};
  const steps = t.steps || [];
  return (
    <div className="scroll">
      <div className="card">
        <div className="card-hd">
          <span className="ref">{t.ref}</span>
          <StatusChip status={t.status} />
        </div>
        <div className="card-bd">
          <div className="section-h" style={{ margin: "0 0 12px" }}>
            {t.doc_type} · {t.title_line}
          </div>
          <ul className="timeline">
            {steps.map((s, i) => (
              <li key={i} className={`step ${s.state || "future"}`}>
                <span className="node" />
                <div className="s-label">{s.label}</div>
                {s.ref && <div className="s-ref">{s.ref}</div>}
                {s.when && <div className="s-when">{s.when}</div>}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// ---- Originator: Alerts feed -------------------------------------------
export function Alerts({ onOpen, onCount }) {
  const { data, error, loading, at, reload } = useAsync(() => api.alerts());
  React.useEffect(() => {
    if (data) onCount && onCount(data.unread || 0);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function markAll() {
    await api.alertsRead().catch(() => {});
    reload();
  }
  async function open(it) {
    if (!it.read_at) await api.alertsRead([it.id]).catch(() => {});
    if (it.doc_ref) onOpen({ mode: "timeline", ref: it.doc_ref });
    else reload();
  }

  if (loading && !data) return <Spinner />;
  const items = (data && data.items) || [];
  const unread = (data && data.unread) || 0;
  return (
    <>
      <div className="metaline" style={{ justifyContent: "space-between", margin: "0 2px 10px" }}>
        <span>{unread ? `${unread} unread` : "All read"}</span>
        <div>
          <button className="btn ghost" onClick={reload} disabled={loading}>
            Refresh
          </button>
          {unread > 0 && (
            <button className="btn ghost" onClick={markAll}>
              Mark all read
            </button>
          )}
        </div>
      </div>
      {error && <ErrLine error={error} onRetry={reload} />}
      {!items.length && !error ? (
        <Empty title="No alerts">Milestone updates land here.</Empty>
      ) : (
        items.map((it) => (
          <div
            key={it.id}
            className="card tap"
            onClick={() => open(it)}
            style={it.read_at ? { opacity: 0.72 } : undefined}
          >
            <div className="card-bd">
              <div style={{ display: "flex", gap: 8 }}>
                {!it.read_at && (
                  <span
                    style={{
                      flex: "0 0 auto",
                      marginTop: 6,
                      width: 8,
                      height: 8,
                      background: "var(--sky)",
                      borderRadius: "50%",
                    }}
                  />
                )}
                <div style={{ flex: 1 }}>
                  <div className="summary" style={{ fontWeight: 500 }}>
                    {it.title}
                  </div>
                  {it.body && (
                    <div style={{ color: "var(--muted)", fontSize: 12.5 }}>
                      {it.body}
                    </div>
                  )}
                  <div className="metaline" style={{ marginTop: 5 }}>
                    {it.doc_ref && <span className="ref">{it.doc_ref}</span>}
                    <span style={{ marginLeft: "auto" }}>
                      {age(it.created_at)} ago
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}
