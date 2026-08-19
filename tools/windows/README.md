# Printing salary slips — HR / Finance (Windows)

## Set up (once per PC)

Copy these **two files** to the Desktop, keeping them together:

- `Print salary slips.cmd`
- `Print-Slips.ps1`

That is the whole setup. The first time you use it, it asks for the printer's IP
address (press Enter to accept `192.168.100.79`) and remembers it.

> If Windows shows a blue "Windows protected your PC" box, click **More info**
> then **Run anyway**. That appears because the file came from another PC.

There is an `Install-SlipPrinter.ps1` as well, which adds a Desktop shortcut and
a Start Menu entry. It is **optional** — everything works without it, and if
Windows blocks it from running, ignore it and use the two files above.

## Print a payroll run

1. Open the payroll run in Sand Planet.
2. Click **Print slips (thermal)**. It says how many slips downloaded.
   **Do not try to open that file** — it is printer code, not a document, and
   Windows has nothing to open it with. That is normal.
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
| Windows asks which app to open the .escpos file with | You double-clicked the download. You never need to open it — use **Print salary slips** instead. |
| Nothing on the Desktop after running the installer | Windows blocked it. Use the two files at the top of this page; the installer is optional. |
| A window flashes and vanishes | Double-click `Print salary slips.cmd`, not the `.ps1`. The `.cmd` keeps the window open. |
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
