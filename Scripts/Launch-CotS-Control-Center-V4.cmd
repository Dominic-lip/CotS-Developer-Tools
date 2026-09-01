@echo off
setlocal
cd /d "%~dp0.."
python "%~dp0CotSControlCenter.py"
exit /b %ERRORLEVEL%
