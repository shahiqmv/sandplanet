// The language a worker's forms print in, set from a worker list. Everyone
// was given a default from his nationality — Sri Lankans Sinhala, Indians
// Tamil — and the site team corrects it here (owner 2026-10-26).
import { useState } from "react";
import { api } from "./api.js";
import { WORKER_LANGUAGES } from "./languages.js";

export default function LanguageCell({ worker, canEdit, onSaved }) {
  const [value, setValue] = useState(worker.preferred_language || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const label = WORKER_LANGUAGES.find(([c]) => c === value)?.[1];
  if (!canEdit) return label || "—";
  async function change(code) {
    const was = value;
    setValue(code); setBusy(true); setErr(null);
    try {
      await api(`/workers/${worker.id}/language`, { method: "PATCH", body: { language: code } });
      onSaved?.(code);
    } catch (e) { setValue(was); setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <span>
      <select value={value} disabled={busy} onChange={(e) => change(e.target.value)}
              title="The language his warning and induction forms print in"
              style={{ fontSize: 12.5, padding: "2px 4px", border: "1px solid var(--line)", borderRadius: 4,
                       background: value ? "var(--paper)" : "#fff3d6" }}>
        {!value && <option value="">set…</option>}
        {WORKER_LANGUAGES.map(([c, l]) => <option key={c} value={c}>{l}</option>)}
      </select>
      {err && <div style={{ color: "var(--red-fg)", fontSize: 11 }}>{err}</div>}
    </span>
  );
}
