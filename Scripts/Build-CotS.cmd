@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-CotS.ps1" %*
exit /b %ERRORLEVEL%
