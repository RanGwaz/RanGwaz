#!/usr/bin/env bash
#
# 将已经通过 MySQL 8.0.36 本机恢复演练的快照导入阿里云 RDS MySQL。
# 密码只从终端静默读取，或从当前用户拥有且权限为 0600 的文件读取。

set -Eeuo pipefail
IFS=$'\n\t'

# 即使调用者误用 bash -x，也不要让随后写入客户端配置的密码出现在跟踪输出。
case "$-" in
  *x*) set +x ;;
esac
umask 077

SCRIPT_NAME="$(basename "$0")"
DUMP_FILE=""
SHA256_FILE=""
ROW_COUNTS_FILE=""
FLYWAY_FILE=""
OBJECTS_FILE=""
METADATA_FILE=""
RESTORE_PROOF_FILE=""
RDS_HOST=""
RDS_PORT="3306"
DATABASE="rangwaz_image_dev"
ADMIN_USER=""
ADMIN_PASSWORD_FILE=""
APP_USER="vibelo_app"
APP_PASSWORD_FILE=""
MYSQL_IMAGE="mysql:8.0.36"
EXPECTED_SERVER_VERSION="8.0.36"
EXPECTED_CHARSET="utf8mb4"
EXPECTED_COLLATION="utf8mb4_0900_ai_ci"
SSL_MODE="PREFERRED"
PULL_IF_MISSING=1
CONFIRM_IMPORT=0

TEMP_DIR=""
ADMIN_CONFIG=""
APP_CONFIG=""
PROBE_TABLE=""
PROBE_ACTIVE=0
IMPORT_STARTED=0

usage() {
  cat <<'EOF'
用法：
  import-mysql-snapshot-to-rds.sh \
    --dump /data/migration/rangwaz_image_dev-时间.sql.gz \
    --host rm-xxxx.mysql.rds.aliyuncs.com \
    --admin-user <RDS高权限迁移账号> \
    [--admin-password-file /root/admin.password] \
    [--app-user vibelo_app] \
    [--app-password-file /root/app.password] \
    --confirm-import

必填：
  --dump                 .sql.gz 快照；其余清单默认按同名前缀查找
  --host                 RDS 内网地址
  --admin-user           只用于本次导入的 RDS 高权限账号
  --confirm-import       明确确认向经过空库检查的目标库导入

可选：
  --port                 默认 3306
  --database             默认 rangwaz_image_dev
  --app-user             验收及应用运行账号，默认 vibelo_app
  --admin-password-file  仅一行密码、属主为当前用户、权限必须恰好 0600
  --app-password-file    规则同上；不提供时分别从终端静默读取
  --sha256-file PATH     默认 <前缀>.sha256
  --row-counts-file PATH 默认 <前缀>.row-counts.tsv
  --flyway-file PATH     默认 <前缀>.flyway.tsv
  --objects-file PATH    默认 <前缀>.objects.tsv
  --metadata-file PATH   默认 <前缀>.meta.json
  --restore-proof PATH   默认 <前缀>.restore-tested.json
  --mysql-image IMAGE    默认 mysql:8.0.36；只 pull，绝不 build
  --no-pull              镜像不存在时直接失败
  --ssl-mode MODE        默认 PREFERRED
  --expected-version VER 默认 8.0.36
  --help

禁止把 RDS 高权限账号或 dms_user_* 自动托管账号配置给应用。
EOF
}

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

