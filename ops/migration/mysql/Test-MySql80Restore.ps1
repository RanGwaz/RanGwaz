[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DumpPath,

    [ValidatePattern('^[A-Za-z0-9_$-]+$')]
    [string]$Database,

    [ValidatePattern('^[A-Za-z0-9_./:-]+$')]
    [string]$MySqlImage = 'mysql:8.0.36',

    [string]$ExpectedServerVersionPrefix = '8.0.36',

    [int]$StartupTimeoutSeconds = 180,

    [switch]$SkipPull,

    [switch]$KeepContainer
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'MySqlMigration.Common.ps1')

function Invoke-DrillMySql {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Sql,

        [switch]$WithoutDatabase
    )

    $arguments = @(
        'exec',
        $script:DrillContainer,
        'mysql',
        '--batch',
        '--skip-column-names',
        '--default-character-set=utf8mb4',
        '-uroot'
    )
    if (-not $WithoutDatabase) {
        $arguments += "--database=$Database"
    }
    $arguments += @('--execute', $Sql)
    $result = Invoke-NativeCapture -FileName 'docker' -Arguments $arguments
    return (Normalize-Newlines -Value $result.StdOut).TrimEnd("`n")
}

function Get-TargetCountsTsv {
    $tableNames = Invoke-DrillMySql -Sql @"
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = '$Database' AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;
"@
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("table_name`trow_count")
    if (-not [string]::IsNullOrWhiteSpace($tableNames)) {
        foreach ($tableName in ($tableNames -split "`n")) {
            $quoted = Quote-MySqlIdentifier -Value $tableName
            $count = (Invoke-DrillMySql -Sql "SELECT COUNT(*) FROM $quoted;").Trim()
            if ($count -notmatch '^\d+$') {
                throw "恢复库表 $tableName 的行数返回值无效：$count"
            }
            $lines.Add("$tableName`t$count")
        }
    }
    return ($lines -join "`n") + "`n"
}

function Get-TargetFlywayTsv {
    $body = Invoke-DrillMySql -Sql @"
SET SESSION time_zone = '+00:00';
SELECT installed_rank,
       version,
       description,
       type,
       script,
       checksum,
       installed_by,
       DATE_FORMAT(installed_on, '%Y-%m-%dT%H:%i:%s.%fZ'),
       execution_time,
       success
FROM flyway_schema_history
ORDER BY installed_rank;
"@
    $result = "installed_rank`tversion`tdescription`ttype`tscript`tchecksum`tinstalled_by`tinstalled_on_utc`texecution_time`tsuccess`n"
    if (-not [string]::IsNullOrWhiteSpace($body)) {
        $result += $body.TrimEnd("`n") + "`n"
    }
    return $result
}

function Get-TargetObjectsTsv {
    $body = Invoke-DrillMySql -Sql @"
SELECT object_type, object_name
FROM (
    SELECT IF(TABLE_TYPE = 'BASE TABLE', 'TABLE', 'VIEW') AS object_type,
           TABLE_NAME AS object_name
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = '$Database'
    UNION ALL
    SELECT ROUTINE_TYPE AS object_type, ROUTINE_NAME AS object_name
    FROM information_schema.ROUTINES
    WHERE ROUTINE_SCHEMA = '$Database'
    UNION ALL
    SELECT 'TRIGGER' AS object_type, TRIGGER_NAME AS object_name
    FROM information_schema.TRIGGERS
    WHERE TRIGGER_SCHEMA = '$Database'
    UNION ALL
    SELECT 'EVENT' AS object_type, EVENT_NAME AS object_name
    FROM information_schema.EVENTS
    WHERE EVENT_SCHEMA = '$Database'
) AS objects
ORDER BY object_type, object_name;
"@
    $result = "object_type`tobject_name`n"
    if (-not [string]::IsNullOrWhiteSpace($body)) {
        $result += $body.TrimEnd("`n") + "`n"
    }
    return $result
}

