#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $- == *x* ]]; then
  set +x
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd -P)
BASE_COMPOSE="$REPO_ROOT/infra/docker-compose.public.yml"
TLS_COMPOSE="$REPO_ROOT/infra/docker-compose.public.tls.yml"
TLS_CONFIG="$REPO_ROOT/infra/nginx/gateway.tls.conf"
ROUTES_CONFIG="$REPO_ROOT/infra/nginx/gateway.routes.conf"

DOMAIN='vibelo.xin'
WWW_DOMAIN='www.vibelo.xin'
CERT_DIR=''
EXPECTED_IP=''
ENV_FILE="$REPO_ROOT/.env.public"
MIN_VALID_DAYS=14
NGINX_IMAGE='nginx:1.27-alpine'

usage() {
  cat <<'EOF'
用法：
  bash ops/public/validate-domain-tls.sh \
    --cert-dir /data/vibelo-tls \
    --expected-ip 你的ECS公网IPv4

可选参数：
  --env-file FILE       .env.public 路径（默认仓库根目录/.env.public）
  --min-valid-days N    证书至少还需有效 N 天（默认 14）
  --nginx-image IMAGE   已离线导入的 Nginx 镜像（默认 nginx:1.27-alpine）
  -h, --help            显示帮助

这是上线前门禁，不会修改 .env.public、Nginx、现有容器或数据卷，也不会拉取
或构建镜像。它会只读检查 DNS、证书、私钥、CORS、Compose 展开，并用临时
容器执行 nginx -t；临时容器随后自动删除，缺少任一条件都会失败。
EOF
}

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

require_argument() {
  local option=$1
  local count=$2
  ((count >= 2)) || die "$option 缺少参数"
}

