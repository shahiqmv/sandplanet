# Printing salary slips — setup for HR / Finance (Windows)

One-time setup, then printing a payroll run is two clicks.

## Set up (once per PC)

1. Copy this whole `windows` folder to the PC (Desktop is fine).
2. Right-click **`Install-SlipPrinter.ps1`** → **Run with PowerShell**.
3. It asks for the printer's IP address. Press Enter to accept
   `192.168.100.79`, or type the current one.
4. It checks the printer answers, sets everything up, and offers a test print.
   Say yes — if the test slip comes out, you are done.

No administrator rights needed. Nothing is changed for other users of the PC.

## Print a payroll run

1. Open the payroll run in Sand Planet.
2. Click **Print slips (thermal)** — a `.escpos` file downloads.
3. Open the downloaded file (click it in the browser's downloads bar).

The slips print, one per worker, cut between each.

**Slips preview** next to it gives the same slips as a PDF — for checking on
screen or keeping on file. Don't try to print the PDF on the thermal printer; it
will come out as pages of rubbish. The printer only understands the `.escpos`
file.

To reprint one worker, click the 🖨️ on their row.

## If it does not print

| What you see | What it means |
|---|---|
| "The printer did not answer" | Printer off, or on a different WiFi. Check it, then retry. |
| "Does not look like a slip file" | You opened the PDF instead of the `.escpos` file. |
| The download opens in Notepad | Setup did not finish — run `Install-SlipPrinter.ps1` again. |
| Nothing at all, no message | The printer may be in STAR mode. Open `http://<printer-ip>/` in a browser, set emulation to ESC/POS, and power the printer off and on. |

**The printer's address changed?** Run `Install-SlipPrinter.ps1` again and enter
the new one. Nothing else needs touching.

## For whoever maintains this

The printer speaks raw ESC/POS on port 9100 and has no PDF interpreter, so
Windows' *Add Printer* cannot usefully drive it — that is why setup works this
way instead. The **server** renders the slips (it has PyMuPDF and Pillow
already), and the PC only opens a socket and posts the bytes, so these PCs need
nothing installed.

- `Install-SlipPrinter.ps1` — writes `%LOCALAPPDATA%\SandPlanet\printer.json`,
  copies the sender there, associates `.escpos` (HKCU only), adds a Start Menu
  entry.
- `Print-Slips.ps1` — the sender. Reads the IP from `printer.json` unless
  `-Printer` is given. Refuses a file that does not begin `ESC @`, so a PDF
  cannot be sent by mistake.
- Endpoints: `GET /api/v1/payroll/runs/<id>/slips.escpos` and
  `GET /api/v1/payroll/lines/<id>/slip.escpos`.
