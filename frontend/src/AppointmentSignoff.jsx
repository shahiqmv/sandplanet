import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, inputStyle } from "./ui.jsx";

// The signatory's queue of Appointment Confirmations awaiting their digital
// stamp, plus their one-time stamp upload. A limited view — no access to the
// candidate's case documents, only the letter to review + approve.
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
  const sign = (id) => run(() =>
    api(`/onboarding/letters/${id}/sign`, { method: "POST" }));

  if (!data) {
    return <div style={{ padding: 20, color: "var(--muted)" }}>
      {err || "Loading…"}</div>;
  }
  const list = data.letters || [];
  return (
    <div style={{ maxWidth: 780, margin: "0 auto", padding: "8px 4px" }}>
      <h2 style={{ margin: "4px 0 2px" }}>Appointment Confirmations to sign</h2>
      <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 12 }}>
        Review each appointment offer and apply your digital stamp. Once you
        approve, the signed copy becomes available for the team to print.</div>

      <div style={{ ...card, marginBottom: 14, display: "flex", gap: 12,
        alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontWeight: 600 }}>Your approval stamp{" "}
            {data.has_stamp
              ? <Chip tone="ok">Set</Chip>
              : <Chip tone="warn">Not set</Chip>}</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            A stamp/seal image (PNG or JPG). Uploaded once and applied to every
            confirmation you sign. Upload again to replace it.</div>
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
          padding: 24 }}>Nothing awaiting your signature.</div>
      ) : list.map((l) => (
        <div key={l.id} style={{ ...card, marginBottom: 8, display: "flex",
          gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontWeight: 600 }}>{l.candidate_name}
              <span style={{ color: "var(--muted)", fontWeight: 400,
                fontSize: 12.5 }}> · {l.position || "—"}</span></div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
              {l.ref} · {l.nationality || "—"} · {l.case_ref}
              {l.created_by ? ` · raised by ${l.created_by}` : ""}</div>
          </div>
          <a href={`/api/v1${l.draft}`} target="_blank" rel="noreferrer"
             style={{ ...inputStyle, textDecoration: "none", color: "var(--navy)",
               padding: "6px 12px", fontWeight: 600 }}>Review draft</a>
          <Btn variant="primary" disabled={busy || !data.has_stamp}
            title={data.has_stamp ? "" : "Upload your stamp first"}
            onClick={() => sign(l.id)}>Approve &amp; stamp</Btn>
        </div>
      ))}
    </div>
  );
}