function Assert-SnapshotTsvStructure {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Rows,

        [Parameter(Mandatory = $true)]
        [string]$Flyway,

        [Parameter(Mandatory = $true)]
        [string]$Objects
    )

    $rowLines = @($Rows.TrimEnd("`n") -split "`n")
    if ($rowLines.Count -lt 2 -or $rowLines[0] -cne "table_name`trow_count") {
        throw 'row-counts.tsv 表头无效或没有数据行。'
    }
    $seenTables = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    for ($index = 1; $index -lt $rowLines.Count; $index++) {
        $parts = @($rowLines[$index] -split "`t")
        if ($parts.Count -ne 2 -or
            [string]::IsNullOrWhiteSpace($parts[0]) -or
            $parts[1] -notmatch '^\d+$' -or
            -not $seenTables.Add($parts[0])) {
            throw "row-counts.tsv 第 $($index + 1) 行格式、计数或唯一性无效。"
        }
    }

    $flywayLines = @($Flyway.TrimEnd("`n") -split "`n")
    if ($flywayLines.Count -lt 2 -or
        $flywayLines[0] -cne "installed_rank`tversion`tdescription`ttype`tscript`tchecksum`tinstalled_by`tinstalled_on_utc`texecution_time`tsuccess") {
        throw 'flyway.tsv 表头无效或没有数据行。'
    }
    for ($index = 1; $index -lt $flywayLines.Count; $index++) {
        $parts = @($flywayLines[$index] -split "`t")
        if ($parts.Count -ne 10 -or $parts[9] -cne '1') {
            throw "flyway.tsv 第 $($index + 1) 行格式无效或迁移未成功。"
        }
    }

    $objectLines = @($Objects.TrimEnd("`n") -split "`n")
    if ($objectLines.Count -lt 2 -or $objectLines[0] -cne "object_type`tobject_name") {
        throw 'objects.tsv 表头无效或没有数据行。'
    }
    $seenObjects = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    for ($index = 1; $index -lt $objectLines.Count; $index++) {
        $parts = @($objectLines[$index] -split "`t")
        $objectKey = if ($parts.Count -eq 2) { $parts[0] + "`0" + $parts[1] } else { '' }
        if ($parts.Count -ne 2 -or
            $parts[0] -notmatch '^(TABLE|VIEW|PROCEDURE|FUNCTION|TRIGGER|EVENT)$' -or
            [string]::IsNullOrWhiteSpace($parts[1]) -or
            -not $seenObjects.Add($objectKey)) {
            throw "objects.tsv 第 $($index + 1) 行格式、类型或唯一性无效。"
        }
    }
}

function Remove-ExplicitDefiner {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Line
    )

    $isConditionalMetadata = $Line -match '^\s*/\*!\d{5}.*\bDEFINER='
    $isCreateMetadata = $Line -match '^\s*CREATE\b.*\bDEFINER='
    if (-not $isConditionalMetadata -and -not $isCreateMetadata) {
        return $Line
    }

    $marker = 'DEFINER='
    $start = $Line.IndexOf($marker, [StringComparison]::Ordinal)
    if ($start -lt 0) {
        return $Line
    }
    $cursor = $start + $marker.Length

    foreach ($part in 1..2) {
        if ($Line[$cursor] -ne '`') {
            throw "无法安全解析 DEFINER 元数据：$Line"
        }
        $cursor++
        $closed = $false
        while ($cursor -lt $Line.Length) {
            if ($Line[$cursor] -eq '`') {
                if (($cursor + 1) -lt $Line.Length -and $Line[$cursor + 1] -eq '`') {
                    $cursor += 2
                    continue
                }
                $cursor++
                $closed = $true
                break
            }
            $cursor++
        }
        if (-not $closed) {
            throw "无法安全解析 DEFINER 元数据：$Line"
        }
        if ($part -eq 1) {
            if ($cursor -ge $Line.Length -or $Line[$cursor] -ne '@') {
                throw "无法安全解析 DEFINER 元数据：$Line"
            }
            $cursor++
        }
    }

    while ($cursor -lt $Line.Length -and [char]::IsWhiteSpace($Line[$cursor])) {
        $cursor++
    }
    return $Line.Substring(0, $start) + $Line.Substring($cursor)
}

