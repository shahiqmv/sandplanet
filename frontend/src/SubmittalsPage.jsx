import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { QA_LABELS } from "./QADocs.jsx";
import { Btn, StatusChip, card, inputStyle, td, th } from "./ui.jsx";

// The order the work happens in, not alphabetical.
const TYPES = ["IR", "MAR", "SD", "MS", "MXD", "BBS", "TWD", "MOC"];

// Short labels for the filter row — the full names are too long to sit in a
// row of eight, and everyone on site says "IR" and "MAR" out loud anyway.
const SHORT = {
  IR: "Inspections", MAR: "Materials", SD: "Shop Drawings",
  MS: "Method Statements", MXD: "Mix Designs", BBS: "Bar Bending",
  TWD: "Temporary Works", MOC: "Mock-ups",
};

const STATES = [["", "All"], ["open", "Open"],
                ["with_client", "With client"], ["settled", "Settled"]];

const PAGE = 40;

// What the submittal is about, wherever that particular type keeps it. Every
// type has a different "subject" field; the register is unreadable without it.
function subjectOf(d) {
  const p = d.payload || {};
  return p.work_description || p.material_description || p.drawing_title
    || p.mockup_title || p.title || p.method_title || p.element
    || p.structure || p.description || p.discipline || "";
}

function FilterChip({ on, children, ...props }) {
  return (
    <button {...props}
      style={{ padding: "5px 12px", borderRadius: 999, fontSize: 12.5,
               cursor: "pointer", fontFamily: "inherit",
               fontWeight: on ? 700 : 500,
               border: `1px solid ${on ? "var(--navy)" : "var(--line)"}`,
               background: on ? "var(--navy)" : "transparent",
               color: on ? "#fff" : "var(--muted)" }}>
      {children}
    </button>
  );
}

export default function SubmittalsPage({ site, project, me, onOpenDoc,
                                         onNewQa, onClose }) {
  const [data, setData] = useState(null);
  const [types, setTypes] = useState([]);
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const canRaise = ["SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN"]
    .includes(me.role);

  // Typing shouldn't fire a request per keystroke against a register that
  // scans payloads.
  useEffect(() => {
    const t = setTimeout(() => { setSearch(q); setOffset(0); }, 350);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(() => {
    setBusy(true);
    const params = new URLSearchParams({ site: site.id, limit: PAGE,
                                         offset });
    if (types.length) params.set("types", types.join(","));
    if (state) params.set("state", state);
    if (search) params.set("q", search);
    if (project) params.set("project", project.id);
    api(`/registers/submittals?${params}`)
      .then(setData)
      .catch(() => setData({ results: [], total: 0 }))
      .finally(() => setBusy(false));
  }, [site.id, project, types, state, search, offset]);

  useEffect(() => { load(); }, [load]);

  const toggleType = (t) => {
    setOffset(0);
    setTypes((cur) => cur.includes(t) ? cur.filter((x) => x !== t)
                                      : [...cur, t]);
  };

  const rows = data?.results || [];
  const total = data?.total || 0;
  const counts = data?.counts;

  return (
    <section style={{ ...card, padding: 24 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 4 }}>
        <h2 style={{ margin: 0, color: "var(--navy)" }}>
          Submittals — {site.code}
        </h2>
        {counts && (
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            {counts.total} on record
            {counts.open > 0 && <> · <b style={{ color: "var(--amber-fg)" }}>
              {counts.open} open</b></>}
            {counts.with_client > 0 && <> · {counts.with_client} with the
              client</>}
          </span>
        )}
        <button onClick={onClose}
                style={{ marginLeft: "auto", background: "transparent",
                         border: "1px solid #BFD6E6", borderRadius: 8,
                         padding: "6px 14px", cursor: "pointer",
                         fontFamily: "inherit", color: "var(--navy)" }}>
          Close
        </button>
      </div>

      {canRaise && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                      margin: "14px 0 16px" }}>
          {TYPES.map((t) => (
            <Btn key={t} variant="navy" onClick={() => onNewQa(t)}
                 title={QA_LABELS[t]}>+ {t}</Btn>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 7, flexWrap: "wrap",
                    alignItems: "center", marginBottom: 12 }}>
        {STATES.map(([v, label]) => (
          <FilterChip key={v} on={state === v}
                      onClick={() => { setState(v); setOffset(0); }}>
            {label}
          </FilterChip>
        ))}
        <span style={{ width: 1, height: 20, background: "var(--line)",
                       margin: "0 4px" }} />
        {TYPES.map((t) => (
          <FilterChip key={t} on={types.includes(t)}
                      title={QA_LABELS[t]}
                      onClick={() => toggleType(t)}>
            {SHORT[t]}
            {counts?.types?.find((c) => c.doc_type === t)
              && ` ${counts.types.find((c) => c.doc_type === t).total}`}
          </FilterChip>
        ))}
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Search reference or content…"
               style={{ ...inputStyle, width: 240, marginLeft: "auto" }} />
      </div>

      {busy && !data && (
        <p style={{ color: "var(--muted)", fontSize: 13.5 }}>Loading…</p>
      )}

      {data && rows.length === 0 && (
        <p style={{ color: "var(--muted)", fontSize: 13.5 }}>
          {total === 0 && !search && !types.length && !state
            ? "No submittals raised for this site yet."
            : "Nothing matches those filters."}
        </p>
      )}

      {rows.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          opacity: busy ? 0.55 : 1 }}>
            <thead>
              <tr>
                <th style={th}>Ref</th>
                <th style={th}>Type</th>
                <th style={th}>Date</th>
                <th style={th}>Subject</th>
                <th style={{ ...th, textAlign: "right" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.ref}>
                  <td style={{ ...td, width: 140 }}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc(d.ref); }}
                       style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                      {d.ref}
                    </a>
                  </td>
                  <td style={{ ...td, width: 130, color: "var(--muted)",
                               fontSize: 12.5 }}>
                    {SHORT[d.doc_type] || d.doc_type}
                  </td>
                  <td style={{ ...td, width: 100 }}>{d.doc_date}</td>
                  <td style={td}>{subjectOf(d).slice(0, 90)}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    <StatusChip status={d.is_void ? "VOID" : d.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE && (
        <div style={{ display: "flex", alignItems: "center", gap: 12,
                      marginTop: 14 }}>
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
            {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
          </span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <Btn variant="secondary" disabled={offset === 0}
                 onClick={() => setOffset(Math.max(offset - PAGE, 0))}>
              Previous</Btn>
            <Btn variant="secondary" disabled={offset + PAGE >= total}
                 onClick={() => setOffset(offset + PAGE)}>
              Next</Btn>
          </span>
        </div>
      )}
    </section>
  );
}
