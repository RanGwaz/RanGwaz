#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $- == *x* ]]; then
  set +x
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd -P)
REQUIREMENTS_FILE="$REPO_ROOT/tools/requirements_search_reindex.txt"
EXPECTED_WHEEL_NAME='pymysql-1.1.2-py3-none-any.whl'
EXPECTED_WHEEL_SIZE='45300'
EXPECTED_WHEEL_SHA256='e6b1d89711dd51f8f74b1631fe08f039e7d76cf67a42a323d3178f0f25762ed9'
EXPECTED_PYMYSQL_VERSION='1.1.2'
WHEEL_PATH=''
VENV_PATH='/opt/vibelo/.venv-ops'

usage() {
  cat <<'EOF'
用法：
  bash ops/public/install-search-reindex-dependencies.sh \
    --wheel /data/migration/search-reindex/pymysql-1.1.2-py3-none-any.whl \
    [--venv /opt/vibelo/.venv-ops]

只从固定 wheel 离线安装搜索重建依赖；不访问 PyPI，不升级 pip。
EOF
}

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

while (($# > 0)); do
  case "$1" in
    --wheel)
      (($# >= 2)) || die '--wheel 缺少路径'
      WHEEL_PATH=$2
      shift 2
      ;;
    --venv)
      (($# >= 2)) || die '--venv 缺少路径'
      VENV_PATH=$2
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

[[ -n $WHEEL_PATH ]] || die '必须提供 --wheel'
[[ -f $REQUIREMENTS_FILE && ! -L $REQUIREMENTS_FILE ]] ||
  die "固定依赖清单无效：$REQUIREMENTS_FILE"
[[ -f $WHEEL_PATH && ! -L $WHEEL_PATH ]] || die 'wheel 必须是普通文件且不能是符号链接'
[[ ${WHEEL_PATH##*/} == "$EXPECTED_WHEEL_NAME" ]] ||
  die "wheel 文件名必须是 $EXPECTED_WHEEL_NAME"
[[ $VENV_PATH == /* && $VENV_PATH != / ]] || die '--venv 必须是非根目录绝对路径'
[[ ! -L $VENV_PATH ]] || die 'venv 不能是符号链接'

command -v python3 >/dev/null 2>&1 || die '找不到 python3'
command -v sha256sum >/dev/null 2>&1 || die '找不到 sha256sum'
command -v stat >/dev/null 2>&1 || die '找不到 stat'

actual_size=$(stat -c '%s' -- "$WHEEL_PATH")
[[ $actual_size == "$EXPECTED_WHEEL_SIZE" ]] ||
  die "wheel 尺寸错误：$actual_size，预期 $EXPECTED_WHEEL_SIZE"
actual_sha256=$(sha256sum -- "$WHEEL_PATH")
actual_sha256=${actual_sha256%% *}
[[ $actual_sha256 == "$EXPECTED_WHEEL_SHA256" ]] ||
  die "wheel SHA256 错误：$actual_sha256"

python3 - <<'PY' || die 'Python 版本必须至少为 3.8'
import sys
raise SystemExit(0 if sys.version_info >= (3, 8) else 1)
PY

attestation="$VENV_PATH/.vibelo-search-reindex-wheel.sha256"
if [[ -e $VENV_PATH ]]; then
  [[ -d $VENV_PATH && -x $VENV_PATH/bin/python ]] ||
    die "既有 venv 无效，拒绝覆盖：$VENV_PATH"
  [[ -f $attestation && ! -L $attestation ]] ||
    die "既有 venv 缺少固定 wheel 凭据，拒绝继续：$attestation"
  [[ $(<"$attestation") == "$EXPECTED_WHEEL_SHA256" ]] ||
    die '既有 venv 的 wheel 凭据不匹配'
  installed_version=$(
    "$VENV_PATH/bin/python" -c 'import importlib.metadata, pymysql; print(importlib.metadata.version("PyMySQL"))'
  ) || die '既有 venv 无法导入 PyMySQL'
  [[ $installed_version == "$EXPECTED_PYMYSQL_VERSION" ]] ||
    die "既有 venv PyMySQL 版本错误：$installed_version"
  printf '[通过] 既有搜索重建 venv 与固定 wheel 凭据一致：%s\n' "$VENV_PATH"
  exit 0
fi

parent_dir=${VENV_PATH%/*}
[[ -d $parent_dir && ! -L $parent_dir ]] ||
  die "venv 父目录必须已存在且不能是符号链接：$parent_dir"

umask 022
temporary_venv=$(mktemp -d "$parent_dir/.vibelo-venv.tmp.XXXXXXXX") ||
  die '无法创建临时 venv 目录'
rmdir -- "$temporary_venv"
cleanup_temporary_venv() {
  if [[ -n ${temporary_venv:-} && -e $temporary_venv ]]; then
    rm -rf -- "$temporary_venv"
  fi
}
trap cleanup_temporary_venv EXIT

python3 -m venv "$temporary_venv" ||
  die '创建 venv 失败；请先通过系统镜像安装 python3-venv 后重试'

PIP_DISABLE_PIP_VERSION_CHECK=1 \
PIP_NO_INDEX=1 \
  "$temporary_venv/bin/python" -m pip install \
    --no-index \
    --no-deps \
    --require-hashes \
    --find-links "${WHEEL_PATH%/*}" \
    --requirement "$REQUIREMENTS_FILE"

installed_version=$(
  "$temporary_venv/bin/python" -c 'import importlib.metadata, pymysql; print(importlib.metadata.version("PyMySQL"))'
) || die '离线安装后无法导入 PyMySQL'
[[ $installed_version == "$EXPECTED_PYMYSQL_VERSION" ]] ||
  die "离线安装后的 PyMySQL 版本错误：$installed_version"

temporary_attestation="$temporary_venv/.vibelo-search-reindex-wheel.sha256"
printf '%s\n' "$EXPECTED_WHEEL_SHA256" >"$temporary_attestation"
chmod 0644 -- "$temporary_attestation"
mv -T -- "$temporary_venv" "$VENV_PATH" || die '无法原子发布已验收 venv'
temporary_venv=''
trap - EXIT
printf '[通过] PyMySQL %s 已从固定 wheel 离线安装到 %s\n' \
  "$EXPECTED_PYMYSQL_VERSION" "$VENV_PATH"
