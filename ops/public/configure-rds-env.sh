#!/usr/bin/env bash
set -Eeuo pipefail

# This script intentionally disables xtrace: secrets must never be printed even
# when the caller accidentally invokes it with `bash -x`.
if [[ $- == *x* ]]; then
  set +x
fi

umask 077

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=public-common.sh
source "$SCRIPT_DIR/public-common.sh"
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd -P)
EXAMPLE_FILE="$REPO_ROOT/.env.public.example"
ENV_FILE="$REPO_ROOT/.env.public"

DEFAULT_RDS_HOST='rm-bp111eaxy9eeuvqcb.mysql.rds.aliyuncs.com'
DEFAULT_RDS_PORT='3306'
DEFAULT_DATABASE='rangwaz_image_dev'
DEFAULT_APP_USER='vibelo_app'

RDS_HOST=$DEFAULT_RDS_HOST
RDS_PORT=$DEFAULT_RDS_PORT
DATABASE=$DEFAULT_DATABASE
APP_USER=$DEFAULT_APP_USER
PUBLIC_HTTP_PORT_OVERRIDE=''
ALLOWED_ORIGIN_OVERRIDE=''
SMS_MOCK_OVERRIDE=''
SMS_SIGN_NAME_OVERRIDE=''
SMS_TEMPLATE_CODE_OVERRIDE=''
SSL_MODE_OVERRIDE=''

WORK_FILE=''
NEXT_FILE=''
ENV_FOUND=0
ENV_RAW=''
ENV_PLAIN=''
ENV_QUOTED=''
SELECTED_RAW=''
SECRET_INPUT=''
SECRET_CONFIRM=''

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

note() {
  printf '%s\n' "$*" >&2
}

usage() {
  cat <<'EOF'
用法：
  bash ops/public/configure-rds-env.sh [选项]

非秘密参数：
  --rds-host HOST             RDS 内网地址
  --rds-port PORT             RDS 端口，默认 3306
  --database NAME             业务数据库名
  --app-user USER             RDS 标准应用账号
  --public-http-port PORT      Nginx 对外 HTTP 端口
  --allowed-origin URL         前端正式域名，例如 https://www.example.cn
  --sms-mock true|false        是否使用模拟短信，公网默认 false
  --sms-sign-name NAME         阿里云短信签名
  --sms-template-code CODE     阿里云短信模板代码
  --ssl-mode MODE              PREFERRED、REQUIRED、VERIFY_CA 或 VERIFY_IDENTITY
  -h, --help                   显示帮助

所有密码、Token、MinIO 凭据和短信 AccessKey 都只能在静默提示中输入；
脚本不接受秘密命令行参数。已有有效秘密按 Enter 即可保留。
EOF
}

cleanup() {
  unset SECRET_INPUT SECRET_CONFIRM SELECTED_RAW ENV_RAW ENV_PLAIN ENV_QUOTED
  if [[ -n ${NEXT_FILE:-} && -f ${NEXT_FILE:-} ]]; then
    rm -f -- "$NEXT_FILE"
  fi
  if [[ -n ${WORK_FILE:-} && -f ${WORK_FILE:-} ]]; then
    rm -f -- "$WORK_FILE"
  fi
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

require_argument() {
  local option=$1
  local count=$2
  ((count >= 2)) || die "$option 缺少值"
}

validate_port() {
  local label=$1
  local value=$2

  [[ $value =~ ^[0-9]+$ ]] ||
    die "$label 必须是 1 到 65535 之间的整数"
  ((10#$value >= 1 && 10#$value <= 65535)) ||
    die "$label 必须是 1 到 65535 之间的整数"
}

validate_single_line() {
  local label=$1
  local value=$2

  [[ -n $value ]] || die "$label 不能为空"
  [[ $value != *$'\n'* && $value != *$'\r'* ]] ||
    die "$label 不能包含换行符"
}

while (($# > 0)); do
  case "$1" in
    --rds-host)
      require_argument "$1" "$#"
      RDS_HOST=$2
      shift 2
      ;;
    --rds-port)
      require_argument "$1" "$#"
      RDS_PORT=$2
      shift 2
      ;;
    --database)
      require_argument "$1" "$#"
      DATABASE=$2
      shift 2
      ;;
    --app-user)
      require_argument "$1" "$#"
      APP_USER=$2
      shift 2
      ;;
    --public-http-port)
      require_argument "$1" "$#"
      PUBLIC_HTTP_PORT_OVERRIDE=$2
      shift 2
      ;;
    --allowed-origin)
      require_argument "$1" "$#"
      ALLOWED_ORIGIN_OVERRIDE=$2
      shift 2
      ;;
    --sms-mock)
      require_argument "$1" "$#"
      SMS_MOCK_OVERRIDE=${2,,}
      shift 2
      ;;
    --sms-sign-name)
      require_argument "$1" "$#"
      SMS_SIGN_NAME_OVERRIDE=$2
      shift 2
      ;;
    --sms-template-code)
      require_argument "$1" "$#"
      SMS_TEMPLATE_CODE_OVERRIDE=$2
      shift 2
      ;;
    --ssl-mode)
      require_argument "$1" "$#"
      SSL_MODE_OVERRIDE=${2^^}
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

