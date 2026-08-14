#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
RELEASE_SCRIPT="$SCRIPT_DIR/public-release.sh"
IMPORT_SCRIPT="$SCRIPT_DIR/import-public-image-bundle.sh"
DEPENDENCY_SCRIPT="$SCRIPT_DIR/install-search-reindex-dependencies.sh"
PREFLIGHT_SCRIPT="$SCRIPT_DIR/preflight.sh"
LOCAL_RELEASE_SCRIPT="$SCRIPT_DIR/New-PublicReleaseBundle.ps1"
COMMON_SCRIPT="$SCRIPT_DIR/public-common.sh"

TEMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/vibelo-public-release-test.XXXXXXXX")
trap 'rm -rf -- "$TEMP_ROOT"' EXIT

# shellcheck source=public-common.sh
source "$COMMON_SCRIPT"

fail() {
  printf '失败：%s\n' "$*" >&2
  exit 1
}

for script in "$RELEASE_SCRIPT" "$IMPORT_SCRIPT" "$DEPENDENCY_SCRIPT" "$PREFLIGHT_SCRIPT" "$COMMON_SCRIPT"; do
  [[ -f $script ]] || fail "缺少脚本：$script"
  bash -n "$script" || fail "Shell 语法错误：$script"
done

[[ -f $LOCAL_RELEASE_SCRIPT ]] || fail '缺少 Windows 本地 release 薄入口'
grep -qF -- '--pull=false' "$LOCAL_RELEASE_SCRIPT" || fail '本地构建必须禁止更新基础镜像'
grep -qF -- "'build', '--pull=false', '--platform', 'linux/amd64'" "$LOCAL_RELEASE_SCRIPT" ||
  fail '本地构建必须固定 linux/amd64'
[[ $(grep -cF "'build', '--pull=false', '--platform', 'linux/amd64'" "$LOCAL_RELEASE_SCRIPT") -eq 2 ]] ||
  fail '本地入口必须且只能构建 Backend/Frontend 各一次'
grep -qF 'Export-PublicImageBundle.ps1' "$LOCAL_RELEASE_SCRIPT" || fail '本地入口必须复用固定导出器'

grep -qF -- '--validate-only' "$IMPORT_SCRIPT" || fail '镜像导入器缺少只读验收模式'
grep -qF -- '--validate-only' "$DEPENDENCY_SCRIPT" || fail '固定 wheel 安装器缺少只读验收模式'
grep -qF -- '--allow-running-gateway-ports' "$PREFLIGHT_SCRIPT" || fail '预检缺少安全更新端口模式'
grep -qF "label=com.docker.compose.project=vibelo-public" "$PREFLIGHT_SCRIPT" ||
  fail '预检没有把端口例外绑定到固定 Compose 项目'
grep -qF "label=com.docker.compose.service=gateway" "$PREFLIGHT_SCRIPT" ||
  fail '预检没有把端口例外绑定到 Gateway 服务'
grep -qF 'grep -Fqx -- "$busy_address"' "$PREFLIGHT_SCRIPT" ||
  fail '预检必须确认每一个监听地址都属于当前 Gateway'

for required in \
  '--confirm-release' \
  '--confirm-database-compatible' \
  '--no-build --pull never' \
  'stop gateway backend frontend kafka zookeeper redis elasticsearch' \
  'start-minio-target.sh' \
  '--confirm-promote' \
  'VECTOR_ENABLED' \
  'MODEL_RECALL_ENABLED' \
  'MODEL_RANKING_ENABLED' \
  'vibelo-content-ingest.timer' \
  'vibelo-content-ingest.service' \
  '443/tcp' \
  'flock -n' \
  'vibelo_git_release_head_is_trusted' \
  'vibelo_git_path_has_changes' \
  'vibelo_running_compose_service_uses_image_id' \
  'VIBELO_MINIO_IMAGE_ID' \
  'vibelo_run_clean_environment bash "$PREFLIGHT_SCRIPT"' \
  'vibelo_lock_docker_to_local_engine' \
  'vibelo_public_compose' \
  '--verify-online' \
  'infra/docker-compose.public.yml' \
  'infra/nginx' \
  'tools/reindex_search_es.py' \
  'tools/requirements_search_reindex.txt' \
  'refs/remotes/origin/main'; do
  grep -qF -- "$required" "$RELEASE_SCRIPT" || fail "简化发布入口缺少安全门禁：$required"
