@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-ToolLab.ps1" %*
exit /b %ERRORLEVEL%
