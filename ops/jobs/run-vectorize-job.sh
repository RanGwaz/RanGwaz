#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

REPO_ROOT=${VIBELO_REPO_ROOT:-/opt/vibelo}
PYTHON=${VIBELO_VECTOR_PYTHON:-$REPO_ROOT/.venv-vector/bin/python}
MIN_TOTAL_MEMORY_KB=${VIBELO_VECTOR_MIN_TOTAL_MEMORY_KB:-15728640}
MIN_AVAILABLE_MEMORY_KB=${VIBELO_VECTOR_MIN_AVAILABLE_MEMORY_KB:-6291456}
SUPPORTED_PROJECTION_VERSION=siglip-image-feature-l2-rp512-seed20260606-v1

log() { printf '%s [vectorize] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "$*" >&2; exit 2; }
require() { [[ -n ${!1:-} ]] || die "Missing required environment variable: $1"; }

require_data_path() {
  local name=$1
  local path resolved
  require "$name"
  path=${!name}
  resolved=$(realpath -m -- "$path") || die "Cannot resolve $name"
  case "$resolved" in
    /data/*) ;;
    *) die "$name must resolve below /data: $path" ;;
  esac
}

[[ -x $PYTHON ]] || die "Vector Python is not executable: $PYTHON"
[[ -r $REPO_ROOT/tools/vectorize_images.py ]] || die "Vector worker is not readable"
mountpoint -q /data || die "/data is not an independent mount point"

total_memory_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
available_memory_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
[[ $total_memory_kb =~ ^[0-9]+$ && $available_memory_kb =~ ^[0-9]+$ ]] || die "Cannot read host memory"
((total_memory_kb >= MIN_TOTAL_MEMORY_KB)) || die "Vectorization requires at least 15 GiB RAM"
if ((available_memory_kb < MIN_AVAILABLE_MEMORY_KB)); then
  log "Available memory is below 6 GiB; skip this run without affecting the website"
  exit 75
fi

for name in VIBELO_DB_HOST VIBELO_DB_PORT VIBELO_DB_NAME VIBELO_DB_USER VIBELO_DB_PASSWORD; do
  require "$name"
done
for name in VIBELO_MILVUS_COLLECTION VIBELO_EMBED_VECTOR_VERSION VIBELO_EMBED_MODEL_PATH VIBELO_EMBED_PROJECTION_VERSION; do
  require "$name"
done
[[ $VIBELO_EMBED_PROJECTION_VERSION == "$SUPPORTED_PROJECTION_VERSION" ]] || \
  die "VIBELO_EMBED_PROJECTION_VERSION does not match this vector worker"

require_data_path VIBELO_EMBED_MODEL_PATH
[[ -d $VIBELO_EMBED_MODEL_PATH && -r $VIBELO_EMBED_MODEL_PATH ]] || \
  die "Local model directory is missing or unreadable: $VIBELO_EMBED_MODEL_PATH"

for name in MODEL_CACHE_ROOT VIBELO_HF_HOME TORCH_HOME XDG_CACHE XDG_CACHE_HOME VIBELO_VECTOR_READY_MARKER; do
  require_data_path "$name"
  if [[ $name == VIBELO_VECTOR_READY_MARKER ]]; then
    marker_parent=$(dirname -- "${!name}")
    mkdir -p -- "$marker_parent"
    [[ -d $marker_parent && -w $marker_parent ]] || die "$name parent is not writable: ${!name}"
  else
    mkdir -p -- "${!name}"
    [[ -d ${!name} && -w ${!name} ]] || die "$name is not writable: ${!name}"
  fi
done
[[ $(realpath -m -- "$XDG_CACHE") == $(realpath -m -- "$XDG_CACHE_HOME") ]] || \
  die "XDG_CACHE and XDG_CACHE_HOME must identify the same directory"

for name in VIBELO_REQUIRE_DATA_CACHE VIBELO_MODEL_OFFLINE HF_HUB_OFFLINE TRANSFORMERS_OFFLINE HF_DATASETS_OFFLINE VIBELO_REQUIRE_VECTOR_READY_MARKER; do
  [[ ${!name:-} == 1 ]] || die "$name must be 1 for the production vector job"
done
[[ ${VIBELO_USE_HF_PROXY:-0} == 0 ]] || die "Hugging Face proxy must be disabled in offline mode"

milvus_host=${VIBELO_MILVUS_HOST:-127.0.0.1}
milvus_port=${VIBELO_MILVUS_PORT:-19530}
[[ $milvus_port =~ ^[0-9]+$ ]] || die "Invalid VIBELO_MILVUS_PORT"
"$PYTHON" - "$milvus_host" "$milvus_port" <<'PY' || die "Milvus is not reachable"
import socket
import sys

with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=3):
    pass
PY

export VIBELO_BACKEND_BASE_URL=${VIBELO_BACKEND_BASE_URL:-http://127.0.0.1}
export VIBELO_EMBED_DEVICE=${VIBELO_EMBED_DEVICE:-cpu}
export VIBELO_EMBED_BATCH_SIZE=${VIBELO_EMBED_BATCH_SIZE:-2}
export VIBELO_EMBED_LIMIT=${VIBELO_EMBED_LIMIT:-2000}
export VIBELO_EMBED_REQUIRE_INDEX_COUNT_MATCH=${VIBELO_EMBED_REQUIRE_INDEX_COUNT_MATCH:-1}

log "Start incremental vectorization: version=$VIBELO_EMBED_VECTOR_VERSION collection=$VIBELO_MILVUS_COLLECTION limit=$VIBELO_EMBED_LIMIT"
"$PYTHON" "$REPO_ROOT/tools/vectorize_images.py"
log "Incremental vectorization completed"