done
runtime_contract_block=$(
  sed -n '/^RUNTIME_CONTRACT_PATHS=(/,/^)$/p' "$RELEASE_SCRIPT"
)
expected_runtime_contract_block=$'RUNTIME_CONTRACT_PATHS=(\n  infra/docker-compose.public.yml\n  infra/nginx\n  tools/reindex_search_es.py\n  tools/requirements_search_reindex.txt\n)'
[[ $runtime_contract_block == "$expected_runtime_contract_block" ]] ||
  fail '运行契约路径必须且只能包含 Compose、Nginx、reindex 和固定 requirements'
[[ $(grep -cF '"$CURRENT_RELEASE" "$RELEASE"' "$RELEASE_SCRIPT") -ge 2 ]] ||
  fail 'validate/deploy/rollback 必须检查 current release 到目标 release 的运行契约'
grep -qF '"$RELEASE" "$ORIGIN_MAIN_COMMIT"' "$RELEASE_SCRIPT" ||
  fail '旧目标必须检查与 origin/main 当前运行契约的兼容性'
grep -qF 'deploy 要求当前 HEAD、目标 release 与 origin/main 三者完全一致' "$RELEASE_SCRIPT" ||
  fail 'deploy 必须使用最新受信任发布器且不得绕过 rollback 门禁'

if grep -Eq 'systemctl[^\n]*vibelo-content\.(timer|service)' "$RELEASE_SCRIPT"; then
  fail '发布入口使用了不存在的旧内容任务 unit 名'
fi
if grep -qF 'sudo bash "$MINIO_SCRIPT"' "$RELEASE_SCRIPT"; then
  fail '已要求 root 的发布路径不应再次依赖 sudo'
fi
grep -qF 'for command_name in systemctl curl flock chown mv touch date' "$RELEASE_SCRIPT" ||
  fail '正式发布缺少变更命令前置检查'
[[ $(grep -cF -- 'git status --porcelain=v1 --untracked-files=no' "$RELEASE_SCRIPT") -eq 2 ]] ||
  fail '发布初始与 formal helper 调用前都必须检查已跟踪文件清洁状态'
if grep -qF -- 'git status --porcelain=v1 --untracked-files=all' "$RELEASE_SCRIPT"; then
  fail '发布入口不得因无关个人未跟踪文件拒绝发布'
fi
if grep -Eq '(^|[[:space:]])git[[:space:]]+(switch|checkout|reset|clean)([[:space:]]|$)' "$RELEASE_SCRIPT"; then
  fail '发布入口不得切换/改写 Git 工作树；必须保留最新受信任 helper 与所有个人文件'
fi

if grep -Eq '(^|[[:space:]])docker[[:space:]]+(compose[[:space:]]+)?(build|pull)([[:space:]]|$)' "$RELEASE_SCRIPT"; then
  fail 'ECS 发布入口不得在线 build/pull'
fi
if grep -Eq 'docker[[:space:]]+compose[^\n]*(down|--profile|up[[:space:]]+--build)' "$RELEASE_SCRIPT"; then
  fail 'ECS 发布入口不得 down、启用 profile 或 up --build'
fi
if grep -qF 'docker-compose.public.tls.yml' "$RELEASE_SCRIPT"; then
  fail '简化 HTTP 发布入口不得自动叠加 TLS'
fi
if grep -Eq '(^|[^[:alnum:]_])latest([^[:alnum:]_]|$)' "$RELEASE_SCRIPT" &&
  ! grep -qF '不能是 latest' "$RELEASE_SCRIPT"; then
  fail '发布入口不得使用 latest'
fi

