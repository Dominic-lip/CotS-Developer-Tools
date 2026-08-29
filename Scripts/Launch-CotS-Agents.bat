@echo off
if /I "%1"=="manual" ( codex & exit /b )
start "CotS Autonomous Codex" /min python "%~dp0CotSAgentSupervisor.py"
