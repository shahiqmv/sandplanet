// Shared components per SP_Design_Brief.md — build screens from these
// only; tokens live in index.css and are never hard-coded elsewhere.

export const card = {
  background: "var(--paper)",
  border: "1px solid var(--line)",
  borderRadius: 12,
  boxShadow: "0 1px 2px rgba(24,36,48,.04), 0 4px 14px rgba(24,36,48,.05)",
  padding: 24,
  marginBottom: 20,
};

export const inputStyle = {
  width: "100%",
  padding: "7px 9px",
  border: "1px solid #BFD6E6",
  borderRadius: 8,
  fontSize: 14,
  fontFamily: "var(--font-body)",
  background: "var(--paper)",
  boxSizing: "border-box",
};

// Buttons — semantic color mapping (brief): sky = create/issue/do,
// navy = authority (approve/verify), secondary = safe alternative,
// ghost = navigation, danger = void/remove (never solid red).
const btnBase = {
  padding: "8px 18px",
  borderRadius: 8,
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
  border: "1px solid transparent",
  transition: "background 150ms ease, border-color 150ms ease",
};
export const BTN = {
  primary: { ...btnBase, background: "var(--sky)", color: "#fff" },
  navy: { ...btnBase, background: "var(--navy)", color: "#fff" },
  secondary: { ...btnBase, background: "var(--paper)", color: "var(--navy)",
               border: "1px solid #BFD6E6" },
  ghost: { ...btnBase, background: "transparent", color: "var(--navy)",
           border: "1px solid transparent" },
  danger: { ...btnBase, background: "var(--paper)", color: "var(--red-fg)",
            border: "1px solid var(--red-fg)" },
};
export function Btn({ variant = "primary", style, className, ...props }) {
  // Hover/active/disabled states come from the .btn classes (index.css);
  // the inline BTN object stays as the base so style={} overrides keep
  // working exactly as before.
  return <button
    className={`btn btn-${variant}${className ? ` ${className}` : ""}`}
    style={style} {...props} />;
}

// Small inline icon set (lucide-style strokes) — replaces the emoji that
// used to label the site quick-action buttons. currentColor, so icons take
// the button's text color automatically.
const ICON_PATHS = {
  clock: <><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></>,
  users: <><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" /></>,
  wallet: <><path d="M20 12V8H6a2 2 0 0 1-2-2c0-1.1.9-2 2-2h12v4" />
    <path d="M4 6v12c0 1.1.9 2 2 2h14v-4" />
    <path d="M18 12a2 2 0 0 0-2 2c0 1.1.9 2 2 2h4v-4h-4z" /></>,
  box: <><path d="M21 8l-9-5-9 5v8l9 5 9-5V8z" />
    <polyline points="3 8 12 13 21 8" /><line x1="12" y1="13" x2="12" y2="21" /></>,
  wrench: <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />,
  anchor: <><circle cx="12" cy="5" r="3" /><line x1="12" y1="22" x2="12" y2="8" />
    <path d="M5 12H2a10 10 0 0 0 20 0h-3" /></>,
  globe: <><circle cx="12" cy="12" r="10" />
    <line x1="2" y1="12" x2="22" y2="12" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></>,
  boat: <><path d="M22 18H2a4 4 0 0 0 4 4h12a4 4 0 0 0 4-4Z" />
    <path d="M21 14 10 2 3 14h18Z" /><path d="M10 2v16" /></>,
  truck: <><rect x="1" y="3" width="15" height="13" />
    <polygon points="16 8 20 8 23 11 23 16 16 16 16 8" />
    <circle cx="5.5" cy="18.5" r="2.5" /><circle cx="18.5" cy="18.5" r="2.5" /></>,
  card: <><rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
    <line x1="1" y1="10" x2="23" y2="10" /></>,
};
export function Icon({ name, size = 14, style }) {
  const paths = ICON_PATHS[name];
  if (!paths) return null;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true"
         style={{ verticalAlign: -2, marginRight: 6, ...style }}>
      {paths}
    </svg>
  );
}

