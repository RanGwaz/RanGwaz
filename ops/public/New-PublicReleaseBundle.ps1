[CmdletBinding()]
param(
    [string]$OutputDirectory = '',
    [switch]$ValidateOnly,
    [string]$GitExecutable = 'git',
    [string]$DockerExecutable = 'docker',
    [string]$MavenExecutable = 'mvn',
    [string]$NpmExecutable = 'npm'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))
$exporter = Join-Path $scriptDir 'Export-PublicImageBundle.ps1'

function Invoke-Checked {
    param(
        [string]$Executable,
        [string[]]$CommandArguments,
        [string]$FailureMessage,
        [string]$WorkingDirectory = $repoRoot
    )

    Push-Location $WorkingDirectory
    try {
        & $Executable @CommandArguments
        if ($LASTEXITCODE -ne 0) {
            throw "$FailureMessage (exit code $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }
}

foreach ($executable in @($GitExecutable, $DockerExecutable, $MavenExecutable, $NpmExecutable)) {
    if (-not (Get-Command $executable -ErrorAction SilentlyContinue)) {
        throw "Local command not found: $executable"
    }
}
if (-not (Test-Path -LiteralPath $exporter -PathType Leaf)) {
    throw "Offline exporter is missing: $exporter"
}

$releaseOutput = @(& $GitExecutable -C $repoRoot rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $releaseOutput.Count -ne 1) {
    throw 'Unable to read Git HEAD'
}
$release = $releaseOutput[0].Trim().ToLowerInvariant()
if ($release -notmatch '^[0-9a-f]{40}$') {
    throw 'Git HEAD is not a full 40-character SHA'
}
$originMainOutput = @(& $GitExecutable -C $repoRoot rev-parse --verify refs/remotes/origin/main)
if ($LASTEXITCODE -ne 0 -or $originMainOutput.Count -ne 1 -or
    $originMainOutput[0].Trim().ToLowerInvariant() -ne $release) {
    throw 'Git HEAD must already be pushed to origin/main'
}

$trackedDirty = @(& $GitExecutable -C $repoRoot status --porcelain=v1 --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect the Git worktree' }
$untrackedBuildInputs = @(& $GitExecutable -C $repoRoot ls-files --others --exclude-standard -- backend frontend)
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect untracked build inputs' }
if (($trackedDirty | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -ne 0 -or
    ($untrackedBuildInputs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -ne 0) {
    throw 'Commit all tracked changes and remove untracked backend/frontend build inputs first'
}

Invoke-Checked $DockerExecutable @('version') 'Docker Engine is unavailable'
$requiredLocalImages = @(
    'maven:3.9.9-eclipse-temurin-17',
    'eclipse-temurin:17-jre-alpine',
    'node:22-alpine',
    'nginx:1.27-alpine',
    'redis:7.4-alpine',
    'docker.elastic.co/elasticsearch/elasticsearch:8.14.3',
    'confluentinc/cp-zookeeper:7.6.1',
    'confluentinc/cp-kafka:7.6.1',
    'minio/minio:RELEASE.2025-04-22T22-12-26Z'
)
foreach ($image in $requiredLocalImages) {
    Invoke-Checked $DockerExecutable @(
        'image', 'inspect', '--platform', 'linux/amd64', $image
    ) "Required fixed linux/amd64 image is missing locally: $image"
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $env:TEMP "vibelo-public-$release"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
Write-Output "Release=$release"
Write-Output "OutputDirectory=$OutputDirectory"

if ($ValidateOnly) {
    Write-Output 'Read-only validation passed; no tests, builds, or release writes were performed.'
    exit 0
}

if (Test-Path -LiteralPath $OutputDirectory) {
    throw "Output directory must not exist: $OutputDirectory"
}

Invoke-Checked $MavenExecutable @('test') 'Backend tests failed' (Join-Path $repoRoot 'backend')
Invoke-Checked $NpmExecutable @('run', 'build') 'Frontend build validation failed' (Join-Path $repoRoot 'frontend')

Invoke-Checked $DockerExecutable @(
    'build', '--pull=false', '--platform', 'linux/amd64',
    '--build-arg', "VIBELO_GIT_REVISION=$release",
    '--tag', "vibelo-public-backend:$release",
    (Join-Path $repoRoot 'backend')
) 'Backend image build failed'

Invoke-Checked $DockerExecutable @(
    'build', '--pull=false', '--platform', 'linux/amd64',
    '--build-arg', "VIBELO_GIT_REVISION=$release",
    '--build-arg', 'VITE_API_BASE=/api',
    '--build-arg', 'VITE_MEDIA_UPLOAD_ENABLED=false',
    '--tag', "vibelo-public-frontend:$release",
    (Join-Path $repoRoot 'frontend')
) 'Frontend image build failed'

& $exporter -Release $release -TargetDirectory $OutputDirectory `
    -GitExecutable $GitExecutable -DockerExecutable $DockerExecutable
if ($LASTEXITCODE -ne 0) {
    throw "Offline release export failed (exit code $LASTEXITCODE)"
}

Write-Output 'Local tests, exactly two commit image builds, and full-SHA offline export completed.'
Write-Output "Upload only the three bundle files to ECS: /data/releases/$release/"
