// Shared presentational bits for Planet Mobile.
import React from "react";

// The ring mark — matches the app icon / PDF letterhead motif.
export function RingMark({ size = 64, light = false }) {
  const ring = light ? "#ffffff" : "#16527e";
  const dot = "#29abe2";
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="26" fill="none" stroke={ring} strokeWidth="5" />
      <circle cx="32" cy="32" r="13" fill="none" stroke={ring} strokeWidth="5" />
      <circle cx="32" cy="6" r="5" fill={dot} />
    </svg>
  );
}

export function Spinner() {
  return <div className="spinner" role="status" aria-label="Loading" />;
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <div className="big">{title}</div>
      {children && <div>{children}</div>}
    </div>
  );
}

// Status → chip tone. OK-ish states green, blocked/returned red, else neutral.
const OK = /APPROV|AUTHORIS|PAID|COMPLETE|RECEIVED|VERIFIED|CLOSED|DEPARTED|SENT|ACKNOWLEDG/;
const BAD = /RETURN|REJECT|CANCEL|SHORT|PENDING_ITEMS|HOLD/;
export function StatusChip({ status, label }) {
  const s = status || "";
  const tone = OK.test(s) ? "ok" : BAD.test(s) ? "alert" : "";
  return <span className={`chip ${tone}`}>{label || pretty(s)}</span>;
}

export function pretty(s) {
  return (s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Money — grouped thousands, currency suffix, no decimals for whole amounts.
export function money(v, ccy) {
  if (v == null || v === "") return "";
  const n = Number(v);
  const s = n.toLocaleString("en-US", {
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  });
  return ccy ? `${s} ${ccy}` : s;
}

// Relative age, e.g. "3d", "5h", "just now".
export function age(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.round(hrs / 24);
  return `${days}d`;
}

export function Toast({ toast }) {
  if (!toast) return null;
  return <div className={`toast ${toast.tone || ""}`}>{toast.msg}</div>;
}

// Stamp overlay played after an action, before returning to the inbox.
export function Stamp({ text, tone }) {
  return (
    <div className="stamp-wrap">
      <div className={`stamp ${tone || ""}`}>{text}</div>
    </div>
  );
}
