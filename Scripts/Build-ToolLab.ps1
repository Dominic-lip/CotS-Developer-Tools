[CmdletBinding()]
param(
    [string]$EngineRoot = 'C:\Program Files\Epic Games\UE_5.8',
    [ValidateSet('Development','DebugGame')]
    [string]$Configuration = 'Development',
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$project = Join-Path $repo 'ToolLab\CotSToolLab.uproject'
$buildBat = Join-Path $EngineRoot 'Engine\Build\BatchFiles\Build.bat'
$ubtLocal = Join-Path $env:LOCALAPPDATA 'UnrealBuildTool'

if (-not (Test-Path -LiteralPath $project)) {
    throw "Tool Lab project not found: $project"
}
if (-not (Test-Path -LiteralPath $buildBat)) {
    throw "Unreal Build.bat not found: $buildBat"
}

Write-Host 'CotS Tool Lab build'
Write-Host "Project: $project"
Write-Host "Engine:  $EngineRoot"
Write-Host "Target:  CotSToolLabEditor Win64 $Configuration"

# UBT always writes/rotates logs and trace files under LOCALAPPDATA. Some AI-agent
# sandboxes can read the project but cannot write there, which causes dotnet.exe to
# terminate with CLR exception 0xE0434352 before UBT can report a useful error.
# Probe that exact write path before launching UBT so we fail cleanly instead of
# producing a misleading Windows application-error popup.
try {
    if (-not (Test-Path -LiteralPath $ubtLocal)) {
        New-Item -ItemType Directory -Path $ubtLocal -Force | Out-Null
    }

    $probe = Join-Path $ubtLocal ('.cots-write-probe-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    Set-Content -LiteralPath $probe -Value 'CotS UBT write probe' -Encoding Ascii -ErrorAction Stop
    Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
}
catch {
    Write-Host ''
    Write-Host '[BLOCKED] UnrealBuildTool local diagnostics directory is not writable from this execution context.' -ForegroundColor Yellow
    Write-Host "Path: $ubtLocal"
    Write-Host "Reason: $($_.Exception.Message)"
    Write-Host ''
    Write-Host 'This commonly occurs when an AI coding agent runs the build inside its filesystem sandbox.'
    Write-Host 'Do not invoke raw dotnet/UnrealBuildTool from the same sandbox; that can trigger a 0xE0434352 popup.'
    Write-Host 'Run Scripts\Build-ToolLab.cmd from a normal user PowerShell, or have the agent request an explicitly unsandboxed/approved execution.'
    exit 87
}

$args = @(
    'CotSToolLabEditor',
    'Win64',
    $Configuration,
    "-Project=$project",
    '-WaitMutex',
    '-NoHotReloadFromIDE'
)

if ($Clean) {
    Write-Host 'Cleaning target first...'
    & $buildBat 'CotSToolLabEditor' 'Win64' $Configuration "-Project=$project" '-Clean' '-WaitMutex'
    if ($LASTEXITCODE -ne 0) {
        throw "Unreal clean failed with exit code $LASTEXITCODE"
    }
}

& $buildBat @args
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "`n[FAIL] CotS Tool Lab build failed with exit code $exitCode" -ForegroundColor Red
    exit $exitCode
}

Write-Host "`n[OK] CotS Tool Lab editor target built successfully." -ForegroundColor Green
exit 0
