#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd -P)
BASE_COMPOSE="$REPO_ROOT/infra/docker-compose.public.yml"
TLS_COMPOSE="$REPO_ROOT/infra/docker-compose.public.tls.yml"
HTTP_CONFIG="$REPO_ROOT/infra/nginx/gateway.conf"
TLS_CONFIG="$REPO_ROOT/infra/nginx/gateway.tls.conf"
ROUTES_CONFIG="$REPO_ROOT/infra/nginx/gateway.routes.conf"
VALIDATOR="$SCRIPT_DIR/validate-domain-tls.sh"

fail() {
  printf 'TLS 配置静态测试失败：%s\n' "$*" >&2
  exit 1
}

bash -n "$VALIDATOR" || fail 'validate-domain-tls.sh 语法错误'
bash "$VALIDATOR" --help >/dev/null || fail 'validate-domain-tls.sh --help 失败'
if bash "$VALIDATOR" >/dev/null 2>&1; then
  fail 'validate-domain-tls.sh 未拒绝缺少证书目录/IP 的调用'
fi
if grep -Eq '^[[:space:]]*--(domain|www-domain)\)' "$VALIDATOR"; then
  fail 'TLS 门禁允许覆盖硬编码 Nginx 域名，可能产生假通过'
fi
grep -qF '((${#resolved[@]} == 1))' "$VALIDATOR" ||
  fail 'TLS 门禁没有要求每个域名唯一解析到目标 IPv4'
grep -qF 'resolve_ipv6' "$VALIDATOR" ||
  fail 'TLS 门禁没有检查额外 IPv6/AAAA 路由'
grep -qF '((${#resolved_ipv6[@]} == 0))' "$VALIDATOR" ||
  fail 'TLS 门禁没有拒绝当前单 ECS 方案之外的 AAAA 路由'

grep -qF 'include /etc/nginx/vibelo/gateway.routes.conf;' "$HTTP_CONFIG" ||
  fail '默认 HTTP 配置没有加载共享路由'
grep -qF 'listen 80 default_server;' "$HTTP_CONFIG" ||
  fail '默认 HTTP 配置不再监听 80'
if grep -qF '/etc/nginx/tls/' "$HTTP_CONFIG"; then
  fail '默认 HTTP 配置错误依赖证书'
fi

grep -qF 'listen 443 ssl default_server;' "$TLS_CONFIG" ||
  fail 'TLS 配置缺少 443 默认拒绝入口'
grep -qF 'ssl_reject_handshake on;' "$TLS_CONFIG" ||
  fail 'TLS 配置没有拒绝未知 SNI'
grep -qF 'server_name vibelo.xin;' "$TLS_CONFIG" ||
  fail 'TLS 配置缺少主域名'
grep -qF 'server_name www.vibelo.xin;' "$TLS_CONFIG" ||
  fail 'TLS 配置缺少 www 域名'
grep -qF 'return 308 https://vibelo.xin$request_uri;' "$TLS_CONFIG" ||
  fail 'TLS 配置缺少固定主域名重定向'
grep -qF 'location = /gateway/health {' "$TLS_CONFIG" ||
  fail 'TLS 配置破坏 Docker HTTP 健康检查'
grep -qF 'ssl_certificate /etc/nginx/tls/fullchain.pem;' "$TLS_CONFIG" ||
  fail 'TLS 配置证书路径错误'
grep -qF 'ssl_certificate_key /etc/nginx/tls/privkey.pem;' "$TLS_CONFIG" ||
  fail 'TLS 配置私钥路径错误'

for route in \
  'location = /gateway/health {' \
  'location = /api/auth/sms-code {' \
  'location = /api/actuator/health {' \
  'location /api/ {' \
  'location /media/object/ {' \
  'location /uploads/ {' \
  'location / {'; do
  grep -qF "$route" "$ROUTES_CONFIG" || fail "共享路由缺少：$route"
done

grep -qF './nginx/gateway.routes.conf:/etc/nginx/vibelo/gateway.routes.conf:ro' \
  "$BASE_COMPOSE" || fail '默认 Compose 没有只读挂载共享路由'
grep -qF '${PUBLIC_HTTPS_PORT:-443}:443' "$TLS_COMPOSE" ||
  fail 'TLS Compose 没有映射 443'
grep -qF 'source: ${VIBELO_TLS_CERT_DIR:?' "$TLS_COMPOSE" ||
  fail 'TLS Compose 没有强制显式证书目录'
grep -qF 'target: /etc/nginx/tls' "$TLS_COMPOSE" ||
  fail 'TLS Compose 证书挂载目标错误'
grep -qF 'read_only: true' "$TLS_COMPOSE" ||
  fail 'TLS Compose 证书挂载不是只读'

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  tmp_dir=$(mktemp -d)
  trap 'rm -rf -- "$tmp_dir"' EXIT
  env_file="$tmp_dir/public.env"
  cert_dir="$tmp_dir/certs"
  mkdir -p -- "$cert_dir"
  : >"$cert_dir/fullchain.pem"
  : >"$cert_dir/privkey.pem"
  printf '%s\n' \
    'SPRING_DATASOURCE_URL=jdbc:mysql://db.example.invalid:3306/app' \
    'SPRING_DATASOURCE_USERNAME=test' \
    'SPRING_DATASOURCE_PASSWORD=test' \
    'MINIO_ACCESS_KEY=test' \
    'MINIO_SECRET_KEY=test' \
    'APP_AUTH_TOKEN_SECRET=test-token-secret-at-least-32-characters' \
    'APP_MODERATION_TOKEN=distinct-test-moderation-token-32-characters' \
    >"$env_file"
  chmod 600 "$env_file" "$cert_dir/privkey.pem" 2>/dev/null || true

  VIBELO_TLS_CERT_DIR="$cert_dir" docker compose \
    --env-file "$env_file" -f "$BASE_COMPOSE" config --quiet >/dev/null ||
    fail '默认 HTTP Compose 无法展开'
  VIBELO_TLS_CERT_DIR="$cert_dir" docker compose \
    --env-file "$env_file" -f "$BASE_COMPOSE" -f "$TLS_COMPOSE" \
    config --quiet >/dev/null || fail 'TLS Compose 无法展开'
fi

printf '域名/TLS 配置静态回归测试通过。\n'
