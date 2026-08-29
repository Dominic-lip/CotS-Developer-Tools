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
