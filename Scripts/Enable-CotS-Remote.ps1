param([switch]$Disable)

$ErrorActionPreference = "Stop"
if (-not (Get-Command tailscale.exe -ErrorAction SilentlyContinue)) {
    throw "Tailscale CLI not found. Install/sign in to Tailscale first."
}

if ($Disable) {
    tailscale serve reset
    Write-Host "Tailscale Serve configuration reset."
    exit 0
}

tailscale status
tailscale serve --bg http://127.0.0.1:8765
Write-Host ""
Write-Host "CotS telemetry is now served through your private Tailscale tailnet."
Write-Host "The localhost endpoint remains http://127.0.0.1:8765/."
Write-Host "Remote restart/stop actions still require the CotS bearer token."
