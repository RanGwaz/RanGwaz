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

EXPECTED_RDS_HOST='rm-bp111eaxy9eeuvqcb.mysql.rds.aliyuncs.com'
EXPECTED_RDS_PORT='3306'
EXPECTED_DATABASE='rangwaz_image_dev'
EXPECTED_APP_USER='vibelo_app'
CHECK_RDS_HOST=$EXPECTED_RDS_HOST
CHECK_RDS_PORT=$EXPECTED_RDS_PORT
CHECK_DATABASE=$EXPECTED_DATABASE
CHECK_APP_USER=$EXPECTED_APP_USER
RDS_TARGET_READY=0
EXPECTED_DOCKER_ROOT='/data/docker'
EXPECTED_CONTAINERD_ROOT='/data/containerd'
MIN_SWAP_BYTES=4000000000
MIN_VM_MAX_MAP_COUNT=1048576

PASSES=0
WARNINGS=0
FAILURES=0
ENV_AVAILABLE=0
ENV_FOUND=0
ENV_RAW=''
ENV_PLAIN=''
ALLOW_RUNNING_GATEWAY_PORTS=false

usage() {
  cat <<'EOF'
用法：
  sudo bash ops/public/preflight.sh [--allow-running-gateway-ports]

这是只读上线预检：不创建目录、不修改配置、不启动容器、不拉取或构建镜像。
脚本会列出全部通过、警告和失败项，并在存在失败项时返回非零状态。
--allow-running-gateway-ports 仅供受控更新流程使用：80/443 只有在确由当前
vibelo-public Gateway 容器发布时才允许占用；其他监听者仍会导致失败。
EOF
}

