@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Bootstrap-ToolLab.ps1" %*
exit /b %ERRORLEVEL%
