@echo off
setlocal
pushd "%~dp0.."

rem Start the campaign watchdog first. If another watchdog owns the lock this
rem process exits harmlessly and the existing Control Center can show that fact.
start "CotS Campaign Watchdog" /min python "%~dp0CotSWatchdogCampaign.py"

rem Give the localhost telemetry listener a brief chance to bind before the UI
rem opens, so the UI attaches to the campaign watchdog instead of invoking its
rem fallback production watchdog.
timeout /t 2 /nobreak >nul
python "%~dp0CotSControlCenter24x7Final.py"
set "exit_code=%ERRORLEVEL%"
popd
exit /b %exit_code%
