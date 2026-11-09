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

# ---- split into slips ------------------------------------------------------
# Every slip ends with GS V B 0 — feed to the cutter and cut. The job used
# to go down the wire in one piece, and with 44 raster slips (about 4 MB)
# the printer dropped the connection part-way (Finance, BVR October,
# 2026-11-08). So the slips go one at a time with a breath between, the
# printer is reconnected and the job carried on from the slip that failed,
# and a run that still fails can be resumed from where it stopped instead of
# printing everyone's slip twice.
$ends = New-Object System.Collections.Generic.List[int]
$pos = 0
while (($pos = [Array]::IndexOf($bytes, [byte]0x1D, $pos)) -ge 0) {
    if ($pos + 3 -lt $bytes.Length -and $bytes[$pos+1] -eq 0x56 -and
        $bytes[$pos+2] -eq 0x42 -and $bytes[$pos+3] -eq 0x00) {
        $ends.Add($pos + 4); $pos += 4
    } else { $pos++ }
}
if ($ends.Count -eq 0 -or $ends[$ends.Count - 1] -ne $bytes.Length) {
    $ends.Add($bytes.Length)
}
$slips = $ends.Count
Say ''
Say "$slips slip(s) -> $Printer" 'White'

# ---- carry on from last time? ---------------------------------------------
$resumePath = Join-Path (Split-Path $configPath) 'resume.json'
$sent = 0
if (Test-Path $resumePath) {
    try {
        $r = Get-Content $resumePath -Raw | ConvertFrom-Json
        if ($r.File -eq (Split-Path $Path -Leaf) -and $r.Size -eq $bytes.Length -and
            $r.Sent -gt 0 -and $r.Sent -lt $slips) {
            Say ''
            Say "Last time $($r.Sent) of $slips slips of this file went through before the printer stopped." 'Yellow'
            $ans = (Read-Host "  Carry on from slip $($r.Sent + 1)? [Y/n]").Trim()
            if ($ans -eq '' -or $ans -match '^[Yy]') { $sent = [int]$r.Sent }
        }
    } catch { }
    Remove-Item $resumePath -ErrorAction SilentlyContinue
}
Say ''

# ---- print -----------------------------------------------------------------
function Connect-Printer {
    $c = New-Object System.Net.Sockets.TcpClient
    $c.SendTimeout = 30000
    $a = $c.BeginConnect($Printer, $Port, $null, $null)
    if (-not $a.AsyncWaitHandle.WaitOne(5000, $false)) { $c.Close(); return $null }
    $c.EndConnect($a)
    return $c
}
function Save-Progress($n) {
    @{ File = (Split-Path $Path -Leaf); Size = $bytes.Length; Sent = $n } |
        ConvertTo-Json | Set-Content -Path $resumePath -Encoding UTF8
}

$client = Connect-Printer
if (-not $client) {
    Fail "The printer at $Printer did not answer." `
         'Check it is switched on, has paper, and is on the office WiFi.'
}
$stream = $client.GetStream()
$chunk = 8192
$tries = 0
$doubtful = @()
$init = [byte[]](0x1B, 0x40)             # ESC @ — initialise, after a reconnect
while ($sent -lt $slips) {
    $from = if ($sent -eq 0) { 0 } else { $ends[$sent - 1] }
    $to = $ends[$sent]
    try {
        if ($tries -gt 0) { $stream.Write($init, 0, 2) }
        for ($off = $from; $off -lt $to; $off += $chunk) {
            $n = [Math]::Min($chunk, $to - $off)
            $stream.Write($bytes, $off, $n)
        }
        $stream.Flush()
        if ($tries -gt 0) { $doubtful += ($sent + 1) }
        $sent++; $tries = 0
        Save-Progress $sent
        Write-Progress -Activity 'Printing salary slips' `
                       -Status "slip $sent of $slips" `
                       -PercentComplete ([int](100 * $sent / $slips))
        # A breath between slips: the printer's buffer is small and its head
        # runs hot on raster. Nothing is lost by waiting.
        Start-Sleep -Milliseconds 400
    } catch {
        $tries++
        try { $stream.Close(); $client.Close() } catch { }
        Write-Progress -Activity 'Printing salary slips' -Completed
        Say "The printer dropped the connection at slip $($sent + 1) of ${slips}: $($_.Exception.Message)" 'Yellow'
        if ($tries -gt 5) {
            Fail "Could not print. $sent of $slips slip(s) went through." `
                 ("Check the printer has paper and its cover is shut, then run this " +
                  "again — it will offer to carry on from slip $($sent + 1).")
        }
        while ($true) {
            Say "Check it has paper and the cover is shut. Trying again in 10 seconds ($tries of 5)..." 'Yellow'
            Start-Sleep -Seconds 10
            $client = Connect-Printer
            if ($client) { break }
            $tries++
            if ($tries -gt 5) {
                Fail "The printer at $Printer did not answer. $sent of $slips slip(s) went through." `
                     ("Check it is switched on and has paper, then run this again — " +
                      "it will offer to carry on from slip $($sent + 1).")
            }
        }
        $stream = $client.GetStream()
    }
}
try {
    Start-Sleep -Milliseconds 500      # let the printer drain before hanging up
    $stream.Close(); $client.Close()
} catch { }
Write-Progress -Activity 'Printing salary slips' -Completed
Remove-Item $resumePath -ErrorAction SilentlyContinue

Say "Sent. $slips slip(s) printing." 'Green'
if ($doubtful.Count -gt 0) {
    Say ("Slip " + ($doubtful -join ', ') + " went out again after the printer stopped — " +
         "if a part-printed copy came out first, discard it.") 'Yellow'
}
if (-not $Quiet) { Start-Sleep -Seconds 3 }
