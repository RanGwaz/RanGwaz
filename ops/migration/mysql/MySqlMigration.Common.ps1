# MySQL 迁移 PowerShell 脚本的内部公共函数。
# 本文件不应单独执行。

function ConvertTo-NativeArgument {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    # 遵循 Windows CommandLineToArgvW 的反斜杠/双引号转义规则。
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashCount = 0

    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashCount++
            continue
        }

        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($backslashCount * 2) + 1)))
            [void]$builder.Append('"')
            $backslashCount = 0
            continue
        }

        if ($backslashCount -gt 0) {
            [void]$builder.Append(('\' * $backslashCount))
            $backslashCount = 0
        }
        [void]$builder.Append($character)
    }

    if ($backslashCount -gt 0) {
        [void]$builder.Append(('\' * ($backslashCount * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function New-NativeProcessStartInfo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FileName,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [switch]$RedirectStandardInput
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FileName
    $startInfo.Arguments = (($Arguments | ForEach-Object { ConvertTo-NativeArgument -Value $_ }) -join ' ')
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.RedirectStandardInput = [bool]$RedirectStandardInput
    # Docker/Linux 工具统一输出 UTF-8；Windows PowerShell 5.1 默认 OEM 解码会破坏中文 Flyway 字段。
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $startInfo.StandardOutputEncoding = $utf8
    $startInfo.StandardErrorEncoding = $utf8
    return $startInfo
}

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FileName,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [switch]$AllowFailure
    )

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = New-NativeProcessStartInfo -FileName $FileName -Arguments $Arguments
    if (-not $process.Start()) {
        throw "无法启动命令：$FileName"
    }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $process.ExitCode
    $process.Dispose()

    if ($exitCode -ne 0 -and -not $AllowFailure) {
        $message = $stderr.Trim()
        if ([string]::IsNullOrWhiteSpace($message)) {
            $message = $stdout.Trim()
        }
        if ($message.Length -gt 2000) {
            $message = $message.Substring(0, 2000) + '...'
        }
        throw "命令执行失败（退出码 $exitCode）：$FileName`n$message"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        StdOut  = $stdout
        StdErr  = $stderr
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Normalize-Newlines {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    return (($Value -replace "`r`n", "`n") -replace "`r", "`n")
}

function Quote-MySqlIdentifier {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return '`' + $Value.Replace('`', '``') + '`'
}

function Get-SnapshotCompanionPaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DumpPath
    )

    $resolvedDump = [System.IO.Path]::GetFullPath($DumpPath)
    if (-not $resolvedDump.EndsWith('.sql.gz', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "快照文件名必须以 .sql.gz 结尾：$resolvedDump"
    }

    $prefix = $resolvedDump.Substring(0, $resolvedDump.Length - '.sql.gz'.Length)
    return [pscustomobject]@{
        Dump      = $resolvedDump
        Sha256    = $prefix + '.sha256'
        RowCounts = $prefix + '.row-counts.tsv'
        Flyway    = $prefix + '.flyway.tsv'
        Objects   = $prefix + '.objects.tsv'
        Metadata  = $prefix + '.meta.json'
        RestoreProof = $prefix + '.restore-tested.json'
    }
}

function Assert-SnapshotArtifacts {
    param(
        [Parameter(Mandatory = $true)]
        $Paths
    )

    foreach ($path in @(
            $Paths.Dump,
            $Paths.Sha256,
            $Paths.RowCounts,
            $Paths.Flyway,
            $Paths.Objects,
            $Paths.Metadata
        )) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "缺少迁移快照文件：$path"
        }
    }
}

function Test-GzipArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $file = $null
    $gzip = $null
    try {
        $file = [System.IO.File]::OpenRead($Path)
        $gzip = New-Object System.IO.Compression.GZipStream(
            $file,
            [System.IO.Compression.CompressionMode]::Decompress,
            $false
        )
        $buffer = New-Object byte[] (1024 * 1024)
        while ($gzip.Read($buffer, 0, $buffer.Length) -gt 0) {
            # 读取到 EOF 会同时校验 gzip 尾部 CRC，不把二进制交给 PowerShell 文本管道。
        }
    }
    finally {
        if ($null -ne $gzip) {
            $gzip.Dispose()
        }
        if ($null -ne $file) {
            $file.Dispose()
        }
    }
}

function Get-ExpectedSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Sha256Path
    )

    $line = ([System.IO.File]::ReadAllLines($Sha256Path) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -First 1)
    if ($null -eq $line -or $line -notmatch '^\s*([0-9a-fA-F]{64})\s+') {
        throw "SHA256 清单格式无效：$Sha256Path"
    }
    return $Matches[1].ToLowerInvariant()
}

function Assert-SnapshotSha256 {
    param(
        [Parameter(Mandatory = $true)]
        $Paths
    )

    $expected = Get-ExpectedSha256 -Sha256Path $Paths.Sha256
    $actual = (Get-FileHash -LiteralPath $Paths.Dump -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "快照 SHA256 不一致。期望 $expected，实际 $actual"
    }
    return $actual
}
