#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=minio-common.sh
source "$SCRIPT_DIR/minio-common.sh"

SOURCE_ENDPOINT='http://127.0.0.1:19090'
TARGET_ENDPOINT='http://127.0.0.1:9000'
BUCKET='rangwaz-media'
AUDIT_DIR=''
SAMPLE_COUNT=1000
HELPER="$SCRIPT_DIR/minio_manifest.py"

usage() {
  cat <<'EOF'
用法：
  ./minio-validate.sh [--bucket rangwaz-media] \
    [--sample-count 1000] [--audit-dir /安全目录]

依次执行：
1. 源、目标对象数和总字节精确清单；
2. 全量 key+size 比较；
3. 按对象大小分层、确定性选取约 1000 个对象，逐个流式计算 SHA256。
EOF
}

while (($# > 0)); do
  case "$1" in
    --bucket)
      (($# >= 2)) || minio_die "--bucket 缺少值"
      BUCKET=$2
      shift 2
      ;;
    --sample-count)
      (($# >= 2)) || minio_die "--sample-count 缺少值"
      SAMPLE_COUNT=$2
      shift 2
      ;;
    --audit-dir)
      (($# >= 2)) || minio_die "--audit-dir 缺少值"
      AUDIT_DIR=$2
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      minio_die "未知参数：$1"
      ;;
  esac
done

minio_require_bucket_name "$BUCKET"
[[ $SAMPLE_COUNT =~ ^[1-9][0-9]*$ ]] ||
  minio_die "--sample-count 必须是正整数"
((SAMPLE_COUNT <= 10000)) ||
  minio_die "--sample-count 最大为 10000，避免误下载过多对象"

minio_require_command curl
minio_require_command mc
minio_require_command python3

AUDIT_DIR=$(minio_create_audit_dir "$AUDIT_DIR")
minio_note "验证审计目录：$AUDIT_DIR"

minio_init_private_config
trap minio_cleanup_private_config EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

minio_check_health "$SOURCE_ENDPOINT" "Windows 源 MinIO（经反向隧道）"
minio_check_health "$TARGET_ENDPOINT" "ECS 目标 MinIO"
minio_configure_alias source "$SOURCE_ENDPOINT" "源 MinIO"
minio_configure_alias target "$TARGET_ENDPOINT" "目标 MinIO"

minio_mc ls "source/$BUCKET" >/dev/null ||
  minio_die "源 bucket 不存在或无列举权限：$BUCKET"
minio_mc ls "target/$BUCKET" >/dev/null ||
  minio_die "目标 bucket 不存在或无列举权限：$BUCKET"

minio_note "正在生成源、目标精确清单..."
minio_build_manifest source "$BUCKET" "$AUDIT_DIR/source.jsonl" "$HELPER"
minio_build_manifest target "$BUCKET" "$AUDIT_DIR/target.jsonl" "$HELPER"
minio_print_manifest_summary "源清单" "$AUDIT_DIR/source.jsonl" "$HELPER"
minio_print_manifest_summary "目标清单" "$AUDIT_DIR/target.jsonl" "$HELPER"

set +e
python3 "$HELPER" compare \
  --source "$AUDIT_DIR/source.jsonl" \
  --target "$AUDIT_DIR/target.jsonl" \
  --differences "$AUDIT_DIR/key-size-differences.jsonl"
compare_result=$?
set -e
if ((compare_result == 2)); then
  minio_die "全量 key+size 比较不一致。SHA256 抽样已阻止；先重新运行 mirror。"
elif ((compare_result != 0)); then
  minio_die "全量 key+size 比较失败"
fi

python3 "$HELPER" sample \
  --manifest "$AUDIT_DIR/source.jsonl" \
  --output "$AUDIT_DIR/sha256-sample.jsonl" \
  --count "$SAMPLE_COUNT"

minio_note "开始流式 SHA256 校验；不会在 ECS 落完整对象副本。"
set +e
python3 "$HELPER" verify \
  --mc "$(command -v mc)" \
  --config-dir "$MC_CONFIG_DIR" \
  --source-alias source \
  --target-alias target \
  --bucket "$BUCKET" \
  --sample "$AUDIT_DIR/sha256-sample.jsonl" \
  --report "$AUDIT_DIR/sha256-report.jsonl"
verify_result=$?
set -e
if ((verify_result == 2)); then
  minio_die "存在 SHA256 或对象字节数不一致。不要启动后端；查看 sha256-report.jsonl。"
elif ((verify_result != 0)); then
  minio_die "SHA256 校验执行失败；保留同一审计目录重跑可复用已完成的匹配项。"
fi

minio_note "全部验证门禁通过：精确数量、总字节、全量 key+size、分层 SHA256 抽样均一致。"
