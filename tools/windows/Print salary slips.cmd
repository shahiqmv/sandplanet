@echo off
rem ===========================================================================
rem  Sand Planet - PRINT SALARY SLIPS
rem
rem  ONE file. Put it wherever you like - the Desktop is fine - and
rem  double-click it. Nothing to install, nothing to keep it next to.
rem
rem  (It is one file because two that had to stay together did not survive
rem  contact with reality: the .cmd was copied to the Desktop on its own and
rem  could not find its script - owner 2026-08-19. The PowerShell that does
rem  the work is at the bottom of this file; the line below feeds it to
rem  PowerShell, which also sidesteps the script-blocking that stops a .ps1
rem  running when it came from another PC.)
rem ===========================================================================
title Sand Planet - print salary slips
set "SLIPFILE=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText('%~f0');$i=$t.IndexOf([char]35+':POWERSHELL');Invoke-Expression $t.Substring($i+12)"
if errorlevel 1 pause
exit /b
#:POWERSHELL
# --- everything below here is PowerShell, run by the line above -------------
$Path    = $env:SLIPFILE
$Printer = $null
$Port    = 9100
$Quiet   = $false
$ErrorActionPreference = 'Stop'
$configPath = Join-Path $env:LOCALAPPDATA 'SandPlanet\printer.json'

function Say($t, $c = 'Gray') { Write-Host "  $t" -ForegroundColor $c }
function Done($code) {
    Write-Host ''
    if (-not $Quiet) { Read-Host '  Press Enter to close' }
    exit $code
}
function Fail($msg, $hint) {
    Write-Host ''
    Say $msg 'Red'
    if ($hint) { Say $hint 'Yellow' }
    Done 1
}

Write-Host ''
Write-Host '  Sand Planet — print salary slips' -ForegroundColor Cyan
Write-Host '  --------------------------------' -ForegroundColor DarkGray

# ---- which printer ---------------------------------------------------------
if (-not $Printer) {
    if (Test-Path $configPath) {
        $Printer = (Get-Content $configPath -Raw | ConvertFrom-Json).Printer
    }
}
# Ask once and remember, rather than sending people to an installer that may
# never have run — the installer is now a convenience, not a prerequisite
# (owner 2026-08-19).
if (-not $Printer) {
    Write-Host ''
    Say 'First time on this PC — which printer?' 'White'
    $Printer = (Read-Host '  Printer IP address [192.168.100.79]').Trim()
    if (-not $Printer) { $Printer = '192.168.100.79' }
    if ($Printer -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
        Fail "'$Printer' is not an IP address." `
             'It looks like 192.168.100.79 — check the printer''s self-test slip.'
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $configPath) | Out-Null
    @{ Printer = $Printer; Port = $Port } | ConvertTo-Json |
        Set-Content -Path $configPath -Encoding UTF8
    Say "Saved. This PC will use $Printer from now on." 'Green'
}

# ---- which file ------------------------------------------------------------
# No argument = find it ourselves. Asking HR to hunt for a download and pick an
# app to open it with was the wrong idea (owner 2026-08-19).
if (-not $Path) {
    # Ask Windows where Downloads actually IS. On a work PC it is often
    # redirected into OneDrive under a company-specific name, so guessing
    # "%USERPROFILE%\Downloads" finds nothing (owner 2026-08-19).
    $dl = $null
    try {
        $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
        $guid = '{374DE290-123F-4565-9164-39C4925E467B}'      # Downloads
        $raw = (Get-ItemProperty $key -Name $guid -ErrorAction Stop).$guid
        $dl = [Environment]::ExpandEnvironmentVariables($raw)
    } catch { }

    $folders = @(
        $dl,
        (Join-Path $env:USERPROFILE 'Downloads'),
        [Environment]::GetFolderPath('Desktop'),
        $PSScriptRoot                                  # beside this script
    )
    # …and any OneDrive Downloads, whatever the company called the folder.
    Get-ChildItem $env:USERPROFILE -Directory -Filter 'OneDrive*' `
                  -ErrorAction SilentlyContinue | ForEach-Object {
        $folders += (Join-Path $_.FullName 'Downloads')
        $folders += (Join-Path $_.FullName 'Desktop')
    }
    $folders = $folders | Where-Object { $_ -and (Test-Path $_) } |
               Select-Object -Unique

    $found = Get-ChildItem -Path $folders -Filter '*.escpos' -File `
                           -ErrorAction SilentlyContinue |
             Sort-Object LastWriteTime -Descending

    if (-not $found) {
        Say ''
        Say 'Looked in:' 'Yellow'
        $folders | ForEach-Object { Say "  $_" 'DarkGray' }
        Fail 'No slip file (.escpos) found.' `
             ("In Sand Planet open the payroll run, click 'Print slips', " +
              "then run this again. Leave the file in Downloads — there is " +
              "no need to move it.")
    }

    $Path = $found[0].FullName
    $age = [int]((Get-Date) - $found[0].LastWriteTime).TotalMinutes
    Say ''
    Say "File   $($found[0].Name)" 'White'
    Say ("       downloaded " + $(if ($age -lt 1) { 'just now' }
                                 elseif ($age -lt 60) { "$age minute(s) ago" }
                                 else { $found[0].LastWriteTime.ToString('dd MMM HH:mm') }))
    # More than one lying about is how you print last month's slips by mistake.
    if ($found.Count -gt 1) {
        Say ''
        Say "$($found.Count) slip files here — this is the newest." 'Yellow'
        Say 'To print an older one, drag it onto this icon instead.' 'Yellow'
    }
}

