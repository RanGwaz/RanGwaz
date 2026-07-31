#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=minio-common.sh
source "$SCRIPT_DIR/minio-common.sh"

SOURCE_ENDPOINT='http://127.0.0.1:19090'
TARGET_ENDPOINT='http://127.0.0.1:9000'
BUCKET='rangwaz-media'
AUDIT_DIR=''
MAX_WORKERS=4
HELPER="$SCRIPT_DIR/minio_manifest.py"

usage() {
  cat <<'EOF'
用法：
  ./minio-migrate.sh [--bucket rangwaz-media] [--audit-dir /安全目录]
                      [--max-workers 4]

脚本从 ECS 的 127.0.0.1:19090（SSH 反向隧道源）流式 mirror 到
127.0.0.1:9000（目标 MinIO），不创建 65 GiB 中间包。
EOF
}

while (($# > 0)); do
  case "$1" in
    --bucket)
      (($# >= 2)) || minio_die "--bucket 缺少值"
      BUCKET=$2
      shift 2
      ;;
    --audit-dir)
      (($# >= 2)) || minio_die "--audit-dir 缺少值"
      AUDIT_DIR=$2
      shift 2
      ;;
    --max-workers)
      (($# >= 2)) || minio_die "--max-workers 缺少值"
      MAX_WORKERS=$2
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
[[ $MAX_WORKERS =~ ^[0-9]+$ ]] &&
  ((MAX_WORKERS >= 1 && MAX_WORKERS <= 32)) ||
  minio_die "--max-workers 必须是 1 到 32 的整数"
minio_require_command curl
minio_require_command mc
minio_require_command python3

mirror_help=$(mc mirror --help 2>&1) ||
  minio_die "无法读取 mc mirror 帮助，请检查 mc 安装"
# --md5 是新版 mc 的隐藏兼容参数，普通帮助文本可能不列出；在真实
# mirror 命令中保留它，但这里只用可见参数判断客户端是否足够新。
for required_flag in --max-workers --summary; do
  [[ $mirror_help == *"$required_flag"* ]] ||
    minio_die "当前 mc 版本过旧，缺少 $required_flag；请更新官方 mc 后重试"
done
unset mirror_help required_flag

AUDIT_DIR=$(minio_create_audit_dir "$AUDIT_DIR")
minio_note "审计文件目录：$AUDIT_DIR"

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

if ! minio_mc ls "target/$BUCKET" >/dev/null 2>&1; then
  minio_note "目标 bucket 尚不存在。"
  IFS= read -r -p "输入 CREATE $BUCKET 以创建空目标 bucket：" create_confirmation </dev/tty
  [[ $create_confirmation == "CREATE $BUCKET" ]] ||
    minio_die "未确认创建目标 bucket"
  minio_mc mb "target/$BUCKET"
fi

minio_note "正在生成迁移前精确清单；317,076 个对象时需要等待一段时间..."
minio_build_manifest source "$BUCKET" "$AUDIT_DIR/source-before.jsonl" "$HELPER"
minio_build_manifest target "$BUCKET" "$AUDIT_DIR/target-before.jsonl" "$HELPER"
minio_print_manifest_summary "迁移前源清单" "$AUDIT_DIR/source-before.jsonl" "$HELPER"
minio_print_manifest_summary "迁移前目标清单" "$AUDIT_DIR/target-before.jsonl" "$HELPER"

cat >&2 <<EOF

硬门禁：
1. 已停止所有会写入源 bucket 的服务；
2. 目标为 $TARGET_ENDPOINT/$BUCKET；
3. 脚本不会删除目标多余对象，也不会忽略复制错误；
4. 中断后可重新运行本脚本。
EOF

IFS= read -r -p "输入 MIRROR $BUCKET 开始流式迁移：" mirror_confirmation </dev/tty
[[ $mirror_confirmation == "MIRROR $BUCKET" ]] ||
  minio_die "未确认迁移"

minio_note "开始 mc mirror（并发 $MAX_WORKERS）。请保持 Windows 隧道窗口运行..."
minio_note "--summary 模式可能长时间不显示逐对象进度；只要进程和隧道仍存活就不要中断。"
set +e
minio_mc mirror \
  --overwrite \
  --retry \
  --md5 \
  --max-workers "$MAX_WORKERS" \
  --summary \
  "source/$BUCKET" \
  "target/$BUCKET"
mirror_result=$?
set -e

if ((mirror_result != 0)); then
  minio_die "mc mirror 返回 $mirror_result。源数据未被修改；修复网络后重新运行即可断点续传。"
fi

minio_note "mirror 完成，正在生成迁移后精确清单..."
minio_build_manifest source "$BUCKET" "$AUDIT_DIR/source-after.jsonl" "$HELPER"
minio_build_manifest target "$BUCKET" "$AUDIT_DIR/target-after.jsonl" "$HELPER"
minio_print_manifest_summary "迁移后源清单" "$AUDIT_DIR/source-after.jsonl" "$HELPER"
minio_print_manifest_summary "迁移后目标清单" "$AUDIT_DIR/target-after.jsonl" "$HELPER"

set +e
python3 "$HELPER" compare \
  --source "$AUDIT_DIR/source-before.jsonl" \
  --target "$AUDIT_DIR/source-after.jsonl" \
  --differences "$AUDIT_DIR/source-changed-differences.jsonl"
compare_result=$?
set -e
if ((compare_result == 2)); then
  minio_die "迁移期间源 bucket 发生变化。必须冻结写入后重新迁移和验证。"
elif ((compare_result != 0)); then
  minio_die "源清单稳定性比较失败"
fi

set +e
python3 "$HELPER" compare \
  --source "$AUDIT_DIR/source-after.jsonl" \
  --target "$AUDIT_DIR/target-after.jsonl" \
  --differences "$AUDIT_DIR/source-target-differences.jsonl"
compare_result=$?
set -e
if ((compare_result == 2)); then
  minio_die "目标 key+size 与源不一致。不要启动后端；查看差异文件并重新运行 mirror。"
elif ((compare_result != 0)); then
  minio_die "源目标清单比较失败"
fi

minio_note "迁移门禁通过：源未变化，目标对象数、总字节、全量 key+size 均与源一致。"
minio_note "下一步必须运行 minio-validate.sh 完成分层 SHA256 抽样，之后才能切换应用。"
