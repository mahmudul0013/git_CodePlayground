@echo off
rem Removes the login auto-start created by install-autostart.bat (does not stop a running server; use stop-dashboard.bat).
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TradeView-dashboard.bat" 2>nul && echo Auto-start removed. || echo Auto-start was not installed.
pause
