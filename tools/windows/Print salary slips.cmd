@echo off
rem ---------------------------------------------------------------------------
rem  Sand Planet — print salary slips
rem
rem  Put this file and Print-Slips.ps1 together anywhere (the Desktop is fine)
rem  and double-click THIS one.
rem
rem  A .cmd is used rather than the .ps1 directly because Windows blocks
rem  PowerShell scripts that came from another PC, and does it by closing the
rem  window before anyone can read why — which is exactly what happened when
rem  the installer appeared to do nothing (owner 2026-08-19). Launching with
rem  -ExecutionPolicy Bypass from here sidesteps that, and needs no admin.
rem ---------------------------------------------------------------------------
title Sand Planet - print salary slips
set "HERE=%~dp0"

if not exist "%HERE%Print-Slips.ps1" (
  echo.
  echo   Print-Slips.ps1 is missing.
  echo   It must sit in the same folder as this file:
  echo   %HERE%
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%Print-Slips.ps1" %*

rem Keep the window if PowerShell itself failed, so the reason is readable.
if errorlevel 1 pause