cleanup() {
  local status=$?
  set +e

  if [[ "$PROBE_ACTIVE" -eq 1 && -n "$ADMIN_CONFIG" && -f "$ADMIN_CONFIG" && -n "$PROBE_TABLE" ]]; then
    admin_mysql --database="$DATABASE" \
      --execute="DROP VIEW IF EXISTS \`${PROBE_TABLE}_view\`; DROP TRIGGER IF EXISTS \`${PROBE_TABLE}_trigger\`; DROP PROCEDURE IF EXISTS \`${PROBE_TABLE}_procedure\`; DROP FUNCTION IF EXISTS \`${PROBE_TABLE}_function\`; DROP EVENT IF EXISTS \`${PROBE_TABLE}_event\`; DROP TABLE IF EXISTS \`${PROBE_TABLE}\`;" \
      >/dev/null 2>&1
  fi

  unset ADMIN_PASSWORD APP_PASSWORD password escaped_password
  if [[ -n "$TEMP_DIR" && "$TEMP_DIR" == /tmp/vibelo-mysql-rds.* && -d "$TEMP_DIR" ]]; then
    rm -rf -- "$TEMP_DIR"
  fi

  if [[ "$status" -ne 0 && "$IMPORT_STARTED" -eq 1 ]]; then
    printf '%s\n' \
      '导入已经开始但未成功完成。MySQL DDL 不能整体回滚；请先重建/清空目标库，再从头执行，切勿使用 --force 跳过错误。' \
      >&2
  fi
  exit "$status"
}
trap cleanup EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dump) DUMP_FILE="${2:?--dump 缺少值}"; shift 2 ;;
    --host) RDS_HOST="${2:?--host 缺少值}"; shift 2 ;;
    --port) RDS_PORT="${2:?--port 缺少值}"; shift 2 ;;
    --database) DATABASE="${2:?--database 缺少值}"; shift 2 ;;
    --admin-user) ADMIN_USER="${2:?--admin-user 缺少值}"; shift 2 ;;
    --admin-password-file) ADMIN_PASSWORD_FILE="${2:?--admin-password-file 缺少值}"; shift 2 ;;
    --app-user) APP_USER="${2:?--app-user 缺少值}"; shift 2 ;;
    --app-password-file) APP_PASSWORD_FILE="${2:?--app-password-file 缺少值}"; shift 2 ;;
    --sha256-file) SHA256_FILE="${2:?--sha256-file 缺少值}"; shift 2 ;;
    --row-counts-file) ROW_COUNTS_FILE="${2:?--row-counts-file 缺少值}"; shift 2 ;;
    --flyway-file) FLYWAY_FILE="${2:?--flyway-file 缺少值}"; shift 2 ;;
    --objects-file) OBJECTS_FILE="${2:?--objects-file 缺少值}"; shift 2 ;;
    --metadata-file) METADATA_FILE="${2:?--metadata-file 缺少值}"; shift 2 ;;
    --restore-proof) RESTORE_PROOF_FILE="${2:?--restore-proof 缺少值}"; shift 2 ;;
    --mysql-image) MYSQL_IMAGE="${2:?--mysql-image 缺少值}"; shift 2 ;;
    --expected-version) EXPECTED_SERVER_VERSION="${2:?--expected-version 缺少值}"; shift 2 ;;
    --ssl-mode) SSL_MODE="${2:?--ssl-mode 缺少值}"; shift 2 ;;
    --no-pull) PULL_IF_MISSING=0; shift ;;
    --confirm-import) CONFIRM_IMPORT=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "未知参数：$1（使用 --help 查看说明）" ;;
  esac
done

