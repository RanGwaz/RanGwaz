#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $- == *x* ]]; then
  set +x
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=public-common.sh
source "$SCRIPT_DIR/public-common.sh"
vibelo_lock_docker_to_local_engine
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd -P)
ENV_FILE="$REPO_ROOT/.env.public"
COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.public.yml"
IMPORT_SCRIPT="$SCRIPT_DIR/import-public-image-bundle.sh"
DEPENDENCY_SCRIPT="$SCRIPT_DIR/install-search-reindex-dependencies.sh"
PREFLIGHT_SCRIPT="$SCRIPT_DIR/preflight.sh"
MINIO_SCRIPT="$REPO_ROOT/ops/migration/minio/start-minio-target.sh"
REINDEX_SCRIPT="$REPO_ROOT/tools/reindex_search_es.py"

ACTION=''
RELEASE=''
BUNDLE_DIRECTORY=''
WHEEL_PATH='/data/migration/search-reindex/pymysql-1.1.2-py3-none-any.whl'
VENV_PATH='/opt/vibelo/.venv-ops'
CONFIRMED_RELEASE=''
CONFIRM_DATABASE_COMPATIBLE=false
DRY_RUN=false
CURRENT_RELEASE=''
TARGET_BACKEND_IMAGE=''
TARGET_FRONTEND_IMAGE=''
CANDIDATE_ENV=''
ENV_PUBLISHED=false
MAINTENANCE_STARTED=false
CONTENT_TIMER_WAS_ACTIVE=false
CONTENT_TIMER_WAS_ENABLED=false
ORIGIN_MAIN_COMMIT=''
BUNDLE_MINIO_IMAGE_ID=''
RUNTIME_CONTRACT_PATHS=(
  infra/docker-compose.public.yml
  infra/nginx
  tools/reindex_search_es.py
  tools/requirements_search_reindex.txt
)

usage() {
  cat <<'EOF'
用法：
  sudo bash ops/public/public-release.sh validate \
    --release <完整40位Git SHA>

  sudo bash ops/public/public-release.sh deploy \
    --release <完整40位Git SHA> \
    --confirm-release <同一个完整40位Git SHA>

  sudo bash ops/public/public-release.sh rollback \
    --release <已验收旧版本的完整40位Git SHA> \
    --confirm-release <同一个完整40位Git SHA> \
    --confirm-database-compatible

可选参数：
  --bundle-directory PATH  默认 /data/releases/<SHA>
  --wheel PATH             默认固定 PyMySQL 1.1.2 wheel 路径
  --venv PATH              默认 /opt/vibelo/.venv-ops
  --dry-run                等同 validate；不导入、不切换、不停止或启动服务

deploy/rollback 是单 ECS 的受控 HTTP 发布入口。它只使用本地完整 SHA bundle，
不会构建、拉取镜像、启用 TLS、启用推荐 profile 或删除数据卷。
EOF
}

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

note() {
  printf '%s\n' "$*"
}

