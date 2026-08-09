#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

for script in \
  "$ROOT/ops/jobs/run-content-pipeline.sh" \
  "$ROOT/ops/jobs/run-vectorize-job.sh" \
  "$ROOT/ops/jobs/content-job-preflight.sh" \
  "$ROOT/ops/jobs/install-content-timer.sh" \
  "$ROOT/ops/jobs/install-vector-timer.sh"; do
  bash -n "$script"
done

grep -q '^Persistent=false$' "$ROOT/ops/jobs/systemd/vibelo-content-ingest.timer"
grep -q '^MemoryMax=1024M$' "$ROOT/ops/jobs/systemd/vibelo-content-ingest.service"
grep -q 'flock --nonblock' "$ROOT/ops/jobs/systemd/vibelo-content-ingest.service"
grep -q '^VIBELO_CONTENT_COLLECT_ENABLED=false$' "$ROOT/ops/jobs/content-job.env.example"
grep -q '^Persistent=false$' "$ROOT/ops/jobs/systemd/vibelo-vectorize.timer"
grep -q 'MemTotal' "$ROOT/ops/jobs/run-vectorize-job.sh"
grep -q '^Restart=on-failure$' "$ROOT/ops/jobs/systemd/vibelo-vector-recall.service"
grep -q 'SENSITIVE_SERVICE_GROUPS=(root docker sudo wheel adm lxd systemd-journal)' \
  "$ROOT/ops/jobs/install-vector-timer.sh"
grep -q 'id -nG.*user' "$ROOT/ops/jobs/install-vector-timer.sh"
grep -q '^VIBELO_EMBED_PROJECTION_VERSION=siglip-image-feature-l2-rp512-seed20260606-v1$' \
  "$ROOT/ops/jobs/vector-job.env.example"

bash -s -- "$ROOT/ops/jobs/install-vector-timer.sh" <<'BASH'
set -Eeuo pipefail
source "$1"
MOCK_GROUPS='vibelo-vectorize vibelo-vector-runtime'
id() {
  if [[ ${1:-} == -nG ]]; then
    printf '%s\n' "$MOCK_GROUPS"
  else
    command id "$@"
  fi
}
assert_safe_service_groups vibelo-vectorize
MOCK_GROUPS='vibelo-vectorize vibelo-vector-runtime docker'
if (assert_safe_service_groups vibelo-vectorize) 2>/dev/null; then
  printf '向量服务账号敏感附加组动态门禁未生效。\n' >&2
  exit 1
fi
BASH

if grep -Eq 'LTAI[0-9A-Za-z]{12,}' \
  "$ROOT/tools/dataset_collector.py" \
  "$ROOT/tools/import_images.py" \
  "$ROOT/ops/jobs/content-job.env.example" \
  "$ROOT/ops/jobs/vector-job.env.example"; then
  printf '检测到内容任务代码中存在硬编码凭据。\n' >&2
  exit 1
fi

grep -q '公网定时器禁止运行浏览器采集' "$ROOT/ops/jobs/run-content-pipeline.sh"
grep -q '必须保持 VIBELO_CONTENT_COLLECT_ENABLED=false' "$ROOT/ops/jobs/content-job-preflight.sh"
grep -q '^quiesce_content_timer$' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q 'reject_task_tree_symlinks' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q -- '--no-dereference' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q 'TUNING_KEYS=(' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q '^prepare_minimal_environment$' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q '^publish_minimal_environment$' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q 'ENV_PUBLISH_STARTED=true' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q 'systemctl is-enabled.*TIMER_UNIT' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q 'systemctl disable --now.*TIMER_UNIT' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q 'restore_timer_before_publish' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q 'id -gn.*SERVICE_USER' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q 'root|docker|sudo|wheel' "$ROOT/ops/jobs/install-content-timer.sh"
grep -q '任务树禁止符号链接' "$ROOT/ops/jobs/run-content-pipeline.sh"
grep -q 'APP_MODERATION_TOKEN:' "$ROOT/infra/docker-compose.public.yml"
if grep -q 'chown -R' "$ROOT/ops/jobs/install-content-timer.sh"; then
  printf '内容任务安装器禁止递归跟随式 chown -R。\n' >&2
  exit 1
fi

unit_install_line=$(grep -n -m1 'vibelo-content-ingest.service" /etc/systemd/system/' \
  "$ROOT/ops/jobs/install-content-timer.sh" | cut -d: -f1)
publish_line=$(grep -n -m1 '^publish_minimal_environment$' \
  "$ROOT/ops/jobs/install-content-timer.sh" | cut -d: -f1)
[[ -n $unit_install_line && -n $publish_line && $publish_line -gt $unit_install_line ]] || {
  printf '内容任务环境必须在 unit 与迁权准备完成后才原子发布。\n' >&2
  exit 1
}

printf '内容定时任务静态回归测试通过。\n'
