[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$ContainerName = 'rangwaz-mysql',

    [ValidatePattern('^[A-Za-z0-9_$-]+$')]
    [string]$Database = 'rangwaz_image_dev',

    [ValidatePattern('^[A-Za-z0-9_.@%-]+$')]
    [string]$DatabaseUser = 'root',

    [string]$OutputDirectory = (Join-Path ([System.IO.Path]::GetTempPath()) 'VibeloMysqlSnapshots'),

    [string]$SnapshotName,

    [string]$ExpectedSourceVersionPrefix = '8.4.',

    [switch]$UseContainerRootPassword,

    [Parameter(Mandatory = $true)]
    [switch]$MaintenanceConfirmed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'MySqlMigration.Common.ps1')

function ConvertTo-MySqlOptionValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if ($Value.IndexOf("`0") -ge 0 -or $Value -match "[`r`n]") {
        throw '密码不能包含 NUL、回车或换行。'
    }
    return $Value.Replace('\', '\\').Replace('"', '\"')
}

function Invoke-ContainerMySql {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Sql
    )

    $result = Invoke-NativeCapture -FileName 'docker' -Arguments @(
        'exec',
        $ContainerName,
        'mysql',
        "--defaults-extra-file=$script:RemoteOptionFile",
        '--batch',
        '--skip-column-names',
        '--default-character-set=utf8mb4',
        "--database=$Database",
        '--execute',
        $Sql
    )
    return (Normalize-Newlines -Value $result.StdOut).TrimEnd("`n")
}

function Get-ExactTableCounts {
    $tableSql = @"
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = '$Database' AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;
"@
    $namesText = Invoke-ContainerMySql -Sql $tableSql
    $names = @()
    if (-not [string]::IsNullOrWhiteSpace($namesText)) {
        $names = @(($namesText -split "`n") | Where-Object { $_ -ne '' })
    }

    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($tableName in $names) {
        if ($tableName -match "[`t`r`n]") {
            throw "表名包含 TSV 无法安全表达的字符：$tableName"
        }
        $quotedTable = Quote-MySqlIdentifier -Value $tableName
        $count = (Invoke-ContainerMySql -Sql "SELECT COUNT(*) FROM $quotedTable;").Trim()
        if ($count -notmatch '^\d+$') {
            throw "无法取得表 $tableName 的精确行数，返回值：$count"
        }
        $rows.Add([pscustomobject]@{
                TableName = $tableName
                RowCount  = [Int64]::Parse($count, [System.Globalization.CultureInfo]::InvariantCulture)
            })
    }
    # Windows PowerShell 5.1 对 Generic.List 直接使用 @($rows) 会触发
    # ArgumentException；调用 ToArray 后再交给管道可保持稳定的 object[]。
    return $rows.ToArray()
}

function Convert-CountsToTsv {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Rows
    )

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("table_name`trow_count")
    foreach ($row in $Rows) {
        $lines.Add(("{0}`t{1}" -f $row.TableName, $row.RowCount))
    }
    return ($lines -join "`n") + "`n"
}

function Get-FlywayTsv {
    $exists = (Invoke-ContainerMySql -Sql @"
SELECT COUNT(*)
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = '$Database'
  AND TABLE_NAME = 'flyway_schema_history'
  AND TABLE_TYPE = 'BASE TABLE';
"@).Trim()
    if ($exists -ne '1') {
        throw "数据库 $Database 缺少 flyway_schema_history；禁止生成不完整迁移快照。"
    }

    $body = Invoke-ContainerMySql -Sql @"
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
    $tsv = "installed_rank`tversion`tdescription`ttype`tscript`tchecksum`tinstalled_by`tinstalled_on_utc`texecution_time`tsuccess`n"
    if (-not [string]::IsNullOrWhiteSpace($body)) {
        $tsv += $body.TrimEnd("`n") + "`n"
    }

    $failed = (Invoke-ContainerMySql -Sql 'SELECT COUNT(*) FROM flyway_schema_history WHERE success <> 1;').Trim()
    if ($failed -ne '0') {
        throw "flyway_schema_history 存在 $failed 条失败记录；请先修复再导出。"
    }
    return $tsv
}

function Get-ObjectInventoryTsv {
    $body = Invoke-ContainerMySql -Sql @"
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
    $tsv = "object_type`tobject_name`n"
    if (-not [string]::IsNullOrWhiteSpace($body)) {
        $tsv += $body.TrimEnd("`n") + "`n"
    }
    return $tsv
}

function Assert-CountsEqual {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Before,

        [Parameter(Mandatory = $true)]
        [object[]]$After
    )

    $beforeText = Convert-CountsToTsv -Rows $Before
    $afterText = Convert-CountsToTsv -Rows $After
    if ($beforeText -cne $afterText) {
        throw '导出期间表集合或精确行数发生变化。请停止全部写入方后重新导出。'
    }
}

