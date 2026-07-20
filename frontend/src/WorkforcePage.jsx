import { useState } from "react";
import SubcontractorsPanel from "./SubcontractorsPanel.jsx";
import WorkerManagementPanel from "./WorkerManagementPanel.jsx";
import { ghostButton } from "./ui.jsx";

// Dedicated site workforce page (owner: keep this off the site dashboard,
// which was getting too long). Two tabs: direct salaried workers and
// subcontractor teams.
const TABS = [["direct", "Direct workers"], ["subcontract", "Subcontractors"]];

export default function WorkforcePage({ site, me, onClose }) {
  const [tab, setTab] = useState("direct");
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    marginBottom: 14 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          Workforce — {site.name}</h2>
        <button onClick={onClose}
                style={{ ...ghostButton, marginLeft: "auto" }}>Close</button>
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
        {TABS.map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
                  style={{ ...ghostButton, padding: "4px 14px", fontSize: 13,
                           background: tab === key ? "var(--sp-navy)" : "#fff",
                           color: tab === key ? "#fff" : "var(--sp-navy)" }}>
            {label}
          </button>
        ))}
      </div>
      {tab === "direct" && <WorkerManagementPanel site={site} me={me} />}
      {tab === "subcontract" && <SubcontractorsPanel site={site} me={me} />}
    </div>
  );
}
