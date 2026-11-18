// "A supplier with a very similar name is already on file" — shown when a new
// supplier's name matches one already in the directory once "Pvt", "Ltd",
// "PLC" and punctuation are set aside (owner 2026-11-18: Trading had typed
// in Kelani Cables beside Purchasing's Kelani Cables PLC).
const CAT = { LOCAL: "local", INTERNATIONAL: "international",
              FORWARDER: "forwarder", CLEARING_AGENT: "clearing agent" };

export default function SimilarSuppliers({ similar, onUse, useLabel,
                                           onCreateAnyway, onCancel, busy }) {
  if (!similar?.length) return null;
  return (
    <div role="alertdialog" aria-label="Similar suppliers already on file"
      style={{ margin: "10px 0", padding: "12px 14px", borderRadius: 8,
               background: "#fff6e0", border: "1px solid #ecd08a",
               fontSize: 13.5, color: "#4a3a00" }}>
      <strong>This supplier may already be on file.</strong>
      <div style={{ marginTop: 6, display: "flex", flexDirection: "column",
                    gap: 6 }}>
        {similar.map((s) => (
          <div key={s.id} style={{ display: "flex", gap: 10,
                                   alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontWeight: 600 }}>{s.name}</span>
            <span style={{ fontSize: 12, color: "#6b5a1a" }}>
              {[CAT[s.category] || s.category, s.country,
                s.is_trading ? "used in trading" : null]
                .filter(Boolean).join(" · ")}</span>
            {onUse && (
              <button type="button" disabled={busy} onClick={() => onUse(s)}
                style={{ marginLeft: "auto", padding: "3px 10px",
                         fontSize: 12.5, borderRadius: 6, cursor: "pointer",
                         border: "1px solid #b98d10", background: "#fff",
                         color: "#4a3a00" }}>
                {useLabel || "Use this one"}</button>
            )}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, display: "flex", gap: 8,
                    flexWrap: "wrap" }}>
        <button type="button" disabled={busy} onClick={onCreateAnyway}
          style={{ padding: "4px 12px", fontSize: 12.5, borderRadius: 6,
                   cursor: "pointer", border: "1px solid #c9b46a",
                   background: "transparent", color: "#4a3a00" }}>
          It's a different company — create it</button>
        {onCancel && (
          <button type="button" onClick={onCancel}
            style={{ padding: "4px 12px", fontSize: 12.5, borderRadius: 6,
                     cursor: "pointer", border: "none",
                     background: "transparent", color: "#6b5a1a" }}>
            Cancel</button>
        )}
      </div>
    </div>
  );
}
