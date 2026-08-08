#!/usr/bin/env bash

# Shared helpers for the MinIO migration scripts.

minio_die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

minio_note() {
  printf '%s\n' "$*" >&2
}

minio_require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    minio_die "缺少命令：$1"
}

minio_require_bucket_name() {
  local bucket_name=$1

  [[ $bucket_name =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] ||
    minio_die "bucket 名称不符合 S3 常用命名规则：$bucket_name"
}

minio_require_loopback_endpoint() {
  local endpoint=$1

  [[ $endpoint =~ ^https?://(127[.]0[.]0[.]1|localhost):[0-9]{1,5}/?$ ]] ||
    minio_die "只允许回环地址 MinIO endpoint，收到：$endpoint"
}

minio_init_private_config() {
  local temp_root=${TMPDIR:-/tmp}

  umask 077
  MC_CONFIG_DIR=$(mktemp -d "$temp_root/vibelo-minio-mc.XXXXXXXX") ||
    minio_die "无法创建临时 mc 配置目录"
  chmod 700 "$MC_CONFIG_DIR"
  export MC_CONFIG_DIR
}

minio_cleanup_private_config() {
  if [[ -n ${MC_CONFIG_DIR:-} && -d ${MC_CONFIG_DIR:-} ]]; then
    chmod -R u+rwX,go-rwx "$MC_CONFIG_DIR" 2>/dev/null || true
    rm -rf -- "$MC_CONFIG_DIR"
  fi
  unset MC_CONFIG_DIR
}

minio_mc() {
  [[ -n ${MC_CONFIG_DIR:-} ]] ||
    minio_die "mc 临时配置尚未初始化"
  mc --config-dir "$MC_CONFIG_DIR" "$@"
}

minio_check_health() {
  local endpoint=${1%/}
  local label=$2

  minio_require_loopback_endpoint "$endpoint"
  curl \
    --fail \
    --silent \
    --show-error \
    --max-time 5 \
    "$endpoint/minio/health/live" \
    >/dev/null ||
    minio_die "$label 健康检查失败：$endpoint"
}

minio_configure_alias() {
  local alias_name=$1
  local endpoint=${2%/}
  local label=$3
  local access_key
  local secret_key
  local alias_result=0
  local xtrace_was_enabled=0

  minio_require_loopback_endpoint "$endpoint"

  if [[ $- == *x* ]]; then
    xtrace_was_enabled=1
    set +x
  fi

  case ${VIBELO_MINIO_CREDENTIAL_INPUT:-tty} in
    tty)
      IFS= read -r -s -p "$label Access Key（隐藏输入）: " access_key </dev/tty ||
        minio_die "无法读取 $label Access Key"
      printf '\n' >/dev/tty
      IFS= read -r -s -p "$label Secret Key（隐藏输入）: " secret_key </dev/tty ||
        minio_die "无法读取 $label Secret Key"
      printf '\n' >/dev/tty
      ;;
    stdin)
      IFS= read -r access_key || minio_die "无法从标准输入读取 $label Access Key"
      IFS= read -r secret_key || minio_die "无法从标准输入读取 $label Secret Key"
      ;;
    *)
      minio_die 'VIBELO_MINIO_CREDENTIAL_INPUT 只能是 tty 或 stdin'
      ;;
  esac

  if [[ -z $access_key || -z $secret_key ]]; then
    unset access_key secret_key
    minio_die "$label 凭据不能为空"
  fi

  if minio_mc alias set \
    "$alias_name" \
    "$endpoint" \
    "$access_key" \
    "$secret_key" \
    --api S3v4 \
    >/dev/null; then
    alias_result=0
  else
    alias_result=$?
  fi

  unset access_key secret_key
  find "$MC_CONFIG_DIR" -type d -exec chmod 700 {} + 2>/dev/null || true
  find "$MC_CONFIG_DIR" -type f -exec chmod 600 {} + 2>/dev/null || true

  if ((xtrace_was_enabled)); then
    set -x
  fi

  ((alias_result == 0)) ||
    minio_die "$label 凭据校验或 alias 配置失败"
}

minio_read_confirmation() {
  local prompt=$1
  local confirmation

  case ${VIBELO_MINIO_CONFIRMATION_INPUT:-tty} in
    tty)
      IFS= read -r -p "$prompt" confirmation </dev/tty ||
        minio_die '无法从终端读取确认词'
      ;;
    stdin)
      IFS= read -r confirmation || minio_die '无法从标准输入读取确认词'
      ;;
    *)
      minio_die 'VIBELO_MINIO_CONFIRMATION_INPUT 只能是 tty 或 stdin'
      ;;
  esac

  printf '%s' "$confirmation"
}

minio_create_audit_dir() {
  local requested_dir=$1

  if [[ -z $requested_dir ]]; then
    requested_dir="$PWD/minio-audit-$(date -u +%Y%m%dT%H%M%SZ)"
  fi

  mkdir -p -- "$requested_dir"
  chmod 700 "$requested_dir"
  (
    cd -- "$requested_dir"
    pwd -P
  )
}

minio_build_manifest() {
  local alias_name=$1
  local bucket_name=$2
  local output_file=$3
  local helper_file=$4

  minio_mc --json ls --recursive "$alias_name/$bucket_name" |
    python3 "$helper_file" build --output "$output_file"
}

minio_print_manifest_summary() {
  local label=$1
  local manifest_file=$2
  local helper_file=$3

  printf '%s：' "$label"
  python3 "$helper_file" summary --manifest "$manifest_file"
}
