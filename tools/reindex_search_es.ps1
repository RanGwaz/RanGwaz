param(
    [string]$Python = "python",
    [string]$MysqlHost = "",
    [int]$MysqlPort = 0,
    [string]$MysqlDatabase = "",
    [string]$MysqlUser = "",
    [string]$MysqlPassword = "",
    [string]$EsUrl = "",
    [string]$EsIndex = "",
    [int]$BatchSize = 0,
    [int]$Limit = 0,
    [switch]$NoRecreate,
    [switch]$ReplaceConflictingIndex,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $env:PYTHONIOENCODING) {
    $env:PYTHONIOENCODING = "utf-8"
}

$ToolsDir = $PSScriptRoot
$RootDir = Resolve-Path (Join-Path $ToolsDir "..")
$Script = Join-Path $ToolsDir "reindex_search_es.py"

$Arguments = @($Script)
if ($MysqlHost) { $Arguments += @("--mysql-host", $MysqlHost) }
if ($MysqlPort -gt 0) { $Arguments += @("--mysql-port", [string]$MysqlPort) }
if ($MysqlDatabase) { $Arguments += @("--mysql-database", $MysqlDatabase) }
if ($MysqlUser) { $Arguments += @("--mysql-user", $MysqlUser) }
if ($MysqlPassword) { $Arguments += @("--mysql-password", $MysqlPassword) }
if ($EsUrl) { $Arguments += @("--es-url", $EsUrl) }
if ($EsIndex) { $Arguments += @("--es-index", $EsIndex) }
if ($BatchSize -gt 0) { $Arguments += @("--batch-size", [string]$BatchSize) }
if ($Limit -gt 0) { $Arguments += @("--limit", [string]$Limit) }
if ($NoRecreate) { $Arguments += "--no-recreate" }
if ($ReplaceConflictingIndex) { $Arguments += "--replace-conflicting-index" }
if ($DryRun) { $Arguments += "--dry-run" }

Set-Location $RootDir
& $Python @Arguments
exit $LASTEXITCODE
