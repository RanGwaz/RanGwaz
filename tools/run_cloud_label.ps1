param(
    [string]$ConfigPath = "",
    [int]$Limit = -1,
    [switch]$InitConfig
)

$ErrorActionPreference = "Stop"

$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ToolsDir "..")
$ExampleConfig = Join-Path $ToolsDir "cloud_label_config.example.ps1"
$LocalConfig = Join-Path $ToolsDir "cloud_label_config.local.ps1"

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = $LocalConfig
}

if ($InitConfig) {
    if (Test-Path -LiteralPath $ConfigPath) {
        Write-Host "Config already exists: $ConfigPath"
    } else {
        Copy-Item -LiteralPath $ExampleConfig -Destination $ConfigPath
        Write-Host "Created config: $ConfigPath"
    }
    Write-Host "Open it, replace sk-your-api-key, then run:"
    Write-Host "  .\tools\run_cloud_label.ps1"
    exit 0
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Copy-Item -LiteralPath $ExampleConfig -Destination $ConfigPath
    throw "Created $ConfigPath. Fill VIBELO_CLOUD_LABEL_API_KEY first, then run this script again."
}

. $ConfigPath

if ($Limit -ge 0) {
    $env:VIBELO_LABEL_LIMIT = [string]$Limit
}

$missing = @()
foreach ($name in @(
    "VIBELO_CLOUD_LABEL_API_BASE_URL",
    "VIBELO_CLOUD_LABEL_API_KEY",
    "VIBELO_CLOUD_LABEL_MODEL"
)) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if ([string]::IsNullOrWhiteSpace($value)) {
        $missing += $name
    }
}
if ($missing.Count -gt 0) {
    throw "Missing cloud label config: $($missing -join ', ')"
}
if ($env:VIBELO_CLOUD_LABEL_API_KEY -eq "sk-your-api-key") {
    throw "Edit $ConfigPath and replace sk-your-api-key with your real API key."
}

$Python = Join-Path $ToolsDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project Python not found: $Python. Run tools\setup_local_gpu.ps1 first."
}

Set-Location $RootDir
Write-Host "Cloud label model: $env:VIBELO_CLOUD_LABEL_MODEL"
Write-Host "Cloud label API:   $env:VIBELO_CLOUD_LABEL_API_BASE_URL"
Write-Host "Batch limit:       $env:VIBELO_LABEL_LIMIT"
if ($env:VIBELO_CLOUD_LABEL_PROXY_URL) {
    Write-Host "Proxy:             $env:VIBELO_CLOUD_LABEL_PROXY_URL"
}

& $Python (Join-Path $ToolsDir "cloud_label_images.py")
exit $LASTEXITCODE