function Import-NormalizedDump {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $arguments = @(
        'exec',
        '-i',
        $script:DrillContainer,
        'mysql',
        '--binary-mode=1',
        '--default-character-set=utf8mb4',
        '-uroot',
        "--database=$Database"
    )
    # 此处没有 --force；任何一条 SQL 失败都会使 mysql 客户端返回非零。
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = New-NativeProcessStartInfo `
        -FileName 'docker' `
        -Arguments $arguments `
        -RedirectStandardInput
    if (-not $process.Start()) {
        throw '无法启动 MySQL 恢复进程。'
    }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $file = $null
    $gzip = $null
    $reader = $null
    $writer = $null
    $streamError = $null
    $normalizationCount = 0
    try {
        $file = [System.IO.File]::OpenRead($Path)
        $gzip = New-Object System.IO.Compression.GZipStream(
            $file,
            [System.IO.Compression.CompressionMode]::Decompress,
            $false
        )
        $utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
        $reader = New-Object System.IO.StreamReader($gzip, $utf8Strict, $true, (1024 * 1024), $false)
        $writer = New-Object System.IO.StreamWriter(
            $process.StandardInput.BaseStream,
            (New-Object System.Text.UTF8Encoding($false)),
            (1024 * 1024),
            $false
        )
        $writer.NewLine = "`n"

        $lineNumber = 0
        while (($line = $reader.ReadLine()) -ne $null) {
            $lineNumber++
            if ($lineNumber -le 5 -and
                $line -match '^\s*/\*!\d+\\-\s+enable the sandbox mode\s+\*/\s*$') {
                $normalizationCount++
                continue
            }

            $normalized = Remove-ExplicitDefiner -Line $line
            if ($normalized -cne $line) {
                $normalizationCount++
            }
            $writer.WriteLine($normalized)
        }
        $writer.Flush()
    }
    catch {
        $streamError = $_
    }
    finally {
        if ($null -ne $writer) {
            $writerToDispose = $writer
            $writer = $null
            try {
                # StreamWriter 拥有 BaseStream；只由它关闭标准输入。
                $writerToDispose.Dispose()
            }
            catch {
                if ($null -eq $streamError) {
                    $streamError = $_
                }
            }
        }
        else {
            try {
                $process.StandardInput.Close()
            }
            catch {
                if ($null -eq $streamError) {
                    $streamError = $_
                }
            }
        }
        if ($null -ne $reader) {
            $reader.Dispose()
        }
        elseif ($null -ne $gzip) {
            $gzip.Dispose()
        }
        elseif ($null -ne $file) {
            $file.Dispose()
        }
    }

    if ($null -ne $streamError -and -not $process.HasExited) {
        try {
            $process.Kill()
        }
        catch {
            # 后续仍统一等待并读取 mysql 的 stdout/stderr。
        }
    }
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $process.ExitCode
    $process.Dispose()
    if ($exitCode -ne 0) {
        $message = $stderr.Trim()
        if ($null -ne $streamError) {
            $streamMessage = $streamError.Exception.Message
            if ([string]::IsNullOrWhiteSpace($message)) {
                $message = "快照流处理错误：$streamMessage"
            }
            else {
                $message += "`n快照流处理错误：$streamMessage"
            }
        }
        if ($message.Length -gt 3000) {
            $message = $message.Substring(0, 3000) + '...'
        }
        throw "MySQL 8.0.36 恢复失败（退出码 $exitCode）：`n$message"
    }
    if ($null -ne $streamError) {
        throw "MySQL 进程虽正常退出，但快照流处理失败：$($streamError.Exception.Message)"
    }
    if (-not [string]::IsNullOrWhiteSpace($stdout)) {
        Write-Verbose $stdout
    }
    Write-Host "兼容化处理元数据行数：$normalizationCount"
}

