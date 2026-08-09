#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT=${VIBELO_REPO_ROOT:-/opt/vibelo}
PUBLIC_ENV=$REPO_ROOT/.env.public
CONFIG_DIR=/etc/vibelo
JOB_ENV=$CONFIG_DIR/content-job.env
SERVICE_USER=vibelo-jobs
SERVICE_GROUP=vibelo-jobs
JOB_ROOT=/data/vibelo-ingest
TIMER_UNIT=vibelo-content-ingest.timer
SERVICE_UNIT=vibelo-content-ingest.service
TEMP_ENV=''
TIMER_WAS_ACTIVE=false
TIMER_ENABLE_STATE=not-found
TIMER_QUIESCED=false
ENV_PUBLISH_STARTED=false
INSTALL_COMPLETE=false
SECRET_KEYS=(
  VIBELO_DB_HOST
  VIBELO_DB_PORT
  VIBELO_DB_NAME
  VIBELO_DB_USER
  VIBELO_DB_PASSWORD
  MINIO_ACCESS_KEY
  MINIO_SECRET_KEY
  MINIO_BUCKET
)
TUNING_KEYS=(
  VIBELO_CONTENT_IMPORT_ENABLED
  VIBELO_CONTENT_SEARCH_REINDEX_ENABLED
  VIBELO_CONTENT_MIN_FREE_BYTES
  VIBELO_CONTENT_MIN_AVAILABLE_MEMORY_KB
  VIBELO_IMPORT_USERNAME
  VIBELO_IMPORT_LIMIT
  VIBELO_IMPORT_RESUME
  VIBELO_IMPORT_MAX_FILE_BYTES
  VIBELO_IMPORT_MAX_IMAGE_PIXELS
  VIBELO_IMPORT_MAX_IMAGE_DIMENSION
)

die() {
  printf '内容任务安装失败：%s\n' "$*" >&2
  exit 1
}

cleanup() {
  local rc=$?
  trap - EXIT
  [[ -z $TEMP_ENV ]] || rm -f -- "$TEMP_ENV"
  if [[ $INSTALL_COMPLETE != true && $TIMER_QUIESCED == true ]]; then
    if [[ $ENV_PUBLISH_STARTED == true ]]; then
      # Once the candidate environment starts replacing the active file, do
      # not revive a possibly mixed new-env/old-unit deployment.  Leave the
      # timer stopped for explicit operator recovery.
      if ! systemctl disable --now "$TIMER_UNIT" >/dev/null 2>&1; then
        printf '警告：无法确认 %s 已禁用，请立即人工检查。\n' "$TIMER_UNIT" >&2
        rc=1
      fi
      printf '警告：任务环境发布开始后安装失败；%s 保持停止，请修复后重跑安装器。\n' \
        "$TIMER_UNIT" >&2
    elif [[ $TIMER_WAS_ACTIVE == true ]]; then
      if ! restore_timer_before_publish; then
        printf '警告：安装失败后无法恢复 %s，请人工检查。\n' "$TIMER_UNIT" >&2
        rc=1
      fi
    elif ! restore_timer_before_publish; then
      printf '警告：安装失败后无法恢复 %s 的启用状态，请人工检查。\n' "$TIMER_UNIT" >&2
      rc=1
    fi
  fi
  exit "$rc"
}
trap cleanup EXIT

unit_active_state() {
  systemctl show --property=ActiveState --value "$1" 2>/dev/null || true
}

restore_timer_before_publish() {
  case "$TIMER_ENABLE_STATE" in
    enabled)
      systemctl enable "$TIMER_UNIT" >/dev/null 2>&1 || return 1
      ;;
    enabled-runtime)
      systemctl enable --runtime "$TIMER_UNIT" >/dev/null 2>&1 || return 1
      ;;
    disabled|not-found|'')
      ;;
    *)
      return 1
      ;;
  esac
  if [[ $TIMER_WAS_ACTIVE == true ]]; then
    systemctl start "$TIMER_UNIT" >/dev/null 2>&1 || return 1
  fi
}

