param(
    [string]$Python = "python",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu121",
    [string]$TorchWheelUrl = "",
    [string]$PypiIndexUrl = "http://mirrors.aliyun.com/pypi/simple/",
    [string]$PypiTrustedHost = "mirrors.aliyun.com",
    [string]$ProxyUrl = "",
    [switch]$CpuTorch
)

$ErrorActionPreference = "Stop"

$ToolsDir = $PSScriptRoot
$RootDir = Resolve-Path (Join-Path $ToolsDir "..")
$VenvDir = Join-Path $ToolsDir ".venv"
$PipCacheDir = Join-Path $ToolsDir ".pip-cache"
$TempDir = Join-Path $ToolsDir ".tmp"
$ModelsDir = Join-Path $ToolsDir "models"

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

New-Item -ItemType Directory -Force -Path $PipCacheDir, $TempDir, $ModelsDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ModelsDir "huggingface"), (Join-Path $ModelsDir "torch"), (Join-Path $ModelsDir "ollama") | Out-Null

$env:PIP_CACHE_DIR = $PipCacheDir
$env:TEMP = $TempDir
$env:TMP = $TempDir
$env:HF_HOME = Join-Path $ModelsDir "huggingface"
$env:HF_HUB_CACHE = Join-Path $env:HF_HOME "hub"
$env:TRANSFORMERS_CACHE = Join-Path $env:HF_HOME "transformers"
$env:TORCH_HOME = Join-Path $ModelsDir "torch"
$env:XDG_CACHE_HOME = Join-Path $ModelsDir "cache"
$env:OLLAMA_MODELS = Join-Path $ModelsDir "ollama"

if ($ProxyUrl) {
    $env:HTTP_PROXY = $ProxyUrl
    $env:HTTPS_PROXY = $ProxyUrl
    $env:http_proxy = $ProxyUrl
    $env:https_proxy = $ProxyUrl
    Write-Host "Using proxy:"
    Write-Host "  $ProxyUrl"
}

if (-not (Test-Path $VenvDir)) {
    Invoke-Checked $Python @("-m", "venv", $VenvDir)
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
Invoke-Checked $VenvPython @("-m", "pip", "install", "-i", $PypiIndexUrl, "--trusted-host", $PypiTrustedHost, "--upgrade", "pip", "setuptools", "wheel")

if ($CpuTorch) {
    Invoke-Checked $VenvPython @("-m", "pip", "install", "-i", $PypiIndexUrl, "--trusted-host", $PypiTrustedHost, "torch")
} else {
    $PyTag = & $VenvPython -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')"
    if (-not $TorchWheelUrl -and $PyTag -eq "cp310") {
        $TorchWheelUrl = "https://download.pytorch.org/whl/cu121/torch-2.5.1%2Bcu121-cp310-cp310-win_amd64.whl"
    }
    if ($TorchWheelUrl) {
        $TorchWheelName = [System.Uri]::UnescapeDataString((Split-Path $TorchWheelUrl -Leaf))
        $TorchWheelPath = Join-Path $PipCacheDir $TorchWheelName
        if (-not (Test-Path $TorchWheelPath)) {
            Invoke-Checked "curl.exe" @("-L", "-C", "-", "--retry", "5", "--retry-delay", "5", "-o", $TorchWheelPath, $TorchWheelUrl)
        }
        Invoke-Checked $VenvPython @("-m", "pip", "install", "--force-reinstall", "--no-deps", $TorchWheelPath)
    } else {
        Invoke-Checked $VenvPython @("-m", "pip", "install", "torch", "--index-url", $TorchIndexUrl)
    }
}

Invoke-Checked $VenvPython @("-m", "pip", "install", "-i", $PypiIndexUrl, "--trusted-host", $PypiTrustedHost, "-r", (Join-Path $ToolsDir "requirements_recommendation.txt"))
Invoke-Checked $VenvPython @("-m", "pip", "install", "-i", $PypiIndexUrl, "--trusted-host", $PypiTrustedHost, "huggingface_hub")

Write-Host ""
Write-Host "Local GPU Python is ready:"
Write-Host "  $VenvPython"
Write-Host "Caches and models stay under:"
Write-Host "  $ToolsDir"
Write-Host ""
Write-Host "Next:"
Write-Host "  & `"$VenvPython`" tools/download_local_models.py"
