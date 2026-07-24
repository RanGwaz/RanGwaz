[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$ModelDir = $env:VIBELO_RECOMMENDATION_MODEL_DIR,
    [ValidateRange(1, 3650)]
    [int]$Days = 180,
    [ValidateRange(500, 20000000)]
    [int]$EventLimit = 2000000,
    [ValidateRange(2, 4096)]
    [int]$TrainingBatchSize = 128,
    [ValidateRange(1, 4096)]
    [int]$IndexBatchSize = 512,
    [ValidateRange(1, 10000)]
    [int]$ValidationSampleSize = 32,
    [switch]$NoAmp
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
}


if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python environment not found: $Python"
}
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
function Invoke-PythonStep {
    param([string[]]$Arguments)

    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $pythonPath @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
        return [int]$LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
}


if ([string]::IsNullOrWhiteSpace($ModelDir)) {
    $ModelDir = Join-Path $PSScriptRoot "models\recommendation"
} elseif (-not [System.IO.Path]::IsPathRooted($ModelDir)) {
    $ModelDir = Join-Path $repoRoot $ModelDir
}
$modelPath = [System.IO.Path]::GetFullPath($ModelDir)
New-Item -ItemType Directory -Force -Path $modelPath | Out-Null
$env:VIBELO_RECOMMENDATION_MODEL_DIR = $modelPath

$lockPath = Join-Path $modelPath ".two_tower_pipeline.lock"
try {
    $lockStream = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch {
    throw "Cannot acquire the two-tower pipeline lock at $lockPath. Another run may still be active."
}
try {

$trainScript = Join-Path $PSScriptRoot "train_two_tower_recall.py"
$publishScript = Join-Path $PSScriptRoot "publish_two_tower_index.py"
$registryPath = Join-Path $modelPath "two_tower\registry.json"

$trainArguments = @(
    $trainScript,
    "--days", [string]$Days,
    "--limit", [string]$EventLimit,
    "--batch-size", [string]$TrainingBatchSize,
    "--min-actors", "50",
    "--min-examples", "500"
)
if ($NoAmp) {
    $trainArguments += "--no-amp"
}

Write-Host "Training a gated two-tower candidate..."
$trainExit = Invoke-PythonStep -Arguments $trainArguments
if ($trainExit -ne 0) {
    throw "Two-tower training failed or the data/metric gate rejected the candidate (exit $trainExit)."
}

if (-not (Test-Path -LiteralPath $registryPath -PathType Leaf)) {
    throw "Training completed without a registry: $registryPath"
}
$registry = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$candidateVersion = [string]$registry.entries.candidate.version
if ([string]::IsNullOrWhiteSpace($candidateVersion)) {
    throw "Training completed without registering a candidate."
}

Write-Host "Building, validating, and promoting candidate $candidateVersion..."
$publishArguments = @(
    $publishScript,
    "--model-dir", $modelPath,
    "--version", $candidateVersion,
    "--batch-size", [string]$IndexBatchSize,
    "--sample-size", [string]$ValidationSampleSize,
    "--promote"
)
$publishExit = Invoke-PythonStep -Arguments $publishArguments
if ($publishExit -ne 0) {
    throw "Index publication failed; candidate $candidateVersion was not promoted (exit $publishExit)."
}

$publishedRegistry = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$currentVersion = [string]$publishedRegistry.entries.current.version
if ($currentVersion -ne $candidateVersion) {
    throw "Promotion verification failed: current=$currentVersion, expected=$candidateVersion"
}

Write-Host "Two-tower version $currentVersion is now current."
} finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
}
