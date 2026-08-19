<#
    Print salary slips on the thermal printer.

    Normally you just double-click the "Print salary slips" icon on the Desktop.
    With no argument this finds the newest slip file you downloaded and prints
    it, so there is nothing to locate and nothing to "open with".

        Print-Slips.ps1                       newest download, print it
        Print-Slips.ps1 slips-BVR-2026-07.escpos
        Print-Slips.ps1 -Printer 192.168.100.79 slips.escpos

    The .escpos file is the printer's own language, rendered by the server with
    the cut already in it. This opens a socket and posts the bytes — no driver,
    no PDF reader, nothing to install.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)] [string] $Path,
    [string] $Printer,
    [int]    $Port = 9100,
    [switch] $Quiet
)

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
    if (-not $Printer) {
        Fail 'No printer is set up on this PC.' `
             'Run Install-SlipPrinter.ps1 once, then try again.'
    }
}

# ---- which file ------------------------------------------------------------
# No argument = find it ourselves. Asking HR to hunt for a download and pick an
# app to open it with was the wrong idea (owner 2026-08-19).
if (-not $Path) {
    $folders = @(
        (Join-Path $env:USERPROFILE 'Downloads'),
        [Environment]::GetFolderPath('Desktop'),
        (Join-Path $env:USERPROFILE 'OneDrive\Downloads')
    ) | Where-Object { Test-Path $_ }

    $found = Get-ChildItem -Path $folders -Filter '*.escpos' -File `
                           -ErrorAction SilentlyContinue |
             Sort-Object LastWriteTime -Descending

    if (-not $found) {
        Fail 'No slip file found in Downloads or on the Desktop.' `
             ("In Sand Planet, open the payroll run and click " +
              "'Print slips (thermal)'. Then run this again.")
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
