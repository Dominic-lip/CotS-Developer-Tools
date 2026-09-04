@echo off
echo Legacy launcher: redirecting to Launch-CotS.bat
call "%~dp0Launch-CotS.bat" %*
exit /b %ERRORLEVEL%
