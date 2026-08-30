@echo off
if /I "%1"=="manual" ( codex & exit /b )
echo You may minimize this window. Closing it stops autonomous development.
start "CotS Autonomous Factory" cmd /k python "%~dp0CotSFactoryController.py"