valid_domain() {
  local value=$1
  [[ ${#value} -le 253 &&
    $value == *.* &&
    $value =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ &&
    $value != *..* ]]
}

valid_ipv4() {
  local value=$1
  local octet=''
  local -a octets=()

  [[ $value =~ ^[0-9]+(\.[0-9]+){3}$ ]] || return 1
  IFS='.' read -r -a octets <<<"$value"
  ((${#octets[@]} == 4)) || return 1
  for octet in "${octets[@]}"; do
    [[ ${#octet} -le 3 ]] || return 1
    [[ ${#octet} -eq 1 || ${octet:0:1} != 0 ]] || return 1
    ((10#$octet >= 0 && 10#$octet <= 255)) || return 1
  done
}

read_env_plain() {
  local key=$1
  local raw=''

  raw=$(awk -v wanted="$key" '
    index($0, wanted "=") == 1 { value = substr($0, length(wanted) + 2) }
    END { if (value != "") print value }
  ' "$ENV_FILE")
  raw=${raw%$'\r'}
  if ((${#raw} >= 2)); then
    if [[ ${raw:0:1} == "'" && ${raw: -1} == "'" ]] ||
      [[ ${raw:0:1} == '"' && ${raw: -1} == '"' ]]; then
      raw=${raw:1:${#raw}-2}
    fi
  fi
  printf '%s' "$raw"
}

resolve_ipv4() {
  local host=$1

  getent ahostsv4 "$host" 2>/dev/null |
    awk '$1 ~ /^[0-9]+(\.[0-9]+){3}$/ {print $1}' |
    sort -u || true
}

resolve_ipv6() {
  local host=$1

  # ahostsv6 can expose IPv4-mapped addresses. They are not DNS AAAA
  # records, so only real IPv6 addresses are treated as an unexpected route.
  getent ahostsv6 "$host" 2>/dev/null |
    awk '$1 ~ /:/ && tolower($1) !~ /^::ffff:/ {print tolower($1)}' |
    sort -u || true
}

while (($# > 0)); do
  case "$1" in
    --cert-dir)
      require_argument "$1" "$#"
      CERT_DIR=$2
      shift 2
      ;;
    --expected-ip)
      require_argument "$1" "$#"
      EXPECTED_IP=$2
      shift 2
      ;;
    --env-file)
      require_argument "$1" "$#"
      ENV_FILE=$2
      shift 2
      ;;
    --min-valid-days)
      require_argument "$1" "$#"
      MIN_VALID_DAYS=$2
      shift 2
      ;;
    --nginx-image)
      require_argument "$1" "$#"
      NGINX_IMAGE=$2
      shift 2
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

[[ -n $CERT_DIR ]] || die '必须提供 --cert-dir'
[[ -n $EXPECTED_IP ]] || die '必须提供 --expected-ip，防止把证书发布到错误主机'
valid_domain "$DOMAIN" || die "主域名格式错误：$DOMAIN"
valid_domain "$WWW_DOMAIN" || die "www 域名格式错误：$WWW_DOMAIN"
[[ $WWW_DOMAIN != "$DOMAIN" ]] || die '主域名与 www 域名不能相同'
valid_ipv4 "$EXPECTED_IP" || die "ECS 公网 IPv4 格式错误：$EXPECTED_IP"
[[ $MIN_VALID_DAYS =~ ^[0-9]+$ ]] || die '--min-valid-days 必须是整数'
((MIN_VALID_DAYS >= 1 && MIN_VALID_DAYS <= 3650)) ||
  die '--min-valid-days 必须在 1 到 3650 之间'

for command in awk docker getent openssl sort stat; do
  command -v "$command" >/dev/null 2>&1 || die "缺少命令：$command"
done

[[ -f $ENV_FILE && ! -L $ENV_FILE ]] || die ".env.public 不是普通文件：$ENV_FILE"
env_mode=$(stat -c '%a' -- "$ENV_FILE")
[[ $env_mode == 600 ]] || die ".env.public 权限必须是 600，当前为 $env_mode"

[[ -d $CERT_DIR && ! -L $CERT_DIR ]] || die "证书目录不存在或是符号链接：$CERT_DIR"
CERT_DIR=$(cd -- "$CERT_DIR" && pwd -P)
CERT_FILE="$CERT_DIR/fullchain.pem"
KEY_FILE="$CERT_DIR/privkey.pem"
[[ -f $CERT_FILE && ! -L $CERT_FILE ]] || die "缺少普通文件：$CERT_FILE"
[[ -f $KEY_FILE && ! -L $KEY_FILE ]] || die "缺少普通文件：$KEY_FILE"

key_mode=$(stat -c '%a' -- "$KEY_FILE")
[[ $key_mode =~ ^[0-7]{3,4}$ ]] || die "无法识别私钥权限：$key_mode"
(( (8#$key_mode & 077) == 0 )) ||
  die "私钥不能向 group/other 开放，当前权限为 $key_mode；请执行 chmod 600"

openssl crl2pkcs7 -nocrl -certfile "$CERT_FILE" 2>/dev/null |
  openssl pkcs7 -print_certs -noout >/dev/null 2>&1 ||
  die 'fullchain.pem 不是可解析的 PEM 证书链'
openssl x509 -in "$CERT_FILE" -noout -checkend "$((MIN_VALID_DAYS * 86400))" \
  >/dev/null 2>&1 || die "证书将在 $MIN_VALID_DAYS 天内过期或尚未生效"
openssl x509 -in "$CERT_FILE" -noout -checkhost "$DOMAIN" \
  >/dev/null 2>&1 || die "证书不覆盖 $DOMAIN"
openssl x509 -in "$CERT_FILE" -noout -checkhost "$WWW_DOMAIN" \
  >/dev/null 2>&1 || die "证书不覆盖 $WWW_DOMAIN"
openssl pkey -in "$KEY_FILE" -passin pass: -noout >/dev/null 2>&1 ||
  die 'privkey.pem 无法解析，或私钥带口令（Nginx 无人值守启动不接受带口令私钥）'

cert_public_key=$(
  openssl x509 -in "$CERT_FILE" -pubkey -noout 2>/dev/null |
    openssl pkey -pubin -outform DER 2>/dev/null |
    openssl dgst -sha256
)
key_public_key=$(
  openssl pkey -in "$KEY_FILE" -passin pass: -pubout -outform DER 2>/dev/null |
    openssl dgst -sha256
)
[[ -n $cert_public_key && $cert_public_key == "$key_public_key" ]] ||
  die '证书与私钥不匹配'
unset cert_public_key key_public_key
printf '[通过] 证书链、域名覆盖、有效期、私钥权限和密钥匹配校验通过\n'

for host in "$DOMAIN" "$WWW_DOMAIN"; do
  mapfile -t resolved < <(resolve_ipv4 "$host")
  ((${#resolved[@]} == 1)) ||
    die "$host 必须且只能有一个公网 IPv4 解析（当前：${resolved[*]:-无}）"
  [[ ${resolved[0]} == "$EXPECTED_IP" ]] ||
    die "$host 未唯一解析到预期 ECS 公网 IP $EXPECTED_IP（当前：${resolved[0]}）"
  mapfile -t resolved_ipv6 < <(resolve_ipv6 "$host")
  ((${#resolved_ipv6[@]} == 0)) ||
    die "$host 存在未纳入当前单 ECS 方案的 IPv6/AAAA 解析：${resolved_ipv6[*]}"
done
unset resolved resolved_ipv6
printf '[通过] %s 与 %s 均唯一解析到 %s，且不存在额外 AAAA 路由\n' "$DOMAIN" "$WWW_DOMAIN" "$EXPECTED_IP"

allowed_origin=$(read_env_plain APP_WEB_ALLOWED_ORIGIN_PATTERNS)
origin_count=$(grep -c '^APP_WEB_ALLOWED_ORIGIN_PATTERNS=' "$ENV_FILE" || true)
((origin_count == 1)) ||
  die "APP_WEB_ALLOWED_ORIGIN_PATTERNS 必须且只能配置一次，当前 $origin_count 次"
[[ $allowed_origin == "https://$DOMAIN" ]] ||
  die "APP_WEB_ALLOWED_ORIGIN_PATTERNS 必须是唯一规范来源 https://$DOMAIN"
https_port=$(read_env_plain PUBLIC_HTTPS_PORT)
https_port_count=$(grep -c '^PUBLIC_HTTPS_PORT=' "$ENV_FILE" || true)
((https_port_count == 1)) ||
  die "PUBLIC_HTTPS_PORT 必须且只能配置一次，当前 $https_port_count 次"
[[ $https_port == 443 ]] || die 'PUBLIC_HTTPS_PORT 必须是 443'
env_cert_dir=$(read_env_plain VIBELO_TLS_CERT_DIR)
env_cert_dir_count=$(grep -c '^VIBELO_TLS_CERT_DIR=' "$ENV_FILE" || true)
((env_cert_dir_count == 1)) ||
  die "VIBELO_TLS_CERT_DIR 必须且只能配置一次，当前 $env_cert_dir_count 次"
[[ -d $env_cert_dir ]] || die "VIBELO_TLS_CERT_DIR 不存在：$env_cert_dir"
env_cert_dir=$(cd -- "$env_cert_dir" && pwd -P)
[[ $env_cert_dir == "$CERT_DIR" ]] ||
  die "VIBELO_TLS_CERT_DIR 与 --cert-dir 不一致：$env_cert_dir"
unset allowed_origin origin_count https_port https_port_count env_cert_dir env_cert_dir_count
printf '[通过] 后端 CORS 来源固定为 https://%s\n' "$DOMAIN"
printf '[通过] HTTPS 端口与只读证书目录运行参数通过\n'

docker compose --env-file "$ENV_FILE" \
  -f "$BASE_COMPOSE" \
  -f "$TLS_COMPOSE" \
  config --quiet >/dev/null || die 'TLS Compose 配置无法安全展开'
printf '[通过] TLS Compose 覆盖配置可展开（未构建、未拉取、未启动）\n'

docker image inspect "$NGINX_IMAGE" >/dev/null 2>&1 ||
  die "本机不存在固定 Nginx 镜像 $NGINX_IMAGE；本脚本不会在线拉取"
docker run --rm --pull=never --network none \
  --add-host backend:127.0.0.1 \
  --add-host frontend:127.0.0.1 \
  --mount "type=bind,src=$TLS_CONFIG,dst=/etc/nginx/nginx.conf,readonly" \
  --mount "type=bind,src=$ROUTES_CONFIG,dst=/etc/nginx/vibelo/gateway.routes.conf,readonly" \
  --mount "type=bind,src=$CERT_DIR,dst=/etc/nginx/tls,readonly" \
  "$NGINX_IMAGE" nginx -t >/dev/null || die 'nginx -t 失败'
printf '[通过] 固定 Nginx 镜像内 nginx -t 通过（临时容器已自动删除）\n'

cat <<EOF
=== Vibelo 域名/TLS 上线门禁通过 ===
本脚本没有修改配置、证书、现有容器或数据卷；临时语法检查容器已删除。
确认 ICP 备案已经完成且阿里云备案状态允许开站后，按部署文档显式加入：
  -f infra/docker-compose.public.tls.yml
不要在备案审核期间启用站点。
EOF