quiesce_content_timer() {
  local timer_state service_state disabled_state
  timer_state=$(unit_active_state "$TIMER_UNIT")
  case "$timer_state" in
    active|activating|reloading) TIMER_WAS_ACTIVE=true ;;
  esac

  TIMER_ENABLE_STATE=$(systemctl is-enabled "$TIMER_UNIT" 2>/dev/null || true)
  case "$TIMER_ENABLE_STATE" in
    enabled|enabled-runtime|disabled|not-found|'') ;;
    *) die "$TIMER_UNIT 的启用状态不受支持：$TIMER_ENABLE_STATE" ;;
  esac

  if [[ $TIMER_ENABLE_STATE == not-found || -z $TIMER_ENABLE_STATE ]]; then
    systemctl stop "$TIMER_UNIT" >/dev/null 2>&1 || true
  else
    systemctl disable --now "$TIMER_UNIT" || die "无法禁用并停止 $TIMER_UNIT"
  fi
  TIMER_QUIESCED=true

  timer_state=$(unit_active_state "$TIMER_UNIT")
  case "$timer_state" in
    active|activating|reloading)
      die "$TIMER_UNIT 未能停止，拒绝修改任务配置"
      ;;
  esac
  disabled_state=$(systemctl is-enabled "$TIMER_UNIT" 2>/dev/null || true)
  case "$disabled_state" in
    enabled|enabled-runtime)
      die "$TIMER_UNIT 未能禁用，拒绝修改任务配置"
      ;;
  esac

  service_state=$(unit_active_state "$SERVICE_UNIT")
  case "$service_state" in
    active|activating|reloading|deactivating)
      die "$SERVICE_UNIT 当前仍在运行；未修改配置，并将恢复 timer 原状态"
      ;;
  esac
}

ensure_service_identity() {
  local group primary_group
  getent group "$SERVICE_GROUP" >/dev/null || groupadd --system "$SERVICE_GROUP"
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --gid "$SERVICE_GROUP" --home-dir /nonexistent \
      --shell /usr/sbin/nologin --no-create-home "$SERVICE_USER"
  fi
  [[ $(id -u "$SERVICE_USER") -ne 0 ]] || die "$SERVICE_USER 不能是 root"
  primary_group=$(id -gn "$SERVICE_USER")
  [[ $primary_group == "$SERVICE_GROUP" ]] ||
    die "$SERVICE_USER 主组必须是 $SERVICE_GROUP，当前为 $primary_group"
  for group in $(id -nG "$SERVICE_USER"); do
    case "$group" in
      root|docker|sudo|wheel|adm|lxd|systemd-journal)
        die "$SERVICE_USER 不能属于敏感附加组：$group"
        ;;
    esac
  done
}

