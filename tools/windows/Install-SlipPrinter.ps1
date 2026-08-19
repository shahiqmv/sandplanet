<#
    One-time setup so HR/Finance can print salary slips on the thermal printer.

    Run this ONCE per PC. It does not need administrator rights — everything it
    writes is under the current user.

        Right-click this file -> Run with PowerShell

    What it sets up, and why:
      * asks for the printer's IP and actually tests port 9100, so a wrong
        address is caught here rather than on payroll day;
      * stores the address in one file, so a printer that moves is one edit;
      * associates .escpos files with Print-Slips.ps1, so printing a run is
        "click Print slips in the app, then open the download";
      * offers a test print.

    The printer speaks raw ESC/POS on port 9100 and has no PDF interpreter, so
    Windows' Add Printer cannot drive it usefully — that is deliberate here, not
    an omission. The server renders the slips; this PC only posts the bytes.
#>
[CmdletBinding()]
param(
    [string] $Printer = '192.168.100.79',
    [int]    $Port = 9100
)

$ErrorActionPreference = 'Stop'
$appDir     = Join-Path $env:LOCALAPPDATA 'SandPlanet'
$configPath = Join-Path $appDir 'printer.json'
$senderPath = Join-Path $appDir 'Print-Slips.ps1'
$launchPath = Join-Path $appDir 'print-slips.cmd'
$here       = Split-Path -Parent $MyInvocation.MyCommand.Path

function Say($t, $c = 'Gray')  { Write-Host "  $t" -ForegroundColor $c }
function Head($t) { Write-Host ''; Write-Host "  $t" -ForegroundColor Cyan;
                    Write-Host ('  ' + ('-' * $t.Length)) -ForegroundColor DarkGray }

Head 'Sand Planet — salary slip printer setup'

# ---- 1. the address ---------------------------------------------------------
$answer = Read-Host "  Printer IP address [$Printer]"
if ($answer) { $Printer = $answer.Trim() }
if ($Printer -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
    Say "'$Printer' is not an IP address. Setup stopped." 'Red'
    Read-Host '  Press Enter to close'; exit 1
}

# ---- 2. prove it before trusting it ----------------------------------------
Say ''
Say "Checking $Printer`:$Port ..."
$client = New-Object System.Net.Sockets.TcpClient
$try = $client.BeginConnect($Printer, $Port, $null, $null)
$reached = $try.AsyncWaitHandle.WaitOne(5000, $false)
if ($reached) { try { $client.EndConnect($try) } catch { $reached = $false } }
$client.Close()

if ($reached) {
    Say "Printer answered. Good." 'Green'
} else {
    Say "No answer from $Printer on port $Port." 'Yellow'
    Say 'Common causes: the printer is off, it is on a different WiFi network,'
    Say 'or the address has changed (check the printer''s self-test slip).'
    Say ''
    if ((Read-Host '  Save this address anyway? (y/N)') -notmatch '^[Yy]') {
        Say 'Setup stopped — nothing was changed.' 'Red'
        Read-Host '  Press Enter to close'; exit 1
    }
}

# ---- 3. install ------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
@{ Printer = $Printer; Port = $Port
   Installed = (Get-Date).ToString('s') } |
    ConvertTo-Json | Set-Content -Path $configPath -Encoding UTF8

Copy-Item (Join-Path $here 'Print-Slips.ps1') $senderPath -Force

# A .cmd wrapper, because Windows will not let a .ps1 be a file handler
# directly and double-clicking one opens Notepad.
@"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "$senderPath" %1
"@ | Set-Content -Path $launchPath -Encoding ASCII

# ---- 4. make the download printable by opening it ---------------------------
# Per-user association only (HKCU) — no admin rights, and nothing done to
# anyone else's account on a shared PC.
$cls = 'HKCU:\Software\Classes'
New-Item -Path "$cls\.escpos" -Force | Out-Null
Set-ItemProperty -Path "$cls\.escpos" -Name '(default)' -Value 'SandPlanet.Slips'
New-Item -Path "$cls\SandPlanet.Slips\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path "$cls\SandPlanet.Slips" -Name '(default)' `
                 -Value 'Sand Planet salary slips'
Set-ItemProperty -Path "$cls\SandPlanet.Slips\shell\open\command" `
                 -Name '(default)' -Value "`"$launchPath`" `"%1`""

$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$sc = (New-Object -ComObject WScript.Shell).CreateShortcut(
        (Join-Path $startMenu 'Print salary slips.lnk'))
$sc.TargetPath = $launchPath
$sc.WorkingDirectory = $appDir
$sc.Description = 'Send a downloaded .escpos slip file to the thermal printer'
$sc.Save()

Head 'Done'
Say "Printer   $Printer`:$Port"
Say "Settings  $configPath"
Say ''
Say 'To print a payroll run:' 'White'
Say '  1. Open the payroll run in Sand Planet'
Say '  2. Click "Print slips (thermal)" — a .escpos file downloads'
Say '  3. Open the downloaded file. The slips print and cut.'
Say ''

# ---- 5. offer to prove the whole path --------------------------------------
if ($reached -and (Read-Host '  Send a test print now? (Y/n)') -notmatch '^[Nn]') {
    $esc = [char]27; $gs = [char]29
    $t  = "$esc@"
    $t += "$esc" + 'a' + [char]1 + "$esc" + 'E' + [char]1 + "SAND PLANET`n"
    $t += "$esc" + 'E' + [char]0 + "slip printer ready`n"
    $t += "$esc" + 'a' + [char]0 + ('-' * 42) + "`n"
    $t += "This PC can print salary slips.`n"
    $t += (Get-Date).ToString('dd MMM yyyy HH:mm') + "`n`n`n"
    $t += "$gs" + 'V' + [char]66 + [char]0
    $tmp = Join-Path $env:TEMP 'sp-test.escpos'
    [System.IO.File]::WriteAllBytes($tmp,
        [System.Text.Encoding]::ASCII.GetBytes($t))
    & powershell -NoProfile -ExecutionPolicy Bypass -File $senderPath $tmp -Quiet
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    Say 'Test sent — check the printer.' 'Green'
}

Write-Host ''
Read-Host '  Press Enter to close'
