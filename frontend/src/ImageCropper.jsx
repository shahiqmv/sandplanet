import { useEffect, useRef, useState } from "react";
import { Btn, card } from "./ui.jsx";

// A minimal, dependency-free crop modal: the image covers a fixed-aspect frame;
// drag to reposition, slider to zoom; outputs a JPEG blob at the target size and
// exact aspect. The server re-crops as a guarantee, but this respects the user's
// framing so the grid never surprises them.
export default function ImageCropper({ file, aspect, outW, label,
                                       onCancel, onDone }) {
  const FRAME_W = 440;
  const FRAME_H = Math.round(FRAME_W / aspect);
  const canvasRef = useRef(null);
  const imgRef = useRef(null);
  const view = useRef({ base: 1, x: 0, y: 0, iw: 0, ih: 0 });
  const drag = useRef(null);
  const [ready, setReady] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const base = Math.max(FRAME_W / img.width, FRAME_H / img.height);
      imgRef.current = img;
      view.current = { base, x: 0, y: 0, iw: img.width, ih: img.height };
      // centre the image in the frame
      view.current.x = (FRAME_W - img.width * base) / 2;
      view.current.y = (FRAME_H - img.height * base) / 2;
      setReady(true);
    };
    img.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => { if (ready) clampDraw(); }, [ready, zoom]);   // eslint-disable-line

  function clampDraw() {
    const v = view.current, s = v.base * zoom;
    const w = v.iw * s, h = v.ih * s;
    v.x = Math.min(0, Math.max(FRAME_W - w, v.x));   // keep frame covered
    v.y = Math.min(0, Math.max(FRAME_H - h, v.y));
    const ctx = canvasRef.current.getContext("2d");
    ctx.clearRect(0, 0, FRAME_W, FRAME_H);
    ctx.drawImage(imgRef.current, v.x, v.y, w, h);
  }

  function down(e) {
    const p = e.touches ? e.touches[0] : e;
    drag.current = { mx: p.clientX, my: p.clientY,
                     vx: view.current.x, vy: view.current.y };
  }
  function move(e) {
    if (!drag.current) return;
    const p = e.touches ? e.touches[0] : e;
    view.current.x = drag.current.vx + (p.clientX - drag.current.mx);
    view.current.y = drag.current.vy + (p.clientY - drag.current.my);
    clampDraw();
  }
  function up() { drag.current = null; }

  useEffect(() => {
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    window.addEventListener("touchmove", move, { passive: false });
    window.addEventListener("touchend", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      window.removeEventListener("touchmove", move);
      window.removeEventListener("touchend", up);
    };
  });   // rebind each render so latest closures are used

  function confirm() {
    setBusy(true);
    const out = document.createElement("canvas");
    out.width = outW;
    out.height = Math.round(outW / aspect);
    const k = outW / FRAME_W;                        // frame → output scale
    const v = view.current, s = v.base * zoom;
    out.getContext("2d").drawImage(
      imgRef.current, v.x * k, v.y * k, v.iw * s * k, v.ih * s * k);
    out.toBlob((blob) => onDone(blob), "image/jpeg", 0.9);
  }

  return (
    <div onClick={onCancel}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
                  display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 80, padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: FRAME_W + 48 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>
          Position {label || "image"}</div>
        <div style={{ position: "relative", width: FRAME_W, height: FRAME_H,
          borderRadius: 8, overflow: "hidden", background: "#0b1a26",
          cursor: "grab", touchAction: "none" }}
          onMouseDown={down} onTouchStart={down}>
          <canvas ref={canvasRef} width={FRAME_W} height={FRAME_H} />
          {/* subtle rule-of-thirds guide */}
          <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
            boxShadow: "inset 0 0 0 1px rgba(255,255,255,.35)" }} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10,
          marginTop: 10 }}>
          <span style={{ fontSize: 12, color: "var(--muted)" }}>Zoom</span>
          <input type="range" min="1" max="3" step="0.01" value={zoom}
            onChange={(e) => setZoom(parseFloat(e.target.value))}
            style={{ flex: 1 }} />
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <Btn variant="primary" disabled={!ready || busy}
            onClick={confirm}>Use photo</Btn>
          <Btn variant="ghost" onClick={onCancel}>Cancel</Btn>
        </div>
        <p style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>
          Drag to reposition · zoom to fill the frame.</p>
      </div>
    </div>
  );
}
