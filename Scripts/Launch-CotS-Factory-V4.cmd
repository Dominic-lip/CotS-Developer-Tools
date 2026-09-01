@echo off
setlocal
cd /d "%~dp0.."
python "%~dp0CotSFactoryBootstrapV4.py"
exit /b %ERRORLEVEL%