while (($# > 0)); do
  case "$1" in
    --allow-running-gateway-ports)
      ALLOW_RUNNING_GATEWAY_PORTS=true
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf '错误：未知参数：%s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

pass() {
  PASSES=$((PASSES + 1))
  printf '[通过] %s\n' "$*"
}

warn() {
  WARNINGS=$((WARNINGS + 1))
  printf '[警告] %s\n' "$*"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf '[失败] %s\n' "$*"
}

have_command() {
  command -v "$1" >/dev/null 2>&1
}

plain_from_raw() {
  local raw=$1

  ENV_PLAIN=$raw
  ENV_PLAIN=${ENV_PLAIN%$'\r'}
  if ((${#ENV_PLAIN} >= 2)); then
    if [[ ${ENV_PLAIN:0:1} == "'" && ${ENV_PLAIN: -1} == "'" ]]; then
      ENV_PLAIN=${ENV_PLAIN:1:${#ENV_PLAIN}-2}
      ENV_PLAIN=${ENV_PLAIN//\\\'/\'}
    elif [[ ${ENV_PLAIN:0:1} == '"' && ${ENV_PLAIN: -1} == '"' ]]; then
      ENV_PLAIN=${ENV_PLAIN:1:${#ENV_PLAIN}-2}
    fi
  fi
}

is_placeholder() {
  vibelo_is_placeholder "$1"
}

get_env_plain() {
  local key=$1
  local line

  ENV_FOUND=0
  ENV_RAW=''
  ENV_PLAIN=''
  ((ENV_AVAILABLE == 1)) || return 1

  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line == "$key="* ]]; then
      ENV_FOUND=1
      ENV_RAW=${line#*=}
      plain_from_raw "$ENV_RAW"
      return 0
    fi
  done <"$ENV_FILE"
  return 1
}

check_required_env() {
  local key=$1
  local label=$2
  local minimum_length=${3:-1}

  if ! get_env_plain "$key"; then
    fail "$label 缺少变量 $key"
  elif is_placeholder "$ENV_PLAIN"; then
    fail "$label 仍为空或占位符（$key）"
  elif ((${#ENV_PLAIN} < minimum_length)); then
    fail "$label 长度不足（$key）"
  else
    pass "$label 已配置（不显示值）"
  fi
}

check_expected_env() {
  local key=$1
  local expected=$2
  local label=$3

  if ! get_env_plain "$key"; then
    fail "$label 缺少变量 $key"
  elif [[ $ENV_PLAIN != "$expected" ]]; then
    fail "$label 不是预期值（$key）"
  else
    pass "$label 正确"
  fi
}

printf '%s\n' '=== Vibelo 公网上线只读预检 ==='

if have_command findmnt; then
  if data_target=$(findmnt -rn -o TARGET --target /data 2>/dev/null); then
    if [[ $data_target == /data ]]; then
      pass '/data 是独立挂载点'
      if data_options=$(findmnt -rn -o OPTIONS --target /data 2>/dev/null); then
        if [[ ",$data_options," == *,ro,* ]]; then
          fail '/data 当前是只读挂载'
        else
          pass '/data 不是只读挂载'
        fi
      else
        fail '无法读取 /data 挂载参数'
      fi
    else
      fail "/data 不是独立挂载点（当前落在 $data_target）"
    fi
  else
    fail '找不到 /data 挂载点'
  fi
else
  fail '缺少 findmnt，无法验证 /data'
fi

if have_command docker; then
  if docker_root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null); then
    if [[ $docker_root == "$EXPECTED_DOCKER_ROOT" ]]; then
      pass "DockerRoot 已迁移到 $EXPECTED_DOCKER_ROOT"
    else
      fail "DockerRoot 应为 $EXPECTED_DOCKER_ROOT，当前为 ${docker_root:-未知}"
    fi
  else
    fail 'Docker Engine 不可用，无法读取 DockerRoot'
  fi
else
  fail '缺少 docker 命令'
fi

if have_command containerd; then
  if containerd_dump=$(containerd config dump 2>/dev/null); then
    containerd_root=$(
      awk -F= '
        /^[[:space:]]*root[[:space:]]*=/ {
          value=$2
          gsub(/^[[:space:]"]+|[[:space:]"]+$/, "", value)
          print value
          exit
        }
      ' <<<"$containerd_dump"
    )
    containerd_root=$(vibelo_normalize_toml_string "$containerd_root")
    if [[ $containerd_root == "$EXPECTED_CONTAINERD_ROOT" ]]; then
      pass "containerd root 已迁移到 $EXPECTED_CONTAINERD_ROOT"
    else
      fail "containerd root 应为 $EXPECTED_CONTAINERD_ROOT，当前为 ${containerd_root:-未知}"
    fi
  else
    fail '无法读取生效中的 containerd 配置'
  fi
else
  fail '缺少 containerd 命令'
fi

if have_command swapon; then
  if swap_bytes=$(vibelo_total_swap_bytes); then
    if [[ $swap_bytes =~ ^[0-9]+$ ]] &&
      ((swap_bytes >= MIN_SWAP_BYTES)); then
      pass 'Swap 已启用且总量不少于 4 GB'
    elif [[ $swap_bytes =~ ^[0-9]+$ ]] && ((swap_bytes > 0)); then
      fail "Swap 已启用但不足 4 GB（当前约 $((swap_bytes / 1000000)) MB）"
    else
      fail 'Swap 未启用'
    fi
  else
    fail '无法读取 Swap 状态'
  fi
else
  fail '缺少 swapon，无法验证 Swap'
fi

if [[ -r /proc/sys/vm/max_map_count ]]; then
  vm_max_map_count=$(<"/proc/sys/vm/max_map_count")
  if [[ $vm_max_map_count =~ ^[0-9]+$ ]] &&
    ((vm_max_map_count >= MIN_VM_MAX_MAP_COUNT)); then
    pass "vm.max_map_count=$vm_max_map_count"
  else
    fail "vm.max_map_count 至少应为 $MIN_VM_MAX_MAP_COUNT，当前为 ${vm_max_map_count:-未知}"
  fi
else
  fail '无法读取 vm.max_map_count'
fi

if have_command ss; then
  if socket_list=$(ss -H -ltn 2>/dev/null); then
    gateway_container_id=''
    gateway_container_count=0
    if [[ $ALLOW_RUNNING_GATEWAY_PORTS == true ]] && have_command docker; then
      mapfile -t gateway_container_ids < <(
        docker ps \
          --filter 'label=com.docker.compose.project=vibelo-public' \
          --filter 'label=com.docker.compose.service=gateway' \
          --format '{{.ID}}' 2>/dev/null || true
      )
      gateway_container_count=${#gateway_container_ids[@]}
      if ((gateway_container_count == 1)); then
        gateway_container_id=${gateway_container_ids[0]}
      fi
    fi
    for port in 80 443; do
      port_busy=0
      gateway_owns_all_busy_addresses=0
      busy_addresses=()
      while IFS= read -r socket_line || [[ -n $socket_line ]]; do
        [[ -n $socket_line ]] || continue
        read -r _state _recvq _sendq local_address _peer_address _rest \
          <<<"$socket_line"
        if [[ ${local_address:-} == *":$port" ]]; then
          port_busy=1
          busy_addresses+=("$local_address")
        fi
      done <<<"$socket_list"
      if ((port_busy == 1)) &&
        [[ $ALLOW_RUNNING_GATEWAY_PORTS == true &&
          $gateway_container_count -eq 1 ]]; then
        mapfile -t gateway_port_bindings < <(
          docker port "$gateway_container_id" "$port/tcp" 2>/dev/null || true
        )
        if ((${#gateway_port_bindings[@]} > 0)); then
          gateway_owns_all_busy_addresses=1
          for busy_address in "${busy_addresses[@]}"; do
            if ! printf '%s\n' "${gateway_port_bindings[@]}" |
              grep -Fqx -- "$busy_address"; then
              gateway_owns_all_busy_addresses=0
              break
            fi
          done
        fi
      fi
      if ((port_busy == 0)); then
        pass "TCP $port 端口空闲"
      elif ((gateway_owns_all_busy_addresses == 1)); then
        pass "TCP $port 由当前 vibelo-public Gateway 占用（受控更新模式）"
      else
        fail "TCP $port 已被占用：${busy_addresses[*]}"
      fi
      unset gateway_port_bindings busy_address gateway_owns_all_busy_addresses
    done
    unset gateway_container_id gateway_container_count gateway_container_ids
  else
    fail '无法读取 TCP 监听端口'
  fi
else
  fail '缺少 ss，无法验证 80/443 端口'
fi

if [[ -L $ENV_FILE ]]; then
  fail '.env.public 不能是符号链接'
elif [[ ! -f $ENV_FILE ]]; then
  fail "缺少 $ENV_FILE"
else
  ENV_AVAILABLE=1
  env_mode=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || true)
  if [[ $env_mode == 600 ]]; then
    pass '.env.public 权限为 600'
  else
    fail ".env.public 权限必须是 600，当前为 ${env_mode:-未知}"
  fi
fi

if ((ENV_AVAILABLE == 1)); then
  RDS_TARGET_READY=1
  check_required_env VIBELO_DB_HOST '训练任务 RDS 地址'
  if get_env_plain VIBELO_DB_HOST &&
    [[ $ENV_PLAIN =~ ^[A-Za-z0-9.-]+$ ]]; then
    CHECK_RDS_HOST=$ENV_PLAIN
  else
    fail 'VIBELO_DB_HOST 不是合法的 RDS 主机名'
    RDS_TARGET_READY=0
  fi
  check_required_env VIBELO_DB_PORT '训练任务 RDS 端口'
  if get_env_plain VIBELO_DB_PORT &&
    [[ $ENV_PLAIN =~ ^[0-9]+$ ]] &&
    ((10#$ENV_PLAIN >= 1 && 10#$ENV_PLAIN <= 65535)); then
    CHECK_RDS_PORT=$ENV_PLAIN
  else
    fail 'VIBELO_DB_PORT 不是 1 到 65535 的整数'
    RDS_TARGET_READY=0
  fi
  check_required_env VIBELO_DB_NAME '训练任务数据库名'
  if get_env_plain VIBELO_DB_NAME &&
    [[ $ENV_PLAIN =~ ^[A-Za-z0-9_]+$ ]]; then
    CHECK_DATABASE=$ENV_PLAIN
  else
    fail 'VIBELO_DB_NAME 格式无效'
    RDS_TARGET_READY=0
  fi
  check_required_env VIBELO_DB_USER '训练任务应用账号'
  if get_env_plain VIBELO_DB_USER &&
    [[ $ENV_PLAIN =~ ^[A-Za-z0-9_]+$ ]] &&
    [[ ${ENV_PLAIN,,} != dms_user_* ]]; then
    CHECK_APP_USER=$ENV_PLAIN
  else
    fail 'VIBELO_DB_USER 必须是标准 RDS 账号，不能使用 dms_user_*'
    RDS_TARGET_READY=0
  fi

  if ! get_env_plain APP_WEB_ALLOWED_ORIGIN_PATTERNS; then
    fail '浏览器允许来源缺少变量 APP_WEB_ALLOWED_ORIGIN_PATTERNS'
  elif vibelo_is_origin_placeholder "$ENV_PLAIN"; then
    fail '浏览器允许来源仍是示例或占位符'
  elif ! vibelo_is_valid_origin "$ENV_PLAIN"; then
    fail '浏览器允许来源不是有效 origin；不能包含路径、query 或无效端口'
  else
    pass '浏览器允许来源已配置（不显示值）'
    if [[ $ENV_PLAIN == https://* ]]; then
      pass '浏览器允许来源使用 HTTPS'
    else
      warn '浏览器允许来源不是 HTTPS；仅在域名 TLS 尚未接入时临时使用'
    fi
  fi

  RELEASE_BACKEND_SHA=''
  RELEASE_FRONTEND_SHA=''
  if get_env_plain VIBELO_BACKEND_IMAGE &&
    [[ $ENV_PLAIN =~ ^[^[:space:]@]+:([0-9a-f]{40})$ ]]; then
    RELEASE_BACKEND_SHA=${BASH_REMATCH[1]}
  fi
  if get_env_plain VIBELO_FRONTEND_IMAGE &&
    [[ $ENV_PLAIN =~ ^[^[:space:]@]+:([0-9a-f]{40})$ ]]; then
    RELEASE_FRONTEND_SHA=${BASH_REMATCH[1]}
  fi
  if [[ -n $RELEASE_BACKEND_SHA &&
    $RELEASE_BACKEND_SHA == "$RELEASE_FRONTEND_SHA" ]]; then
    pass '前后端镜像使用同一个完整 Git SHA 发布标签'
  else
    warn '前后端镜像尚未配置为同一个完整 Git SHA；导入离线发布包后再设置'
  fi
  unset RELEASE_BACKEND_SHA RELEASE_FRONTEND_SHA

  check_required_env SPRING_DATASOURCE_URL 'Spring RDS JDBC 地址'
  if get_env_plain SPRING_DATASOURCE_URL &&
    ! is_placeholder "$ENV_PLAIN"; then
    if [[ $ENV_PLAIN == *"//$CHECK_RDS_HOST:$CHECK_RDS_PORT/$CHECK_DATABASE?"* ]]; then
      pass 'Spring JDBC 指向目标 RDS 数据库'
    else
      fail 'Spring JDBC 未指向预期的 RDS 内网地址和业务库'
    fi
    if [[ $ENV_PLAIN == *'sslMode=PREFERRED'* ||
      $ENV_PLAIN == *'sslMode=REQUIRED'* ||
      $ENV_PLAIN == *'sslMode=VERIFY_'* ]]; then
      pass 'Spring JDBC 已声明 SSL 模式'
    else
      fail 'Spring JDBC 缺少 sslMode 参数'
    fi
  fi

  check_required_env SPRING_DATASOURCE_USERNAME 'Spring RDS 应用账号'
  if get_env_plain SPRING_DATASOURCE_USERNAME; then
    if [[ $ENV_PLAIN == "$CHECK_APP_USER" &&
      ${ENV_PLAIN,,} != dms_user_* ]]; then
      pass 'Spring 与训练任务使用同一个标准 RDS 应用账号'
    else
      fail 'Spring 与训练任务的 RDS 应用账号不一致，或使用了 dms_user_*'
    fi
  fi
  check_required_env SPRING_DATASOURCE_PASSWORD 'Spring RDS 密码'
  check_required_env APP_AUTH_TOKEN_SECRET '登录 Token 签名密钥' 32
  check_required_env APP_MODERATION_TOKEN '独立人工审核令牌' 32
  check_required_env MINIO_ACCESS_KEY 'MinIO Access Key' 3
  check_required_env MINIO_SECRET_KEY 'MinIO Secret Key' 8
  check_required_env VIBELO_DB_PASSWORD '训练任务 RDS 密码'

  AUTH_TOKEN_SECRET=''
  MODERATION_TOKEN=''
  if get_env_plain APP_AUTH_TOKEN_SECRET && ! is_placeholder "$ENV_PLAIN"; then
    AUTH_TOKEN_SECRET=$ENV_PLAIN
  fi
  if get_env_plain APP_MODERATION_TOKEN && ! is_placeholder "$ENV_PLAIN"; then
    MODERATION_TOKEN=$ENV_PLAIN
  fi
  if [[ -n $AUTH_TOKEN_SECRET && -n $MODERATION_TOKEN ]]; then
    if [[ $AUTH_TOKEN_SECRET != "$MODERATION_TOKEN" ]]; then
      pass '登录签名密钥与人工审核令牌已隔离'
    else
      fail 'APP_MODERATION_TOKEN 不能复用 APP_AUTH_TOKEN_SECRET'
    fi
  fi
  unset AUTH_TOKEN_SECRET MODERATION_TOKEN

  SPRING_PASSWORD=''
  VIBELO_PASSWORD=''
  if get_env_plain SPRING_DATASOURCE_PASSWORD &&
    ! is_placeholder "$ENV_PLAIN"; then
    SPRING_PASSWORD=$ENV_PLAIN
  fi
  if get_env_plain VIBELO_DB_PASSWORD &&
    ! is_placeholder "$ENV_PLAIN"; then
    VIBELO_PASSWORD=$ENV_PLAIN
  fi
  if [[ -n $SPRING_PASSWORD && -n $VIBELO_PASSWORD ]]; then
    if [[ $SPRING_PASSWORD == "$VIBELO_PASSWORD" ]]; then
      pass 'Spring 与训练任务使用同一份 RDS 应用密码'
    else
      fail 'Spring 与训练任务的 RDS 应用密码不一致'
    fi
  fi
  unset SPRING_PASSWORD VIBELO_PASSWORD

  if get_env_plain APP_SMS_MOCK; then
    sms_mock=${ENV_PLAIN,,}
  else
    sms_mock=''
  fi
  case "$sms_mock" in
    false)
      pass '真实短信模式已启用'
      check_required_env ALIYUN_SMS_ACCESS_KEY_ID '阿里云短信 AccessKey ID'
      check_required_env ALIYUN_SMS_ACCESS_KEY_SECRET '阿里云短信 AccessKey Secret'
      check_required_env ALIYUN_SMS_SIGN_NAME '阿里云短信签名'
      check_required_env ALIYUN_SMS_TEMPLATE_CODE '阿里云短信模板代码'
      ;;
    true)
      warn 'APP_SMS_MOCK=true，当前不会发送真实短信'
      ;;
    *)
      fail 'APP_SMS_MOCK 缺失或不是 true/false'
      ;;
  esac
fi

if ((RDS_TARGET_READY == 0)); then
  fail 'RDS 目标配置无效，跳过 DNS 与 TCP 检查'
elif have_command getent; then
  if getent ahosts "$CHECK_RDS_HOST" >/dev/null 2>&1; then
    pass "RDS DNS 可解析：$CHECK_RDS_HOST"
  else
    fail "RDS DNS 无法解析：$CHECK_RDS_HOST"
  fi
else
  fail '缺少 getent，无法验证 RDS DNS'
fi

if ((RDS_TARGET_READY == 0)); then
  :
elif have_command timeout && have_command bash; then
  if timeout 5 bash -c \
    'exec 3<>"/dev/tcp/${1}/${2}"' \
    _ "$CHECK_RDS_HOST" "$CHECK_RDS_PORT" \
    >/dev/null 2>&1; then
    pass "RDS TCP 可连接：$CHECK_RDS_HOST:$CHECK_RDS_PORT"
  else
    fail "RDS TCP 连接失败：$CHECK_RDS_HOST:$CHECK_RDS_PORT"
  fi
else
  fail '缺少 timeout 或 bash，无法验证 RDS TCP'
fi

if [[ ! -f $COMPOSE_FILE ]]; then
  fail "缺少 Compose 文件：$COMPOSE_FILE"
elif ((ENV_AVAILABLE == 0)); then
  fail '缺少 .env.public，跳过 Compose 配置校验'
elif ! have_command docker; then
  fail '缺少 docker，跳过 Compose 配置校验'
elif ! vibelo_run_clean_environment docker compose -p vibelo-public version >/dev/null 2>&1; then
  fail 'Docker Compose 插件不可用'
elif vibelo_public_compose "$ENV_FILE" "$COMPOSE_FILE" \
  config --quiet \
  >/dev/null 2>&1; then
  pass 'Docker Compose 配置可展开（未构建、未启动）'
else
  fail 'Docker Compose 配置校验失败（未显示配置，避免泄露秘密）'
fi

unset ENV_RAW ENV_PLAIN
printf '\n预检汇总：通过 %d，警告 %d，失败 %d。\n' \
  "$PASSES" "$WARNINGS" "$FAILURES"

if ((FAILURES > 0)); then
  printf '%s\n' '结论：尚不满足上线前置条件；请逐项修复所有 [失败]。' >&2
  exit 1
fi

printf '%s\n' '结论：上线前置检查通过。脚本没有启动服务或构建镜像。'