validate_line=$(grep -n -- '--validate-only' "$RELEASE_SCRIPT" | head -n 1 | cut -d: -f1)
import_line=$(grep -n '=== 导入已验收的本地镜像' "$RELEASE_SCRIPT" | cut -d: -f1)
stop_line=$(grep -n 'stop gateway backend frontend kafka zookeeper redis elasticsearch' "$RELEASE_SCRIPT" | cut -d: -f1)
reindex_line=$(grep -n -- '--confirm-promote' "$RELEASE_SCRIPT" | tail -n 1 | cut -d: -f1)
backend_line=$(grep -n 'backend frontend' "$RELEASE_SCRIPT" | tail -n 1 | cut -d: -f1)
gateway_line=$(grep -n -- '--no-deps gateway' "$RELEASE_SCRIPT" | tail -n 1 | cut -d: -f1)
[[ $validate_line -lt $import_line && $import_line -lt $stop_line ]] ||
  fail '必须先只读验收、再导入，最后才进入维护窗口'
[[ $stop_line -lt $reindex_line && $reindex_line -lt $backend_line && $backend_line -lt $gateway_line ]] ||
  fail '搜索重建、Backend/Frontend、Gateway 的恢复顺序错误'

# 行为回归：即使调用者 shell 注入同名变量，Compose 也只能看到固定白名单环境，
# 且参数必须显式固定项目名和 env/compose 文件。
mkdir -p "$TEMP_ROOT/bin"
cat >"$TEMP_ROOT/bin/docker" <<'MOCK_DOCKER'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'VIBELO=%s\n' "${VIBELO_BACKEND_IMAGE-UNSET}"
printf 'COMPOSE_PROJECT=%s\n' "${COMPOSE_PROJECT_NAME-UNSET}"
printf 'COMPOSE_PROFILES=%s\n' "${COMPOSE_PROFILES-UNSET}"
printf 'SPRING=%s\n' "${SPRING_DATASOURCE_URL-UNSET}"
printf 'DOCKER_HOST=%s\n' "${DOCKER_HOST-UNSET}"
printf 'DOCKER_CONTEXT=%s\n' "${DOCKER_CONTEXT-UNSET}"
printf 'DOCKER_CONFIG=%s\n' "${DOCKER_CONFIG-UNSET}"
printf 'ARGS='
printf '<%s>' "$@"
printf '\n'
MOCK_DOCKER
chmod +x "$TEMP_ROOT/bin/docker"

compose_probe=$(
  PATH="$TEMP_ROOT/bin:$PATH" \
  VIBELO_BACKEND_IMAGE='attacker/backend:latest' \
  COMPOSE_PROJECT_NAME='attacker-project' \
  COMPOSE_PROFILES='recommendation' \
  SPRING_DATASOURCE_URL='jdbc:attacker' \
  DOCKER_HOST='tcp://attacker.invalid:2376' \
  DOCKER_CONTEXT='attacker-context' \
  DOCKER_CONFIG='/attacker/docker-config' \
    vibelo_public_compose /private/.env.public /repo/compose.yml config --quiet
)
[[ $compose_probe == *'VIBELO=UNSET'* &&
  $compose_probe == *'COMPOSE_PROJECT=UNSET'* &&
  $compose_probe == *'COMPOSE_PROFILES=UNSET'* &&
  $compose_probe == *'SPRING=UNSET'* &&
  $compose_probe == *'DOCKER_HOST=unix:///var/run/docker.sock'* &&
  $compose_probe == *'DOCKER_CONTEXT=UNSET'* &&
  $compose_probe == *'DOCKER_CONFIG=UNSET'* ]] ||
  fail '干净 Compose 环境仍继承调用者业务/Compose 变量'
[[ $compose_probe == *'ARGS=<compose><-p><vibelo-public><--env-file></private/.env.public><-f></repo/compose.yml><config><--quiet>'* ]] ||
  fail 'Compose 调用没有固定项目名或显式配置文件'
(
  export DOCKER_HOST='tcp://attacker.invalid:2376'
  export DOCKER_CONTEXT='attacker-context'
  export DOCKER_CONFIG='/attacker/docker-config'
  vibelo_lock_docker_to_local_engine
  [[ $DOCKER_HOST == 'unix:///var/run/docker.sock' &&
    ! -v DOCKER_CONTEXT && ! -v DOCKER_CONFIG ]] ||
    fail '直接 Docker 调用没有锁定 ECS 本机 Engine'
)

