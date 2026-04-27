param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8000,
    [ValidateSet("critical", "error", "warning", "info", "debug", "trace")]
    [string]$LogLevel = "info",
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$CommandArgs = @(
    "run", "python", "-m", "uvicorn",
    "src.web.app:app",
    "--host", $HostAddress,
    "--port", $Port.ToString(),
    "--log-level", $LogLevel
)

if (-not $NoReload) {
    $CommandArgs += "--reload"
}

Write-Host "========================================"
Write-Host "SurveyMAE Web Server"
Write-Host "========================================"
Write-Host ""
Write-Host "Starting server at: http://localhost:$Port"
Write-Host "Press Ctrl+C to stop"
Write-Host ""

Push-Location $ProjectRoot
try {
    & uv @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
