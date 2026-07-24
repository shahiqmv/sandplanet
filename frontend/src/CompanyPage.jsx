import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { buttonStyle, card, inputStyle } from "./ui.jsx";

// Company identity (owner, 2026-07-08): logo image file, tax info,
// registration no and address managed in one place — every PDF letterhead
// and footer pulls from here.

const IDENTITY = [
  ["company_legal_name", "Legal name", "Sand Planet Pvt Ltd"],
  ["company_reg_no", "Company registration no", "e.g. C-0123/2015"],
  ["company_tin", "TIN (tax identification no)", ""],
  ["company_address", "Registered address", ""],
  ["company_phone", "Phone", ""],
  ["company_email", "Email", ""],
  ["company_website", "Website", "www.sandplanet.mv"],
  ["company_tagline", "Tagline (external documents)", ""],
];
// Bank accounts are managed as a list below (used for receipts + PVs); the
// primary account is the 'pay to' printed on invoices.
const FIELDS = IDENTITY;

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
    <div style={{ maxWidth: 620 }}>
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

      {IDENTITY.map(([key, label, placeholder]) => (
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
    <BankAccounts />
    </div>
  );
}

// Receiving bank accounts — the accounts money lands in, selectable as the
// "account credited" when Finance issues an official receipt. Separate from
// the single "pay to" account printed on invoices above.
const BLANK_ACC = { label: "", bank_name: "", branch: "", account_name: "",
  account_no: "", currency: "USD", swift: "", iban: "" };

function BankAccounts() {
  const [accts, setAccts] = useState(null);
  const [draft, setDraft] = useState(null);   // new/edit form or null
  const [error, setError] = useState(null);

  const load = () => api("/receivables/bank-accounts")
    .then((r) => setAccts(r.accounts)).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function save() {
    setError(null);
    if (!draft.label.trim()) { setError("Give the account a label."); return; }
    try {
      if (draft.id)
        await api(`/receivables/bank-accounts/${draft.id}`,
          { method: "PUT", body: draft });
      else
        await api("/receivables/bank-accounts", { method: "POST", body: draft });
      setDraft(null); load();
    } catch (e) { setError(e.message); }
  }
  async function deactivate(a) {
    if (!window.confirm(`Deactivate "${a.label}"?`)) return;
    try { await api(`/receivables/bank-accounts/${a.id}`, { method: "DELETE" }); load(); }
    catch (e) { setError(e.message); }
  }
  async function makePrimary(a) {
    try {
      await api(`/receivables/bank-accounts/${a.id}`,
        { method: "PUT", body: { is_primary: true } });
      load();
    } catch (e) { setError(e.message); }
  }

  return (
    <section style={{ ...card, maxWidth: 620, marginTop: 16 }}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Bank accounts
      </h2>
      <p style={{ fontSize: 12, color: "#5a6b78", marginTop: -6 }}>
        The company’s bank accounts — picked as the “account credited” on client
        receipts and the “debit account” on payment vouchers. The
        <strong> primary</strong> account is the “pay to” shown on invoices.
        Deactivating keeps past documents intact.
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {accts == null ? <p style={{ fontSize: 13 }}>Loading…</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13, margin: "8px 0" }}>
          <tbody>
            {accts.map((a) => (
              <tr key={a.id} style={{ borderTop: "1px solid var(--sp-border)",
                opacity: a.is_active ? 1 : 0.5 }}>
                <td style={{ padding: "6px 4px" }}>
                  <strong>{a.label}</strong>
                  {a.is_primary && <span style={{ fontSize: 10, marginLeft: 6,
                    padding: "1px 6px", borderRadius: 4, background: "#e6f0f7",
                    color: "var(--sp-navy)", fontWeight: 700 }}>PRIMARY</span>}
                  {!a.is_active && <span style={{ fontSize: 11,
                    color: "#5a6b78" }}> (inactive)</span>}
                  <div style={{ fontSize: 11, color: "#5a6b78" }}>
                    {[a.bank_name, a.account_no, a.currency]
                      .filter(Boolean).join(" · ")}</div>
                </td>
                <td style={{ padding: "6px 4px", textAlign: "right",
                             whiteSpace: "nowrap" }}>
                  {a.is_active && !a.is_primary && (
                    <button onClick={() => makePrimary(a)}
                      style={linkBtn}>Make primary</button>
                  )}
                  <button onClick={() => setDraft({ ...a })}
                    style={linkBtn}>Edit</button>
                  {a.is_active && (
                    <button onClick={() => deactivate(a)}
                      style={{ ...linkBtn, color: "#c0392b" }}>Deactivate</button>
                  )}
                </td>
              </tr>
            ))}
            {!accts.length && (
              <tr><td style={{ padding: "6px 4px", color: "#5a6b78" }}>
                No bank accounts yet.</td></tr>
            )}
          </tbody>
        </table>
      )}

      {draft ? (
        <div style={{ border: "1px solid var(--sp-border)", borderRadius: 8,
                      padding: 12, marginTop: 8 }}>
          {[["label", "Label (e.g. BML USD Current)"], ["bank_name", "Bank name"],
            ["branch", "Branch"], ["account_name", "Account name"],
            ["account_no", "Account number"], ["currency", "Currency"],
            ["swift", "SWIFT / BIC"], ["iban", "IBAN"]].map(([k, label]) => (
            <label key={k} style={{ display: "block", fontSize: 13,
                                    marginBottom: 8 }}>
              {label}
              <input value={draft[k] || ""}
                onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                style={{ ...inputStyle, width: "100%", marginTop: 3 }} />
            </label>
          ))}
          <button onClick={save} style={buttonStyle}>Save account</button>
          <button onClick={() => setDraft(null)}
            style={{ ...linkBtn, marginLeft: 10 }}>Cancel</button>
        </div>
      ) : (
        <button onClick={() => setDraft({ ...BLANK_ACC })} style={buttonStyle}>
          + Add receiving account</button>
      )}
    </section>
  );
}

const linkBtn = { border: "none", background: "none", cursor: "pointer",
  color: "var(--sp-navy)", fontSize: 13, marginLeft: 8 };
