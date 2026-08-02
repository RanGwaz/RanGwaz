[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$EcsHost,

    [ValidateNotNullOrEmpty()]
    [string]$EcsUser = "root",

    [ValidateRange(1, 65535)]
    [int]$SshPort = 22,

    [ValidateRange(1, 65535)]
    [int]$LocalMinioPort = 9000,

    [ValidateRange(1, 65535)]
    [int]$RemoteTunnelPort = 19090,

    [ValidateSet("Start", "Verify")]
    [string]$Mode = "Start",

    [string]$IdentityFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-SafeSshToken {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($Value.StartsWith("-") -or $Value -match "\s") {
        throw "$Name must not start with '-' or contain whitespace."
    }
}

function Test-LocalMinio {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $healthUrl = "http://127.0.0.1:$Port/minio/health/live"
    try {
        $response = Invoke-WebRequest `
            -Uri $healthUrl `
            -UseBasicParsing `
            -TimeoutSec 5
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
            throw "HTTP $($response.StatusCode)"
        }
    }
    catch {
        throw "Windows source MinIO health check failed at $healthUrl. Start Docker Desktop and MinIO first. Cause: $($_.Exception.Message)"
    }
}

Assert-SafeSshToken -Value $EcsHost -Name "EcsHost"
Assert-SafeSshToken -Value $EcsUser -Name "EcsUser"

$sshCommand = Get-Command "ssh.exe" -ErrorAction SilentlyContinue
if (-not $sshCommand) {
    throw "ssh.exe was not found. Enable the Windows OpenSSH Client first."
}

$commonArguments = @(
    "-p", $SshPort.ToString(),
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ForwardAgent=no",
    "-o", "ForwardX11=no",
    "-o", "PermitLocalCommand=no",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "TCPKeepAlive=yes"
)

if ($IdentityFile) {
    $resolvedIdentityFile = (Resolve-Path -LiteralPath $IdentityFile).Path
    $commonArguments += @(
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-i", $resolvedIdentityFile
    )
}

$sshTarget = "$EcsUser@$EcsHost"

if ($Mode -eq "Verify") {
    $remoteHealthUrl = "http://127.0.0.1:$RemoteTunnelPort/minio/health/live"
    $remoteCommand = "set -eu; ss -lnt | grep -Eq '127[.]0[.]0[.]1:$RemoteTunnelPort([[:space:]]|`$)'; curl --fail --silent --show-error --max-time 5 '$remoteHealthUrl' >/dev/null; printf '%s\n' 'Reverse tunnel and source MinIO health checks passed'"

    Write-Host "Verifying the loopback-only reverse tunnel from the ECS..."
    & $sshCommand.Source @commonArguments $sshTarget $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Verification failed. Keep the Start-mode PowerShell open and check that ECS sshd permits remote forwarding."
    }
    exit 0
}

Test-LocalMinio -Port $LocalMinioPort

$forwardSpec = "127.0.0.1:${RemoteTunnelPort}:127.0.0.1:${LocalMinioPort}"
$startArguments = $commonArguments + @(
    "-N",
    "-T",
    "-o", "ExitOnForwardFailure=yes",
    "-R", $forwardSpec,
    $sshTarget
)

Write-Host "Windows source MinIO health check passed."
Write-Host "Opening: ECS 127.0.0.1:$RemoteTunnelPort -> Windows 127.0.0.1:$LocalMinioPort"
Write-Host "Keep this window open. Press Ctrl+C to close the tunnel. Run Verify mode in a second PowerShell."

& $sshCommand.Source @startArguments
exit $LASTEXITCODE
