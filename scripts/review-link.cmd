@echo off
REM Team review link — serves the built app on :8000 and opens a public
REM Cloudflare quick tunnel. NOTE: the https://....trycloudflare.com URL
REM changes on every launch; watch the "sp-tunnel" window and share the
REM new link. Stop by closing both windows. Production deploy (M6) will
REM replace this with a permanent address.
cd /d "%~dp0..\backend"
start "sp-backend" .venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
start "sp-tunnel" "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8000
echo Backend and tunnel starting - the public link appears in the sp-tunnel window.
pause