// Dropdown of controlled options that still lets the user type a value not
// on the list ("Other…"). value/onChange behave like a plain input.
export function SelectOrOther({ value, onChange, options, placeholder,
                               width, style }) {
  const OTHER = "__other__";
  const known = options.includes(value) || value === "";
  const sel = known ? value : OTHER;
  const box = { ...inputStyle, width: width || "100%", ...style };
  return (
    <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
      <select value={sel} style={box}
              onChange={(e) => onChange(
                e.target.value === OTHER ? " " : e.target.value)}>
        <option value="">{placeholder || "Select…"}</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
        <option value={OTHER}>Other…</option>
      </select>
      {sel === OTHER && (
        <input autoFocus value={value.trim() === "" ? "" : value}
               placeholder="Specify" style={box}
               onChange={(e) => onChange(e.target.value)} />
      )}
    </span>
  );
}

// Legacy aliases — old screens keep working, now on brief semantics
export const buttonStyle = BTN.navy;
export const ghostButton = BTN.secondary;

export const th = {
  textAlign: "left",
  fontSize: 12,
  color: "var(--navy)",
  fontWeight: 600,
  padding: "6px 8px",
  borderBottom: "2px solid var(--sky)",
};

export const td = {
  padding: "7px 8px",
  fontSize: 13,
  borderTop: "1px solid var(--row-line)",
  verticalAlign: "top",
};

// Chips — four tones only (brief)
const CHIP_TONES = {
  ok: { background: "var(--green-bg)", color: "var(--green-fg)" },
  warn: { background: "var(--amber-bg)", color: "var(--amber-fg)" },
  alert: { background: "var(--red-bg)", color: "var(--red-fg)" },
  info: { background: "var(--sky-soft)", color: "var(--navy)" },
};
export function Chip({ tone = "info", children }) {
  return (
    <span style={{ ...CHIP_TONES[tone], fontSize: 11.5, fontWeight: 600,
                   padding: "2px 10px", borderRadius: 999,
                   whiteSpace: "nowrap", display: "inline-block" }}>
      {children}
    </span>
  );
}

const STATUS_TONES = {
  ACTIVE: "ok", VERIFIED: "ok", LOADED: "ok", RECEIVED: "ok",
  COMPLETE: "ok", APPROVED: "ok", ACKNOWLEDGED: "ok",
  PAID_PO_ISSUED: "ok", CLOSED: "ok",
  AWARDED: "info", ISSUED: "info", SUBMITTED: "info", PM_APPROVED: "info",
  SENT_TO_HO: "info", PR_RAISED: "info", LOADING_PLANNED: "info",
  DEPARTED: "info", COUNTED: "info", DIRECTOR_APPROVED: "info",
  AUTHORISED: "ok", PAID: "ok",
  DRAFT: "warn", ON_HOLD: "warn", PARTIALLY_LOADED: "warn",
  APPROVED_WITH_COMMENTS: "warn", REVISE_RESUBMIT: "warn",
  CLOSED_BY_PM: "warn", PAYMENT_PROCESSING: "warn", CANCELLED: "warn",
  VOID: "alert", RECEIVED_WITH_SHORTAGE: "alert",
  SHORTAGE_REPORTED: "alert", REJECTED: "alert",
};
export function StatusChip({ status }) {
  if (!status) return null;
  return (
    <Chip tone={STATUS_TONES[status] || "info"}>
      {String(status).replace(/_/g, " ")}
    </Chip>
  );
}

// RefStamp — document references never render as plain text (brief)
export function RefStamp({ children, small }) {
  return (
    <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600,
                   fontSize: small ? 11 : 12.5, color: "var(--navy)",
                   border: "1.5px solid var(--navy)", borderRadius: 3,
                   padding: small ? "0px 5px" : "1px 7px",
                   whiteSpace: "nowrap", display: "inline-block" }}>
      {children}
    </span>
  );
}

// IssuedStamp — green ink stamp once a document is issued
export function IssuedStamp({ refText, label = "ISSUED" }) {
  return (
    <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600,
                   fontSize: 12, color: "var(--green-fg)",
                   border: "2px solid var(--green-fg)", borderRadius: 4,
                   padding: "3px 10px", display: "inline-block",
                   transform: "rotate(-4deg)", letterSpacing: "0.04em" }}>
      {refText} · {label}
    </span>
  );
}

