param(
    [string]$Model = "qwen2.5-coder:14b",
    [switch]$InstallOllama,
    [switch]$PullModel = $true
)

$ErrorActionPreference = "Stop"
$Ollama = (Get-Command ollama.exe -ErrorAction SilentlyContinue).Source

if (-not $Ollama -and $InstallOllama) {
    $Winget = (Get-Command winget.exe -ErrorAction SilentlyContinue).Source
    if (-not $Winget) { throw "Ollama is not installed and winget was not found." }
    Write-Host "Installing Ollama locally..."
    & $Winget install --id Ollama.Ollama --exact --accept-source-agreements --accept-package-agreements
    $Ollama = (Get-Command ollama.exe -ErrorAction SilentlyContinue).Source
}

if (-not $Ollama) {
    Write-Host "Ollama is not installed/on PATH."
    Write-Host "Install Ollama, then rerun this script, or rerun with -InstallOllama."
    exit 2
}

Write-Host "Ollama: $Ollama"
if ($PullModel) {
    Write-Host "Pulling local operations model: $Model"
    Write-Host "This is a local-model download and may be several GB."
    & $Ollama pull $Model
    if ($LASTEXITCODE -ne 0) { throw "ollama pull failed with exit code $LASTEXITCODE" }
}

$env:COTS_LOCAL_AI_MODEL = $Model
Write-Host ""
Write-Host "Testing CotS local AI discovery..."
python "$PSScriptRoot\CotSLocalAI.py"
Write-Host ""
Write-Host "Recommended persistent setting (optional):"
Write-Host "  setx COTS_LOCAL_AI_MODEL `"$Model`""
Write-Host ""
Write-Host "CotS Local AI uses only http://127.0.0.1:11434 and has no cloud fallback."
