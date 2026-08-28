[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('codex', 'claude')]
    [string]$Agent,

    [Parameter(Mandatory = $true)]
    [string]$Task,

    [string]$WorkingDirectory = 'C:\Dev',

    [switch]$NonInteractive,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$taskPath = (Resolve-Path -LiteralPath $Task).Path
$workPath = (Resolve-Path -LiteralPath $WorkingDirectory).Path
$taskName = [System.IO.Path]::GetFileName($taskPath)

$agentExe = if ($Agent -eq 'codex') { 'codex' } else { 'claude' }
if (-not (Get-Command $agentExe -ErrorAction SilentlyContinue)) {
    throw "Required CLI '$agentExe' was not found on PATH."
}

$instruction = @"
Read the following CotS task specification completely before acting:
$taskPath

Treat that file as the authoritative specification for this run.
Read and obey any AGENTS.md/CLAUDE.md instructions that apply to the working directory.
Inspect current state before modifying anything. Follow the task's allowed/forbidden scope.
Compile/validate/test where required and report exactly what was actually verified.
"@

Write-Host "CotS task runner"
Write-Host "  Agent:   $Agent"
Write-Host "  Task:    $taskName"
Write-Host "  Workdir: $workPath"
Write-Host "  Mode:    $(if ($NonInteractive) { 'non-interactive' } else { 'interactive' })"

if ($DryRun) {
    Write-Host "`n--- Prompt ---"
    Write-Host $instruction
    exit 0
}

Push-Location $workPath
try {
    if ($Agent -eq 'codex') {
        if ($NonInteractive) {
            & codex exec $instruction
        }
        else {
            & codex $instruction
        }
    }
    else {
        if ($NonInteractive) {
            & claude -p $instruction
        }
        else {
            & claude $instruction
        }
    }

    if ($LASTEXITCODE -ne 0) {
        throw "$agentExe exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
