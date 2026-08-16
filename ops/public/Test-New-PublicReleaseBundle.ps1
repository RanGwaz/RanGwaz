$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$releaseScript = Join-Path $scriptDir 'New-PublicReleaseBundle.ps1'
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("vibelo-new-release-test-" + [guid]::NewGuid().ToString('N'))
$release = '3f2f3e3e55dd1b3991c43d82bb9adedae8579920'

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw "Assertion failed: $Message"
    }
}

New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $fakeGit = Join-Path $tempRoot 'fake-git.ps1'
    $fakeDocker = Join-Path $tempRoot 'fake-docker.ps1'
    $fakeUnusedCommand = Join-Path $tempRoot 'fake-unused-command.ps1'

    @"
`$joined = `$args -join ' '
if (`$joined -match 'rev-parse HEAD$' -or
    `$joined -match 'rev-parse --verify refs/remotes/origin/main$') {
    Write-Output '$release'
    exit 0
}
if (`$joined -match 'status --porcelain=v1 --untracked-files=no$' -or
    `$joined -match 'ls-files --others --exclude-standard (?:-- )?backend frontend$') {
    exit 0
}
Write-Error "Unexpected fake Git arguments: `$joined"
exit 1
"@ | Set-Content -LiteralPath $fakeGit -Encoding utf8NoBOM

    @'
$joined = $args -join ' '
if ($joined -eq 'version' -or $joined -match '^image inspect --platform linux/amd64 ') {
    exit 0
}
Write-Error "Unexpected fake Docker arguments: $joined"
exit 1
'@ | Set-Content -LiteralPath $fakeDocker -Encoding utf8NoBOM

    @'
Write-Error 'ValidateOnly must not invoke Maven or npm'
exit 1
'@ | Set-Content -LiteralPath $fakeUnusedCommand -Encoding utf8NoBOM

    $output = @(& $releaseScript -ValidateOnly `
        -GitExecutable $fakeGit `
        -DockerExecutable $fakeDocker `
        -MavenExecutable $fakeUnusedCommand `
        -NpmExecutable $fakeUnusedCommand)

    Assert-True ($output -contains "Release=$release") 'ValidateOnly should report the full release SHA'
    Assert-True ($output -contains 'Read-only validation passed; no tests, builds, or release writes were performed.') `
        'clean tracked worktree with no untracked build inputs should pass read-only validation'

    Write-Output 'New-PublicReleaseBundle PowerShell regression tests passed.'
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
