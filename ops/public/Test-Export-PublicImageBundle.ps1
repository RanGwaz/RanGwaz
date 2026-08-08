$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$exporter = Join-Path $scriptDir 'Export-PublicImageBundle.ps1'
$release = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$backendImage = "vibelo-public-backend:$release"
$frontendImage = "vibelo-public-frontend:$release"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("vibelo-public-export-test-" + [guid]::NewGuid().ToString('N'))

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw "FAIL: $Message"
    }
}

function Invoke-ExporterFixture {
    param([string]$Target)

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $script:ExporterOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $exporter `
            -Release $release `
            -TargetDirectory $Target `
            -GitExecutable $fakeGit `
            -DockerExecutable $fakeDocker 2>&1
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $fakeGit = Join-Path $tempRoot 'fake-git.ps1'
    $fakeDocker = Join-Path $tempRoot 'fake-docker.ps1'
    $target = Join-Path $tempRoot 'release'

    @'
if ($args -contains 'status') {
    if ($env:VIBELO_TEST_GIT_DIRTY -eq '1') {
        Write-Output ' M dirty.txt'
    }
    exit 0
}
if ($args -contains 'ls-files') {
    if ($env:VIBELO_TEST_UNTRACKED_BUILD_INPUT -eq '1') {
        Write-Output 'backend/src/main/java/Untracked.java'
    }
    exit 0
}
if ($args -contains 'HEAD') {
    Write-Output $env:VIBELO_TEST_GIT_HEAD
    exit 0
}
Write-Error "unexpected git arguments: $args"
exit 91
'@ | Set-Content -LiteralPath $fakeGit -Encoding UTF8

    @'
if ($args.Count -ge 3 -and $args[0] -eq 'image' -and $args[1] -eq 'inspect') {
    $platformIndex = [Array]::IndexOf($args, '--platform')
    if ($platformIndex -lt 0 -or $platformIndex + 1 -ge $args.Count -or
        $args[$platformIndex + 1] -ne 'linux/amd64') {
        Write-Error 'inspect must explicitly select linux/amd64'
        exit 94
    }
    $ref = $args[$args.Count - 1]
    $formatIndex = [Array]::IndexOf($args, '--format')
    if ($formatIndex -ge 0 -and $formatIndex + 1 -lt $args.Count -and
        $args[$formatIndex + 1] -eq '{{json .Config.Labels}}') {
        if ($ref -eq $env:VIBELO_TEST_WRONG_REVISION_IMAGE) {
            $revision = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        } else {
            $revision = $env:VIBELO_TEST_GIT_HEAD
        }
        Write-Output (ConvertTo-Json @{ 'org.opencontainers.image.revision' = $revision } -Compress)
        exit 0
    }
    if ($ref -eq $env:VIBELO_TEST_MISSING_IMAGE) {
        Write-Error "missing fixture image: $ref"
        exit 1
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($ref))
    } finally {
        $sha.Dispose()
    }
    $id = -join ($digest | ForEach-Object { $_.ToString('x2') })
    $os = 'linux'
    $arch = if ($ref -eq $env:VIBELO_TEST_WRONG_PLATFORM_IMAGE) { 'arm64' } else { 'amd64' }
    Write-Output "sha256:$id|$os|$arch"
    exit 0
}
if ($args.Count -ge 4 -and $args[0] -eq 'image' -and $args[1] -eq 'save') {
    $platformIndex = [Array]::IndexOf($args, '--platform')
    if ($platformIndex -lt 0 -or $platformIndex + 1 -ge $args.Count -or
        $args[$platformIndex + 1] -ne 'linux/amd64') {
        Write-Error 'save must explicitly select linux/amd64'
        exit 95
    }
    $outputIndex = [Array]::IndexOf($args, '--output')
    if ($outputIndex -lt 0 -or $outputIndex + 1 -ge $args.Count) {
        Write-Error 'missing --output'
        exit 92
    }
    [IO.File]::WriteAllText($args[$outputIndex + 1], 'fixture docker image bundle')
    exit 0
}
Write-Error "unexpected docker arguments: $args"
exit 93
'@ | Set-Content -LiteralPath $fakeDocker -Encoding UTF8

    $env:VIBELO_TEST_GIT_HEAD = $release
    $env:VIBELO_TEST_GIT_DIRTY = '0'
    $env:VIBELO_TEST_UNTRACKED_BUILD_INPUT = '0'
    $env:VIBELO_TEST_MISSING_IMAGE = ''
    $env:VIBELO_TEST_WRONG_PLATFORM_IMAGE = ''
    $env:VIBELO_TEST_WRONG_REVISION_IMAGE = ''

    $exitCode = Invoke-ExporterFixture $target
    Assert-True ($exitCode -eq 0) "fixture export should succeed; output: $ExporterOutput"
    Assert-True ($ExporterOutput -contains "VIBELO_BACKEND_IMAGE=$backendImage") 'output should provide the ECS backend image variable'
    Assert-True ($ExporterOutput -contains "VIBELO_FRONTEND_IMAGE=$frontendImage") 'output should provide the ECS frontend image variable'

    $bundle = Join-Path $target "vibelo-public-$release-linux-amd64.tar"
    $manifest = Join-Path $target "vibelo-public-$release-images.tsv"
    $checksums = Join-Path $target 'SHA256SUMS'
    Assert-True (Test-Path -LiteralPath $bundle -PathType Leaf) 'bundle should exist'
    Assert-True ((Get-Item -LiteralPath $bundle).Length -gt 0) 'bundle should not be empty'
    Assert-True (Test-Path -LiteralPath $manifest -PathType Leaf) 'manifest should exist'
    Assert-True (Test-Path -LiteralPath $checksums -PathType Leaf) 'SHA256SUMS should exist'

    $manifestLines = Get-Content -LiteralPath $manifest
    Assert-True ($manifestLines.Count -eq 9) 'manifest should contain one header and exactly eight images'
    Assert-True ($manifestLines[0] -eq "ref`timage_id`tos`tarch") 'manifest header should be fixed'
    $expectedRefs = @(
        'nginx:1.27-alpine',
        $frontendImage,
        $backendImage,
        'redis:7.4-alpine',
        'docker.elastic.co/elasticsearch/elasticsearch:8.14.3',
        'confluentinc/cp-zookeeper:7.6.1',
        'confluentinc/cp-kafka:7.6.1',
        'minio/minio:RELEASE.2025-04-22T22-12-26Z'
    )
    $actualRefs = @($manifestLines | Select-Object -Skip 1 | ForEach-Object { ($_ -split "`t", 2)[0] })
    Assert-True (($actualRefs -join "`n") -eq ($expectedRefs -join "`n")) 'manifest image set and order should be fixed'
    Assert-True ((Get-Content -LiteralPath $checksums).Count -eq 2) 'SHA256SUMS should contain only bundle and manifest'

    $checksumLines = Get-Content -LiteralPath $checksums
    $bundleSha = (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifestSha = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-True ($checksumLines[0] -eq "$bundleSha  $(Split-Path -Leaf $bundle)") 'bundle SHA256 should be exact'
    Assert-True ($checksumLines[1] -eq "$manifestSha  $(Split-Path -Leaf $manifest)") 'manifest SHA256 should be exact'

    $env:VIBELO_TEST_GIT_DIRTY = '1'
    $dirtyTarget = Join-Path $tempRoot 'dirty-release'
    Assert-True ((Invoke-ExporterFixture $dirtyTarget) -ne 0) 'dirty Git worktree should be rejected'
    Assert-True (-not (Test-Path -LiteralPath $dirtyTarget)) 'dirty rejection should happen before target creation'
    $env:VIBELO_TEST_GIT_DIRTY = '0'

    $env:VIBELO_TEST_UNTRACKED_BUILD_INPUT = '1'
    $untrackedBuildTarget = Join-Path $tempRoot 'untracked-build-input-release'
    Assert-True ((Invoke-ExporterFixture $untrackedBuildTarget) -ne 0) 'untracked frontend/backend build inputs should be rejected'
    Assert-True (-not (Test-Path -LiteralPath $untrackedBuildTarget)) 'build-input rejection should happen before target creation'
    $env:VIBELO_TEST_UNTRACKED_BUILD_INPUT = '0'

    $env:VIBELO_TEST_GIT_HEAD = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
    Assert-True ((Invoke-ExporterFixture (Join-Path $tempRoot 'wrong-head-release')) -ne 0) 'non-HEAD release should be rejected'
    $env:VIBELO_TEST_GIT_HEAD = $release

    $env:VIBELO_TEST_MISSING_IMAGE = 'redis:7.4-alpine'
    Assert-True ((Invoke-ExporterFixture (Join-Path $tempRoot 'missing-image-release')) -ne 0) 'missing required image should be rejected'
    $env:VIBELO_TEST_MISSING_IMAGE = ''

    $env:VIBELO_TEST_WRONG_PLATFORM_IMAGE = 'confluentinc/cp-kafka:7.6.1'
    Assert-True ((Invoke-ExporterFixture (Join-Path $tempRoot 'wrong-platform-release')) -ne 0) 'non-linux-amd64 image should be rejected'
    $env:VIBELO_TEST_WRONG_PLATFORM_IMAGE = ''

    $env:VIBELO_TEST_WRONG_REVISION_IMAGE = $frontendImage
    Assert-True ((Invoke-ExporterFixture (Join-Path $tempRoot 'wrong-revision-release')) -ne 0) 'a release image with a stale Git revision label should be rejected'
    $env:VIBELO_TEST_WRONG_REVISION_IMAGE = ''

    Write-Output 'Public image bundle export fixture tests passed.'
} finally {
    Remove-Item Env:VIBELO_TEST_GIT_HEAD -ErrorAction SilentlyContinue
    Remove-Item Env:VIBELO_TEST_GIT_DIRTY -ErrorAction SilentlyContinue
    Remove-Item Env:VIBELO_TEST_UNTRACKED_BUILD_INPUT -ErrorAction SilentlyContinue
    Remove-Item Env:VIBELO_TEST_MISSING_IMAGE -ErrorAction SilentlyContinue
    Remove-Item Env:VIBELO_TEST_WRONG_PLATFORM_IMAGE -ErrorAction SilentlyContinue
    Remove-Item Env:VIBELO_TEST_WRONG_REVISION_IMAGE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}

# Negative fixtures intentionally execute failing mock commands. Do not leak
# their native exit code after every assertion has passed.
$global:LASTEXITCODE = 0