if (-not $MaintenanceConfirmed) {
    throw '必须显式传入 -MaintenanceConfirmed，并先停止后端、导入器及所有写入任务。'
}

$dockerCheck = Invoke-NativeCapture -FileName 'docker' -Arguments @('version', '--format', '{{.Server.Version}}')
if ([string]::IsNullOrWhiteSpace($dockerCheck.StdOut)) {
    throw 'Docker Engine 未就绪。'
}

$containerState = Invoke-NativeCapture -FileName 'docker' -Arguments @(
    'inspect',
    '--format',
    '{{.State.Running}}',
    $ContainerName
)
if ($containerState.StdOut.Trim() -ne 'true') {
    throw "MySQL 容器未运行：$ContainerName"
}

foreach ($commandName in @('mysql', 'mysqldump', 'bash', 'gzip')) {
    [void](Invoke-NativeCapture -FileName 'docker' -Arguments @(
            'exec',
            $ContainerName,
            'bash',
            '-c',
            "command -v $commandName >/dev/null"
        ))
}

$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($outputRoot) | Out-Null
if ([string]::IsNullOrWhiteSpace($SnapshotName)) {
    $SnapshotName = '{0}-{1}' -f $Database, ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
}
if ($SnapshotName -notmatch '^[A-Za-z0-9_.-]+$') {
    throw 'SnapshotName 仅允许字母、数字、点、下划线和连字符。'
}

$paths = Get-SnapshotCompanionPaths -DumpPath (Join-Path $outputRoot ($SnapshotName + '.sql.gz'))
foreach ($destination in @(
        $paths.Dump,
        $paths.Sha256,
        $paths.RowCounts,
        $paths.Flyway,
        $paths.Objects,
        $paths.Metadata
    )) {
    if (Test-Path -LiteralPath $destination) {
        throw "目标文件已存在，脚本不会覆盖：$destination"
    }
}

$localOptionFile = [System.IO.Path]::GetTempFileName()
$script:RemoteOptionFile = '/tmp/vibelo-mysql-{0}.cnf' -f ([Guid]::NewGuid().ToString('N'))
$remoteDumpFile = '/tmp/vibelo-mysql-{0}.sql.gz' -f ([Guid]::NewGuid().ToString('N'))
$partialDump = $paths.Dump + '.partial'
$remoteOptionCreated = $false
$remoteDumpCreated = $false
$hostDumpValidated = $false
$finalFilesCreated = New-Object System.Collections.Generic.List[string]
$plainPassword = $null
$passwordPointer = [IntPtr]::Zero
$exportStartedUtc = [DateTime]::UtcNow

