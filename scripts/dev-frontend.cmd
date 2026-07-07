@echo off
rem Dev launcher: ensures Node is on PATH (fresh installs) and starts Vite.
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "%~dp0..\frontend"
npm run dev