if (-not (Test-Path -LiteralPath $Path)) { Fail "Cannot find the file: $Path" }
$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Path))
if ($bytes.Length -lt 8) { Fail 'That file is empty.' }
# ESC @ — every job the server builds starts by initialising the printer.
if (-not ($bytes[0] -eq 0x1B -and $bytes[1] -eq 0x40)) {
    Fail 'That is not a slip file.' `
         ("Use the 'Print slips (thermal)' button in Sand Planet — not " +
          "'Slips preview', which gives a PDF for reading on screen.")
}

$slips = 0
for ($i = 0; $i -lt $bytes.Length - 2; $i++) {
    if ($bytes[$i] -eq 0x1D -and $bytes[$i+1] -eq 0x56) { $slips++ }   # GS V = cut
}
Say ''
Say "$slips slip(s) -> $Printer" 'White'
Say ''

# ---- print -----------------------------------------------------------------
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $conn = $client.BeginConnect($Printer, $Port, $null, $null)
    if (-not $conn.AsyncWaitHandle.WaitOne(5000, $false)) {
        $client.Close()
        Fail "The printer at $Printer did not answer." `
             'Check it is switched on, has paper, and is on the office WiFi.'
    }
    $client.EndConnect($conn)
    $stream = $client.GetStream()
    $chunk = 8192
    for ($off = 0; $off -lt $bytes.Length; $off += $chunk) {
        $n = [Math]::Min($chunk, $bytes.Length - $off)
        $stream.Write($bytes, $off, $n)
        if ($bytes.Length -gt 200000) {
            $pct = [int](100 * ($off + $n) / $bytes.Length)
            Write-Progress -Activity 'Printing salary slips' `
                           -Status "$pct%" -PercentComplete $pct
        }
    }
    $stream.Flush()
    Start-Sleep -Milliseconds 500      # let the printer drain before hanging up
    $stream.Close(); $client.Close()
    Write-Progress -Activity 'Printing salary slips' -Completed
} catch {
    Fail "Could not print: $($_.Exception.Message)" `
         'If it keeps failing, check the printer IP has not changed.'
}

Say "Sent. $slips slip(s) printing." 'Green'
if (-not $Quiet) { Start-Sleep -Seconds 3 }