[[ -n "$DUMP_FILE" ]] || die '缺少 --dump'
[[ -n "$RDS_HOST" ]] || die '缺少 --host'
[[ -n "$ADMIN_USER" ]] || die '缺少 --admin-user'
[[ "$CONFIRM_IMPORT" -eq 1 ]] || die '必须显式传入 --confirm-import'
[[ "$DUMP_FILE" == *.sql.gz ]] || die '--dump 必须以 .sql.gz 结尾'
[[ "$RDS_HOST" =~ ^[A-Za-z0-9.-]+$ ]] || die 'RDS host 格式不安全'
[[ "$RDS_PORT" =~ ^[0-9]+$ ]] && ((RDS_PORT >= 1 && RDS_PORT <= 65535)) || die 'RDS port 无效'
[[ "$DATABASE" =~ ^[A-Za-z0-9_$-]+$ ]] || die '数据库名格式不安全'
[[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.@%-]+$ ]] || die '迁移账号名格式不安全'
[[ "$APP_USER" =~ ^[A-Za-z0-9_.@%-]+$ ]] || die '应用账号名格式不安全'
[[ "$MYSQL_IMAGE" =~ ^[A-Za-z0-9_./:@-]+$ ]] || die 'MySQL 镜像名格式不安全'
[[ "$EXPECTED_SERVER_VERSION" =~ ^[0-9]+([.][0-9]+){1,2}$ ]] || die '预期版本格式无效'
[[ "$SSL_MODE" =~ ^(DISABLED|PREFERRED|REQUIRED|VERIFY_CA|VERIFY_IDENTITY)$ ]] || die 'ssl-mode 无效'
[[ "$ADMIN_USER" != dms_user_* ]] || die 'dms_user_* 是 DMS 自动托管账号，禁止用于数据库迁移'
[[ "$APP_USER" != dms_user_* ]] || die 'dms_user_* 是 DMS 自动托管账号，禁止用于应用运行'
[[ "$ADMIN_USER" != "$APP_USER" ]] || die '迁移高权限账号与应用账号必须分离'

DUMP_FILE="$(readlink -f -- "$DUMP_FILE")"
prefix="${DUMP_FILE%.sql.gz}"
SHA256_FILE="${SHA256_FILE:-${prefix}.sha256}"
ROW_COUNTS_FILE="${ROW_COUNTS_FILE:-${prefix}.row-counts.tsv}"
FLYWAY_FILE="${FLYWAY_FILE:-${prefix}.flyway.tsv}"
OBJECTS_FILE="${OBJECTS_FILE:-${prefix}.objects.tsv}"
METADATA_FILE="${METADATA_FILE:-${prefix}.meta.json}"
RESTORE_PROOF_FILE="${RESTORE_PROOF_FILE:-${prefix}.restore-tested.json}"

for artifact in \
  "$DUMP_FILE" \
  "$SHA256_FILE" \
  "$ROW_COUNTS_FILE" \
  "$FLYWAY_FILE" \
  "$OBJECTS_FILE" \
  "$METADATA_FILE" \
  "$RESTORE_PROOF_FILE"; do
  [[ -f "$artifact" ]] || die "缺少快照或门禁文件：$artifact"
done

for command_name in docker gzip sha256sum awk diff stat mktemp readlink; do
  command -v "$command_name" >/dev/null 2>&1 || die "缺少命令：$command_name"
done
docker info >/dev/null 2>&1 || die 'Docker Engine 未就绪'

expected_sha="$(awk 'NF { print $1; exit }' "$SHA256_FILE")"
[[ "$expected_sha" =~ ^[0-9a-fA-F]{64}$ ]] || die 'SHA256 清单格式无效'
expected_sha="${expected_sha,,}"
actual_sha="$(sha256sum -- "$DUMP_FILE")"
actual_sha="${actual_sha%% *}"
actual_sha="${actual_sha,,}"
[[ "$actual_sha" == "$expected_sha" ]] || die "dump SHA256 不一致：期望 $expected_sha，实际 $actual_sha"
gzip -t -- "$DUMP_FILE" || die 'gzip 完整性校验失败'

