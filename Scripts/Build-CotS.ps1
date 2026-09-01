[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\Dev\CotS',
    [string]$EngineRoot = 'C:\Program Files\Epic Games\UE_5.8',
    [ValidateSet('Development','DebugGame')]
    [string]$Configuration = 'Development',
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

$project = Join-Path $ProjectRoot 'CotS.uproject'
$buildBat = Join-Path $EngineRoot 'Engine\Build\BatchFiles\Build.bat'
$ubtLocal = Join-Path $env:LOCALAPPDATA 'UnrealBuildTool'

if (-not (Test-Path -LiteralPath $project)) {
    throw "CotS production project not found: $project"
}
if (-not (Test-Path -LiteralPath $buildBat)) {
    throw "Unreal Build.bat not found: $buildBat"
}

try {
    if (-not (Test-Path -LiteralPath $ubtLocal)) {
        New-Item -ItemType Directory -Path $ubtLocal -Force | Out-Null
    }
    $probe = Join-Path $ubtLocal ('.cots-write-probe-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    Set-Content -LiteralPath $probe -Value 'CotS UBT write probe' -Encoding Ascii -ErrorAction Stop
    Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
}
catch {
    Write-Host '[BLOCKED] UnrealBuildTool diagnostics directory is not writable from this execution context.' -ForegroundColor Yellow
    Write-Host "Path: $ubtLocal"
    Write-Host "Reason: $($_.Exception.Message)"
    exit 87
}

Write-Host 'CotS production build'
Write-Host "Project: $project"
Write-Host "Engine:  $EngineRoot"
Write-Host "Target:  CotSEditor Win64 $Configuration"

if ($Clean) {
    & $buildBat 'CotSEditor' 'Win64' $Configuration "-Project=$project" '-Clean' '-WaitMutex'
    if ($LASTEXITCODE -ne 0) {
        throw "Unreal clean failed with exit code $LASTEXITCODE"
    }
}

$args = @(
    'CotSEditor',
    'Win64',
    $Configuration,
    "-Project=$project",
    '-WaitMutex',
    '-NoHotReloadFromIDE'
)

& $buildBat @args
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Write-Host "`n[FAIL] CotS production build failed with exit code $exitCode" -ForegroundColor Red
    exit $exitCode
}

Write-Host "`n[OK] CotS production editor target built successfully." -ForegroundColor Green
exit 0