# 行为回归：固定 tag 不能代替内容身份。即使服务/tag 相同，只要 bundle 的
# image ID 与运行容器实际 Image ID 不同就必须拒绝。
MATCHING_IMAGE_ID="sha256:$(printf 'a%.0s' {1..64})"
DIFFERENT_IMAGE_ID="sha256:$(printf 'b%.0s' {1..64})"
cat >"$TEMP_ROOT/bin/docker" <<'MOCK_RUNTIME_DOCKER'
#!/usr/bin/env bash
set -Eeuo pipefail
case "$1" in
  ps)
    printf '%s\n' 'runtime-minio-container-id'
    ;;
  container)
    if [[ $2 == inspect && $3 == --format && $4 == '{{.Id}}' ]]; then
      printf '%s\n' 'runtime-minio-container-id'
    elif [[ $2 == inspect && $3 == --format && $4 == '{{.Image}}' ]]; then
      printf '%s\n' "$MOCK_RUNTIME_IMAGE_ID"
    else
      exit 64
    fi
    ;;
  *)
    exit 64
    ;;
esac
MOCK_RUNTIME_DOCKER
chmod +x "$TEMP_ROOT/bin/docker"
export MOCK_RUNTIME_IMAGE_ID=$MATCHING_IMAGE_ID
PATH="$TEMP_ROOT/bin:$PATH" \
  vibelo_running_compose_service_uses_image_id \
    vibelo-public minio vibelo-public-minio-1 "$MATCHING_IMAGE_ID" ||
  fail '相同 bundle/runtime MinIO image ID 应通过'
if PATH="$TEMP_ROOT/bin:$PATH" \
  vibelo_running_compose_service_uses_image_id \
    vibelo-public minio vibelo-public-minio-1 "$DIFFERENT_IMAGE_ID"; then
  fail '相同固定 tag 下不同 MinIO image ID 未被拒绝'
fi
[[ $VIBELO_RUNTIME_IMAGE_ID == "$MATCHING_IMAGE_ID" ]] ||
  fail 'MinIO runtime image ID 读取错误'
unset MOCK_RUNTIME_IMAGE_ID MATCHING_IMAGE_ID DIFFERENT_IMAGE_ID

# 行为回归：临时 Git 仓库验证 stale HEAD 门禁和 migration 差异门禁。
GIT_FIXTURE="$TEMP_ROOT/git-fixture"
mkdir -p "$GIT_FIXTURE"
git -C "$GIT_FIXTURE" init -q
git -C "$GIT_FIXTURE" config user.name 'Vibelo Test'
git -C "$GIT_FIXTURE" config user.email 'vibelo-test@example.invalid'
printf '%s\n' 'restore.txt' >"$GIT_FIXTURE/.gitignore"
printf '%s\n' 'base' >"$GIT_FIXTURE/base.txt"
git -C "$GIT_FIXTURE" add .gitignore base.txt
git -C "$GIT_FIXTURE" commit -q -m base
BASE_COMMIT=$(git -C "$GIT_FIXTURE" rev-parse HEAD)

git -C "$GIT_FIXTURE" switch -q -c target
printf '%s\n' 'tracked-at-target' >"$GIT_FIXTURE/collision.txt"
git -C "$GIT_FIXTURE" add -A
git -C "$GIT_FIXTURE" commit -q -m target
TARGET_COMMIT=$(git -C "$GIT_FIXTURE" rev-parse HEAD)
git -C "$GIT_FIXTURE" update-ref refs/remotes/origin/main "$TARGET_COMMIT"
git -C "$GIT_FIXTURE" switch -q --detach "$BASE_COMMIT"
printf '%s\n' 'personal-unrelated' >"$GIT_FIXTURE/unrelated.txt"

(
  cd "$GIT_FIXTURE"
  if vibelo_git_release_head_is_trusted deploy "$TARGET_COMMIT" "$TARGET_COMMIT"; then
    fail 'stale HEAD 仍可运行 deploy'
  fi
  if vibelo_git_release_head_is_trusted rollback "$BASE_COMMIT" "$TARGET_COMMIT"; then
    fail 'stale HEAD 仍可运行 rollback'
  fi
  [[ $(<unrelated.txt) == personal-unrelated ]] || fail 'HEAD 门禁修改了个人未跟踪文件'
  git switch -q --detach "$TARGET_COMMIT"
  vibelo_git_release_head_is_trusted deploy "$TARGET_COMMIT" "$TARGET_COMMIT" ||
    fail 'HEAD/target/origin 一致时应允许 deploy'
  vibelo_git_release_head_is_trusted rollback "$BASE_COMMIT" "$TARGET_COMMIT" ||
    fail '最新发布器应允许验收旧 rollback 目标'
)

