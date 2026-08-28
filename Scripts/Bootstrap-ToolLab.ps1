[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$RepositoryRoot
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Split-Path -Parent $PSScriptRoot
}

$repo = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$pluginSource = Join-Path $repo 'UnrealPlugin\CotSDeveloperTools'
$pluginsDir = Join-Path $repo 'ToolLab\Plugins'
$pluginLink = Join-Path $pluginsDir 'CotSDeveloperTools'

if (-not (Test-Path $pluginSource)) {
    throw "Plugin source not found: $pluginSource"
}

if (-not (Test-Path $pluginsDir)) {
    New-Item -ItemType Directory -Path $pluginsDir | Out-Null
}

if (Test-Path $pluginLink) {
    Write-Host "Tool Lab plugin link already exists: $pluginLink"
    exit 0
}

if ($PSCmdlet.ShouldProcess($pluginLink, "Create directory junction to $pluginSource")) {
    cmd /c "mklink /J `"$pluginLink`" `"$pluginSource`""
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create Tool Lab plugin junction. mklink exit code: $LASTEXITCODE"
    }
    Write-Host "Created: $pluginLink -> $pluginSource"
}