metadata_database="$(awk -F'"' '/^[[:space:]]*"source_database"[[:space:]]*:/ { print $4; exit }' "$METADATA_FILE")"
[[ "$metadata_database" == "$DATABASE" ]] || die "meta.json 数据库名为 $metadata_database，与参数 $DATABASE 不一致"
metadata_sha="$(awk -F'"' '/^[[:space:]]*"dump_sha256"[[:space:]]*:/ { print $4; exit }' "$METADATA_FILE")"
[[ "${metadata_sha,,}" == "$actual_sha" ]] || die 'meta.json 中 SHA256 与 dump 不一致'
proof_sha="$(awk -F'"' '/^[[:space:]]*"dump_sha256"[[:space:]]*:/ { print $4; exit }' "$RESTORE_PROOF_FILE")"
proof_version="$(awk -F'"' '/^[[:space:]]*"tested_server_version"[[:space:]]*:/ { print $4; exit }' "$RESTORE_PROOF_FILE")"
proof_rows="$(awk -F: '/^[[:space:]]*"exact_row_counts_verified"[[:space:]]*:/ { gsub(/[ ,]/, "", $2); print $2; exit }' "$RESTORE_PROOF_FILE")"
proof_flyway="$(awk -F: '/^[[:space:]]*"flyway_verified"[[:space:]]*:/ { gsub(/[ ,]/, "", $2); print $2; exit }' "$RESTORE_PROOF_FILE")"
proof_objects="$(awk -F: '/^[[:space:]]*"object_inventory_verified"[[:space:]]*:/ { gsub(/[ ,]/, "", $2); print $2; exit }' "$RESTORE_PROOF_FILE")"
[[ "${proof_sha,,}" == "$actual_sha" ]] || die '恢复演练凭据不属于当前 dump'
[[ "$proof_version" == "$EXPECTED_SERVER_VERSION"* ]] || die "恢复演练版本 $proof_version 不符合 $EXPECTED_SERVER_VERSION"
[[ "$proof_rows" == 'true' &&
  "$proof_flyway" == 'true' &&
  "$proof_objects" == 'true' ]] ||
  die '恢复演练凭据未通过精确行数、Flyway 或对象清单门禁'

awk -F '\t' '
  NR == 1 {
    sub(/\r$/, "", $2)
    if ($1 != "table_name" || $2 != "row_count" || NF != 2) exit 10
    next
  }
  {
    sub(/\r$/, "", $2)
    if (NF != 2 || $1 == "" || $2 !~ /^[0-9]+$/ || seen[$1]++) exit 11
  }
  END { if (NR < 2) exit 12 }
' "$ROW_COUNTS_FILE" || die 'row-counts.tsv 格式、重复项或精确行数无效'

awk -F '\t' '
  NR == 1 {
    sub(/\r$/, "", $10)
    if ($1 != "installed_rank" || $10 != "success" || NF != 10) exit 20
    next
  }
  {
    sub(/\r$/, "", $10)
    if (NF != 10 || $10 != "1") exit 21
  }
' "$FLYWAY_FILE" || die 'flyway.tsv 格式无效或包含失败迁移'

awk -F '\t' '
  NR == 1 {
    sub(/\r$/, "", $2)
    if ($1 != "object_type" || $2 != "object_name" || NF != 2) exit 30
    next
  }
  {
    sub(/\r$/, "", $2)
    if (NF != 2 || $1 !~ /^(TABLE|VIEW|PROCEDURE|FUNCTION|TRIGGER|EVENT)$/ || $2 == "" || seen[$1 SUBSEP $2]++) exit 31
  }
' "$OBJECTS_FILE" || die 'objects.tsv 格式、类型或重复项无效'

if ! docker image inspect "$MYSQL_IMAGE" >/dev/null 2>&1; then
  [[ "$PULL_IF_MISSING" -eq 1 ]] || die "本机没有镜像 $MYSQL_IMAGE，且指定了 --no-pull"
  printf '本机没有 %s，开始拉取；脚本不会构建任何镜像。\n' "$MYSQL_IMAGE"
  docker pull "$MYSQL_IMAGE"
fi
client_version="$(docker run --rm --network none "$MYSQL_IMAGE" mysql --version)"
[[ "$client_version" == *"$EXPECTED_SERVER_VERSION"* ]] || die "客户端镜像版本不符合预期：$client_version"