required_env_line() {
  local key=$1 line raw
  local -a matches=()
  while IFS= read -r line; do
    matches+=("${line%$'\r'}")
  done < <(grep -E "^${key}=" -- "$PUBLIC_ENV" || true)
  ((${#matches[@]} == 1)) || die ".env.public 必须且只能配置一次 $key"
  line=${matches[0]}
  raw=${line#*=}
  [[ -n $raw && $raw != "''" && $raw != '""' ]] || die "$key 为空"
  [[ ! $raw =~ ^\$\{[A-Za-z_][A-Za-z0-9_]*\}$ ]] || die "$key 仍是未展开占位符"
  printf '%s\n' "$line"
}

is_secret_key() {
  local wanted=$1 key
  for key in "${SECRET_KEYS[@]}"; do
    [[ $key == "$wanted" ]] && return 0
  done
  return 1
}

is_tuning_key() {
  local wanted=$1 key
  for key in "${TUNING_KEYS[@]}"; do
    [[ $key == "$wanted" ]] && return 0
  done
  return 1
}

prepare_minimal_environment() {
  local key line raw template
  local -a matches=()
  declare -A public_lines=()
  declare -A existing_lines=()

  template=$REPO_ROOT/ops/jobs/content-job.env.example
  [[ -f $template ]] || die "缺少任务环境模板：$template"
  grep -qx 'VIBELO_CONTENT_COLLECT_ENABLED=false' "$template" ||
    die '公网任务模板必须固定关闭 VIBELO_CONTENT_COLLECT_ENABLED'

  # Validate every required secret before touching the active environment.
  for key in "${SECRET_KEYS[@]}"; do
    public_lines[$key]=$(required_env_line "$key")
  done

  # Preserve only known, non-secret tuning keys from an existing file. Unknown
  # assignments are deliberately discarded so SMS, token and unrelated keys
  # can never leak into the systemd service environment.
  if [[ -f $JOB_ENV && ! -L $JOB_ENV ]]; then
    while IFS= read -r line || [[ -n $line ]]; do
      line=${line%$'\r'}
      [[ $line =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]] || continue
      key=${BASH_REMATCH[1]}
      is_secret_key "$key" && continue
      # Preserve only explicitly safe booleans/numeric resource tuning and the
      # business author name. Paths and endpoints always come from the audited
      # template so they cannot drift outside systemd ReadWritePaths.
      is_tuning_key "$key" || continue
      mapfile -t matches < <(grep -E "^${key}=" -- "$template" || true)
      ((${#matches[@]} == 1)) || continue
      [[ -z ${existing_lines[$key]+x} ]] || die "$JOB_ENV 重复配置 $key"
      raw=${line#*=}
      [[ -n $raw ]] || die "$JOB_ENV 中的 $key 为空"
      existing_lines[$key]=$line
    done <"$JOB_ENV"
  elif [[ -e $JOB_ENV ]]; then
    die "$JOB_ENV 必须是普通文件"
  fi

  TEMP_ENV=$(mktemp "$CONFIG_DIR/.content-job.env.XXXXXXXX")
  chmod 0600 "$TEMP_ENV"
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%$'\r'}
    if [[ $line =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]]; then
      key=${BASH_REMATCH[1]}
      if [[ -n ${public_lines[$key]+x} ]]; then
        printf '%s\n' "${public_lines[$key]}"
        continue
      fi
      if [[ -n ${existing_lines[$key]+x} ]]; then
        printf '%s\n' "${existing_lines[$key]}"
        continue
      fi
    fi
    printf '%s\n' "$line"
  done <"$template" >"$TEMP_ENV"

  for key in "${SECRET_KEYS[@]}"; do
    unset 'public_lines[$key]'
  done
}

publish_minimal_environment() {
  [[ -n $TEMP_ENV && -f $TEMP_ENV && ! -L $TEMP_ENV ]] ||
    die '最小任务环境候选文件缺失或不是普通文件'
  chown root:"$SERVICE_GROUP" "$TEMP_ENV"
  chmod 0640 "$TEMP_ENV"
  # Set the barrier before mv.  Even an uncertain/failed rename must not cause
  # cleanup to restart the previous timer automatically.
  ENV_PUBLISH_STARTED=true
  mv -f -- "$TEMP_ENV" "$JOB_ENV"
  TEMP_ENV=''
}

reject_task_tree_symlinks() {
  local link=''
  if [[ -L $JOB_ROOT ]]; then
    die "$JOB_ROOT 不能是符号链接"
  fi
  if [[ -e $JOB_ROOT && ! -d $JOB_ROOT ]]; then
    die "$JOB_ROOT 必须是目录"
  fi
  if [[ -d $JOB_ROOT ]]; then
    link=$(find -P "$JOB_ROOT" -xdev -type l -print -quit)
    [[ -z $link ]] || die "任务树禁止符号链接：$link"
  fi
}

migrate_task_tree_ownership() {
  reject_task_tree_symlinks
  find -P "$JOB_ROOT" -xdev \
    -exec chown --no-dereference "$SERVICE_USER:$SERVICE_GROUP" -- {} +
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || {
  printf '请使用 sudo/root 安装 systemd timer。\n' >&2
  exit 1
}
[[ -f $REPO_ROOT/ops/jobs/systemd/vibelo-content-ingest.service ]] || {
  printf '找不到定时任务模板：%s\n' "$REPO_ROOT" >&2
  exit 1
}
[[ -f $PUBLIC_ENV ]] || {
  printf '缺少 %s/.env.public\n' "$REPO_ROOT" >&2
  exit 1
}
mountpoint -q /data || {
  printf '/data 不是独立挂载点，拒绝安装。\n' >&2
  exit 1
}

for command in chmod chown find getent grep groupadd id install mapfile mktemp mountpoint mv rm systemctl useradd; do
  command -v "$command" >/dev/null 2>&1 || die "缺少命令：$command"
done

quiesce_content_timer
reject_task_tree_symlinks
ensure_service_identity
[[ ! -L $CONFIG_DIR ]] || die "$CONFIG_DIR 不能是符号链接"
install -d -m 0755 "$CONFIG_DIR"
prepare_minimal_environment
reject_task_tree_symlinks
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 \
  "$JOB_ROOT" \
  "$JOB_ROOT/dataset" \
  "$JOB_ROOT/dataset/images" \
  "$JOB_ROOT/dataset/processed" \
  "$JOB_ROOT/history" \
  "$JOB_ROOT/state"
# Earlier versions ran as root with umask 077. Migrate the bounded task tree so
# the dedicated service account can resume old manifests, history and images.
migrate_task_tree_ownership
reject_task_tree_symlinks

install -m 0644 "$REPO_ROOT/ops/jobs/systemd/vibelo-content-ingest.service" /etc/systemd/system/
install -m 0644 "$REPO_ROOT/ops/jobs/systemd/vibelo-content-ingest.timer" /etc/systemd/system/
reject_task_tree_symlinks
publish_minimal_environment
systemctl daemon-reload
systemctl enable --now "$TIMER_UNIT"
INSTALL_COMPLETE=true

printf '定时器已启用；最小任务环境已从 .env.public 同步，不含短信和 Token 密钥。\n'
printf '安装过程没有立即执行采集、导入或向量计算。\n'
systemctl list-timers "$TIMER_UNIT" --no-pager || true
