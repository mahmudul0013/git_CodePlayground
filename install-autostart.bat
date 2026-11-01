@echo off
rem Makes the dashboard start by itself (minimised) every time you log in to Windows. No admin rights needed.
rem Undo with uninstall-autostart.bat.
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
> "%STARTUP%\TradeView-dashboard.bat" (
  echo @echo off
  echo start "" /min cmd /c "%~dp0start-dashboard.bat"
)
echo Installed: %STARTUP%\TradeView-dashboard.bat
echo The server will now start minimised at every login. Start it right now with start-dashboard.bat.
pause