TEMP_DIR="$(mktemp -d /tmp/vibelo-mysql-rds.XXXXXXXX)"
chmod 700 "$TEMP_DIR"
ADMIN_CONFIG="$TEMP_DIR/admin.cnf"
APP_CONFIG="$TEMP_DIR/app.cnf"

load_password() {
  local password_file="$1"
  local prompt="$2"
  local target_variable="$3"
  local loaded_password=""

  if [[ -n "$password_file" ]]; then
    [[ -f "$password_file" ]] || die "密码文件不存在：$password_file"
    [[ "$(stat -c '%a' "$password_file")" == '600' ]] || die "密码文件权限必须恰好为 0600：$password_file"
    [[ "$(stat -c '%u' "$password_file")" == "$(id -u)" ]] || die "密码文件必须属于当前用户：$password_file"
    loaded_password="$(<"$password_file")"
  else
    IFS= read -r -s -p "$prompt" loaded_password
    printf '\n'
  fi

  [[ -n "$loaded_password" ]] || die '密码不能为空'
  [[ "$loaded_password" != *$'\n'* && "$loaded_password" != *$'\r'* ]] || die '密码不能包含换行'
  printf -v "$target_variable" '%s' "$loaded_password"
  loaded_password=""
}

write_client_config() {
  local config_path="$1"
  local user_name="$2"
  local raw_password="$3"
  local escaped="$raw_password"
  escaped="${escaped//\\/\\\\}"
  escaped="${escaped//\"/\\\"}"

  {
    printf '[client]\n'
    printf 'host=%s\n' "$RDS_HOST"
    printf 'port=%s\n' "$RDS_PORT"
    printf 'protocol=TCP\n'
    printf 'user=%s\n' "$user_name"
    printf 'password="%s"\n' "$escaped"
    printf 'default-character-set=utf8mb4\n'
    printf 'ssl-mode=%s\n' "$SSL_MODE"
  } >"$config_path"
  chmod 600 "$config_path"
}

load_password "$ADMIN_PASSWORD_FILE" '请输入 RDS 高权限迁移账号密码：' ADMIN_PASSWORD
write_client_config "$ADMIN_CONFIG" "$ADMIN_USER" "$ADMIN_PASSWORD"
unset ADMIN_PASSWORD
load_password "$APP_PASSWORD_FILE" "请输入 RDS 应用账号 $APP_USER 的密码：" APP_PASSWORD
write_client_config "$APP_CONFIG" "$APP_USER" "$APP_PASSWORD"
unset APP_PASSWORD

mysql_with_config() {
  local config_path="$1"
  shift
  docker run --rm \
    --interactive \
    --network host \
    --volume "$config_path:/run/secrets/mysql.cnf:ro" \
    "$MYSQL_IMAGE" \
    mysql \
    --defaults-extra-file=/run/secrets/mysql.cnf \
    --connect-timeout=10 \
    "$@"
}

admin_mysql() {
  mysql_with_config "$ADMIN_CONFIG" "$@"
}

app_mysql() {
  mysql_with_config "$APP_CONFIG" "$@"
}

admin_query() {
  local sql="$1"
  admin_mysql --batch --skip-column-names --database="$DATABASE" --execute="$sql"
}

app_query() {
  local sql="$1"
  app_mysql --batch --skip-column-names --database="$DATABASE" --execute="$sql"
}

database_exists="$(admin_mysql --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$DATABASE';")"
[[ "$database_exists" == '1' ]] || die "目标数据库不存在：$DATABASE"

server_version="$(admin_mysql --batch --skip-column-names --execute='SELECT VERSION();')"
[[ "$server_version" == "$EXPECTED_SERVER_VERSION"* ]] || die "RDS 版本 $server_version 不符合 $EXPECTED_SERVER_VERSION"
database_settings="$(admin_query "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$DATABASE';")"
[[ "$database_settings" == "${EXPECTED_CHARSET}"$'\t'"${EXPECTED_COLLATION}" ]] ||
  die "目标库字符集/排序规则为 $database_settings，预期 ${EXPECTED_CHARSET}/${EXPECTED_COLLATION}"

