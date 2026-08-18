// Shrink a photo in the browser before it is uploaded.
//
// Site photos go up straight off a phone — 4 to 7 MB each. gunicorn runs SYNC
// workers, so a worker sits blocked for the WHOLE transfer, not just the
// processing: on 2026-08-18 three site photos held all three workers until
// they hit the 120-second timeout and the app was unreachable for eight
// minutes. Caddy now buffers the body, which stops one slow upload costing a
// worker; this stops the upload being enormous in the first place.
//
// 1600px on the long edge at q0.82 is a DPR photo that still reads clearly in
// the PDF, at roughly a tenth of the bytes.
//
// Deliberately NOT applied to stamps, seals, logos or passport scans:
// re-encoding flattens PNG transparency (the company seal is a transparent
// PNG) and softens the detail the passport reader depends on.

const MAX_EDGE = 1600;
const QUALITY = 0.82;
// Below this a photo is already small enough that re-encoding buys nothing and
// risks making it worse.
const SKIP_UNDER_BYTES = 600 * 1024;

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("decode")); };
    img.src = url;
  });
}

/**
 * Returns a smaller JPEG File, or the ORIGINAL file when shrinking does not
 * apply or fails. Never rejects — an upload must not be lost to a resize.
 */
export async function shrinkPhoto(file, { maxEdge = MAX_EDGE,
                                          quality = QUALITY } = {}) {
  if (!file || !file.type?.startsWith("image/")) return file;
  if (file.type === "image/gif") return file;            // may be animated
  if (file.size <= SKIP_UNDER_BYTES) return file;
  try {
    const img = await loadImage(file);
    const { width, height } = img;
    if (!width || !height) return file;
    const scale = Math.min(1, maxEdge / Math.max(width, height));
    // Already small enough on both edges — but a big file, so re-encoding at
    // its own size still sheds the bloat a phone camera writes in.
    const w = Math.round(width * scale);
    const h = Math.round(height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, w, h);
    const blob = await new Promise((res) =>
      canvas.toBlob(res, "image/jpeg", quality));
    if (!blob || blob.size >= file.size) return file;    // no gain — keep it
    const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg",
                                    lastModified: Date.now() });
  } catch {
    return file;                                         // upload the original
  }
}