try {
    if ($UseContainerRootPassword) {
        if ($DatabaseUser -ne 'root') {
            throw '-UseContainerRootPassword 仅允许与 -DatabaseUser root 一起使用。'
        }

        $containerOptionScript = @'
set -Eeuo pipefail
output_file="$1"
user_name="$2"
: "${MYSQL_ROOT_PASSWORD:?容器缺少 MYSQL_ROOT_PASSWORD}"
case "$MYSQL_ROOT_PASSWORD" in
  *$'\n'*|*$'\r'*) printf '%s\n' 'MYSQL_ROOT_PASSWORD 不能包含换行' >&2; exit 2 ;;
esac
escaped_password=${MYSQL_ROOT_PASSWORD//\\/\\\\}
escaped_password=${escaped_password//\"/\\\"}
umask 077
printf '[client]\nhost=localhost\nprotocol=socket\nuser=%s\npassword="%s"\ndefault-character-set=utf8mb4\n' \
  "$user_name" "$escaped_password" > "$output_file"
chmod 600 "$output_file"
unset escaped_password
'@
        [void](Invoke-NativeCapture -FileName 'docker' -Arguments @(
                'exec',
                $ContainerName,
                'bash',
                '-c',
                $containerOptionScript,
                'vibelo-option-file',
                $script:RemoteOptionFile,
                $DatabaseUser
            ))
        $remoteOptionCreated = $true
        Write-Host '使用 MySQL 容器内现有 root 凭据；密码未离开容器。'
    }
    else {
        $securePassword = Read-Host "请输入本机 MySQL 用户 $DatabaseUser 的密码" -AsSecureString
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        $escapedPassword = ConvertTo-MySqlOptionValue -Value $plainPassword
        $optionContent = @"
[client]
host=localhost
protocol=socket
user=$DatabaseUser
password="$escapedPassword"
default-character-set=utf8mb4
"@
        Write-Utf8NoBom -Path $localOptionFile -Content ($optionContent + "`n")
        $plainPassword = $null
        $escapedPassword = $null
        $optionContent = $null
        if ($passwordPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
            $passwordPointer = [IntPtr]::Zero
        }

        [void](Invoke-NativeCapture -FileName 'docker' -Arguments @(
                'cp',
                $localOptionFile,
                ('{0}:{1}' -f $ContainerName, $script:RemoteOptionFile)
            ))
        $remoteOptionCreated = $true
        [void](Invoke-NativeCapture -FileName 'docker' -Arguments @(
                'exec',
                $ContainerName,
                'chmod',
                '600',
                $script:RemoteOptionFile
            ))
    }

    $sourceVersion = (Invoke-ContainerMySql -Sql 'SELECT VERSION();').Trim()
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSourceVersionPrefix) -and
        -not $sourceVersion.StartsWith($ExpectedSourceVersionPrefix, [StringComparison]::Ordinal)) {
        throw "源 MySQL 版本为 $sourceVersion，不符合预期前缀 $ExpectedSourceVersionPrefix"
    }
    $nonTransactionalTables = Invoke-ContainerMySql -Sql @"
SELECT CONCAT(TABLE_NAME, ':', COALESCE(ENGINE, 'NULL'))
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = '$Database'
  AND TABLE_TYPE = 'BASE TABLE'
  AND COALESCE(ENGINE, '') <> 'InnoDB'
ORDER BY TABLE_NAME;
"@
    if (-not [string]::IsNullOrWhiteSpace($nonTransactionalTables)) {
        throw "发现非 InnoDB 基础表，--single-transaction 无法保证一致性：`n$nonTransactionalTables"
    }
    $dumpClientVersion = (Invoke-NativeCapture -FileName 'docker' -Arguments @(
            'exec',
            $ContainerName,
            'mysqldump',
            '--version'
        )).StdOut.Trim()

    Write-Host '正在生成导出前的精确行数、Flyway 与对象清单...'
    $countsBefore = @(Get-ExactTableCounts)
    $flywayBefore = Get-FlywayTsv
    $objectsBefore = Get-ObjectInventoryTsv

    Write-Host '正在 MySQL 容器内生成 gzip 快照（不会经过 PowerShell 文本管道）...'
    $dumpScript = @'
set -Eeuo pipefail
option_file="$1"
database="$2"
output_file="$3"
umask 077
mysqldump \
  --defaults-extra-file="$option_file" \
  --single-transaction \
  --quick \
  --skip-add-locks \
  --skip-lock-tables \
  --routines \
  --events \
  --triggers \
  --hex-blob \
  --set-gtid-purged=OFF \
  --skip-column-statistics \
  --no-tablespaces \
  --max-allowed-packet=1G \
  --output-as-version=BEFORE_8_2_0 \
  --default-character-set=utf8mb4 \
  --tz-utc \
  --quote-names \
  "$database" | gzip -1 -c > "$output_file"
