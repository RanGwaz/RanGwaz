#!/usr/bin/env bash

# Shared, side-effect-free validators for public deployment scripts.

vibelo_is_placeholder() {
  local value=$1
  local lower=${value,,}

  case "$lower" in
    '' | replace_me | replace_with_* | change_me | changeme | '<'*'>' | *example.com*)
      return 0
      ;;
  esac
  return 1
}

vibelo_is_origin_placeholder() {
  local value=$1
  local lower=${value,,}

  vibelo_is_placeholder "$value" && return 0
  case "$lower" in
    *example.* | *203.0.113.* | *198.51.100.* | *192.0.2.* | \
      *'你的'* | *'公网ip'* | *your_ip* | *your_domain*)
      return 0
      ;;
  esac
  return 1
}

vibelo_is_valid_origin() {
  local value=$1
  local scheme=''
  local remainder=''
  local host=''
  local port=''
  local domain=''
  local label=''
  local octet=''
  local -a labels=()
  local -a octets=()

  # CORS origin 只允许 scheme + 真实 IPv4/域名 + 可选端口。
  # 当前首发 ECS 是 IPv4，故不接受未完整校验的 IPv6 文本。
  case "$value" in
    http://*) scheme=http; remainder=${value#http://} ;;
    https://*) scheme=https; remainder=${value#https://} ;;
    *) return 1 ;;
  esac
  [[ -n $remainder &&
    $remainder != */* &&
    $remainder != *'?'* &&
    $remainder != *'#'* &&
    $remainder != *'@'* &&
    $remainder != *'['* &&
    $remainder != *']'* ]] || return 1

  if [[ $remainder == *:* ]]; then
    host=${remainder%%:*}
    port=${remainder#*:}
    [[ -n $host &&
      -n $port &&
      $port != *:* &&
      $port =~ ^[0-9]+$ &&
      ${#port} -le 5 ]] || return 1
    [[ ${#port} -eq 1 || ${port:0:1} != 0 ]] || return 1
    ((10#$port >= 1 && 10#$port <= 65535)) || return 1
    if [[ $scheme == http && 10#$port -eq 80 ]] ||
      [[ $scheme == https && 10#$port -eq 443 ]]; then
      return 1
    fi
  else
    host=$remainder
  fi

  if [[ $host =~ ^[0-9.]+$ ]]; then
    [[ $host =~ ^[0-9]+(\.[0-9]+){3}$ ]] || return 1
    IFS='.' read -r -a octets <<<"$host"
    ((${#octets[@]} == 4)) || return 1
    for octet in "${octets[@]}"; do
      ((${#octet} <= 3)) || return 1
      [[ ${#octet} -eq 1 || ${octet:0:1} != 0 ]] || return 1
      ((10#$octet >= 0 && 10#$octet <= 255)) || return 1
    done
    return 0
  fi

  domain=$host
  if [[ $domain == '*.'* ]]; then
    domain=${domain#*.}
  elif [[ $domain == *'*'* ]]; then
    return 1
  fi
  [[ -n $domain && ${#domain} -le 253 && $domain == *.* ]] || return 1
  IFS='.' read -r -a labels <<<"$domain"
  ((${#labels[@]} >= 2)) || return 1
  for label in "${labels[@]}"; do
    [[ ${#label} -ge 1 &&
      ${#label} -le 63 &&
      $label =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || return 1
  done
  return 0
}

vibelo_normalize_toml_string() {
  local value=$1

  # Trim surrounding whitespace first, then one matching TOML quote pair.
  value=${value#"${value%%[![:space:]]*}"}
  value=${value%"${value##*[![:space:]]}"}
  if ((${#value} >= 2)); then
    if [[ ${value:0:1} == "'" && ${value: -1} == "'" ]] ||
      [[ ${value:0:1} == '"' && ${value: -1} == '"' ]]; then
      value=${value:1:${#value}-2}
    fi
  fi
  printf '%s' "$value"
}

vibelo_total_swap_bytes() {
  local swap_sizes=''

  swap_sizes=$(swapon --show=SIZE --bytes --noheadings 2>/dev/null) || return 1
  awk '
    NF == 0 { next }
    NF != 1 || $1 !~ /^[0-9]+$/ { invalid = 1; next }
    { total += $1 }
    END {
      if (invalid) exit 1
      printf "%.0f", total + 0
    }
  ' <<<"$swap_sizes"
}

# Compose 的 --env-file 不会覆盖调用者 shell 中的同名变量。所有受控公网发布
# 都通过这组白名单环境执行，故 VIBELO_*、COMPOSE_*、SPRING_* 等调用者变量
# 不会参与 Compose 插值。Docker Engine 强制固定为 ECS 本机系统 socket。
vibelo_run_clean_environment() {
  local variable_name=''
  local -a clean_environment=(
    env -i
    "PATH=$PATH"
    'DOCKER_HOST=unix:///var/run/docker.sock'
  )
  local -a allowed_variables=(
    HOME USER LOGNAME
    LANG LC_ALL LC_CTYPE TZ
  )

  for variable_name in "${allowed_variables[@]}"; do
    if [[ -v $variable_name ]]; then
      clean_environment+=("$variable_name=${!variable_name}")
    fi
  done
  "${clean_environment[@]}" "$@"
}

vibelo_lock_docker_to_local_engine() {
  export DOCKER_HOST='unix:///var/run/docker.sock'
  unset DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS_VERIFY DOCKER_CERT_PATH
  unset XDG_RUNTIME_DIR
}

vibelo_public_compose() {
  local env_file=$1
  local compose_file=$2
  shift 2

  vibelo_run_clean_environment docker compose \
    -p vibelo-public \
    --env-file "$env_file" \
    -f "$compose_file" \
    "$@"
}

# 发布器本身必须来自 origin/main 当前提交：deploy 还要求目标就是该提交；
# validate/rollback 可以验收旧目标，但运行脚本的 HEAD 仍必须是最新主线。
vibelo_git_release_head_is_trusted() {
  local action=$1
  local release=$2
  local origin_main=$3
  local current_head=''

  current_head=$(git rev-parse --verify 'HEAD^{commit}' 2>/dev/null) || return 2
  case "$action" in
    deploy)
      [[ $current_head == "$release" && $release == "$origin_main" ]]
      ;;
    validate | rollback)
      [[ $current_head == "$origin_main" ]]
      ;;
    *)
      return 2
      ;;
  esac
}

# 返回 0 表示任一指定路径在两个提交间有改动，1 表示无改动，2 表示 Git 查询失败。
vibelo_git_path_has_changes() {
  local from_commit=$1
  local to_commit=$2
  local rc=0
  shift 2

  (($# > 0)) || return 2
  if git diff --quiet "$from_commit" "$to_commit" -- "$@" 2>/dev/null; then
    return 1
  else
    rc=$?
    ((rc == 1)) && return 0
    return 2
  fi
}

VIBELO_RUNTIME_IMAGE_ID=''
vibelo_running_compose_service_uses_image_id() {
  local project=$1
  local service=$2
  local expected_container_name=$3
  local expected_image_id=${4,,}
  local named_container_id=''
  local container_id_output=''
  local -a container_ids=()

  VIBELO_RUNTIME_IMAGE_ID=''
  [[ $expected_image_id =~ ^sha256:[0-9a-f]{64}$ ]] || return 2
  container_id_output=$(docker ps -q --no-trunc \
    --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$service") || return 2
  if [[ -n $container_id_output ]]; then
    mapfile -t container_ids <<<"$container_id_output" || return 2
  fi
  ((${#container_ids[@]} == 1 && ${#container_ids[0]} > 0)) || return 2
  named_container_id=$(docker container inspect \
    --format '{{.Id}}' "$expected_container_name" 2>/dev/null) || return 2
  [[ $named_container_id == "${container_ids[0]}" ]] || return 2
  VIBELO_RUNTIME_IMAGE_ID=$(docker container inspect \
    --format '{{.Image}}' "${container_ids[0]}" 2>/dev/null) || return 2
  VIBELO_RUNTIME_IMAGE_ID=${VIBELO_RUNTIME_IMAGE_ID,,}
  [[ $VIBELO_RUNTIME_IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ ]] || return 2
  [[ $VIBELO_RUNTIME_IMAGE_ID == "$expected_image_id" ]]
}