object_count_before="$(admin_query "
SELECT
  (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$DATABASE') +
  (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = '$DATABASE') +
  (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = '$DATABASE') +
  (SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA = '$DATABASE');
")"
[[ "$object_count_before" == '0' ]] || die "目标库不是空库（对象数 $object_count_before）；脚本拒绝覆盖"

# 在仍为空库时验证 vibelo_app 的 DDL/DML 权限，成功后立即清理探针。
PROBE_TABLE="__vibelo_migration_probe_${$}"
PROBE_ACTIVE=1
app_query "
CREATE TABLE \`${PROBE_TABLE}\` (id BIGINT NOT NULL PRIMARY KEY, value_text VARCHAR(32) NOT NULL);
INSERT INTO \`${PROBE_TABLE}\` (id, value_text) VALUES (1, 'probe');
UPDATE \`${PROBE_TABLE}\` SET value_text = 'checked' WHERE id = 1;
DELETE FROM \`${PROBE_TABLE}\` WHERE id = 1;
ALTER TABLE \`${PROBE_TABLE}\` ADD COLUMN checked_at DATETIME(6) NULL;
CREATE INDEX \`${PROBE_TABLE}_idx\` ON \`${PROBE_TABLE}\` (value_text);
DROP INDEX \`${PROBE_TABLE}_idx\` ON \`${PROBE_TABLE}\`;
CREATE VIEW \`${PROBE_TABLE}_view\` AS SELECT id, value_text FROM \`${PROBE_TABLE}\`;
DROP VIEW \`${PROBE_TABLE}_view\`;
CREATE PROCEDURE \`${PROBE_TABLE}_procedure\`() SELECT 1;
DROP PROCEDURE \`${PROBE_TABLE}_procedure\`;
DROP TABLE \`${PROBE_TABLE}\`;
" >/dev/null
PROBE_ACTIVE=0

object_count_after_probe="$(admin_query "
SELECT
  (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$DATABASE') +
  (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = '$DATABASE') +
  (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = '$DATABASE') +
  (SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA = '$DATABASE');
")"
[[ "$object_count_after_probe" == '0' ]] || die '权限探针清理后目标库仍非空，禁止导入'

printf '%s\n' \
  'RDS 导入门禁通过：' \
  "  地址：${RDS_HOST}:${RDS_PORT}" \
  "  数据库：${DATABASE}" \
  "  服务端：${server_version}" \
  "  迁移账号：${ADMIN_USER}（仅本次导入）" \
  "  应用账号：${APP_USER}（验收和运行）" \
  "  Dump SHA256：${actual_sha}"

normalize_mysql_dump() {
  # 仅处理 mysqldump 生成的元数据行：
  # 1. 去除 8.4 客户端专属 sandbox 指令，使 8.0.36 客户端可读；
  # 2. 去除源实例显式 DEFINER，避免把本机账号带进 RDS。
  LC_ALL=C awk '
    function fail(message) {
      print "SQL 兼容化失败：" message > "/dev/stderr"
      exit 91
    }
    function strip_definer(line, marker, start, cursor, part, closed, c, next_c) {
      marker = "DEFINER="
      start = index(line, marker)
      if (start == 0) return line
      cursor = start + length(marker)

      for (part = 1; part <= 2; part++) {
        if (substr(line, cursor, 1) != "`") fail("无法解析 DEFINER 元数据")
        cursor++
        closed = 0
        while (cursor <= length(line)) {
          c = substr(line, cursor, 1)
          next_c = substr(line, cursor + 1, 1)
          if (c == "`" && next_c == "`") {
            cursor += 2
          } else if (c == "`") {
            cursor++
            closed = 1
            break
          } else {
            cursor++
          }
        }
        if (!closed) fail("DEFINER 引号未闭合")
        if (part == 1) {
          if (substr(line, cursor, 1) != "@") fail("DEFINER 缺少 @")
          cursor++
        }
      }
      while (substr(line, cursor, 1) ~ /[[:space:]]/) cursor++
      return substr(line, 1, start - 1) substr(line, cursor)
    }
    NR <= 5 && $0 ~ /^[[:space:]]*\/\*![0-9]+\\-[[:space:]]+enable the sandbox mode[[:space:]]+\*\/[[:space:]]*$/ {
      next
    }
    /^[[:space:]]*\/\*![0-9][0-9][0-9][0-9][0-9].*DEFINER=/ {
      $0 = strip_definer($0)
    }
    /^[[:space:]]*CREATE([[:space:]]|$).*DEFINER=/ {
      $0 = strip_definer($0)
    }
    { print }
  '
}

