[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $env:TEMP "vibelo-search-reindex")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$wheelName = "pymysql-1.1.2-py3-none-any.whl"
$wheelSize = 45300L
$wheelSha256 = "e6b1d89711dd51f8f74b1631fe08f039e7d76cf67a42a323d3178f0f25762ed9"
$wheelUrl = "https://files.pythonhosted.org/packages/7c/4c/ad33b92b9864cbde84f259d5df035a6447f91891f5be77788e2a3892bce3/pymysql-1.1.2-py3-none-any.whl"

function Assert-Wheel {
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) {
        throw "目标不是普通文件：$Path"
    }
    if ($item.Length -ne $wheelSize) {
        throw "PyMySQL wheel 尺寸错误：$($item.Length)，预期 $wheelSize"
    }
    $actualSha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $wheelSha256) {
        throw "PyMySQL wheel SHA256 错误：$actualSha256"
    }
}

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null
$wheelPath = Join-Path $resolvedOutput $wheelName

if (Test-Path -LiteralPath $wheelPath) {
    Assert-Wheel -Path $wheelPath
    Write-Host "固定 PyMySQL wheel 已存在且校验通过：$wheelPath"
    exit 0
}

$temporaryPath = "$wheelPath.download-$([Guid]::NewGuid().ToString('N'))"
try {
    Invoke-WebRequest -Uri $wheelUrl -OutFile $temporaryPath -UseBasicParsing
    Assert-Wheel -Path $temporaryPath
    Move-Item -LiteralPath $temporaryPath -Destination $wheelPath
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}

Assert-Wheel -Path $wheelPath
Write-Host "固定 PyMySQL wheel 下载并校验完成：$wheelPath"
Write-Host "SHA256：$wheelSha256"