git -C "$GIT_FIXTURE" switch -q --detach "$TARGET_COMMIT"
mkdir -p "$GIT_FIXTURE/backend/src/main/resources/db/migration"
printf '%s\n' '-- fixture' >"$GIT_FIXTURE/backend/src/main/resources/db/migration/V999__fixture.sql"
git -C "$GIT_FIXTURE" add backend/src/main/resources/db/migration/V999__fixture.sql
git -C "$GIT_FIXTURE" commit -q -m migration
MIGRATION_COMMIT=$(git -C "$GIT_FIXTURE" rev-parse HEAD)
printf '%s\n' '-- fixture modified' >"$GIT_FIXTURE/backend/src/main/resources/db/migration/V999__fixture.sql"
git -C "$GIT_FIXTURE" add backend/src/main/resources/db/migration/V999__fixture.sql
git -C "$GIT_FIXTURE" commit -q -m migration-modified
MIGRATION_MODIFIED_COMMIT=$(git -C "$GIT_FIXTURE" rev-parse HEAD)
git -C "$GIT_FIXTURE" mv \
  backend/src/main/resources/db/migration/V999__fixture.sql \
  backend/src/main/resources/db/migration/V999__renamed.sql
git -C "$GIT_FIXTURE" commit -q -m migration-renamed
MIGRATION_RENAMED_COMMIT=$(git -C "$GIT_FIXTURE" rev-parse HEAD)
git -C "$GIT_FIXTURE" rm -q backend/src/main/resources/db/migration/V999__renamed.sql
git -C "$GIT_FIXTURE" commit -q -m migration-deleted
MIGRATION_DELETED_COMMIT=$(git -C "$GIT_FIXTURE" rev-parse HEAD)
(
  cd "$GIT_FIXTURE"
  vibelo_git_path_has_changes "$TARGET_COMMIT" "$MIGRATION_COMMIT" \
    backend/src/main/resources/db/migration ||
    fail '未检测到 release 间 Flyway migration 改动'
  if vibelo_git_path_has_changes "$TARGET_COMMIT" "$TARGET_COMMIT" \
    backend/src/main/resources/db/migration; then
    fail '相同 release 被误判为存在 Flyway migration 改动'
  else
    [[ $? == 1 ]] || fail 'Flyway migration 查询失败未 fail-closed'
  fi
  if vibelo_git_path_has_changes "$BASE_COMMIT" "$TARGET_COMMIT" \
    backend/src/main/resources/db/migration; then
    fail '非 migration 代码变化被误判为 Flyway 改动'
  else
    [[ $? == 1 ]] || fail '非 migration 差异查询失败'
  fi
  for commit_pair in \
    "$MIGRATION_COMMIT:$MIGRATION_MODIFIED_COMMIT" \
    "$MIGRATION_MODIFIED_COMMIT:$MIGRATION_RENAMED_COMMIT" \
    "$MIGRATION_RENAMED_COMMIT:$MIGRATION_DELETED_COMMIT"; do
    IFS=: read -r from_commit to_commit <<<"$commit_pair"
    vibelo_git_path_has_changes "$from_commit" "$to_commit" \
      backend/src/main/resources/db/migration ||
      fail '未检测到 Flyway migration 的修改、重命名或删除'
  done
  if vibelo_git_path_has_changes deadbeef "$TARGET_COMMIT" \
    backend/src/main/resources/db/migration; then
    fail '无效 Git commit 被误判为正常 migration 差异'
  else
    [[ $? == 2 ]] || fail '无效 Git commit 没有 fail-closed'
  fi
)

# 行为回归：所有动作都必须证明 current→target 的真实运行契约一致；no-switch rollback
# 还必须证明旧目标与最新 origin/main 一致。普通业务或控制面 helper 变化不应误伤，
# Compose、Nginx、reindex、固定 requirements 任一变化都必须被路径门禁捕获。
CONTRACT_FIXTURE="$TEMP_ROOT/contract-fixture"
mkdir -p \
  "$CONTRACT_FIXTURE/infra/nginx" \
  "$CONTRACT_FIXTURE/tools" \
  "$CONTRACT_FIXTURE/ops/public"