[[ -f $EXAMPLE_FILE ]] ||
  die "找不到模板：$EXAMPLE_FILE"
[[ ! -L $ENV_FILE ]] ||
  die "$ENV_FILE 不能是符号链接"
[[ $RDS_HOST =~ ^[A-Za-z0-9.-]+$ ]] ||
  die "RDS 地址格式不合法"
[[ $DATABASE =~ ^[A-Za-z0-9_]+$ ]] ||
  die "数据库名只能包含字母、数字和下划线"
[[ $APP_USER =~ ^[A-Za-z0-9_]+$ ]] ||
  die "应用账号只能包含字母、数字和下划线"
if [[ ${APP_USER,,} == dms_user_* ]]; then
  die "DMS 自动服务账号不能作为应用账号；请创建独立的 RDS 标准账号"
fi
validate_port "RDS 端口" "$RDS_PORT"
if [[ -n $PUBLIC_HTTP_PORT_OVERRIDE ]]; then
  validate_port "HTTP 端口" "$PUBLIC_HTTP_PORT_OVERRIDE"
fi
if [[ -n $ALLOWED_ORIGIN_OVERRIDE ]]; then
  validate_single_line "允许来源" "$ALLOWED_ORIGIN_OVERRIDE"
  ! vibelo_is_origin_placeholder "$ALLOWED_ORIGIN_OVERRIDE" ||
    die "允许来源仍是占位符；请换成真实公网 IP 或域名"
  vibelo_is_valid_origin "$ALLOWED_ORIGIN_OVERRIDE" ||
    die "允许来源必须是包含真实公网 IP 或域名的完整 origin"
fi
if [[ -n $SMS_MOCK_OVERRIDE &&
  $SMS_MOCK_OVERRIDE != true &&
  $SMS_MOCK_OVERRIDE != false ]]; then
  die "--sms-mock 只能是 true 或 false"
fi
if [[ -n $SMS_SIGN_NAME_OVERRIDE ]]; then
  validate_single_line "短信签名" "$SMS_SIGN_NAME_OVERRIDE"
fi
if [[ -n $SMS_TEMPLATE_CODE_OVERRIDE ]]; then
  [[ $SMS_TEMPLATE_CODE_OVERRIDE =~ ^[A-Za-z0-9_-]+$ ]] ||
    die "短信模板代码格式不合法"
fi
if [[ -n $SSL_MODE_OVERRIDE ]]; then
  case "$SSL_MODE_OVERRIDE" in
    PREFERRED | REQUIRED | VERIFY_CA | VERIFY_IDENTITY) ;;
    *) die "--ssl-mode 只允许 PREFERRED、REQUIRED、VERIFY_CA 或 VERIFY_IDENTITY" ;;
  esac
fi

if [[ -e $ENV_FILE ]]; then
  [[ -f $ENV_FILE ]] || die "$ENV_FILE 不是普通文件"
  chmod 600 -- "$ENV_FILE" ||
    die "无法把 $ENV_FILE 权限设为 600"
fi

WORK_FILE=$(mktemp "$REPO_ROOT/.env.public.tmp.XXXXXXXX") ||
  die "无法在仓库根目录创建安全临时文件"
chmod 600 -- "$WORK_FILE"

if [[ -f $ENV_FILE ]]; then
  cp -- "$ENV_FILE" "$WORK_FILE"
else
  cp -- "$EXAMPLE_FILE" "$WORK_FILE"
