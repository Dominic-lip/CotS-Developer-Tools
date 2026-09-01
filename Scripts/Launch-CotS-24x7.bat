@echo off
setlocal
cd /d "%~dp0.."

where pythonw.exe >nul 2>nul
if errorlevel 1 (
  set "PYW=python"
) else (
  set "PYW=pythonw.exe"
)

echo Starting CotS 24x7 watchdog...
start "" /b %PYW% "%~dp0CotSWatchdog24x7.py"

echo Opening CotS 24x7 Control Center...
python "%~dp0CotSControlCenter24x7.py"
exit /b %ERRORLEVEL%
