import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, inputStyle } from "./ui.jsx";

// The signatory's queue of onboarding cases awaiting their approval. Signing
// off a case applies the signatory's digital stamp + the company seal to every
// letter in the case (appointment letter, appointment confirmation, sponsor
// letter…) and releases the signed copies for the team to print.
export default function AppointmentSignoff() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  const load = () => api("/onboarding/letters/to-sign").then(setData)
    .catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  async function run(fn) {
    setBusy(true); setErr(null);
    try { const d = await fn(); if (d) setData(d); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  }

  const uploadStamp = (file) => run(async () => {
    const fd = new FormData(); fd.append("stamp", file);
    await apiUpload("/onboarding/my-stamp", fd);
    return api("/onboarding/letters/to-sign");
  });
  const signOff = (caseId) => run(() =>
    api(`/onboarding/cases/${caseId}/sign-off`, { method: "POST" }));

  if (!data) {
    return <div style={{ padding: 20, color: "var(--muted)" }}>
      {err || "Loading…"}</div>;
  }
  const list = data.cases || [];
  return (
    <div style={{ maxWidth: 820, margin: "0 auto", padding: "8px 4px" }}>
      <h2 style={{ margin: "4px 0 2px" }}>Onboarding cases to sign off</h2>
      <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 12 }}>
        Review each case and apply your approval. Signing off stamps every letter
        in the case with your signature and the company seal, and releases the
        signed copies for the team to print.</div>

      <div style={{ ...card, marginBottom: 14, display: "flex", gap: 12,
        alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontWeight: 600 }}>Your approval stamp{" "}
            {data.has_stamp
              ? <Chip tone="ok">Set</Chip>
              : <Chip tone="warn">Not set</Chip>}</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            A stamp/seal image (PNG or JPG). Uploaded once and applied to every
            letter you sign. Upload again to replace it.</div>
        </div>
        <input ref={fileRef} type="file" accept="image/png,image/jpeg"
          style={{ display: "none" }}
          onChange={(e) => { const f = e.target.files?.[0];
            if (f) uploadStamp(f); e.target.value = ""; }} />
        <Btn variant="secondary" disabled={busy}
          onClick={() => fileRef.current?.click()}>
          {data.has_stamp ? "Replace stamp" : "Upload stamp"}</Btn>
      </div>

      {err && <div style={{ color: "var(--red-fg)", fontSize: 13,
        marginBottom: 8 }}>{err}</div>}

      {!list.length ? (
        <div style={{ ...card, color: "var(--muted)", textAlign: "center",
          padding: 24 }}>Nothing awaiting your sign-off.</div>
      ) : list.map((c) => (
        <div key={c.case_id} style={{ ...card, marginBottom: 10 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center",
            flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ fontWeight: 600 }}>{c.candidate_name}
                <span style={{ color: "var(--muted)", fontWeight: 400,
                  fontSize: 12.5 }}> · {c.position || "—"}</span></div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
                {c.case_ref} · {c.nationality || "—"}</div>
            </div>
            <Btn variant="primary" disabled={busy || !data.has_stamp}
              title={data.has_stamp ? "" : "Upload your stamp first"}
              onClick={() => signOff(c.case_id)}>Approve &amp; sign off</Btn>
          </div>

          <div style={{ marginTop: 10, display: "flex", flexDirection: "column",
            gap: 6 }}>
            {(c.letters || []).map((l) => (
              <div key={l.id} style={{ display: "flex", gap: 10,
                alignItems: "center", fontSize: 12.5,
                borderTop: "1px solid var(--line)", paddingTop: 6 }}>
                <span style={{ fontWeight: 600, minWidth: 44 }}>{l.kind}</span>
                <span style={{ flex: 1, color: "var(--muted)" }}>
                  {l.title} · {l.ref}</span>
                {l.draft && <a href={`/api/v1${l.draft}`} target="_blank"
                  rel="noreferrer" style={{ ...inputStyle,
                    textDecoration: "none", color: "var(--navy)",
                    padding: "4px 10px", fontWeight: 600 }}>Review draft</a>}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
