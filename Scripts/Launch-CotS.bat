@echo off
setlocal
pushd "%~dp0.."

rem Canonical CotS operator entry point. The watchdog owns the runtime; closing
rem the Control Center only closes the UI.
start "CotS Development Campaign Watchdog" /min python "%~dp0CotSWatchdogCampaign.py"
timeout /t 2 /nobreak >nul
python "%~dp0CotSControlCenter.py"
set "exit_code=%ERRORLEVEL%"
popd
exit /b %exit_code%
