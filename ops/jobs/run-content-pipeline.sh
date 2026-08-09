#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

REPO_ROOT=${VIBELO_REPO_ROOT:-/opt/vibelo}
JOB_ROOT=${VIBELO_CONTENT_JOB_ROOT:-/data/vibelo-ingest}
DATASET_ROOT=${VIBELO_CONTENT_DATASET_ROOT:-$JOB_ROOT/dataset}
HISTORY_DIR=${VIBELO_CONTENT_HISTORY_DIR:-$JOB_ROOT/history}
STATE_DIR=${VIBELO_CONTENT_STATE_DIR:-$JOB_ROOT/state}
PYTHON=${VIBELO_CONTENT_PYTHON:-$REPO_ROOT/.venv-content/bin/python}
OPS_PYTHON=${VIBELO_OPS_PYTHON:-$REPO_ROOT/.venv-ops/bin/python}
COLLECT_ENABLED=${VIBELO_CONTENT_COLLECT_ENABLED:-false}
IMPORT_ENABLED=${VIBELO_CONTENT_IMPORT_ENABLED:-true}
SEARCH_REINDEX_ENABLED=${VIBELO_CONTENT_SEARCH_REINDEX_ENABLED:-true}
MIN_FREE_BYTES=${VIBELO_CONTENT_MIN_FREE_BYTES:-26843545600}
MIN_AVAILABLE_MEMORY_KB=${VIBELO_CONTENT_MIN_AVAILABLE_MEMORY_KB:-1048576}
MAX_DOWNLOAD_BYTES=${VIBELO_CONTENT_MAX_DOWNLOAD_BYTES:-26214400}
MAX_IMAGE_PIXELS=${VIBELO_CONTENT_MAX_IMAGE_PIXELS:-40000000}
SEARCH_DIRTY_FILE=${VIBELO_CONTENT_SEARCH_DIRTY_FILE:-$STATE_DIR/search-dirty}

run_id=$(date -u +%Y%m%dT%H%M%SZ)
summary_file=$STATE_DIR/import-summary-$run_id.json
status_file=$HISTORY_DIR/$run_id.json
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
current_stage=preflight

log() {
  printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$current_stage" "$*"
}

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

require_uint() {
  local label=$1 value=$2
  [[ $value =~ ^[0-9]+$ ]] || {
    log "$label 必须是非负整数，当前为：$value"
    exit 2
  }
}

require_secret() {
  local name=$1 value=${!1:-}
  [[ -n $value ]] || {
    log "缺少必填环境变量：$name"
    exit 2
  }
}

clear_search_dirty() {
  rm -f -- "$SEARCH_DIRTY_FILE"
}

write_status() {
  local rc=$?
  local outcome=success
  ((rc == 0)) || outcome=failed
  mkdir -p "$HISTORY_DIR"
  printf '{"runId":"%s","startedAt":"%s","finishedAt":"%s","outcome":"%s","exitCode":%d,"stage":"%s"}\n' \
    "$run_id" "$started_at" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$outcome" "$rc" "$current_stage" \
    >"$status_file"
  log "任务结束：outcome=$outcome exitCode=$rc，记录=$status_file"
  exit "$rc"
}

require_uint VIBELO_CONTENT_MIN_FREE_BYTES "$MIN_FREE_BYTES"
require_uint VIBELO_CONTENT_MIN_AVAILABLE_MEMORY_KB "$MIN_AVAILABLE_MEMORY_KB"
require_uint VIBELO_CONTENT_MAX_DOWNLOAD_BYTES "$MAX_DOWNLOAD_BYTES"
require_uint VIBELO_CONTENT_MAX_IMAGE_PIXELS "$MAX_IMAGE_PIXELS"
((MIN_FREE_BYTES >= 26843545600)) || {
  log 'VIBELO_CONTENT_MIN_FREE_BYTES 不能低于 26843545600（25 GiB）'
  exit 2
}
((MIN_AVAILABLE_MEMORY_KB >= 1048576)) || {
  log 'VIBELO_CONTENT_MIN_AVAILABLE_MEMORY_KB 不能低于 1048576（1 GiB）'
  exit 2
}

if is_true "$COLLECT_ENABLED"; then
  log "公网定时器禁止运行浏览器采集；请在本地执行并将已授权、已检查图片同步到 staging 目录"
  exit 2
fi

[[ -d $REPO_ROOT/.git ]] || {
  log "仓库不存在：$REPO_ROOT"
  exit 2
}
mountpoint -q /data || {
  log "/data 不是独立挂载点，拒绝把采集数据写入系统盘"
  exit 2
}