fi
chmod 600 -- "$WORK_FILE"

env_has_key() {
  local key=$1
  local line

  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line == "$key="* ]]; then
      return 0
    fi
  done <"$WORK_FILE"
  return 1
}

ensure_template_keys() {
  local template_line
  local key
  local wrote_header=0

  while IFS= read -r template_line || [[ -n $template_line ]]; do
    [[ $template_line =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    key=${template_line%%=*}
    if ! env_has_key "$key"; then
      if ((wrote_header == 0)); then
        printf '\n# Added from .env.public.example by configure-rds-env.sh\n' \
          >>"$WORK_FILE"
        wrote_header=1
      fi
      printf '%s\n' "$template_line" >>"$WORK_FILE"
    fi
  done <"$EXAMPLE_FILE"
}

get_env_raw() {
  local key=$1
  local line

  ENV_FOUND=0
  ENV_RAW=''
  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line == "$key="* ]]; then
      ENV_FOUND=1
      ENV_RAW=${line#*=}
      return 0
    fi
  done <"$WORK_FILE"
  return 1
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

raw_is_usable_secret() {
  local raw=$1
  local minimum_length=$2

  plain_from_raw "$raw"
  ! is_placeholder "$ENV_PLAIN" &&
    ((${#ENV_PLAIN} >= minimum_length))
}

quote_env_value() {
  local value=$1

  validate_single_line "配置值" "$value"
  value=${value//\'/\\\'}
  ENV_QUOTED="'$value'"
}

set_env_raw() {
  local key=$1
  local raw=$2
  local line
  local found=0

  NEXT_FILE=$(mktemp "$REPO_ROOT/.env.public.edit.XXXXXXXX") ||
    die "无法创建安全临时文件"
  chmod 600 -- "$NEXT_FILE"

  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line == "$key="* ]]; then
      if ((found == 0)); then
        printf '%s=%s\n' "$key" "$raw" >>"$NEXT_FILE"
        found=1
      fi
    else
      printf '%s\n' "$line" >>"$NEXT_FILE"
    fi
  done <"$WORK_FILE"

  if ((found == 0)); then
    printf '%s=%s\n' "$key" "$raw" >>"$NEXT_FILE"
  fi

  mv -f -- "$NEXT_FILE" "$WORK_FILE"
  NEXT_FILE=''
  chmod 600 -- "$WORK_FILE"
}

set_env_value() {
  local key=$1
  local value=$2

  quote_env_value "$value"
  set_env_raw "$key" "$ENV_QUOTED"
  ENV_QUOTED=''
}

prompt_plain_required() {
  local key=$1
  local label=$2
  local validator=$3
  local input=''

  get_env_raw "$key" || true
  if ((ENV_FOUND == 1)); then
    plain_from_raw "$ENV_RAW"
    if ! is_placeholder "$ENV_PLAIN"; then
      if [[ $validator != origin ]] ||
        { ! vibelo_is_origin_placeholder "$ENV_PLAIN" && vibelo_is_valid_origin "$ENV_PLAIN"; }; then
        return 0
      fi
      note "$label 已配置但格式无效，请重新输入。"
    fi
  fi

  [[ -r /dev/tty && -w /dev/tty ]] ||
    die "$label 尚未配置，而且当前没有可交互终端"

  while true; do
    IFS= read -r -p "请输入${label}: " input </dev/tty ||
      die "无法读取${label}"
    validate_single_line "$label" "$input"
    case "$validator" in
      origin)
        if vibelo_is_origin_placeholder "$input" || ! vibelo_is_valid_origin "$input"; then
          note "$label 必须是包含真实公网 IP 或域名的完整 origin。"
          continue
        fi
        ;;
      sms-template)
        if [[ ! $input =~ ^[A-Za-z0-9_-]+$ ]]; then
          note "$label 格式不合法，请重新输入。"
          continue
        fi
        ;;
    esac
    set_env_value "$key" "$input"
    unset input
    return 0
  done
}

prompt_secret_raw() {
  local label=$1
  local existing_raw=$2
  local minimum_length=$3
  local confirm_new=$4
  local has_existing=0

  SELECTED_RAW=''
  if raw_is_usable_secret "$existing_raw" "$minimum_length"; then
    has_existing=1
  fi

  [[ -r /dev/tty && -w /dev/tty ]] ||
    die "$label 需要静默输入，而且当前没有可交互终端"

  while true; do
    if ((has_existing == 1)); then
      IFS= read -r -s \
        -p "$label 已配置；按 Enter 保留，或输入新值: " \
        SECRET_INPUT </dev/tty ||
        die "无法读取 $label"
    else
      IFS= read -r -s \
        -p "请输入 $label（不会回显）: " \
        SECRET_INPUT </dev/tty ||
        die "无法读取 $label"
    fi
    printf '\n' >/dev/tty

    if [[ -z $SECRET_INPUT ]]; then
      if ((has_existing == 1)); then
        SELECTED_RAW=$existing_raw
        unset SECRET_INPUT
        return 0
      fi
      note "$label 不能为空。"
      continue
    fi
    if ((${#SECRET_INPUT} < minimum_length)); then
      note "$label 至少需要 $minimum_length 个字符。"
      unset SECRET_INPUT
      continue
    fi
    validate_single_line "$label" "$SECRET_INPUT"

    if [[ $confirm_new == true ]]; then
      IFS= read -r -s -p "请再次输入 $label: " SECRET_CONFIRM </dev/tty ||
        die "无法读取 $label 确认值"
      printf '\n' >/dev/tty
      if [[ $SECRET_INPUT != "$SECRET_CONFIRM" ]]; then
        note "两次输入不一致，请重新输入。"
        unset SECRET_INPUT SECRET_CONFIRM
        continue
      fi
    fi

    quote_env_value "$SECRET_INPUT"
    SELECTED_RAW=$ENV_QUOTED
    unset SECRET_INPUT SECRET_CONFIRM ENV_QUOTED
    return 0
  done
}

prompt_secret_key() {
  local key=$1
  local label=$2
  local minimum_length=$3
  local confirm_new=$4
  local existing_raw=''

  get_env_raw "$key" || true
  if ((ENV_FOUND == 1)); then
    existing_raw=$ENV_RAW
  fi
  prompt_secret_raw "$label" "$existing_raw" "$minimum_length" "$confirm_new"
  set_env_raw "$key" "$SELECTED_RAW"
  unset existing_raw SELECTED_RAW
}

ensure_template_keys

SSL_MODE='PREFERRED'
if [[ -n $SSL_MODE_OVERRIDE ]]; then
  SSL_MODE=$SSL_MODE_OVERRIDE
else
  # 重跑配置时保留已有的更严格 SSL 模式，避免 RDS 启用 SSL 后被
  # 静默降回 PREFERRED。
  get_env_raw SPRING_DATASOURCE_URL || true
  if ((ENV_FOUND == 1)); then
    plain_from_raw "$ENV_RAW"
    if [[ $ENV_PLAIN =~ (^|[?&])sslMode=([A-Za-z_]+) ]]; then
      EXISTING_SSL_MODE=${BASH_REMATCH[2]^^}
      case "$EXISTING_SSL_MODE" in
        PREFERRED | REQUIRED | VERIFY_CA | VERIFY_IDENTITY)
          SSL_MODE=$EXISTING_SSL_MODE
          ;;
        *)
          die "现有 SPRING_DATASOURCE_URL 的 sslMode 不受支持：$EXISTING_SSL_MODE"
          ;;
      esac
      unset EXISTING_SSL_MODE
    fi
  fi
fi

JDBC_URL="jdbc:mysql://${RDS_HOST}:${RDS_PORT}/${DATABASE}?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&sslMode=${SSL_MODE}&connectTimeout=5000&socketTimeout=10000&tcpKeepAlive=true"
set_env_value SPRING_DATASOURCE_URL "$JDBC_URL"
set_env_value SPRING_DATASOURCE_USERNAME "$APP_USER"
set_env_value VIBELO_DB_HOST "$RDS_HOST"
set_env_value VIBELO_DB_PORT "$RDS_PORT"
set_env_value VIBELO_DB_NAME "$DATABASE"
set_env_value VIBELO_DB_USER "$APP_USER"
unset JDBC_URL

if [[ -n $PUBLIC_HTTP_PORT_OVERRIDE ]]; then
  set_env_raw PUBLIC_HTTP_PORT "$PUBLIC_HTTP_PORT_OVERRIDE"
fi
if [[ -n $ALLOWED_ORIGIN_OVERRIDE ]]; then
  set_env_value APP_WEB_ALLOWED_ORIGIN_PATTERNS "$ALLOWED_ORIGIN_OVERRIDE"
fi
if [[ -n $SMS_MOCK_OVERRIDE ]]; then
  set_env_raw APP_SMS_MOCK "$SMS_MOCK_OVERRIDE"
fi
if [[ -n $SMS_SIGN_NAME_OVERRIDE ]]; then
  set_env_value ALIYUN_SMS_SIGN_NAME "$SMS_SIGN_NAME_OVERRIDE"
fi
if [[ -n $SMS_TEMPLATE_CODE_OVERRIDE ]]; then
  set_env_value ALIYUN_SMS_TEMPLATE_CODE "$SMS_TEMPLATE_CODE_OVERRIDE"
fi

prompt_plain_required \
  APP_WEB_ALLOWED_ORIGIN_PATTERNS \
  "前端正式来源（例如 https://www.example.cn）" \
  origin

get_env_raw APP_SMS_MOCK || true
if ((ENV_FOUND == 1)); then
  plain_from_raw "$ENV_RAW"
  SMS_MOCK_VALUE=${ENV_PLAIN,,}
else
  SMS_MOCK_VALUE=false
  set_env_raw APP_SMS_MOCK false
fi
if [[ $SMS_MOCK_VALUE != true && $SMS_MOCK_VALUE != false ]]; then
  die "APP_SMS_MOCK 只能是 true 或 false"
fi

if [[ $SMS_MOCK_VALUE == false ]]; then
  prompt_plain_required ALIYUN_SMS_SIGN_NAME "阿里云短信签名" plain
  prompt_plain_required ALIYUN_SMS_TEMPLATE_CODE "阿里云短信模板代码" sms-template
fi

SPRING_PASSWORD_RAW=''
VIBELO_PASSWORD_RAW=''
get_env_raw SPRING_DATASOURCE_PASSWORD || true
if ((ENV_FOUND == 1)); then
  SPRING_PASSWORD_RAW=$ENV_RAW
fi
get_env_raw VIBELO_DB_PASSWORD || true
if ((ENV_FOUND == 1)); then
  VIBELO_PASSWORD_RAW=$ENV_RAW
fi
if raw_is_usable_secret "$SPRING_PASSWORD_RAW" 1; then
  RDS_PASSWORD_EXISTING=$SPRING_PASSWORD_RAW
elif raw_is_usable_secret "$VIBELO_PASSWORD_RAW" 1; then
  RDS_PASSWORD_EXISTING=$VIBELO_PASSWORD_RAW
else
  RDS_PASSWORD_EXISTING=''
fi
prompt_secret_raw "RDS 应用账号密码" "$RDS_PASSWORD_EXISTING" 1 true
set_env_raw SPRING_DATASOURCE_PASSWORD "$SELECTED_RAW"
set_env_raw VIBELO_DB_PASSWORD "$SELECTED_RAW"
unset SPRING_PASSWORD_RAW VIBELO_PASSWORD_RAW RDS_PASSWORD_EXISTING SELECTED_RAW

prompt_secret_key APP_AUTH_TOKEN_SECRET "登录 Token 签名密钥" 32 true
prompt_secret_key APP_MODERATION_TOKEN "人工审核令牌" 32 true
prompt_secret_key MINIO_ACCESS_KEY "MinIO Access Key" 3 false
prompt_secret_key MINIO_SECRET_KEY "MinIO Secret Key" 8 true

if [[ $SMS_MOCK_VALUE == false ]]; then
  prompt_secret_key ALIYUN_SMS_ACCESS_KEY_ID "阿里云短信 AccessKey ID" 1 false
  prompt_secret_key ALIYUN_SMS_ACCESS_KEY_SECRET "阿里云短信 AccessKey Secret" 1 true
fi

mv -f -- "$WORK_FILE" "$ENV_FILE"
WORK_FILE=''
chmod 600 -- "$ENV_FILE"

note "配置已安全写入：$ENV_FILE"
note "RDS：${RDS_HOST}:${RDS_PORT}/${DATABASE}"
note "应用账号：$APP_USER"
note "RDS SSL 模式：$SSL_MODE"
note "文件权限：$(stat -c '%a' "$ENV_FILE" 2>/dev/null || printf '未知')"
note "秘密值未显示。下一步运行：sudo bash ops/public/preflight.sh"
