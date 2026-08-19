#!/usr/bin/env python3
"""Print a slips PDF straight to a network ESC/POS thermal printer.

Why not just use the Print dialog: the printer at the office speaks raw ESC/POS
on port 9100 and nothing else — no IPP (631 is closed), no AirPrint, and no PDF
interpreter. macOS 15 ships no ESC/POS driver either, so a CUPS "raw" queue
would send the PDF bytes verbatim and print pages of garbage.

It works out neatly instead, because the thermal slip is generated at 72mm and
203dpi — which is 576 dots, the printer's exact native raster width. So each
page rasterises 1:1 with no resampling, converts to an ESC/POS bitmap, and gets
a cut after it.

    python3 tools/thermal_print.py slips.pdf                 # print
    python3 tools/thermal_print.py slips.pdf --pages 1       # just the first
    python3 tools/thermal_print.py slips.pdf --dry-run       # no paper used
    python3 tools/thermal_print.py https://app.../slips.pdf --cookie "sessionid=…"

Needs pymupdf and pillow (both already in the backend venv):
    backend/.venv/bin/python tools/thermal_print.py …

NOTE: HR and Finance do NOT use this — they are on Windows and the SERVER now
renders the ESC/POS for them (core/thermal.escpos_bytes, served as
/payroll/runs/<id>/slips.escpos). See tools/windows/. This stays as the
admin-side tool for printing a PDF that is already on disk.
"""
import argparse
import io
import socket
import sys

ESC, GS = b"\x1b", b"\x1d"
DOTS = 576                 # 80mm head, 203dpi — matches the slip's own width
BAND = 128                 # raster rows per GS v 0 command


def load(src, cookie=None):
    if src.startswith(("http://", "https://")):
        import urllib.request
        req = urllib.request.Request(src)
        if cookie:
            req.add_header("Cookie", cookie)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if not data.startswith(b"%PDF"):
            sys.exit("That URL did not return a PDF — is the cookie still "
                     "valid? Sign in, copy the session cookie, and retry.")
        return data
    with open(src, "rb") as fh:
        return fh.read()


def page_to_escpos(page):
    """One page → ESC/POS raster bytes."""
    import fitz
    from PIL import Image

    # Render at the width the head actually has, whatever the page size says.
    scale = DOTS / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                          colorspace=fitz.csGRAY, alpha=False)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    if img.width != DOTS:                      # pad, never stretch
        canvas = Image.new("L", (DOTS, img.height), 255)
        canvas.paste(img, (0, 0))
        img = canvas
    # Dither rather than hard-threshold: thermal output is 1-bit, and dithering
    # keeps the thin rules and small type legible.
    bw = img.convert("1")
    raw = bw.tobytes()                          # 1 = white, 0 = black
    row_bytes = (DOTS + 7) // 8
    out = bytearray()
    for top in range(0, img.height, BAND):
        rows = min(BAND, img.height - top)
        chunk = bytearray(raw[top * row_bytes:(top + rows) * row_bytes])
        for i, b in enumerate(chunk):
            chunk[i] = b ^ 0xFF                 # ESC/POS wants 1 = burn
        out += GS + b"v0\x00"
        out += bytes([row_bytes & 0xFF, row_bytes >> 8,
                      rows & 0xFF, rows >> 8])
        out += bytes(chunk)
    return bytes(out)


def build(pdf_bytes, limit=None):
    import fitz
    doc = fitz.open("pdf", pdf_bytes)
    job = bytearray(ESC + b"@")                 # initialise once
    pages = list(doc)[:limit] if limit else list(doc)
    for page in pages:
        job += page_to_escpos(page)
        job += b"\n" * 2
        job += GS + b"V\x42\x00"                # feed to cutter + partial cut
    doc.close()
    return bytes(job), len(pages)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", help="path or URL to the slips PDF")
    ap.add_argument("--host", default="192.168.100.79")
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--pages", type=int, default=None,
                    help="print only the first N slips")
    ap.add_argument("--cookie", default=None, help="session cookie for a URL")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the job and report its size, print nothing")
    a = ap.parse_args()

    job, n = build(load(a.pdf, a.cookie), a.pages)
    print(f"{n} slip(s), {len(job) / 1024:.0f} KB of ESC/POS")
    if a.dry_run:
        print("dry run — nothing sent")
        return
    try:
        with socket.create_connection((a.host, a.port), timeout=10) as s:
            s.sendall(job)
    except OSError as e:
        sys.exit(f"could not reach {a.host}:{a.port} — {e}")
    print(f"sent to {a.host}:{a.port}")


if __name__ == "__main__":
    main()
