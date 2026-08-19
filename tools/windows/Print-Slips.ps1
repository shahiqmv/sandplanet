<#
    Send a .escpos slip file to the thermal printer.

    The app hands you a .escpos file — that is the printer's own language, with
    the cut already in it, rendered on the server. This just opens a socket and
    posts the bytes: no driver, no PDF reader, nothing to install.

    Normally you never run this by hand. Install-SlipPrinter.ps1 associates
    .escpos files with it, so double-clicking the download prints it.

        .\Print-Slips.ps1 slips-BVR-2026-07.escpos
        .\Print-Slips.ps1 slips.escpos -Printer 192.168.100.79
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)] [string] $Path,
    [string] $Printer,
    [int]    $Port = 9100,
    [switch] $Quiet
)

$ErrorActionPreference = 'Stop'
$configPath = Join-Path $env:LOCALAPPDATA 'SandPlanet\printer.json'

function Fail($msg) {
    Write-Host ''
    Write-Host "  $msg" -ForegroundColor Red
    Write-Host ''
    if (-not $Quiet) { Read-Host '  Press Enter to close' }
    exit 1
}

# The IP lives in one place, written by the installer, so a printer that moves
# is a one-line fix and not a hunt through scripts.
if (-not $Printer) {
    if (Test-Path $configPath) {
        $Printer = (Get-Content $configPath -Raw | ConvertFrom-Json).Printer
    }
    if (-not $Printer) {
        Fail "No printer configured. Run Install-SlipPrinter.ps1 first, or pass -Printer <ip>."
    }
}

if (-not (Test-Path -LiteralPath $Path)) { Fail "Cannot find the file: $Path" }
$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Path))
if ($bytes.Length -eq 0) { Fail 'That file is empty.' }
# ESC @ — every job the server builds starts by initialising the printer. If
# this is missing, it is not a slip file (a PDF would print pages of rubbish).
if (-not ($bytes[0] -eq 0x1B -and $bytes[1] -eq 0x40)) {
    Fail "That does not look like a slip file. Download 'Print slips' from the payroll run, not the PDF."
}

$slips = 0
for ($i = 0; $i -lt $bytes.Length - 2; $i++) {
    if ($bytes[$i] -eq 0x1D -and $bytes[$i+1] -eq 0x56) { $slips++ }   # GS V = cut
}

if (-not $Quiet) {
    Write-Host ''
    Write-Host "  Sand Planet — salary slips" -ForegroundColor Cyan
    Write-Host "  $slips slip(s) to $Printer`:$Port"
    Write-Host ''
}

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $ok = $client.BeginConnect($Printer, $Port, $null, $null)
    if (-not $ok.AsyncWaitHandle.WaitOne(5000, $false)) {
        $client.Close()
        Fail "The printer at $Printer did not answer. Is it switched on and on the same network?"
    }
    $client.EndConnect($ok)
    $stream = $client.GetStream()
    # Write in chunks so a big run reports progress instead of appearing to hang.
    $chunk = 8192
    for ($off = 0; $off -lt $bytes.Length; $off += $chunk) {
        $n = [Math]::Min($chunk, $bytes.Length - $off)
        $stream.Write($bytes, $off, $n)
        if (-not $Quiet -and $bytes.Length -gt 200000) {
            $pct = [int](100 * ($off + $n) / $bytes.Length)
            Write-Progress -Activity 'Printing salary slips' -Status "$pct%" -PercentComplete $pct
        }
    }
    $stream.Flush()
    Start-Sleep -Milliseconds 400      # let the printer drain before we hang up
    $stream.Close(); $client.Close()
} catch {
    Fail "Could not print: $($_.Exception.Message)"
}

if (-not $Quiet) {
    Write-Progress -Activity 'Printing salary slips' -Completed
    Write-Host "  Sent. $slips slip(s) printing." -ForegroundColor Green
    Write-Host ''
    Start-Sleep -Seconds 2
}
