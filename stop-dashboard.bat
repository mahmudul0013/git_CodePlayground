@echo off
rem Stops the dashboard server started by start-dashboard.bat (and its restart loop).
rem Only touches this project's processes; other Python programs keep running.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$me=$PID; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $me -and $_.CommandLine -match 'start-dashboard\.bat|server\.py' -and $_.Name -match '^(cmd|python|pythonw|py)\.exe$' } | ForEach-Object { 'stopping ' + $_.Name + ' ' + $_.ProcessId; Stop-Process -Id $_.ProcessId -Force }"
echo Done.
