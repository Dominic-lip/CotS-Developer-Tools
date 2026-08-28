[CmdletBinding()]
param(
    [string]$DevRoot = 'C:\Dev'
)

$ErrorActionPreference = 'Stop'

function Test-CommandAvailable([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) {
        Write-Host "[OK]   $Name -> $($cmd.Source)"
        return $true
    }
    Write-Host "[MISS] $Name"
    return $false
}

Write-Host 'CotS Developer Tools prerequisite check'
Write-Host "Dev root: $DevRoot`n"

$allGood = $true
$allGood = (Test-CommandAvailable 'git') -and $allGood
$allGood = (Test-CommandAvailable 'codex') -and $allGood

# Claude is optional until its connectivity task is run.
if (-not (Test-CommandAvailable 'claude')) {
    Write-Host '       Claude Code is not yet available; Codex work can continue.'
}

$expectedFolders = @('Shardlands', 'CotSDeveloperTools', 'CotS', 'Tasks')
foreach ($folder in $expectedFolders) {
    $path = Join-Path $DevRoot $folder
    if (Test-Path $path) {
        Write-Host "[OK]   $path"
    }
    else {
        Write-Host "[MISS] $path"
        if ($folder -in @('CotSDeveloperTools')) { $allGood = $false }
    }
}

$ueCandidates = @(
    'C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe',
    'D:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe'
)
$ue = $ueCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($ue) {
    Write-Host "[OK]   Unreal Editor 5.8 candidate -> $ue"
}
else {
    Write-Host '[INFO] UnrealEditor.exe was not found in the common launcher locations. This does not prove UE 5.8 is absent.'
}

if (-not $allGood) {
    exit 1
}
