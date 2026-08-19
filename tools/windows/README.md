# Adding the salary-slip printer (Windows)

The thermal printer is added to Windows like any other network printer. Once
that is done, printing slips is Ctrl-P — there is nothing to install from here.

## Add the printer (once per PC)

1. **Install the printer's own Windows driver.** It is on the CD/USB that came
   with it, or on the maker's site — the model is on the label underneath
   (these are usually sold as *XPrinter*, *POS-80*, *Gprinter* or similar).
   Install this first; Windows' built-in drivers cannot render to it.

2. **Settings → Bluetooth & devices → Printers & scanners → Add device**
   → *The printer that I want isn't listed*
   → **Add a printer using a TCP/IP address or hostname**

3. Fill in:

   | | |
   |---|---|
   | Device type | **TCP/IP Device** |
   | Hostname or IP address | **192.168.100.79** |
   | Port name | anything, e.g. `Slip printer` |
   | Query the printer… | **untick** |

4. When asked for the driver, choose the one you installed in step 1.

5. Finish, then **Printer properties → Print Test Page**. If a slip comes out,
   you are done.

## Print a payroll run

1. Open the payroll run in Sand Planet.
2. Click **Print slips** — the slips open as a PDF, one worker per page.
3. Ctrl-P, choose the thermal printer, and set:
   - **Paper size:** the 80mm roll size (often listed as `80 x 297mm` or
     `72.1 x 297mm`)
   - **Scale / Page sizing:** **Actual size** — *not* "Fit to page"
4. Print. Each worker is a separate page, so the cutter separates them.

The pages are already 72mm wide and trimmed to each slip's own length, so at
Actual size they come out right with no blank paper between slips.

To reprint one worker, click the 🖨️ on their row.

## If it does not print

| What you see | What it means |
|---|---|
| Test page fails | Wrong IP, printer off, or on a different WiFi. Ping `192.168.100.79` from a Command Prompt. |
| Prints tiny, or with wide margins | Scale is on "Fit to page". Set **Actual size**. |
| Pages of garbage characters | You picked a text-only driver. Install the maker's driver and change the printer's driver to it. |
| Prints but never cuts | Turn on auto-cut in the driver's preferences (often *Device Settings → Cutter → Cut after each page*). |
| Nothing at all, no error | The printer may be in STAR emulation. Open `http://192.168.100.79/`, set it to ESC/POS, and power-cycle the printer. |

**The printer's address changed?** Printer properties → Ports → Configure Port
→ enter the new IP. A static/reserved address on the router avoids this.