[[ -d $JOB_ROOT && ! -L $JOB_ROOT ]] || {
  log "任务根目录不存在、不是目录或是符号链接：$JOB_ROOT"
  exit 2
}
task_tree_symlink=$(find -P "$JOB_ROOT" -xdev -type l -print -quit)
[[ -z $task_tree_symlink ]] || {
  log "任务树禁止符号链接：$task_tree_symlink"
  exit 2
}

mkdir -p "$DATASET_ROOT/images" "$HISTORY_DIR" "$STATE_DIR"
trap write_status EXIT

available_bytes=$(df --output=avail -B1 -- /data | awk 'NR == 2 {print $1}')
available_memory_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
[[ $available_bytes =~ ^[0-9]+$ ]] || { log "无法读取 /data 可用空间"; exit 2; }
[[ $available_memory_kb =~ ^[0-9]+$ ]] || { log "无法读取可用内存"; exit 2; }
((available_bytes >= MIN_FREE_BYTES)) || {
  log "/data 可用空间不足，至少保留 $MIN_FREE_BYTES 字节，当前 $available_bytes"
  exit 2
}
((available_memory_kb >= MIN_AVAILABLE_MEMORY_KB)) || {
  log "可用内存不足，至少需要 ${MIN_AVAILABLE_MEMORY_KB} KiB，当前 ${available_memory_kb} KiB"
  exit 2
}

curl -fsS --max-time 5 http://127.0.0.1/gateway/health >/dev/null || {
  log "网站网关健康检查失败"
  exit 2
}
curl -fsS --max-time 5 http://127.0.0.1:9000/minio/health/ready >/dev/null || {
  log "MinIO 健康检查失败"
  exit 2
}

if is_true "$IMPORT_ENABLED"; then
  [[ -x $PYTHON ]] || {
    log "内容任务 Python 不可执行：$PYTHON"
    exit 2
  }
fi

imported=0
if is_true "$IMPORT_ENABLED"; then
  current_stage=import
  require_secret VIBELO_DB_HOST
  require_secret VIBELO_DB_NAME
  require_secret VIBELO_DB_USER
  require_secret VIBELO_DB_PASSWORD
  require_secret MINIO_ACCESS_KEY
  require_secret MINIO_SECRET_KEY
  export VIBELO_DATASET_IMAGE_DIR="$DATASET_ROOT/images"
  export VIBELO_IMPORT_RESULT_PATH="$STATE_DIR/import-results.jsonl"
  export VIBELO_IMPORT_SUMMARY_PATH="$summary_file"
  export VIBELO_MINIO_ENDPOINT=${VIBELO_MINIO_ENDPOINT:-127.0.0.1:9000}
  export VIBELO_MEDIA_OBJECT_PREFIX=${VIBELO_MEDIA_OBJECT_PREFIX:-/api/media/object}
  export VIBELO_IMPORT_MAX_FILE_BYTES=${VIBELO_IMPORT_MAX_FILE_BYTES:-$MAX_DOWNLOAD_BYTES}
  export VIBELO_IMPORT_MAX_IMAGE_PIXELS=${VIBELO_IMPORT_MAX_IMAGE_PIXELS:-$MAX_IMAGE_PIXELS}
  export VIBELO_IMPORT_MIN_FREE_BYTES="$MIN_FREE_BYTES"
  export VIBELO_IMPORT_STORAGE_CHECK_PATH=/data
  log "开始幂等导入 MinIO 和 RDS；新图片只进入 PENDING_REVIEW，不会自动公开"
  "$PYTHON" "$REPO_ROOT/tools/import_images.py"
  [[ -s $summary_file ]] || { log "导入器没有生成摘要"; exit 2; }
  imported=$(
    "$PYTHON" -c 'import json,sys; print(int(json.load(open(sys.argv[1], encoding="utf-8"))["imported"]))' \
      "$summary_file"
  )
  require_uint imported "$imported"
  log "本次新增入库：$imported"
fi

if is_true "$SEARCH_REINDEX_ENABLED" && [[ -e $SEARCH_DIRTY_FILE ]]; then
  current_stage=search-reindex
  [[ -x $OPS_PYTHON ]] || {
    log "搜索重建 Python 不可执行：$OPS_PYTHON"
    exit 2
  }
  export VIBELO_ES_URL=${VIBELO_ES_URL:-http://127.0.0.1:9200}
  log "检测到持久 search-dirty 标记，开始受门禁的 Elasticsearch 全量重建与原子 alias 切换"
  "$OPS_PYTHON" "$REPO_ROOT/tools/reindex_search_es.py" --confirm-promote
  clear_search_dirty
elif [[ -e $SEARCH_DIRTY_FILE ]]; then
  log "search-dirty 仍存在，但搜索重建已禁用；标记保留供后续重试"
fi

current_stage=complete
log "内容增量流水线完成"
