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
2. Click **Print slips (thermal)** — a file downloads. **Ignore it.**
3. Double-click **Print salary slips** on the Desktop.

The slips print, one per worker, cut between each.

You do not need to find or open the downloaded file, and you should not be
asked to choose an app to open it with. The Desktop icon finds the newest slip
file on its own — in Downloads, on the Desktop, or in OneDrive Downloads.

If you have downloaded several and want an **older** one, drag that file onto
the Desktop icon instead.

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
| "No slip file found" | Click **Print slips (thermal)** in Sand Planet first. |
| Windows asks which app to open the file with | You double-clicked the download. Use the **Print salary slips** Desktop icon instead — you never need to open that file. |
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
- `Print-Slips.ps1` — the sender. **With no argument it finds the newest
  `.escpos` in Downloads / Desktop / OneDrive Downloads**, which is what the
  Desktop shortcut relies on: the first version of this depended on a Windows
  file association, which Windows frequently ignores, and HR was left facing an
  "open with" dialog. Reads the IP from `printer.json` unless `-Printer` is
  given. Refuses any file that does not begin `ESC @`, so the PDF cannot be sent
  by mistake.
- Endpoints: `GET /api/v1/payroll/runs/<id>/slips.escpos` and
  `GET /api/v1/payroll/lines/<id>/slip.escpos`.
