#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT=${VIBELO_REPO_ROOT:-/opt/vibelo}
JOB_ROOT=${VIBELO_CONTENT_JOB_ROOT:-/data/vibelo-ingest}
PYTHON=${VIBELO_CONTENT_PYTHON:-$REPO_ROOT/.venv-content/bin/python}
OPS_PYTHON=${VIBELO_OPS_PYTHON:-$REPO_ROOT/.venv-ops/bin/python}
failures=0

pass() { printf '[通过] %s\n' "$*"; }
fail() { printf '[失败] %s\n' "$*"; failures=$((failures + 1)); }
require_value() {
  local name=$1
  [[ -n ${!name:-} ]] && pass "$name 已配置（不显示值）" || fail "$name 未配置"
}
require_integer_range() {
  local name=$1 minimum=$2 maximum=$3 value=${!1:-}
  if [[ $value =~ ^[0-9]+$ ]] && ((value >= minimum && value <= maximum)); then
    pass "$name 在安全范围内"
  else
    fail "$name 必须是 ${minimum}..${maximum} 的整数"
  fi
}

mountpoint -q /data && pass '/data 是独立挂载点' || fail '/data 不是独立挂载点'
[[ -d $REPO_ROOT/.git ]] && pass "仓库存在：$REPO_ROOT" || fail "仓库不存在：$REPO_ROOT"
[[ -x $PYTHON ]] && pass "内容任务 Python 可执行" || fail "内容任务 Python 不可执行：$PYTHON"
[[ -x $OPS_PYTHON ]] && pass "搜索重建 Python 可执行" || fail "搜索重建 Python 不可执行：$OPS_PYTHON"
id -u vibelo-jobs >/dev/null 2>&1 \
  && pass '独立服务账号 vibelo-jobs 已存在' \
  || fail '独立服务账号 vibelo-jobs 不存在'

for module in pymysql minio PIL; do
  "$PYTHON" -c "import $module" >/dev/null 2>&1 \
    && pass "Python 依赖可导入：$module" \
    || fail "Python 依赖不可导入：$module"
done
require_integer_range VIBELO_CONTENT_MIN_FREE_BYTES 26843545600 1099511627776
require_integer_range VIBELO_CONTENT_MIN_AVAILABLE_MEMORY_KB 1048576 1073741824
require_integer_range VIBELO_IMPORT_LIMIT 1 500
require_integer_range VIBELO_IMPORT_MAX_FILE_BYTES 1 26214400
require_integer_range VIBELO_IMPORT_MAX_IMAGE_PIXELS 1 40000000
require_integer_range VIBELO_IMPORT_MAX_IMAGE_DIMENSION 1 16384

case "${VIBELO_CONTENT_COLLECT_ENABLED:-false}" in
  1|true|TRUE|yes|YES|on|ON)
    fail '当前公网定时器禁止浏览器采集；必须保持 VIBELO_CONTENT_COLLECT_ENABLED=false'
    ;;
  *) pass '公网服务器浏览器采集已强制关闭' ;;
esac

for name in \
  VIBELO_DB_HOST VIBELO_DB_PORT VIBELO_DB_NAME VIBELO_DB_USER VIBELO_DB_PASSWORD \
  MINIO_ACCESS_KEY MINIO_SECRET_KEY MINIO_BUCKET; do
  require_value "$name"
done

if "$PYTHON" - <<'PY' >/dev/null 2>&1
import os
import pymysql

connection = pymysql.connect(
    host=os.environ["VIBELO_DB_HOST"],
    port=int(os.environ.get("VIBELO_DB_PORT", "3306")),
    user=os.environ["VIBELO_DB_USER"],
    password=os.environ["VIBELO_DB_PASSWORD"],
    database=os.environ["VIBELO_DB_NAME"],
    charset="utf8mb4",
    connect_timeout=5,
    read_timeout=5,
    write_timeout=5,
)
try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1, CURRENT_USER()")
        row = cursor.fetchone()
        if not row or int(row[0]) != 1 or not row[1]:
            raise RuntimeError("unexpected read-only probe result")
finally:
    connection.close()
PY
then
  pass 'RDS 只读认证通过（SELECT 1 / CURRENT_USER）'
else
  fail 'RDS 只读认证失败（网络、账号或权限类型；秘密未显示）'
fi

if "$PYTHON" - <<'PY' >/dev/null 2>&1
import os
from minio import Minio
import urllib3

secure = os.environ.get("VIBELO_MINIO_SECURE", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
client = Minio(
    os.environ.get("VIBELO_MINIO_ENDPOINT", "127.0.0.1:9000"),
    access_key=os.environ["MINIO_ACCESS_KEY"],
    secret_key=os.environ["MINIO_SECRET_KEY"],
    secure=secure,
    http_client=urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=5.0, read=5.0),
        retries=False,
    ),
)
if not client.bucket_exists(os.environ["MINIO_BUCKET"]):
    raise RuntimeError("configured bucket does not exist")
PY
then
  pass 'MinIO 只读认证和 bucket 访问通过'
else
  fail 'MinIO 只读认证失败（网络、账号或 bucket 权限类型；秘密未显示）'
fi

curl -fsS --max-time 5 http://127.0.0.1/gateway/health >/dev/null \
  && pass '网站网关健康' || fail '网站网关不健康'
curl -fsS --max-time 5 http://127.0.0.1:9000/minio/health/ready >/dev/null \
  && pass 'MinIO 健康' || fail 'MinIO 不健康'

if id -u vibelo-jobs >/dev/null 2>&1; then
  if [[ $(id -u) -eq $(id -u vibelo-jobs) ]]; then
    service_test=(test)
  else
    service_test=(runuser -u vibelo-jobs -- test)
  fi
  "${service_test[@]}" -r /etc/vibelo/content-job.env \
    && pass 'vibelo-jobs 可读取最小任务环境文件' \
    || fail 'vibelo-jobs 无法读取 /etc/vibelo/content-job.env'
  "${service_test[@]}" -w "$JOB_ROOT" \
    && pass "vibelo-jobs 可写任务目录：$JOB_ROOT" \
    || fail "vibelo-jobs 无法写任务目录：$JOB_ROOT"
  task_tree_symlink=''
  [[ ! -L $JOB_ROOT ]] && task_tree_symlink=$(find -P "$JOB_ROOT" -xdev -type l -print -quit 2>/dev/null || true)
  [[ ! -L $JOB_ROOT && -z $task_tree_symlink ]] \
    && pass '任务树不存在符号链接' \
    || fail "任务树禁止符号链接：${task_tree_symlink:-$JOB_ROOT}"
  unexpected_owner=$(find -P "$JOB_ROOT" -xdev \
    \( ! -user vibelo-jobs -o ! -group vibelo-jobs \) -print -quit 2>/dev/null || true)
  [[ -z $unexpected_owner ]] \
    && pass '任务树所有权已完整迁移给 vibelo-jobs' \
    || fail "任务树存在非 vibelo-jobs 所有文件：$unexpected_owner"
fi
((failures == 0)) || exit 1
printf '内容定时任务预检通过。\n'
