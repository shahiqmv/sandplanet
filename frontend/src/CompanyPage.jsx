import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { buttonStyle, card, inputStyle } from "./ui.jsx";

// Company identity (owner, 2026-07-08): logo image file, tax info,
// registration no and address managed in one place — every PDF letterhead
// and footer pulls from here.

const FIELDS = [
  ["company_legal_name", "Legal name", "Sand Planet Pvt Ltd"],
  ["company_reg_no", "Company registration no", "e.g. C-0123/2015"],
  ["company_tin", "TIN (tax identification no)", ""],
  ["company_address", "Registered address", ""],
  ["company_phone", "Phone", ""],
  ["company_email", "Email", ""],
  ["company_website", "Website", "www.sandplanet.mv"],
  ["company_tagline", "Tagline (external documents)", ""],
];

export default function CompanyPage() {
  const [values, setValues] = useState({});
  const [logo, setLogo] = useState(null);       // {url, uploaded}
  const [logoFile, setLogoFile] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all(FIELDS.map(([key]) =>
      api(`/parameters/${key}`).then((p) => [key, p.value ?? ""])
        .catch(() => [key, ""])
    )).then((pairs) => setValues(Object.fromEntries(pairs)));
    api("/company/logo").then(setLogo).catch(() => {});
  }, []);

  async function save() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      for (const [key] of FIELDS) {
        await api(`/parameters/${key}`, { method: "PUT",
                                          body: { value: values[key] || "" } });
      }
      if (logoFile) {
        const fd = new FormData();
        fd.append("file", logoFile);
        setLogo(await apiUpload("/company/logo", fd));
        setLogoFile(null);
      }
      setNotice("Company details saved — new PDFs use them immediately "
                + "(already-issued PDFs are archived and stay as printed).");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={{ ...card, maxWidth: 620 }}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Company
      </h2>
      <p style={{ fontSize: 12, color: "#5a6b78", marginTop: -6 }}>
        These details print on every report: the logo on the letterhead;
        legal name, registration no, TIN, address and website in the page
        footer; the full block on external purchase orders.
      </p>

      <div style={{ display: "flex", gap: 16, alignItems: "center",
                    margin: "12px 0", padding: 12,
                    border: "1px solid var(--sp-border)", borderRadius: 8 }}>
        {logo?.url ? (
          <img src={logo.url} alt="Company logo"
               style={{ height: 44, background: "#fff" }} />
        ) : (
          <span style={{ fontSize: 12, color: "#5a6b78" }}>
            Using the built-in stationery logo
          </span>
        )}
        <label style={{ fontSize: 13 }}>
          Replace logo (PNG/JPEG){" "}
          <input type="file" accept="image/png,image/jpeg"
                 onChange={(e) => setLogoFile(e.target.files[0] || null)} />
        </label>
      </div>

      {FIELDS.map(([key, label, placeholder]) => (
        <label key={key}
               style={{ display: "block", fontSize: 13, marginBottom: 10 }}>
          {label}
          <input value={values[key] || ""} placeholder={placeholder}
                 onChange={(e) => setValues({ ...values,
                                              [key]: e.target.value })}
                 style={{ ...inputStyle, width: "100%", marginTop: 3 }} />
        </label>
      ))}

      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      <button onClick={save} disabled={busy} style={buttonStyle}>
        {busy ? "Saving…" : "Save company details"}
      </button>
    </section>
  );
}
