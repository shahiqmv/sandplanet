export const card = {
  background: "#fff",
  border: "1px solid var(--sp-border)",
  borderRadius: 8,
  padding: 24,
  marginBottom: 24,
};

export const inputStyle = {
  width: "100%",
  padding: "7px 9px",
  border: "1px solid var(--sp-border)",
  borderRadius: 6,
  fontSize: 14,
  boxSizing: "border-box",
};

export const buttonStyle = {
  padding: "8px 18px",
  background: "var(--sp-navy)",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  fontSize: 14,
  cursor: "pointer",
};

export const ghostButton = {
  ...buttonStyle,
  background: "#fff",
  color: "var(--sp-navy)",
  border: "1px solid var(--sp-border)",
};

export const th = {
  textAlign: "left",
  fontSize: 12,
  color: "var(--sp-navy)",
  padding: "6px 8px",
  borderBottom: "2px solid var(--sp-sky)",
};

export const td = {
  padding: "7px 8px",
  fontSize: 13,
  borderTop: "1px solid var(--sp-border)",
  verticalAlign: "top",
};

const STATUS_COLORS = {
  ACTIVE: "#1a7f37",
  AWARDED: "#29abe2",
  ON_HOLD: "#b35900",
  CLOSED: "#5a6b78",
  DRAFT: "#b35900",
  ISSUED: "#29abe2",
  VERIFIED: "#1a7f37",
  VOID: "#c0392b",
  SUBMITTED: "#29abe2",
  PM_APPROVED: "#1b75bb",
  SENT_TO_HO: "#1b75bb",
  PR_RAISED: "#1b75bb",
  LOADING_PLANNED: "#29abe2",
  PARTIALLY_LOADED: "#b35900",
  LOADED: "#1a7f37",
  DEPARTED: "#29abe2",
  RECEIVED: "#1a7f37",
  RECEIVED_WITH_SHORTAGE: "#c0392b",
  COUNTED: "#29abe2",
  COMPLETE: "#1a7f37",
  SHORTAGE_REPORTED: "#c0392b",
  APPROVED: "#1a7f37",
  APPROVED_WITH_COMMENTS: "#b35900",
  REVISE_RESUBMIT: "#b35900",
  REJECTED: "#c0392b",
  CLOSED_BY_PM: "#b35900",
  ACKNOWLEDGED: "#1a7f37",
  PAYMENT_PROCESSING: "#b35900",
  PAID_PO_ISSUED: "#1a7f37",
  CANCELLED: "#5a6b78",
};

export function StatusChip({ status }) {
  if (!status) return null;
  return (
    <span
      style={{
        fontSize: 11,
        padding: "2px 9px",
        borderRadius: 12,
        background: STATUS_COLORS[status] || "#5a6b78",
        color: "#fff",
        whiteSpace: "nowrap",
      }}
    >
      {String(status).replace(/_/g, " ")}
    </span>
  );
}

export function SectionTitle({ children }) {
  return (
    <h3
      style={{
        color: "var(--sp-navy)",
        fontSize: 14,
        borderBottom: "1px solid var(--sp-sky)",
        paddingBottom: 4,
        margin: "20px 0 10px",
      }}
    >
      {children}
    </h3>
  );
}