while (($# > 0)); do
  case "$1" in
    validate | deploy | rollback)
      [[ -z $ACTION ]] || die '只能指定一个动作：validate、deploy 或 rollback'
      ACTION=$1
      shift
      ;;
    --release)
      (($# >= 2)) || die '--release 缺少值'
      RELEASE=$2
      shift 2
      ;;
    --bundle-directory)
      (($# >= 2)) || die '--bundle-directory 缺少值'
      BUNDLE_DIRECTORY=$2
      shift 2
      ;;
    --wheel)
      (($# >= 2)) || die '--wheel 缺少值'
      WHEEL_PATH=$2
      shift 2
      ;;
    --venv)
      (($# >= 2)) || die '--venv 缺少值'
      VENV_PATH=$2
      shift 2
      ;;
    --confirm-release)
      (($# >= 2)) || die '--confirm-release 缺少值'
      CONFIRMED_RELEASE=$2
      shift 2
      ;;
    --confirm-database-compatible)
      CONFIRM_DATABASE_COMPATIBLE=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      die "未知参数：$1"
      ;;
  esac
done

[[ -n $ACTION ]] || die '必须指定 validate、deploy 或 rollback'
[[ $RELEASE =~ ^[0-9a-fA-F]{40}$ ]] || die '--release 必须是完整 40 位 Git SHA'
RELEASE=${RELEASE,,}
[[ -n $BUNDLE_DIRECTORY ]] || BUNDLE_DIRECTORY="/data/releases/$RELEASE"
if [[ $DRY_RUN == true ]]; then
  ACTION=validate
fi

if [[ $ACTION == validate ]]; then
  [[ -z $CONFIRMED_RELEASE ]] || die 'validate/dry-run 不接受 --confirm-release'
  [[ $CONFIRM_DATABASE_COMPATIBLE == false ]] ||
    die 'validate/dry-run 不接受 --confirm-database-compatible'
else
  [[ $EUID -eq 0 ]] || die 'deploy/rollback 必须使用 sudo 或 root 执行'
  [[ ${CONFIRMED_RELEASE,,} == "$RELEASE" ]] ||
    die '--confirm-release 必须逐字等于目标完整 SHA'
fi
if [[ $ACTION == rollback && $CONFIRM_DATABASE_COMPATIBLE != true ]]; then
  die 'rollback 必须显式传入 --confirm-database-compatible'
fi

for command_name in git docker env stat awk grep sha256sum python3 mktemp rm chmod; do
  command -v "$command_name" >/dev/null 2>&1 || die "缺少命令：$command_name"
done
if [[ $ACTION != validate ]]; then
  for command_name in systemctl curl flock chown mv touch date; do
    command -v "$command_name" >/dev/null 2>&1 || die "缺少发布命令：$command_name"
  done
fi
vibelo_run_clean_environment docker compose -p vibelo-public version >/dev/null 2>&1 ||
  die 'Docker Compose 插件不可用'

[[ -f $ENV_FILE && ! -L $ENV_FILE ]] || die '.env.public 必须是普通文件且不能是符号链接'
[[ $(stat -c '%a' -- "$ENV_FILE") == 600 ]] || die '.env.public 权限必须是 600'
for required_file in \
  "$COMPOSE_FILE" \
  "$IMPORT_SCRIPT" \
  "$DEPENDENCY_SCRIPT" \
  "$PREFLIGHT_SCRIPT" \
  "$MINIO_SCRIPT" \
  "$REINDEX_SCRIPT"; do
  [[ -f $required_file && ! -L $required_file ]] || die "缺少安全发布文件：$required_file"
done

read_env_plain() {
  local key=$1
  local -a records=()
  local raw=''

  mapfile -t records < <(awk -v key="$key" 'index($0, key "=") == 1 {print substr($0, length(key) + 2)}' "$ENV_FILE")
  ((${#records[@]} <= 1)) || die ".env.public 中 $key 重复"
  if ((${#records[@]} == 0)); then
    ENV_VALUE=''
    return 1
  fi
  raw=${records[0]%$'\r'}
  if ((${#raw} >= 2)) &&
    { [[ ${raw:0:1} == "'" && ${raw: -1} == "'" ]] ||
      [[ ${raw:0:1} == '"' && ${raw: -1} == '"' ]]; }; then
    raw=${raw:1:${#raw}-2}
  fi
  ENV_VALUE=${raw//\\\'/\'}
  return 0
}

require_disabled_feature() {
  local key=$1
  if read_env_plain "$key"; then
    [[ ${ENV_VALUE,,} == false ]] || die "$key 必须保持 false；简化入口不会启用推荐"
  fi
}

read_current_release() {
  local backend_ref=''
  local frontend_ref=''

  read_env_plain VIBELO_BACKEND_IMAGE || true
  backend_ref=$ENV_VALUE
  read_env_plain VIBELO_FRONTEND_IMAGE || true
  frontend_ref=$ENV_VALUE
  if [[ -z $backend_ref && -z $frontend_ref ]]; then
    CURRENT_RELEASE=''
    return 0
  fi
  [[ $backend_ref =~ ^vibelo-public-backend:([0-9a-f]{40})$ ]] ||
    die '当前 VIBELO_BACKEND_IMAGE 必须是完整 SHA tag，不能是 latest/短 SHA/digest'
  CURRENT_RELEASE=${BASH_REMATCH[1]}
  [[ $frontend_ref == "vibelo-public-frontend:$CURRENT_RELEASE" ]] ||
    die '当前前后端镜像必须使用同一个完整 SHA tag'
}

verify_running_minio_matches_bundle() {
  local rc=0

  if vibelo_running_compose_service_uses_image_id \
    vibelo-public \
    minio \
    vibelo-public-minio-1 \
    "$BUNDLE_MINIO_IMAGE_ID"; then
    note '[通过] release bundle 的固定 MinIO image ID 与当前运行容器完全一致'
    return 0
  else
    rc=$?
  fi
  if ((rc == 1)); then
    die 'release bundle 与当前运行 MinIO 使用同一固定 tag 但 image ID 不同；拒绝在维护窗口中重绑 tag'
  fi
  die '无法唯一读取当前运行 MinIO 的容器身份和实际 image ID'
}

require_trusted_worktree() {
  [[ $(git rev-parse HEAD 2>/dev/null || true) == "$ORIGIN_MAIN_COMMIT" ]] ||
    die '发布期间 HEAD 已偏离 origin/main；拒绝混用旧 helper'
  [[ -z $(git status --porcelain=v1 --untracked-files=no) ]] ||
    die '发布期间 Git 已跟踪文件发生变化；拒绝继续调用 helper'
}

require_disabled_feature VECTOR_ENABLED
require_disabled_feature MODEL_RECALL_ENABLED
require_disabled_feature MODEL_RANKING_ENABLED
if read_env_plain COMPOSE_PROFILES && [[ -n $ENV_VALUE ]]; then
  die '简化入口不接受 COMPOSE_PROFILES；不会启用 local-database/recommendation'
fi
if read_env_plain APP_WEB_ALLOWED_ORIGIN_PATTERNS && [[ $ENV_VALUE == *https://* ]]; then
  die '检测到 HTTPS origin；简化入口只管理当前 HTTP/IP 部署，避免静默移除 TLS'
fi
read_current_release
if [[ $ACTION == rollback ]]; then
  [[ -n $CURRENT_RELEASE ]] || die '尚无当前完整 SHA release，不能执行 rollback'
  [[ $CURRENT_RELEASE != "$RELEASE" ]] || die '回滚目标与当前 release 相同'
fi

cd "$REPO_ROOT"
[[ -z $(git status --porcelain=v1 --untracked-files=no) ]] ||
  die 'ECS Git 已跟踪文件不干净；拒绝混合发布'
target_commit=$(git rev-parse --verify "$RELEASE^{commit}" 2>/dev/null || true)
[[ ${target_commit,,} == "$RELEASE" ]] ||
  die '本地 Git 尚无目标 commit；请先 git fetch origin，再重试'
git show-ref --verify --quiet refs/remotes/origin/main ||
  die '缺少 origin/main；请先 git fetch origin main'
ORIGIN_MAIN_COMMIT=$(git rev-parse refs/remotes/origin/main)
git merge-base --is-ancestor "$RELEASE" refs/remotes/origin/main ||
  die '目标 commit 尚未推送到 origin/main'
if ! vibelo_git_release_head_is_trusted "$ACTION" "$RELEASE" "$ORIGIN_MAIN_COMMIT"; then
  case "$ACTION" in
    deploy)
      die 'deploy 要求当前 HEAD、目标 release 与 origin/main 三者完全一致；请先在 main 执行 git pull --ff-only'
      ;;
    validate | rollback)
      die "$ACTION 要求当前 HEAD 等于 origin/main，以确保使用最新受信任发布器；请先更新 main"
      ;;
  esac
fi

[[ -n $CURRENT_RELEASE ]] ||
  die '当前环境尚无完整 SHA release 基线；简化入口无法证明数据库迁移安全，请先走完整首次发布流程'
current_release_commit=$(git rev-parse --verify "$CURRENT_RELEASE^{commit}" 2>/dev/null || true)
[[ ${current_release_commit,,} == "$CURRENT_RELEASE" ]] ||
  die '本地 Git 缺少当前已部署 release commit；请先 fetch 完整历史'
if vibelo_git_path_has_changes \
  "$CURRENT_RELEASE" "$RELEASE" \
  backend/src/main/resources/db/migration; then
  die '当前 release 到目标 release 包含 Flyway migration 改动；请走完整数据库迁移发布流程'
else
  migration_check_rc=$?
  ((migration_check_rc == 1)) || die '无法检查 release 间数据库 migration 差异'
fi
if vibelo_git_path_has_changes \
  "$CURRENT_RELEASE" "$RELEASE" \
  "${RUNTIME_CONTRACT_PATHS[@]}"; then
  die '当前 release 到目标 release 的 Compose/Nginx/搜索重建运行契约不同；请按完整手册发布'
else
  forward_contract_check_rc=$?
  ((forward_contract_check_rc == 1)) ||
    die '无法检查当前 release 到目标 release 的运行契约差异'
fi
if [[ $RELEASE != "$ORIGIN_MAIN_COMMIT" ]]; then
  if vibelo_git_path_has_changes \
    "$RELEASE" "$ORIGIN_MAIN_COMMIT" \
    "${RUNTIME_CONTRACT_PATHS[@]}"; then
    die '目标旧 release 与当前实际使用的 Compose/Nginx/搜索重建运行契约不同；请按完整手册回滚'
  else
    runtime_contract_check_rc=$?
    ((runtime_contract_check_rc == 1)) ||
      die '无法检查目标旧 release 与当前发布运行契约的差异'
  fi
fi

running_gateway_output=$(docker ps \
    --filter 'label=com.docker.compose.project=vibelo-public' \
    --filter 'label=com.docker.compose.service=gateway' \
    --format '{{.ID}}') || die '无法查询本机 vibelo-public Gateway 容器'
running_gateways=()
if [[ -n $running_gateway_output ]]; then
  mapfile -t running_gateways <<<"$running_gateway_output"
fi
if ((${#running_gateways[@]} > 1)); then
  die '检测到多个 vibelo-public Gateway 容器'
elif ((${#running_gateways[@]} == 1)) &&
  docker port "${running_gateways[0]}" 443/tcp 2>/dev/null | grep -q .; then
  die '当前 Gateway 已发布 443；请按 TLS 专用手册更新，简化 HTTP 入口不会降级 TLS'
fi
unset running_gateways running_gateway_output

note '=== 1/5 只读主机与配置预检 ==='
vibelo_run_clean_environment bash "$PREFLIGHT_SCRIPT" --allow-running-gateway-ports

note '=== 2/5 在线 MinIO 严格只读验收 ==='
vibelo_run_clean_environment bash "$MINIO_SCRIPT" --verify-online

note '=== 3/5 完整离线 release 只读验收 ==='
bundle_validation_output=$(bash "$IMPORT_SCRIPT" \
  --release "$RELEASE" \
  --target-directory "$BUNDLE_DIRECTORY" \
  --validate-only)
printf '%s\n' "$bundle_validation_output"
mapfile -t bundle_minio_id_lines < <(
  printf '%s\n' "$bundle_validation_output" |
    awk -F= '$1 == "VIBELO_MINIO_IMAGE_ID" { print substr($0, index($0, "=") + 1) }'
)
((${#bundle_minio_id_lines[@]} == 1)) ||
  die '离线 release 验收未返回唯一的 MinIO image ID'
BUNDLE_MINIO_IMAGE_ID=${bundle_minio_id_lines[0],,}
[[ $BUNDLE_MINIO_IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ ]] ||
  die '离线 release 返回的 MinIO image ID 格式无效'
unset bundle_minio_id_lines bundle_validation_output
verify_running_minio_matches_bundle

note '=== 4/5 固定搜索依赖只读验收 ==='
bash "$DEPENDENCY_SCRIPT" \
  --wheel "$WHEEL_PATH" \
  --venv "$VENV_PATH" \
  --validate-only

note '=== 5/5 目标提交与安全边界验收 ==='
note "目标 release：$RELEASE"
note "当前 release：${CURRENT_RELEASE:-首次发布（未设置）}"
note '确认：不使用 latest，不在线拉取/构建，不启用 TLS 或 recommendation，不删除数据卷。'

if [[ $ACTION == validate ]]; then
  note '只读 validate/dry-run 全部通过；没有导入镜像、修改 Git/.env 或操作服务。'
  exit 0
fi

command -v flock >/dev/null 2>&1 || die '缺少 flock，无法建立单实例发布锁'
exec 9>/run/lock/vibelo-public-release.lock
flock -n 9 || die '已有另一个公网发布/回滚正在运行'

failure_guidance() {
  local rc=$?
  trap - EXIT
  if ((rc == 0)); then
    return
  fi
  if [[ -n $CANDIDATE_ENV && $CANDIDATE_ENV == "$REPO_ROOT/.env.public.candidate."* ]]; then
    rm -f -- "$CANDIDATE_ENV"
    CANDIDATE_ENV=''
  fi
  printf '\n发布未完成（退出码 %d）。\n' "$rc" >&2
  if [[ $MAINTENANCE_STARTED == true ]]; then
    printf '%s\n' '维护窗口已经开始；内容定时器保持停用，请先检查当前容器、Gateway/Backend 和重建日志。' >&2
  fi
  if [[ $ENV_PUBLISHED == true && -n $CURRENT_RELEASE ]]; then
    printf '确认数据库仍向前兼容后，可执行：\n' >&2
    printf 'sudo bash ops/public/public-release.sh rollback --release %s --confirm-release %s --confirm-database-compatible\n' \
      "$CURRENT_RELEASE" "$CURRENT_RELEASE" >&2
  else
    printf '%s\n' '尚未切换镜像环境；修复报错后可直接重试同一命令。' >&2
  fi
  exit "$rc"
}
trap failure_guidance EXIT

note '=== 保持最新受信任发布器；不切换或改写 ECS Git 工作树 ==='
require_trusted_worktree

note '=== 导入已验收的本地镜像（无网络 pull） ==='
verify_running_minio_matches_bundle
bash "$IMPORT_SCRIPT" \
  --release "$RELEASE" \
  --target-directory "$BUNDLE_DIRECTORY"
bash "$DEPENDENCY_SCRIPT" \
  --wheel "$WHEEL_PATH" \
  --venv "$VENV_PATH"

TARGET_BACKEND_IMAGE="vibelo-public-backend:$RELEASE"
TARGET_FRONTEND_IMAGE="vibelo-public-frontend:$RELEASE"

rewrite_env_images() {
  local output=$1
  awk \
    -v backend="$TARGET_BACKEND_IMAGE" \
    -v frontend="$TARGET_FRONTEND_IMAGE" '
      BEGIN { backend_seen = 0; frontend_seen = 0 }
      /^VIBELO_BACKEND_IMAGE=/ {
        if (!backend_seen) print "VIBELO_BACKEND_IMAGE=" backend
        backend_seen = 1
        next
      }
      /^VIBELO_FRONTEND_IMAGE=/ {
        if (!frontend_seen) print "VIBELO_FRONTEND_IMAGE=" frontend
        frontend_seen = 1
        next
      }
      { print }
      END {
        if (!backend_seen) print "VIBELO_BACKEND_IMAGE=" backend
        if (!frontend_seen) print "VIBELO_FRONTEND_IMAGE=" frontend
      }
    ' "$ENV_FILE" >"$output"
  chown --reference="$ENV_FILE" -- "$output"
  chmod 600 -- "$output"
}

CANDIDATE_ENV=$(mktemp "$REPO_ROOT/.env.public.candidate.XXXXXXXX")
rewrite_env_images "$CANDIDATE_ENV"
vibelo_public_compose "$CANDIDATE_ENV" "$COMPOSE_FILE" config --quiet

for target_ref in "$TARGET_BACKEND_IMAGE" "$TARGET_FRONTEND_IMAGE"; do
  docker image inspect --platform linux/amd64 "$target_ref" >/dev/null
  [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$target_ref") == "$RELEASE" ]] ||
    die "镜像 revision label 不匹配：$target_ref"
done

note '=== 进入维护窗口前再次只读验收在线 MinIO ==='
require_trusted_worktree
vibelo_run_clean_environment bash "$MINIO_SCRIPT" --verify-online

MAINTENANCE_STARTED=true
if systemctl cat vibelo-content-ingest.timer >/dev/null 2>&1; then
  systemctl is-active --quiet vibelo-content-ingest.timer && CONTENT_TIMER_WAS_ACTIVE=true || true
  systemctl is-enabled --quiet vibelo-content-ingest.timer && CONTENT_TIMER_WAS_ENABLED=true || true
  systemctl disable --now vibelo-content-ingest.timer
fi
if systemctl cat vibelo-content-ingest.service >/dev/null 2>&1; then
  systemctl stop vibelo-content-ingest.service
  systemctl is-active --quiet vibelo-content-ingest.service && die '内容导入任务仍在运行' || true
fi

note '=== 进入维护窗口：只停止七个非 MinIO 服务 ==='
vibelo_public_compose "$ENV_FILE" "$COMPOSE_FILE" \
  stop gateway backend frontend kafka zookeeper redis elasticsearch

mv -T -- "$CANDIDATE_ENV" "$ENV_FILE"
CANDIDATE_ENV=''
chmod 600 -- "$ENV_FILE"
ENV_PUBLISHED=true

compose() {
  vibelo_public_compose "$ENV_FILE" "$COMPOSE_FILE" "$@"
}

note '=== 只读验收既有 MinIO ==='
vibelo_run_clean_environment bash "$MINIO_SCRIPT" --verify-online

note '=== Elasticsearch 与原子搜索索引发布 ==='
compose up -d --wait --no-build --pull never elasticsearch
(
  for key in VIBELO_DB_HOST VIBELO_DB_PORT VIBELO_DB_NAME VIBELO_DB_USER VIBELO_DB_PASSWORD; do
    read_env_plain "$key" || die ".env.public 缺少 $key"
    export "$key=$ENV_VALUE"
  done
  export VIBELO_ES_URL='http://127.0.0.1:9200'
  export VIBELO_ES_INDEX='rangwaz-images'
  exec "$VENV_PATH/bin/python" "$REINDEX_SCRIPT" \
    --confirm-promote \
    --replace-conflicting-index
)

note '=== 严格分阶段恢复应用 ==='
compose up -d --wait --no-build --pull never redis zookeeper kafka
compose up -d --wait --no-build --pull never --no-deps backend frontend
compose up -d --wait --no-build --pull never --no-deps gateway

curl --fail --silent --show-error --max-time 10 http://127.0.0.1/gateway/health >/dev/null
curl --fail --silent --show-error --max-time 15 http://127.0.0.1/api/actuator/health >/dev/null
curl --fail --silent --show-error --max-time 15 \
  'http://127.0.0.1/api/feed?page=1&pageSize=1' >/dev/null

if [[ $CONTENT_TIMER_WAS_ENABLED == true ]]; then
  systemctl enable vibelo-content-ingest.timer
fi
if [[ $CONTENT_TIMER_WAS_ACTIVE == true ]]; then
  systemctl start vibelo-content-ingest.timer
fi
MAINTENANCE_STARTED=false

history_file='/data/releases/vibelo-public-deployments.tsv'
if [[ -d /data/releases && ! -L /data/releases &&
  (! -e $history_file || (-f $history_file && ! -L $history_file)) ]] &&
  { touch "$history_file" && chmod 600 -- "$history_file" &&
    printf '%s\t%s\t%s\t%s\n' \
      "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
      "$ACTION" \
      "${CURRENT_RELEASE:--}" \
      "$RELEASE" >>"$history_file"; }; then
  note "发布审计记录已追加：$history_file"
else
  printf '警告：服务已健康，但无法安全追加发布审计记录：%s\n' "$history_file" >&2
fi

trap - EXIT
note "公网 $ACTION 完成：${CURRENT_RELEASE:--} -> $RELEASE"
note 'TLS 与 recommendation 均未启用；未执行在线 pull/build，也未删除任何数据卷。'
