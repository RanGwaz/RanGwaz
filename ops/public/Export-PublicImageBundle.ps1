[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$Release,

    [Parameter(Mandatory = $true)]
    [string]$TargetDirectory,

    [string]$BackendImage = '',
    [string]$FrontendImage = '',
    [string]$GitExecutable = 'git',
    [string]$DockerExecutable = 'docker'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Release = $Release.ToLowerInvariant()
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))
$TargetDirectory = [IO.Path]::GetFullPath($TargetDirectory)

if ([string]::IsNullOrWhiteSpace($BackendImage)) {
    $BackendImage = "vibelo-public-backend:$Release"
}
if ([string]::IsNullOrWhiteSpace($FrontendImage)) {
    $FrontendImage = "vibelo-public-frontend:$Release"
}

function Invoke-GitCapture {
    param([string[]]$CommandArguments)

    $output = @(& $GitExecutable -C $repoRoot @CommandArguments)
    if ($LASTEXITCODE -ne 0) {
        throw "git failed with exit code $LASTEXITCODE"
    }
    return $output
}

function Assert-ReleaseImageRef {
    param([string]$Reference, [string]$Label)

    if ([string]::IsNullOrWhiteSpace($Reference) -or
        $Reference -match '[\s\x00-\x1f]' -or
        $Reference.Contains('@') -or
        -not $Reference.EndsWith(":$Release", [StringComparison]::Ordinal)) {
        throw "$Label must be an explicit image tag ending in :$Release"
    }
}

function Write-AsciiLfFile {
    param([string]$Path, [string[]]$Lines)

    $content = ($Lines -join "`n") + "`n"
    [IO.File]::WriteAllText($Path, $content, [Text.Encoding]::ASCII)
}

$trackedDirty = @(Invoke-GitCapture @('status', '--porcelain=v1', '--untracked-files=no'))
$untrackedBuildInputs = @(Invoke-GitCapture @(
    'ls-files', '--others', '--exclude-standard', '--', 'backend', 'frontend'
))
if (($trackedDirty.Count -ne 0 -and -not [string]::IsNullOrWhiteSpace(($trackedDirty -join "`n"))) -or
    ($untrackedBuildInputs.Count -ne 0 -and -not [string]::IsNullOrWhiteSpace(($untrackedBuildInputs -join "`n")))) {
    throw 'Refusing to export images with tracked changes or untracked frontend/backend build inputs'
}

$headOutput = @(Invoke-GitCapture @('rev-parse', 'HEAD'))
if ($headOutput.Count -ne 1) {
    throw 'Unable to determine one Git HEAD commit'
}
$head = $headOutput[0].Trim().ToLowerInvariant()
if ($head -ne $Release) {
    throw "Release does not match Git HEAD: expected $Release, found $head"
}

Assert-ReleaseImageRef $BackendImage 'BackendImage'
Assert-ReleaseImageRef $FrontendImage 'FrontendImage'
if ($BackendImage -eq $FrontendImage) {
    throw 'BackendImage and FrontendImage must be different release tags'
}

$imageRefs = @(
    'nginx:1.27-alpine',
    $FrontendImage,
    $BackendImage,
    'redis:7.4-alpine',
    'docker.elastic.co/elasticsearch/elasticsearch:8.14.3',
    'confluentinc/cp-zookeeper:7.6.1',
    'confluentinc/cp-kafka:7.6.1',
    'minio/minio:RELEASE.2025-04-22T22-12-26Z'
)

$uniqueRefs = @($imageRefs | Sort-Object -Unique)
if ($imageRefs.Count -ne 8 -or $uniqueRefs.Count -ne 8) {
    throw 'The public release must contain exactly eight distinct image references'
}

if (Test-Path -LiteralPath $TargetDirectory) {
    $targetItem = Get-Item -LiteralPath $TargetDirectory -Force
    if (-not $targetItem.PSIsContainer -or ($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'TargetDirectory must be a real directory, not a file or reparse point'
    }
    if (@(Get-ChildItem -LiteralPath $TargetDirectory -Force).Count -ne 0) {
        throw 'TargetDirectory must be empty'
    }
} else {
    New-Item -ItemType Directory -Path $TargetDirectory | Out-Null
}

$bundleName = "vibelo-public-$Release-linux-amd64.tar"
$manifestName = "vibelo-public-$Release-images.tsv"
$bundlePath = Join-Path $TargetDirectory $bundleName
$partialBundlePath = "$bundlePath.partial"
$manifestPath = Join-Path $TargetDirectory $manifestName
$checksumsPath = Join-Path $TargetDirectory 'SHA256SUMS'

$manifestLines = [Collections.Generic.List[string]]::new()
$manifestLines.Add("ref`timage_id`tos`tarch")

foreach ($imageRef in $imageRefs) {
    $inspectOutput = @(& $DockerExecutable image inspect --platform linux/amd64 `
        --format '{{.Id}}|{{.Os}}|{{.Architecture}}' $imageRef)
    if ($LASTEXITCODE -ne 0) {
        throw "Required image is missing or cannot be inspected: $imageRef"
    }
    if ($inspectOutput.Count -ne 1) {
        throw "Image inspection returned an unexpected number of records: $imageRef"
    }
    $parts = @($inspectOutput[0].Trim() -split '\|')
    if ($parts.Count -ne 3) {
        throw "Image inspection returned malformed metadata: $imageRef"
    }
    $imageId = $parts[0].ToLowerInvariant()
    $os = $parts[1].ToLowerInvariant()
    $arch = $parts[2].ToLowerInvariant()
    if ($imageId -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "Image has an invalid full image ID: $imageRef"
    }
    if ($os -ne 'linux' -or $arch -ne 'amd64') {
        throw "Image is not linux/amd64: $imageRef ($os/$arch)"
    }
    if ($imageRef -eq $BackendImage -or $imageRef -eq $FrontendImage) {
        $revisionOutput = @(& $DockerExecutable image inspect --platform linux/amd64 `
            --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' $imageRef)
        if ($LASTEXITCODE -ne 0 -or $revisionOutput.Count -ne 1 -or
            $revisionOutput[0].Trim() -cne $Release) {
            throw "Release image revision label does not exactly match Git HEAD: $imageRef"
        }
    }
    $manifestLines.Add("$imageRef`t$imageId`t$os`t$arch")
}

Write-AsciiLfFile $manifestPath $manifestLines.ToArray()

try {
    $saveArguments = @(
        'image',
        'save',
        '--platform',
        'linux/amd64',
        '--output',
        $partialBundlePath
    ) + $imageRefs
    & $DockerExecutable @saveArguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker image save failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $partialBundlePath -PathType Leaf) -or
        (Get-Item -LiteralPath $partialBundlePath).Length -le 0) {
        throw 'docker image save did not produce a non-empty bundle'
    }
    Move-Item -LiteralPath $partialBundlePath -Destination $bundlePath
} finally {
    if (Test-Path -LiteralPath $partialBundlePath -PathType Leaf) {
        Remove-Item -LiteralPath $partialBundlePath -Force
    }
}

$bundleSha = (Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifestSha = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-AsciiLfFile $checksumsPath @(
    "$bundleSha  $bundleName",
    "$manifestSha  $manifestName"
)

Write-Output "Release image bundle created: $bundlePath"
Write-Output "Bundle SHA256: $bundleSha"
Write-Output "Manifest: $manifestPath"
Write-Output "VIBELO_BACKEND_IMAGE=$BackendImage"
Write-Output "VIBELO_FRONTEND_IMAGE=$FrontendImage"