printf '开始导入；出现任意 SQL 错误都会停止，不使用 --force。\n'
IMPORT_STARTED=1
IMPORT_GZIP_STDERR="$TEMP_DIR/import-gzip.stderr"
IMPORT_NORMALIZE_STDERR="$TEMP_DIR/import-normalize.stderr"
IMPORT_MYSQL_STDERR="$TEMP_DIR/import-mysql.stderr"

# `set -e` 会在管道失败时直接进入 EXIT trap，从而丢失判断具体失败阶段的
# 机会。这里只在执行导入管道时临时关闭 errexit，紧接着保存三段状态，
# 并回放每个进程的原始 stderr。密码仅存在挂载的 0600 客户端配置中，
# 不会出现在这些诊断文件里。
set +e
gzip -dc -- "$DUMP_FILE" 2>"$IMPORT_GZIP_STDERR" |
  normalize_mysql_dump 2>"$IMPORT_NORMALIZE_STDERR" |
  admin_mysql \
    --binary-mode=1 \
    --default-character-set=utf8mb4 \
    --database="$DATABASE" \
    2>"$IMPORT_MYSQL_STDERR"
IMPORT_PIPELINE_STATUSES=("${PIPESTATUS[@]}")
set -e

for import_stderr in \
  "$IMPORT_GZIP_STDERR" \
  "$IMPORT_NORMALIZE_STDERR" \
  "$IMPORT_MYSQL_STDERR"; do
  if [[ -s "$import_stderr" ]]; then
    cat -- "$import_stderr" >&2
  fi
done

IMPORT_GZIP_STATUS="${IMPORT_PIPELINE_STATUSES[0]:-125}"
IMPORT_NORMALIZE_STATUS="${IMPORT_PIPELINE_STATUSES[1]:-125}"
IMPORT_MYSQL_STATUS="${IMPORT_PIPELINE_STATUSES[2]:-125}"
if [[ "$IMPORT_GZIP_STATUS" -ne 0 ||
  "$IMPORT_NORMALIZE_STATUS" -ne 0 ||
  "$IMPORT_MYSQL_STATUS" -ne 0 ]]; then
  printf '导入流水线失败：gzip=%s，SQL 兼容化=%s，mysql=%s。\n' \
    "$IMPORT_GZIP_STATUS" \
    "$IMPORT_NORMALIZE_STATUS" \
    "$IMPORT_MYSQL_STATUS" \
    >&2
  if [[ "$IMPORT_MYSQL_STATUS" -ne 0 && ! -s "$IMPORT_MYSQL_STDERR" ]]; then
    printf '%s\n' \
      'MySQL 导入进程没有返回错误文本；请根据 mysql 退出码检查 Docker 与内核日志。' \
      >&2
  fi
  exit 1
fi

