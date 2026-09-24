// Small shared pieces for the trading app.
import { Chip } from "../ui.jsx";

export const STAGE_LABEL = {
  INQUIRY: "Inquiry", SOURCING: "Sourcing", PRICING: "Pricing",
  QUOTED: "Quoted", WON: "Won", LOST: "Lost",
};
export const STAGES = ["INQUIRY", "SOURCING", "PRICING", "QUOTED", "WON"];

const STAGE_TONE = { INQUIRY: "info", SOURCING: "info", PRICING: "warn",
                     QUOTED: "warn", WON: "ok", LOST: "alert" };

export function StageChip({ stage }) {
  return <Chip tone={STAGE_TONE[stage] || "info"}>{STAGE_LABEL[stage] || stage}</Chip>;
}

export function fmtDate(v) {
  if (!v) return "";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function fmtDateTime(v) {
  if (!v) return "";
  const d = new Date(v);
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric",
                                     hour: "2-digit", minute: "2-digit" });
}

export function fmtMoney(v, dp = 2) {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

export function fmtQty(v) {
  const n = Number(v);
  if (Number.isNaN(n)) return String(v ?? "");
  return Number.isInteger(n) ? String(n) : n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}
