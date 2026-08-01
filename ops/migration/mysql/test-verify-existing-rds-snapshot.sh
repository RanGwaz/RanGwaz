#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
IMPORT_SCRIPT="$SCRIPT_DIR/import-mysql-snapshot-to-rds.sh"

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/vibelo-verify-existing-test.XXXXXXXX")"
trap 'rm -rf -- "$TEMP_ROOT"' EXIT

MOCK_BIN="$TEMP_ROOT/bin"
SNAPSHOT_DIR="$TEMP_ROOT/snapshot"
mkdir -p "$MOCK_BIN" "$SNAPSHOT_DIR"

cat >"$MOCK_BIN/docker" <<'MOCK_DOCKER'
#!/usr/bin/env bash
set -Eeuo pipefail

case "${1:-}" in
  info)
    exit 0
    ;;
  image)
    [[ "${2:-}" == 'inspect' ]] || exit 90
    exit 0
    ;;
  run)
    shift
    if [[ " $* " == *' --network none '* ]]; then
      printf '%s\n' 'mysql  Ver 8.0.36 for Linux on x86_64 (MySQL Community Server - GPL)'
      exit 0
    fi

    sql=''
    config_mount=''
    readonly_guard=0
    previous=''
    for argument in "$@"; do
      case "$argument" in
        -i|--interactive)
          printf '%s\n' 'verify-existing must not attach Docker stdin' >&2
          exit 81
          ;;
        --execute=*) sql="${argument#--execute=}" ;;
        '--init-command=SET SESSION TRANSACTION READ ONLY') readonly_guard=1 ;;
      esac
      if [[ "$previous" == '--volume' ]]; then
        config_mount="$argument"
      fi
      previous="$argument"
    done

    [[ -n "$sql" ]] || {
      printf '%s\n' 'verify-existing attempted a streaming MySQL invocation' >&2
      exit 82
    }
    ((readonly_guard)) || {
      printf '%s\n' 'verify-existing query omitted the read-only session guard' >&2
      exit 83
    }

    config_path="${config_mount%%:*}"
    [[ -f "$config_path" ]] || exit 84
    grep -qx 'user=vibelo_app' "$config_path" || {
      printf '%s\n' 'verify-existing used a non-application account' >&2
      exit 85
    }

    if grep -Eiq '(^|[^A-Z_])(CREATE|INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE|REPLACE|GRANT|REVOKE|LOAD|CALL)([^A-Z_]|$)' <<<"$sql"; then
      printf 'verify-existing attempted mutating SQL: %s\n' "$sql" >&2
      exit 86
    fi

    printf '%s\n' "$sql" >>"$MOCK_DOCKER_QUERY_LOG"

    if [[ "$sql" =~ SELECT[[:space:]]+COUNT\(\*\)[[:space:]]+FROM[[:space:]]+\`([^\`]*)\`\; ]]; then
      table_name="${BASH_REMATCH[1]}"
      printf '%s\n' "$table_name" >>"$MOCK_DOCKER_ROW_QUERY_LOG"
      case "$table_name" in
        demo_alpha) printf '%s\n' '2' ;;
        demo_beta) printf '%s\n' "${MOCK_BETA_COUNT:-3}" ;;
        flyway_schema_history) printf '%s\n' '1' ;;
        *) exit 92 ;;
      esac
    elif [[ "$sql" == *'SELECT COUNT(*) FROM information_schema.SCHEMATA'* ]]; then
      printf '%s\n' '1'
    elif [[ "$sql" == *'SELECT VERSION();'* ]]; then
      printf '%s\n' '8.0.36'
    elif [[ "$sql" == *'DEFAULT_CHARACTER_SET_NAME'* ]]; then
      printf 'utf8mb4\tutf8mb4_0900_ai_ci\n'
    elif [[ "$sql" == *'SELECT TABLE_NAME'* && "$sql" == *"TABLE_TYPE = 'BASE TABLE'"* ]]; then
      printf '%s\n' demo_alpha demo_beta flyway_schema_history
    elif [[ "$sql" == *'SELECT object_type, object_name'* ]]; then
      printf 'TABLE\tdemo_alpha\nTABLE\tdemo_beta\nTABLE\tflyway_schema_history\n'
    elif [[ "$sql" == *'SELECT COUNT(*) FROM flyway_schema_history'* ]]; then
      printf '%s\n' '0'
    elif [[ "$sql" == *'FROM flyway_schema_history'* ]]; then
      printf '1\t1\tinitial\tSQL\tV1__initial.sql\t12345\tvibelo\t2026-01-02T03:04:05.000000Z\t17\t1\n'
    else
      printf 'unhandled verify query: %s\n' "$sql" >&2
      exit 93
    fi
    ;;
  *)
    exit 91
    ;;
esac
MOCK_DOCKER
chmod +x "$MOCK_BIN/docker"

prefix="$SNAPSHOT_DIR/rangwaz_image_dev-test"
printf '%s\n' 'SELECT 1;' | gzip -c >"${prefix}.sql.gz"
dump_sha="$(sha256sum "${prefix}.sql.gz")"
dump_sha="${dump_sha%% *}"
printf '%s  %s\n' "$dump_sha" "$(basename "${prefix}.sql.gz")" >"${prefix}.sha256"
printf 'table_name\trow_count\ndemo_alpha\t2\ndemo_beta\t3\nflyway_schema_history\t1\n' \
  >"${prefix}.row-counts.tsv"
printf 'installed_rank\tversion\tdescription\ttype\tscript\tchecksum\tinstalled_by\tinstalled_on_utc\texecution_time\tsuccess\n1\t1\tinitial\tSQL\tV1__initial.sql\t12345\tvibelo\t2026-01-02T03:04:05.000000Z\t17\t1\n' \
  >"${prefix}.flyway.tsv"
printf 'object_type\tobject_name\nTABLE\tdemo_alpha\nTABLE\tdemo_beta\nTABLE\tflyway_schema_history\n' \
  >"${prefix}.objects.tsv"
cat >"${prefix}.meta.json" <<EOF
{
  "source_database": "rangwaz_image_dev",
  "dump_sha256": "$dump_sha"
}
EOF
cat >"${prefix}.restore-tested.json" <<EOF
{
  "dump_sha256": "$dump_sha",
  "tested_server_version": "8.0.36",
  "exact_row_counts_verified": true,
  "flyway_verified": true,
  "object_inventory_verified": true
}
EOF

printf '%s\n' 'test-app-password' >"$TEMP_ROOT/app.password"
printf '%s\n' 'must-never-be-read' >"$TEMP_ROOT/admin.password"
chmod 600 "$TEMP_ROOT/app.password" "$TEMP_ROOT/admin.password"

assert_contains() {
  local haystack=$1
  local needle=$2
  local label=$3
  [[ "$haystack" == *"$needle"* ]] || {
    printf '失败：%s；输出中缺少 <%s>\n--- 实际输出 ---\n%s\n' \
      "$label" "$needle" "$haystack" >&2
    exit 1
  }
}

assert_not_contains() {
  local haystack=$1
  local needle=$2
  local label=$3
  [[ "$haystack" != *"$needle"* ]] || {
    printf '失败：%s；输出中不应包含 <%s>\n--- 实际输出 ---\n%s\n' \
      "$label" "$needle" "$haystack" >&2
    exit 1
  }
}

run_verify() {
  local beta_count=${1:-3}
  rm -f -- "$TEMP_ROOT/queries" "$TEMP_ROOT/row-queries"
  set +e
  VERIFY_OUTPUT="$({
    PATH="$MOCK_BIN:$PATH" \
      MOCK_BETA_COUNT="$beta_count" \
      MOCK_DOCKER_QUERY_LOG="$TEMP_ROOT/queries" \
      MOCK_DOCKER_ROW_QUERY_LOG="$TEMP_ROOT/row-queries" \
      bash "$IMPORT_SCRIPT" \
        --verify-existing \
        --dump "${prefix}.sql.gz" \
        --host 'rm-test.mysql.rds.aliyuncs.com' \
        --app-user 'vibelo_app' \
        --app-password-file "$TEMP_ROOT/app.password" \
        --mysql-image 'mysql:8.0.36' \
        --no-pull
  } 2>&1)"
  VERIFY_STATUS=$?
  set -e
}

run_verify 3
[[ "$VERIFY_STATUS" -eq 0 ]] || {
  printf '失败：现有库完全一致时只读验收未通过\n--- 实际输出 ---\n%s\n' \
    "$VERIFY_OUTPUT" >&2
  exit 1
}
assert_contains "$VERIFY_OUTPUT" \
  'RDS 现有数据只读精确验收全部通过。' \
  '成功时必须输出独立、明确的只读验收标志'
assert_contains "$VERIFY_OUTPUT" \
  '本次未请求迁移账号密码，未执行导入或数据库写入。' \
  '成功时必须确认没有使用迁移凭据或写库'
assert_not_contains "$VERIFY_OUTPUT" 'RDS 高权限迁移账号密码' '只读验收不得请求迁移密码'
assert_not_contains "$VERIFY_OUTPUT" '开始导入' '只读验收不得进入导入路径'
printf 'demo_alpha\ndemo_beta\nflyway_schema_history\n' >"$TEMP_ROOT/expected-row-queries"
diff -u "$TEMP_ROOT/expected-row-queries" "$TEMP_ROOT/row-queries" || {
  printf '失败：只读验收没有逐一检查全部表\n' >&2
  exit 1
}

run_verify 4
[[ "$VERIFY_STATUS" -ne 0 ]] || {
  printf '失败：RDS 行数不一致时只读验收却返回成功\n' >&2
  exit 1
}
assert_contains "$VERIFY_OUTPUT" \
  '表 demo_beta 行数不一致：期望 3，实际 4' \
  '只读验收应准确报告行数差异'
assert_contains "$VERIFY_OUTPUT" \
  '本次没有请求迁移账号密码，也没有执行导入或数据库写入' \
  '只读验收失败时也必须明确未修改 RDS'
assert_not_contains "$VERIFY_OUTPUT" '请先重建/清空目标库' '只读验收失败不得冒充导入失败'

assert_rejected() {
  local expected_message=$1
  shift
  local output status
  set +e
  output="$(bash "$IMPORT_SCRIPT" \
    --verify-existing \
    --dump "${prefix}.sql.gz" \
    --host 'rm-test.mysql.rds.aliyuncs.com' \
    "$@" 2>&1)"
  status=$?
  set -e
  [[ "$status" -ne 0 ]] || {
    printf '失败：互斥参数未被拒绝：%s\n' "$*" >&2
    exit 1
  }
  assert_contains "$output" "$expected_message" '只读模式必须拒绝导入专用参数'
}

assert_rejected '--verify-existing 与 --confirm-import 互斥' --confirm-import
assert_rejected '--verify-existing 禁止传入 --admin-user' --admin-user migration_admin
assert_rejected '--verify-existing 禁止传入 --admin-password-file' \
  --admin-password-file "$TEMP_ROOT/admin.password"

printf '%s\n' 'RDS 现有数据库只读验收回归测试通过。'