TEMP_EXPECTED_TABLES="$TEMP_DIR/expected-tables.txt"
TEMP_ACTUAL_TABLES="$TEMP_DIR/actual-tables.txt"
TEMP_ACTUAL_ROWS="$TEMP_DIR/actual-row-counts.tsv"
TEMP_ACTUAL_FLYWAY="$TEMP_DIR/actual-flyway.tsv"
TEMP_ACTUAL_OBJECTS="$TEMP_DIR/actual-objects.tsv"

awk -F '\t' 'NR > 1 { sub(/\r$/, "", $1); print $1 }' "$ROW_COUNTS_FILE" >"$TEMP_EXPECTED_TABLES"
app_query "
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = '$DATABASE' AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;
" >"$TEMP_ACTUAL_TABLES"
diff -u "$TEMP_EXPECTED_TABLES" "$TEMP_ACTUAL_TABLES" ||
  die 'RDS 基础表集合与源清单不一致'

printf 'table_name\trow_count\n' >"$TEMP_ACTUAL_ROWS"
while IFS=$'\t' read -r table_name expected_count; do
  expected_count="${expected_count%$'\r'}"
  [[ "$table_name" == 'table_name' ]] && continue
  escaped_table="${table_name//\`/\`\`}"
  actual_count="$(app_query "SELECT COUNT(*) FROM \`${escaped_table}\`;")"
  [[ "$actual_count" == "$expected_count" ]] ||
    die "表 $table_name 行数不一致：期望 $expected_count，实际 $actual_count"
  printf '%s\t%s\n' "$table_name" "$actual_count" >>"$TEMP_ACTUAL_ROWS"
done <"$ROW_COUNTS_FILE"
diff -u "$ROW_COUNTS_FILE" "$TEMP_ACTUAL_ROWS" ||
  die 'RDS 逐表精确行数清单不一致'

{
  printf 'installed_rank\tversion\tdescription\ttype\tscript\tchecksum\tinstalled_by\tinstalled_on_utc\texecution_time\tsuccess\n'
  app_query "
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
"
} >"$TEMP_ACTUAL_FLYWAY"
diff -u "$FLYWAY_FILE" "$TEMP_ACTUAL_FLYWAY" ||
  die 'RDS Flyway 清单与源清单不一致'

{
  printf 'object_type\tobject_name\n'
  app_query "
SELECT object_type, object_name
FROM (
    SELECT IF(TABLE_TYPE = 'BASE TABLE', 'TABLE', 'VIEW') AS object_type,
           TABLE_NAME AS object_name
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = '$DATABASE'
    UNION ALL
    SELECT ROUTINE_TYPE AS object_type, ROUTINE_NAME AS object_name
    FROM information_schema.ROUTINES
    WHERE ROUTINE_SCHEMA = '$DATABASE'
    UNION ALL
    SELECT 'TRIGGER' AS object_type, TRIGGER_NAME AS object_name
    FROM information_schema.TRIGGERS
    WHERE TRIGGER_SCHEMA = '$DATABASE'
    UNION ALL
    SELECT 'EVENT' AS object_type, EVENT_NAME AS object_name
    FROM information_schema.EVENTS
    WHERE EVENT_SCHEMA = '$DATABASE'
) AS objects
ORDER BY object_type, object_name;
"
} >"$TEMP_ACTUAL_OBJECTS"
diff -u "$OBJECTS_FILE" "$TEMP_ACTUAL_OBJECTS" ||
  die "应用账号 $APP_USER 看不到完整数据库对象清单"

failed_flyway="$(app_query 'SELECT COUNT(*) FROM flyway_schema_history WHERE success <> 1;')"
[[ "$failed_flyway" == '0' ]] || die "RDS 存在 $failed_flyway 条失败 Flyway 记录"

IMPORT_STARTED=0
printf '%s\n' \
  'RDS 导入与精确验收全部通过。' \
  "应用运行账号必须使用：${APP_USER}" \
  '不要把本次迁移高权限账号或 dms_user_* 写入 .env.public。' \
  '现在才可以填写 SPRING_DATASOURCE_* 并启动后端。'
