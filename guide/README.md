# Planet User Guide — screenshot pipeline

Everything needed to (re)build **`Planet_User_Guide_R2.pdf`** (doc ref
`PLANET-UG-01`) with real, filled-in screenshots.

## One command

```bash
bash regenerate.sh
```

Rebuilds the demo database, starts the demo server, captures every screen,
renders the letterhead PDFs, and assembles the guide PDF. Run it again any
time the UI changes.

## Isolation — the live server is never touched

The whole pipeline runs against a throwaway instance
(`--settings=config.settings_demo`):

| | Live team-review server | Guide demo instance |
|---|---|---|
| Database | `backend/db.sqlite3` | `backend/db.demo.sqlite3` |
| Media | `backend/media/` | `backend/media-demo/` |
| Port | `8000` (cloudflared tunnel) | `8001` |

`seed_demo` refuses to run against the live DB, and `regen_demo.sh` only ever
deletes the `db.demo.sqlite3` file.

## The pieces

| File | What it does |
|---|---|
| `../backend/config/settings_demo.py` | Isolated DB + media settings |
| `../backend/core/management/commands/seed_demo.py` | Seeds the worked MVR dataset via the real API |
| `../backend/regen_demo.sh` | Drop demo DB → migrate → `seed` → `seed_demo` |
| `../backend/core/management/commands/render_pdfs.py` | Renders the generated letterhead PDFs to PNG |
| `capture.mjs` | Playwright — logs in per role, screenshots every screen |
| `Planet_User_Guide.html` | The guide source (edit prose/layout here) |
| `build_guide.py` | Renders the HTML to `Planet_User_Guide_R2.pdf` (WeasyPrint) |
| `screenshots/` | Output PNGs (`NN-name.png` UI, `pdf-*.png` letterhead) |

## Demo logins

All demo users share the password **`planet-demo`**:
`eng`, `storekeeper`, `pm`, `purchasing`, `director`, `signatory`,
`finance`, `hr`, `admin`.

## Editing the guide

Edit the prose/layout in `Planet_User_Guide.html`, then just
`python build_guide.py` (no re-capture needed). To re-shoot after a UI
change, run the full `regenerate.sh`.

## Not covered (later phase)

International procurement — **PMR, IPR, IRN, SIN** — is described in the guide
but not yet built, so it has no screenshots. Once those screens ship, add them
to `capture.mjs` and the relevant section.
