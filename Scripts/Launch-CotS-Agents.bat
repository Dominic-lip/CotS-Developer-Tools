@echo off
setlocal
if /I "%1"=="manual" goto manual_trusted
if /I "%1"=="manual-safe" goto manual_safe
echo You may minimize this window. Closing it stops autonomous development.
start "CotS Autonomous Factory" cmd /k python "%~dp0CotSFactoryBootstrap.py"
exit /b

:manual_trusted
pushd "%~dp0.."
echo.
echo CotS Manual Codex — TRUSTED WORKSPACE
echo Routine approvals disabled.
echo Scope: %CD%
echo.
codex --ask-for-approval never --sandbox danger-full-access --cd "%CD%"
set "launch_exit=%ERRORLEVEL%"
popd
exit /b %launch_exit%

:manual_safe
pushd "%~dp0.."
echo.
echo CotS Manual Codex — SAFE MODE
echo Normal Codex approval behavior is active.
echo Scope: %CD%
echo.
codex --cd "%CD%"
set "launch_exit=%ERRORLEVEL%"
popd
exit /b %launch_exit%
