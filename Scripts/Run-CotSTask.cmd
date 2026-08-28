@echo off
setlocal
if "%~1"=="" (
    echo Usage:
    echo   Run-CotSTask.cmd -Agent codex -Task Tasks\NNN_TASK.md
    echo   Run-CotSTask.cmd -Agent claude -Task Tasks\NNN_TASK.md
    echo.
    echo Example:
    echo   Run-CotSTask.cmd -Agent codex -Task Tasks\000_TOOLCHAIN_FOUNDATION.md
    exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-CotSTask.ps1" %*
exit /b %ERRORLEVEL%
