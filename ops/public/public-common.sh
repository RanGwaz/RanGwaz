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
