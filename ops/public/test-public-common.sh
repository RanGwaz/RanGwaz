#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=public-common.sh
source "$SCRIPT_DIR/public-common.sh"

assert_equal() {
  local expected=$1
  local actual=$2
  local label=$3

  [[ $actual == "$expected" ]] || {
    printf '失败：%s；期望 <%s>，实际 <%s>\n' "$label" "$expected" "$actual" >&2
    exit 1
  }
}

assert_true() {
  local label=$1
  shift
  "$@" || {
    printf '失败：%s\n' "$label" >&2
    exit 1
  }
}

assert_false() {
  local label=$1
  shift
  if "$@"; then
    printf '失败：%s\n' "$label" >&2
    exit 1
  fi
}

assert_equal '/data/containerd' \
  "$(vibelo_normalize_toml_string "'/data/containerd'")" \
  '应去掉 containerd 单引号'
assert_equal '/data/containerd' \
  "$(vibelo_normalize_toml_string '  "/data/containerd"  ')" \
  '应去掉 containerd 双引号与空白'
assert_equal '/data/containerd' \
  "$(vibelo_normalize_toml_string '/data/containerd')" \
  '无引号路径应保持不变'

assert_true '应接受 IPv4 HTTP origin' \
  vibelo_is_valid_origin 'http://47.96.1.2'
assert_true '应接受 HTTPS 域名和端口' \
  vibelo_is_valid_origin 'https://www.vibelo.cn:8443'
assert_true '应接受 Spring 子域通配模式' \
  vibelo_is_valid_origin 'https://*.vibelo.cn'
assert_false '应拒绝中文 IP 占位符' \
  vibelo_is_valid_origin 'http://你的ECS公网IP'
assert_false '应拒绝带路径的 origin' \
  vibelo_is_valid_origin 'https://www.example.cn/path'
assert_false '应拒绝尾斜杠，避免与浏览器 Origin 不一致' \
  vibelo_is_valid_origin 'https://www.vibelo.cn/'
assert_false '应拒绝无效端口' \
  vibelo_is_valid_origin 'https://www.example.cn:70000'
assert_false '应拒绝可导致算术溢出的超长端口' \
  vibelo_is_valid_origin 'https://vibelo.cn:18446744073709551617'
assert_false '应拒绝带前导零的端口' \
  vibelo_is_valid_origin 'https://vibelo.cn:08443'
assert_false '应拒绝 HTTPS 显式默认端口' \
  vibelo_is_valid_origin 'https://vibelo.cn:443'
assert_false '应拒绝 HTTP 显式默认端口' \
  vibelo_is_valid_origin 'http://vibelo.cn:80'
assert_false '应拒绝裸通配符' \
  vibelo_is_valid_origin 'https://*'
assert_false '应拒绝内嵌通配符' \
  vibelo_is_valid_origin 'https://foo*bar.vibelo.cn'
assert_false '应拒绝未校验 IPv6 文本' \
  vibelo_is_valid_origin 'https://[:::]'
assert_false '应拒绝末尾连字符域名' \
  vibelo_is_valid_origin 'https://vibelo.cn-'
assert_false '应拒绝超出范围的 IPv4' \
  vibelo_is_valid_origin 'http://999.1.2.3'
assert_false '应拒绝可导致算术溢出的 IPv4 段' \
  vibelo_is_valid_origin 'http://18446744073709551617.1.2.3'
assert_false '应拒绝三段纯数字地址' \
  vibelo_is_valid_origin 'http://1.2.3'
assert_false '应拒绝五段纯数字地址' \
  vibelo_is_valid_origin 'http://1.2.3.4.5'
assert_false '应拒绝带前导零的 IPv4 段' \
  vibelo_is_valid_origin 'http://047.96.1.2'
assert_true '应识别中文占位符' \
  vibelo_is_origin_placeholder 'http://你的ECS公网IP'
assert_true '应识别文档保留 IPv4' \
  vibelo_is_origin_placeholder 'http://203.0.113.10'
assert_true '应识别示例域名' \
  vibelo_is_origin_placeholder 'https://www.example.cn'
assert_false '通用密钥占位判断不应误伤中文文本' \
  vibelo_is_placeholder '你的合法业务值'

printf '%s\n' '公网配置公共函数回归测试通过。'
