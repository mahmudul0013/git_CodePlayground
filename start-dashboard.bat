@echo off
rem Starts the TradeView dashboard server without VS Code and restarts it if it ever stops.
rem Double-click this file, or let install-autostart.bat run it at every Windows login.
rem Multi-user: each person signs in and uploads their own two Nordnet CSVs in the browser (kept under data\profiles).
rem First start: the window prints a one-time setup code; open /login.html and create the admin account with it.
rem Leave the window open (minimised is fine). Close it, or run stop-dashboard.bat, to stop the server.
title TradeView dashboard server
cd /d "%~dp0"

set "PY=python"
where python >nul 2>nul || set "PY=py -3"
%PY% --version >nul 2>nul || (
  echo Python was not found. Install Python 3 from python.org and tick "Add python.exe to PATH", then run this again.
  pause
  exit /b 1
)

:loop
echo [%date% %time%] starting server.py  ^(http://localhost:8000^)
%PY% server.py
echo [%date% %time%] server stopped, restarting in 5 seconds... ^(close this window to stop^)
timeout /t 5 /nobreak >nul
goto loop