git -C "$CONTRACT_FIXTURE" init -q
git -C "$CONTRACT_FIXTURE" config user.name 'Vibelo Test'
git -C "$CONTRACT_FIXTURE" config user.email 'vibelo-test@example.invalid'
for contract_path in \
  infra/docker-compose.public.yml \
  infra/nginx/gateway.conf \
  tools/reindex_search_es.py \
  tools/requirements_search_reindex.txt \
  ops/public/public-release.sh; do
  printf '%s\n' 'contract-v1' >"$CONTRACT_FIXTURE/$contract_path"
done
printf '%s\n' 'business-v1' >"$CONTRACT_FIXTURE/business.txt"
git -C "$CONTRACT_FIXTURE" add .
git -C "$CONTRACT_FIXTURE" commit -q -m contract-base
CONTRACT_BASE=$(git -C "$CONTRACT_FIXTURE" rev-parse HEAD)

printf '%s\n' 'business-v2' >"$CONTRACT_FIXTURE/business.txt"
git -C "$CONTRACT_FIXTURE" add business.txt
git -C "$CONTRACT_FIXTURE" commit -q -m unrelated
CONTRACT_UNRELATED=$(git -C "$CONTRACT_FIXTURE" rev-parse HEAD)

CONTRACT_PATHS=(
  infra/docker-compose.public.yml
  infra/nginx
  tools/reindex_search_es.py
  tools/requirements_search_reindex.txt
)
(
  cd "$CONTRACT_FIXTURE"
  if vibelo_git_path_has_changes \
    "$CONTRACT_BASE" "$CONTRACT_UNRELATED" "${CONTRACT_PATHS[@]}"; then
    fail '普通业务代码变化被误判为发布运行契约变化'
  else
    [[ $? == 1 ]] || fail '发布运行契约查询失败'
  fi
)

printf '%s\n' 'trusted-control-plane-v2' >"$CONTRACT_FIXTURE/ops/public/public-release.sh"
git -C "$CONTRACT_FIXTURE" add ops/public/public-release.sh
git -C "$CONTRACT_FIXTURE" commit -q -m control-plane-helper
CONTRACT_CONTROL_PLANE=$(git -C "$CONTRACT_FIXTURE" rev-parse HEAD)
(
  cd "$CONTRACT_FIXTURE"
  if vibelo_git_path_has_changes \
    "$CONTRACT_UNRELATED" "$CONTRACT_CONTROL_PLANE" "${CONTRACT_PATHS[@]}"; then
    fail '受信任 origin/main 控制面 helper 变化被误判为旧应用运行契约变化'
  else
    [[ $? == 1 ]] || fail '控制面 helper 差异查询失败'
  fi
)

previous_contract_commit=$CONTRACT_CONTROL_PLANE
for changed_contract_path in \
  infra/docker-compose.public.yml \
  infra/nginx/gateway.routes.conf \
  tools/reindex_search_es.py \
  tools/requirements_search_reindex.txt; do
  printf '%s\n' "changed-$changed_contract_path" >"$CONTRACT_FIXTURE/$changed_contract_path"
  git -C "$CONTRACT_FIXTURE" add "$changed_contract_path"
  git -C "$CONTRACT_FIXTURE" commit -q -m "contract-$changed_contract_path"
  next_contract_commit=$(git -C "$CONTRACT_FIXTURE" rev-parse HEAD)
  (
    cd "$CONTRACT_FIXTURE"
    vibelo_git_path_has_changes \
      "$previous_contract_commit" "$next_contract_commit" "${CONTRACT_PATHS[@]}" ||
      fail "未检测到发布运行契约变化：$changed_contract_path"
  )
  previous_contract_commit=$next_contract_commit
done
unset contract_path changed_contract_path previous_contract_commit next_contract_commit
unset CONTRACT_CONTROL_PLANE runtime_contract_block expected_runtime_contract_block

printf '%s\n' '公网简化发布入口行为回归测试通过。'
