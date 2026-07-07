import { useEffect, useState } from "react";

const MILESTONES = [
  ["M0", "Repo, local stack, CI, skeleton app", "in progress"],
  ["M1", "Schema, auth, roles, Site & Project module", "pending"],
  ["M2", "DPR end-to-end + PDF + register", "pending"],
  ["M3", "Item Master + procurement chain (MR/PR/LM/GRN)", "pending"],
  ["M4", "IR + MAR revisions; TWS", "pending"],
  ["M5", "Employees, attendance, OT, payroll export", "pending"],
  ["M6", "Notifications, exports, production deploy", "pending"],
];

export default function App() {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    fetch("/api/v1/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: "unreachable" }));
  }, []);

  return (
    <div>
      <header
        style={{
          background: "var(--sp-navy)",
          color: "#fff",
          padding: "14px 28px",
          borderBottom: "4px solid var(--sp-sky)",
          display: "flex",
          alignItems: "baseline",
          gap: 12,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 20, letterSpacing: 0.5 }}>
          SAND PLANET
        </h1>
        <span style={{ color: "var(--sp-sky)", fontSize: 14 }}>
          Site Documents
        </span>
      </header>

      <main style={{ maxWidth: 720, margin: "32px auto", padding: "0 16px" }}>
        <section
          style={{
            background: "#fff",
            border: "1px solid var(--sp-border)",
            borderRadius: 8,
            padding: 24,
            marginBottom: 24,
          }}
        >
          <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
            System status
          </h2>
          <p style={{ margin: 0 }}>
            API:{" "}
            <strong
              style={{
                color: health?.status === "ok" ? "#1a7f37" : "#b35900",
              }}
            >
              {health ? health.status : "checking…"}
            </strong>
            {health?.engine && (
              <span style={{ color: "#5a6b78" }}>
                {" "}
                — database: {health.db} ({health.engine})
              </span>
            )}
          </p>
        </section>

        <section
          style={{
            background: "#fff",
            border: "1px solid var(--sp-border)",
            borderRadius: 8,
            padding: 24,
          }}
        >
          <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
            Build milestones
          </h2>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {MILESTONES.map(([code, label, status]) => (
                <tr key={code} style={{ borderTop: "1px solid var(--sp-border)" }}>
                  <td style={{ padding: "8px 8px 8px 0", fontWeight: 600, color: "var(--sp-navy)", width: 48 }}>
                    {code}
                  </td>
                  <td style={{ padding: 8 }}>{label}</td>
                  <td style={{ padding: 8, textAlign: "right" }}>
                    <span
                      style={{
                        fontSize: 12,
                        padding: "2px 10px",
                        borderRadius: 12,
                        background:
                          status === "in progress" ? "var(--sp-sky)" : "#e6edf3",
                        color: status === "in progress" ? "#fff" : "#5a6b78",
                      }}
                    >
                      {status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  );
}
