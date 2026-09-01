@echo off
setlocal
cd /d "%~dp0.."

where pythonw.exe >nul 2>nul
if errorlevel 1 (
  set "PYW=python"
) else (
  set "PYW=pythonw.exe"
)

echo Starting CotS production 24x7 watchdog...
start "" /b %PYW% "%~dp0CotSWatchdog24x7Final.py"

echo Opening CotS enhanced 24x7 Control Center...
python "%~dp0CotSControlCenter24x7Final.py"
exit /b %ERRORLEVEL%
