#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
IMPORT_SCRIPT="$SCRIPT_DIR/import-mysql-snapshot-to-rds.sh"

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/vibelo-import-test.XXXXXXXX")"
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
    interactive=0
    for argument in "$@"; do
      case "$argument" in
        --execute=*) sql="${argument#--execute=}" ;;
        -i|--interactive) interactive=1 ;;
      esac
    done

    if [[ -z "$sql" ]]; then
      # Docker only forwards the pipeline to the container when -i/--interactive
      # is present.  Without it, mysql receives EOF and the producer can fail
      # with SIGPIPE without any MySQL error text.
      ((interactive)) || exit 0
      input_bytes="$(wc -c)"
      printf '%s\n' "$input_bytes" >"$MOCK_DOCKER_IMPORT_BYTES_FILE"
      if [[ "${MOCK_IMPORT_ERROR_MODE:-silent}" == 'stderr' ]]; then
        printf '%s\n' 'ERROR 1234 (42000) at line 77: simulated RDS SQL failure' >&2
      fi
      if [[ "${MOCK_IMPORT_ERROR_MODE:-silent}" == 'success' ]]; then
        exit 0
      fi
      exit 42
    fi

    if [[ "$sql" =~ SELECT[[:space:]]+COUNT\(\*\)[[:space:]]+FROM[[:space:]]+\`([^\`]*)\`\; ]]; then
      table_name="${BASH_REMATCH[1]}"
      if ((interactive)); then
        # Reproduce the production failure: an interactive Docker query inherits
        # and drains the row-count loop's redirected stdin.
        cat >/dev/null
      fi
      printf '%s\n' "$table_name" >>"$MOCK_DOCKER_ROW_QUERY_LOG"
      case "$table_name" in
        demo_alpha) printf '%s\n' '2' ;;
        demo_beta) printf '%s\n' '3' ;;
        demo_gamma) printf '%s\n' '0' ;;
        *) exit 92 ;;
      esac
    elif [[ "$sql" == *'SELECT COUNT(*) FROM information_schema.SCHEMATA'* ]]; then
      printf '%s\n' '1'
    elif [[ "$sql" == *'SELECT VERSION();'* ]]; then
      printf '%s\n' '8.0.36'
    elif [[ "$sql" == *'DEFAULT_CHARACTER_SET_NAME'* ]]; then
      printf 'utf8mb4\tutf8mb4_0900_ai_ci\n'
    elif [[ "$sql" == *'SELECT TABLE_NAME'* && "$sql" == *"TABLE_TYPE = 'BASE TABLE'"* ]]; then
      printf '%s\n' demo_alpha demo_beta demo_gamma
    elif [[ "$sql" == *'SELECT object_type, object_name'* ]]; then
      printf 'TABLE\tdemo_alpha\nTABLE\tdemo_beta\nTABLE\tdemo_gamma\n'
    elif [[ "$sql" == *'SELECT COUNT(*) FROM flyway_schema_history'* ]]; then
      printf '%s\n' '0'
    elif [[ "$sql" == *'FROM flyway_schema_history'* ]]; then
      :
    elif [[ "$sql" == *'information_schema.TABLES'* && "$sql" == *'information_schema.ROUTINES'* ]]; then
      printf '%s\n' '0'
    fi
    ;;
  *)
    exit 91
    ;;
esac
MOCK_DOCKER
chmod +x "$MOCK_BIN/docker"

prefix="$SNAPSHOT_DIR/rangwaz_image_dev-test"
awk 'BEGIN { for (i = 0; i < 200000; i++) print "SELECT 1;" }' |
  gzip -c >"${prefix}.sql.gz"
expected_import_bytes="$(gzip -dc -- "${prefix}.sql.gz" | wc -c | awk '{ print $1 }')"
dump_sha="$(sha256sum "${prefix}.sql.gz")"
dump_sha="${dump_sha%% *}"
printf '%s  %s\n' "$dump_sha" "$(basename "${prefix}.sql.gz")" >"${prefix}.sha256"
printf 'table_name\trow_count\ndemo\t0\n' >"${prefix}.row-counts.tsv"
printf 'installed_rank\tversion\tdescription\ttype\tscript\tchecksum\tinstalled_by\tinstalled_on_utc\texecution_time\tsuccess\n' >"${prefix}.flyway.tsv"
printf 'object_type\tobject_name\nTABLE\tdemo\n' >"${prefix}.objects.tsv"
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

printf '%s\n' 'test-admin-password' >"$TEMP_ROOT/admin.password"
printf '%s\n' 'test-app-password' >"$TEMP_ROOT/app.password"
chmod 600 "$TEMP_ROOT/admin.password" "$TEMP_ROOT/app.password"

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

run_import_case() {
  local error_mode=$1
  rm -f -- "$TEMP_ROOT/import-bytes"
  set +e
  IMPORT_OUTPUT="$({
    PATH="$MOCK_BIN:$PATH" \
      MOCK_IMPORT_ERROR_MODE="$error_mode" \
      MOCK_DOCKER_IMPORT_BYTES_FILE="$TEMP_ROOT/import-bytes" \
      bash "$IMPORT_SCRIPT" \
        --dump "${prefix}.sql.gz" \
        --host 'rm-test.mysql.rds.aliyuncs.com' \
        --admin-user 'migration_admin' \
        --admin-password-file "$TEMP_ROOT/admin.password" \
        --app-user 'vibelo_app' \
        --app-password-file "$TEMP_ROOT/app.password" \
        --mysql-image 'mysql:8.0.36' \
        --no-pull \
        --confirm-import
  } 2>&1)"
  IMPORT_STATUS=$?
  set -e
  [[ "$IMPORT_STATUS" -ne 0 ]] || {
    printf '失败：模拟导入错误时脚本却返回成功\n' >&2
    exit 1
  }
  [[ -s "$TEMP_ROOT/import-bytes" ]] || {
    printf '失败：导入 SQL 未通过 Docker stdin 到达 MySQL 容器\n--- 实际输出 ---\n%s\n' \
      "$IMPORT_OUTPUT" >&2
    exit 1
  }
  IMPORT_BYTES="$(<"$TEMP_ROOT/import-bytes")"
  [[ "$IMPORT_BYTES" == "$expected_import_bytes" ]] || {
    printf '失败：容器未接收完整导入 SQL；期望 %s 字节，实际 %s 字节\n' \
      "$expected_import_bytes" "$IMPORT_BYTES" >&2
    exit 1
  }
}

run_import_case silent
assert_contains "$IMPORT_OUTPUT" \
  '导入流水线失败：gzip=0，SQL 兼容化=0，mysql=42。' \
  '无 stderr 的失败应明确指出失败阶段和退出码'
assert_contains "$IMPORT_OUTPUT" \
  'MySQL 导入进程没有返回错误文本' \
  '无 stderr 的 MySQL 失败不应只显示兜底提示'
assert_contains "$IMPORT_OUTPUT" \
  '导入已经开始但未成功完成' \
  '失败后仍应保留数据可能部分写入的安全告警'

run_import_case stderr
assert_contains "$IMPORT_OUTPUT" \
  'ERROR 1234 (42000) at line 77: simulated RDS SQL failure' \
  'MySQL 原始错误应回放给操作者'
assert_contains "$IMPORT_OUTPUT" \
  '导入流水线失败：gzip=0，SQL 兼容化=0，mysql=42。' \
  '有 stderr 的失败也应指出失败阶段和退出码'

# The verification loop redirects stdin from this file. Query containers must
# not be interactive, otherwise the first COUNT(*) drains all remaining rows.
printf 'object_type\tobject_name\nTABLE\tdemo_alpha\nTABLE\tdemo_beta\nTABLE\tdemo_gamma\n' \
  >"${prefix}.objects.tsv"

run_completed_import_case() {
  rm -f -- "$TEMP_ROOT/import-bytes" "$TEMP_ROOT/row-queries"
  set +e
  COMPLETED_OUTPUT="$({
    PATH="$MOCK_BIN:$PATH" \
      MOCK_IMPORT_ERROR_MODE='success' \
      MOCK_DOCKER_IMPORT_BYTES_FILE="$TEMP_ROOT/import-bytes" \
      MOCK_DOCKER_ROW_QUERY_LOG="$TEMP_ROOT/row-queries" \
      bash "$IMPORT_SCRIPT" \
        --dump "${prefix}.sql.gz" \
        --host 'rm-test.mysql.rds.aliyuncs.com' \
        --admin-user 'migration_admin' \
        --admin-password-file "$TEMP_ROOT/admin.password" \
        --app-user 'vibelo_app' \
        --app-password-file "$TEMP_ROOT/app.password" \
        --mysql-image 'mysql:8.0.36' \
        --no-pull \
        --confirm-import
  } 2>&1)"
  COMPLETED_STATUS=$?
  set -e
}

printf 'table_name\trow_count\ndemo_alpha\t99\ndemo_beta\t3\ndemo_gamma\t0\n' \
  >"${prefix}.row-counts.tsv"
run_completed_import_case
[[ "$COMPLETED_STATUS" -ne 0 ]] || {
  printf '失败：模拟验收差异时脚本却返回成功\n' >&2
  exit 1
}
assert_contains "$COMPLETED_OUTPUT" \
  'SQL 导入流水线已成功完成，但后续验收未通过' \
  '导入完成后的验收失败应明确保留目标库'
assert_not_contains "$COMPLETED_OUTPUT" \
  '请先重建/清空目标库' \
  '导入完成后的验收失败不应误导操作者立即清库'

printf 'table_name\trow_count\ndemo_alpha\t2\ndemo_beta\t3\ndemo_gamma\t0\n' \
  >"${prefix}.row-counts.tsv"
run_completed_import_case

[[ "$COMPLETED_STATUS" -eq 0 ]] || {
  printf '失败：模拟成功导入未通过完整验收\n--- 实际输出 ---\n%s\n' \
    "$COMPLETED_OUTPUT" >&2
  exit 1
}
printf 'demo_alpha\ndemo_beta\ndemo_gamma\n' >"$TEMP_ROOT/expected-row-queries"
diff -u "$TEMP_ROOT/expected-row-queries" "$TEMP_ROOT/row-queries" || {
  printf '失败：逐表验收没有访问 row-counts.tsv 中的每张表\n' >&2
  exit 1
}
assert_contains "$COMPLETED_OUTPUT" \
  'RDS 导入与精确验收全部通过。' \
  '所有逐表查询完成后应通过精确验收'

printf '%s\n' 'RDS 导入与逐表验收回归测试通过。'