$paths = Get-SnapshotCompanionPaths -DumpPath $DumpPath
Assert-SnapshotArtifacts -Paths $paths
$actualHash = Assert-SnapshotSha256 -Paths $paths
Test-GzipArchive -Path $paths.Dump

$metadata = Get-Content -LiteralPath $paths.Metadata -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($Database)) {
    $Database = [string]$metadata.source_database
}
if ($Database -notmatch '^[A-Za-z0-9_$-]+$') {
    throw "元数据中的数据库名不安全：$Database"
}
if ([string]$metadata.dump_sha256 -ne $actualHash) {
    throw 'meta.json 中的 SHA256 与实际快照不一致。'
}

$expectedRows = Normalize-Newlines -Value ([System.IO.File]::ReadAllText($paths.RowCounts))
$expectedFlyway = Normalize-Newlines -Value ([System.IO.File]::ReadAllText($paths.Flyway))
$expectedObjects = Normalize-Newlines -Value ([System.IO.File]::ReadAllText($paths.Objects))
if (-not $expectedRows.StartsWith("table_name`trow_count`n", [StringComparison]::Ordinal)) {
    throw 'row-counts.tsv 表头无效。'
}
if (-not $expectedFlyway.StartsWith("installed_rank`tversion`tdescription`ttype`tscript`tchecksum`tinstalled_by`tinstalled_on_utc`texecution_time`tsuccess`n", [StringComparison]::Ordinal)) {
    throw 'flyway.tsv 表头无效。'
}
if (-not $expectedObjects.StartsWith("object_type`tobject_name`n", [StringComparison]::Ordinal)) {
    throw 'objects.tsv 表头无效。'
}
Assert-SnapshotTsvStructure `
    -Rows $expectedRows `
    -Flyway $expectedFlyway `
    -Objects $expectedObjects

[void](Invoke-NativeCapture -FileName 'docker' -Arguments @('version', '--format', '{{.Server.Version}}'))
$imageCheck = Invoke-NativeCapture -FileName 'docker' -Arguments @(
    'image',
    'inspect',
    $MySqlImage
) -AllowFailure
if ($imageCheck.ExitCode -ne 0) {
    if ($SkipPull) {
        throw "本机没有镜像 $MySqlImage，且已指定 -SkipPull。"
    }
    Write-Host "本机没有 $MySqlImage，正在拉取（不会构建镜像）..."
    [void](Invoke-NativeCapture -FileName 'docker' -Arguments @('pull', $MySqlImage))
}

$script:DrillContainer = 'vibelo-mysql80-restore-{0}-{1}' -f $PID, ([Guid]::NewGuid().ToString('N').Substring(0, 8))
$containerStarted = $false
try {
    $run = Invoke-NativeCapture -FileName 'docker' -Arguments @(
        'run',
        '--detach',
        '--rm',
        '--network=none',
        '--name',
        $script:DrillContainer,
        '--env',
        'MYSQL_ALLOW_EMPTY_PASSWORD=yes',
        '--env',
        "MYSQL_DATABASE=$Database",
        '--env',
        'TZ=UTC',
        $MySqlImage,
        '--character-set-server=utf8mb4',
        '--collation-server=utf8mb4_0900_ai_ci'
    )
    $containerStarted = $true

    Write-Host "等待临时 MySQL 8.0.36 就绪：$($script:DrillContainer)"
    $ready = $false
    $consecutiveReadyChecks = 0
    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        # 官方 MySQL entrypoint 会先启动一个临时初始化实例；mysqladmin ping
        # 在业务库创建前就可能成功。只有容器 PID 1 已经 exec 为最终 mysqld，
        # 且连续两次确认目标库存在，才允许开始大文件恢复。
        $processProbe = Invoke-NativeCapture -FileName 'docker' -Arguments @(
            'exec',
            $script:DrillContainer,
            'cat',
            '/proc/1/comm'
        ) -AllowFailure
        $databaseProbe = Invoke-NativeCapture -FileName 'docker' -Arguments @(
            'exec',
            $script:DrillContainer,
            'mysql',
            '--batch',
            '--skip-column-names',
            '-uroot',
            '--execute',
            "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$Database';"
        ) -AllowFailure
        if ($processProbe.ExitCode -eq 0 -and
            $processProbe.StdOut.Trim() -eq 'mysqld' -and
            $databaseProbe.ExitCode -eq 0 -and
            $databaseProbe.StdOut.Trim() -eq '1') {
            $consecutiveReadyChecks++
            if ($consecutiveReadyChecks -ge 2) {
                $ready = $true
                break
            }
        }
        else {
            $consecutiveReadyChecks = 0
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        $logs = (Invoke-NativeCapture -FileName 'docker' -Arguments @(
                'logs',
                '--tail',
                '100',
                $script:DrillContainer
            ) -AllowFailure).StdErr
        throw "临时 MySQL 未在 $StartupTimeoutSeconds 秒内就绪：`n$logs"
    }

    $serverVersion = (Invoke-DrillMySql -Sql 'SELECT VERSION();' -WithoutDatabase).Trim()
    if (-not $serverVersion.StartsWith($ExpectedServerVersionPrefix, [StringComparison]::Ordinal)) {
        throw "恢复演练服务端版本为 $serverVersion，不符合预期 $ExpectedServerVersionPrefix"
    }
    $objectCountBefore = (Invoke-DrillMySql -Sql @"
SELECT
  (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$Database') +
  (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = '$Database') +
  (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = '$Database') +
  (SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA = '$Database');
"@).Trim()
    if ($objectCountBefore -ne '0') {
        throw "临时恢复库不是空库（对象数 $objectCountBefore）。"
    }

    Write-Host '开始向临时 MySQL 8.0.36 恢复并执行兼容化元数据处理...'
    Import-NormalizedDump -Path $paths.Dump

    Write-Host '执行表集合、逐表精确行数、Flyway 与对象清单核验...'
    $actualRows = Get-TargetCountsTsv
    $actualFlyway = Get-TargetFlywayTsv
    $actualObjects = Get-TargetObjectsTsv
    if ($actualRows -cne $expectedRows) {
        throw '恢复演练失败：逐表精确行数或表集合与源清单不一致。'
    }
    if ($actualFlyway -cne $expectedFlyway) {
        throw '恢复演练失败：Flyway 清单与源清单不一致。'
    }
    if ($actualObjects -cne $expectedObjects) {
        throw '恢复演练失败：数据库对象清单与源清单不一致。'
    }

    $proof = [ordered]@{
        format_version            = 1
        dump_sha256               = $actualHash
        tested_server_version     = $serverVersion
        tested_at_utc             = [DateTime]::UtcNow.ToString('o')
        exact_row_counts_verified = $true
        flyway_verified           = $true
        object_inventory_verified = $true
        normalization             = 'remove MySQL 8.4 sandbox directive and explicit DEFINER metadata'
    }
    $proofPartial = $paths.RestoreProof + '.partial'
    Write-Utf8NoBom -Path $proofPartial -Content (($proof | ConvertTo-Json -Depth 4) + "`n")
    Move-Item -LiteralPath $proofPartial -Destination $paths.RestoreProof -Force

    Write-Host ''
    Write-Host "恢复演练通过：MySQL $serverVersion，SHA256 $actualHash"
    Write-Host "演练凭据：$($paths.RestoreProof)"
    Write-Host '可进入 RDS 导入阶段。'
}
finally {
    if ($containerStarted) {
        if ($KeepContainer) {
            Write-Warning "已按 -KeepContainer 保留临时容器：$($script:DrillContainer)。该容器无网络且 root 为空密码。"
        }
        else {
            [void](Invoke-NativeCapture -FileName 'docker' -Arguments @(
                    'rm',
                    '--force',
                    $script:DrillContainer
                ) -AllowFailure)
        }
    }
}
