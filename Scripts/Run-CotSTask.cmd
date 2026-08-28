@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-CotSTask.ps1" %*
exit /b %ERRORLEVEL%