gzip -t "$output_file"
'@
    [void](Invoke-NativeCapture -FileName 'docker' -Arguments @(
            'exec',
            $ContainerName,
            'bash',
            '-c',
            $dumpScript,
            'vibelo-mysqldump',
            $script:RemoteOptionFile,
            $Database,
            $remoteDumpFile
        ))
    $remoteDumpCreated = $true

    [void](Invoke-NativeCapture -FileName 'docker' -Arguments @(
            'cp',
            ('{0}:{1}' -f $ContainerName, $remoteDumpFile),
            $partialDump
        ))

    # 宿主端再次完整解压读取，以验证 docker cp 后文件的 gzip CRC。
    Test-GzipArchive -Path $partialDump
    $hostDumpValidated = $true

    Write-Host '正在生成导出后的精确清单并确认维护窗口内数据未变化...'
    $countsAfter = @(Get-ExactTableCounts)
    $flywayAfter = Get-FlywayTsv
    $objectsAfter = Get-ObjectInventoryTsv
    Assert-CountsEqual -Before $countsBefore -After $countsAfter
    if ($flywayBefore -cne $flywayAfter) {
        throw '导出期间 Flyway 清单发生变化，请停止写入后重试。'
    }
    if ($objectsBefore -cne $objectsAfter) {
        throw '导出期间数据库对象清单发生变化，请停止 DDL 后重试。'
    }

    $dumpHash = (Get-FileHash -LiteralPath $partialDump -Algorithm SHA256).Hash.ToLowerInvariant()
    $totalRows = [Int64]0
    foreach ($row in $countsAfter) {
        $totalRows += $row.RowCount
    }
    $flywayRows = @($flywayAfter.TrimEnd("`n") -split "`n").Count - 1
    $objectRows = @($objectsAfter.TrimEnd("`n") -split "`n").Count - 1
    $exportCompletedUtc = [DateTime]::UtcNow
    $metadata = [ordered]@{
        format_version                 = 1
        source_database               = $Database
        source_container              = $ContainerName
        source_server_version         = $sourceVersion
        source_mysqldump_version      = $dumpClientVersion
        expected_restore_version      = '8.0.36'
        exported_at_utc               = $exportCompletedUtc.ToString('o')
        export_duration_seconds       = [Math]::Round(($exportCompletedUtc - $exportStartedUtc).TotalSeconds, 3)
        maintenance_confirmed         = $true
        table_count                   = $countsAfter.Count
        total_exact_rows              = $totalRows
        flyway_migration_count        = $flywayRows
        database_object_count         = $objectRows
        dump_sha256                   = $dumpHash
        rds_stream_normalization      = 'remove MySQL 8.4 sandbox directive and explicit DEFINER metadata'
    }

    Move-Item -LiteralPath $partialDump -Destination $paths.Dump
    $finalFilesCreated.Add($paths.Dump)
    Write-Utf8NoBom -Path $paths.Sha256 -Content ("$dumpHash  " + [System.IO.Path]::GetFileName($paths.Dump) + "`n")
    $finalFilesCreated.Add($paths.Sha256)
    Write-Utf8NoBom -Path $paths.RowCounts -Content (Convert-CountsToTsv -Rows $countsAfter)
    $finalFilesCreated.Add($paths.RowCounts)
    Write-Utf8NoBom -Path $paths.Flyway -Content $flywayAfter
    $finalFilesCreated.Add($paths.Flyway)
    Write-Utf8NoBom -Path $paths.Objects -Content $objectsAfter
    $finalFilesCreated.Add($paths.Objects)
    Write-Utf8NoBom -Path $paths.Metadata -Content (($metadata | ConvertTo-Json -Depth 4) + "`n")
    $finalFilesCreated.Add($paths.Metadata)

    Write-Host ''
    Write-Host 'MySQL 快照导出成功：'
    Write-Host "  Dump: $($paths.Dump)"
    Write-Host "  SHA256: $dumpHash"
    Write-Host "  表数: $($countsAfter.Count)，精确总行数: $totalRows，Flyway: $flywayRows"
}
catch {
    foreach ($created in $finalFilesCreated) {
        Remove-Item -LiteralPath $created -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $partialDump -Force -ErrorAction SilentlyContinue
    throw
}
finally {
    $plainPassword = $null
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    Remove-Item -LiteralPath $localOptionFile -Force -ErrorAction SilentlyContinue
    if ($remoteOptionCreated) {
        [void](Invoke-NativeCapture -FileName 'docker' -Arguments @(
                'exec',
                $ContainerName,
                'rm',
                '-f',
                '--',
                $script:RemoteOptionFile
            ) -AllowFailure)
    }
    if ($remoteDumpCreated -and $hostDumpValidated) {
        [void](Invoke-NativeCapture -FileName 'docker' -Arguments @(
                'exec',
                $ContainerName,
                'rm',
                '-f',
                '--',
                $remoteDumpFile
            ) -AllowFailure)
    }
    elseif ($remoteDumpCreated) {
        Write-Warning "宿主复制与 gzip 校验未全部完成，容器临时 dump 被保留以便排查：${ContainerName}:${remoteDumpFile}"
    }
}