// StampTile — daily obligations: amber dashed while due, paper + green
// stamp when done. Reused for month-lock tiles.
export function StampTile({ title, done, dueText, doneStamp, action }) {
  return (
    <div style={{
      flex: 1, minWidth: 220, borderRadius: 12, padding: "14px 16px",
      background: done ? "var(--paper)" : "var(--amber-bg)",
      border: done ? "1px solid var(--line)"
                   : "1.5px dashed var(--amber-fg)",
    }}>
      {/* Owner (2026-07-08): condensed uppercase was hard on the eye —
          headings use the body face, gently tracked */}
      <div style={{ fontWeight: 700, letterSpacing: "0.02em",
                    fontSize: 13.5, color: done ? "var(--muted)"
                                                : "var(--amber-fg)" }}>
        {title}
      </div>
      <div style={{ marginTop: 10, minHeight: 34 }}>
        {done ? doneStamp : (
          <>
            {dueText && <div style={{ fontSize: 12, color: "var(--amber-fg)",
                                      marginBottom: 8 }}>{dueText}</div>}
            {action}
          </>
        )}
      </div>
    </div>
  );
}

// Eyebrow — display-font uppercase section heading with optional meta
export function Eyebrow({ children, meta, metaTone }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline",
                  justifyContent: "space-between", margin: "18px 0 8px" }}>
      <span style={{ fontWeight: 700, letterSpacing: "0.02em",
                     fontSize: 15, color: "var(--navy)" }}>
        {children}
      </span>
      {meta && (
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12,
                       fontWeight: 600,
                       color: metaTone === "alert" ? "var(--red-fg)"
                                                   : "var(--faint)" }}>
          {meta}
        </span>
      )}
    </div>
  );
}

// Stat — never a bare count: number + label + one colored context line
export function Stat({ value, label, context, tone = "info" }) {
  const toneColor = { ok: "var(--green-fg)", warn: "var(--amber-fg)",
                      alert: "var(--red-fg)", info: "var(--muted)" }[tone];
  return (
    <div style={{ flex: 1, minWidth: 130 }}>
      <div style={{ fontFamily: "var(--font-display)", fontWeight: 700,
                    fontSize: 30, color: "var(--ink)", lineHeight: 1 }}>
        {value}
      </div>
      <div style={{ fontSize: 12.5, fontWeight: 700, marginTop: 2 }}>
        {label}</div>
      {context && (
        <div style={{ fontSize: 11.5, color: toneColor, marginTop: 2 }}>
          {context}</div>
      )}
    </div>
  );
}

// ActionCard — queue rows: left accent by severity, RefStamp + what/where
// + age line; right chip + one button. Order queues severity then age.
const ACCENTS = { alert: "var(--red-fg)", warn: "var(--amber-fg)",
                  info: "var(--sky)" };
export function ActionCard({ severity = "info", refText, text, meta, chip,
                             button }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12,
                  background: "var(--paper)",
                  border: "1px solid var(--line)",
                  borderLeft: `4px solid ${ACCENTS[severity]}`,
                  borderRadius: 12, padding: "10px 14px", marginBottom: 8,
                  boxShadow: "0 1px 3px rgba(24,36,48,.05)",
                  flexWrap: "wrap" }}>
      <RefStamp>{refText}</RefStamp>
      <div style={{ flex: 1, minWidth: 180 }}>
        <div style={{ fontSize: 13.5 }}>{text}</div>
        {meta && <div style={{ fontSize: 11.5, color: "var(--faint)",
                               marginTop: 1 }}>{meta}</div>}
      </div>
      {chip}
      {button}
    </div>
  );
}

export function SectionTitle({ children }) {
  return (
    <h3
      style={{
        color: "var(--navy)",
        fontSize: 14.5,
        borderBottom: "1px solid var(--sky)",
        paddingBottom: 4,
        margin: "20px 0 10px",
      }}
    >
      {children}
    </h3>
  );
}
