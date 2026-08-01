#!/usr/bin/env bash
set -Eeuo pipefail

# 只准备固定版本的 MinIO 离线镜像和 mc 客户端；不会构建、拉取或启动服务。

if [[ $- == *x* ]]; then
  set +x
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../../.." && pwd -P)
ENV_FILE="$REPO_ROOT/.env.public"
COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.public.yml"
PREFLIGHT_SCRIPT="$REPO_ROOT/ops/public/preflight.sh"

DEFAULT_ARTIFACT_DIR='/data/migration/minio'
ARTIFACT_DIR=$DEFAULT_ARTIFACT_DIR

MINIO_IMAGE='minio/minio:RELEASE.2025-04-22T22-12-26Z'
MINIO_RELEASE='RELEASE.2025-04-22T22-12-26Z'
MINIO_ARCHIVE_NAME='minio-RELEASE.2025-04-22T22-12-26Z-linux-amd64.tar'
MINIO_ARCHIVE_SIZE=64023552
MINIO_ARCHIVE_SHA256='c220e4e0ef61abe83a084fdc4942af30c9f00e539fabc63b619ef73f01429d0f'
MINIO_MANIFEST_DIGEST='sha256:3f97c5651cb6662b880c787a232b6b34fec8d8922e08d6617b25d241a21164bb'
MINIO_CONFIG_DIGEST='sha256:9d668e47f1fc60ea49af4203deee87a657eb1aa0e2761fee2c7c2d1df282c880'

MC_RELEASE='RELEASE.2025-08-13T08-35-41Z'
MC_BINARY_NAME='mc-RELEASE.2025-08-13T08-35-41Z-linux-amd64'
MC_BINARY_SIZE=30535864
MC_BINARY_SHA256='01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891'
MC_INSTALL_PATH='/usr/local/bin/mc'

EXPECTED_DOCKER_ROOT='/data/docker'
EXPECTED_COMPOSE_PROJECT='vibelo-public'
EXPECTED_CONTAINER_NAME='vibelo-public-minio-1'
EXPECTED_VOLUME_NAME='vibelo-public_public-minio-data'
MIN_DATA_FREE_BYTES=$((101 * 1024 * 1024 * 1024))
MIN_DATA_FREE_INODES=2000000
MIN_MINIO_MEMORY_BYTES=$((1024 * 1024 * 1024))
MIN_MINIO_RESERVATION_BYTES=$((512 * 1024 * 1024))
PREPARE_TEMP_DIR=''

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

note() {
  printf '%s\n' "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "缺少命令：$1"
}

require_root_owned_nonwritable_path() {
  local path=$1
  local label=$2
  local owner mode

  owner=$(stat -c '%u' -- "$path") || die "无法读取 $label 所有者"
  [[ $owner == '0' ]] || die "$label 必须属于 root，当前 UID 为 $owner：$path"
  mode=$(stat -c '%a' -- "$path") || die "无法读取 $label 权限"
  [[ $mode =~ ^[0-7]{3,4}$ ]] || die "$label 权限格式无效：$mode"
  (((8#$mode & 0022) == 0)) ||
    die "$label 不能允许 group/other 写入，当前权限为 $mode：$path"
}

prepare_cleanup() {
  if [[ -n ${PREPARE_TEMP_DIR:-} && -d ${PREPARE_TEMP_DIR:-} ]]; then
    case "$PREPARE_TEMP_DIR" in
      "${TMPDIR:-/tmp}"/vibelo-minio-prepare.*)
        rm -rf -- "$PREPARE_TEMP_DIR"
        ;;
    esac
  fi
  PREPARE_TEMP_DIR=''
}

usage() {
  cat <<EOF
用法：
  sudo bash ops/migration/minio/prepare-minio-target.sh [--artifact-dir $DEFAULT_ARTIFACT_DIR]

严格校验固定的 MinIO OCI 离线镜像和 mc 二进制，执行公网预检，确认目标卷、
端口、磁盘与 Compose 拓扑为空，再安装 mc 并执行 docker load。

本脚本不会 docker pull、docker build、docker compose up，也不会启动持久服务。
EOF
}

require_regular_artifact() {
  local path=$1
  local expected_size=$2
  local expected_sha=$3
  local label=$4
  local actual_size actual_sha

  [[ -f $path && ! -L $path ]] || die "$label 必须是普通文件且不能是符号链接：$path"
  require_root_owned_nonwritable_path "$path" "$label"
  actual_size=$(stat -c '%s' -- "$path") || die "无法读取 $label 文件尺寸"
  [[ $actual_size == "$expected_size" ]] ||
    die "$label 文件尺寸错误：期望 $expected_size，实际 $actual_size"
  actual_sha=$(sha256sum -- "$path") || die "无法计算 $label SHA256"
  actual_sha=${actual_sha%% *}
  actual_sha=${actual_sha,,}
  [[ $actual_sha == "$expected_sha" ]] ||
    die "$label SHA256 错误：期望 $expected_sha，实际 $actual_sha"

  note "[通过] $label 固定尺寸与 SHA256 校验通过"
}

validate_oci_archive() {
  local archive=$1
  local expected_manifest=$2
  local expected_config=$3
  local expected_release=$4

  python3 - "$archive" "$expected_manifest" "$expected_config" "$expected_release" <<'PY'
import hashlib
import json
import sys
import tarfile


def fail(message: str) -> None:
    print(f"错误：MinIO OCI 离线镜像校验失败：{message}", file=sys.stderr)
    raise SystemExit(1)


archive, expected_manifest, expected_config, expected_release = sys.argv[1:]

try:
    with tarfile.open(archive, mode="r:*") as bundle:
        members = bundle.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            fail("归档包含重复成员名")

        by_name = {member.name: member for member in members}

        def read_regular(name: str) -> bytes:
            member = by_name.get(name)
            if member is None or not member.isfile():
                fail(f"缺少普通文件 {name}")
            stream = bundle.extractfile(member)
            if stream is None:
                fail(f"无法读取 {name}")
            return stream.read()

        try:
            index_bytes = read_regular("index.json")
            index = json.loads(index_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            fail(f"index.json 无效：{exc}")

        if index.get("schemaVersion") != 2:
            fail("index.json schemaVersion 不是 2")
        descriptors = index.get("manifests")
        if not isinstance(descriptors, list) or len(descriptors) != 1:
            fail("归档必须只包含一个平台 manifest")
        descriptor = descriptors[0]
        platform = descriptor.get("platform") or {}
        if platform.get("os") != "linux" or platform.get("architecture") != "amd64":
            fail("manifest 平台不是 linux/amd64")
        if descriptor.get("digest") != expected_manifest:
            fail(f"manifest digest 不是固定值 {expected_manifest}")

        manifest_name = "blobs/sha256/" + expected_manifest.removeprefix("sha256:")
        manifest_bytes = read_regular(manifest_name)
        if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest.removeprefix("sha256:"):
            fail("manifest 内容摘要不一致")
        if descriptor.get("size") != len(manifest_bytes):
            fail("manifest 描述尺寸与实际尺寸不一致")
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            fail(f"manifest JSON 无效：{exc}")

        config_descriptor = manifest.get("config") or {}
        if config_descriptor.get("digest") != expected_config:
            fail(f"config digest 不是固定值 {expected_config}")
        config_name = "blobs/sha256/" + expected_config.removeprefix("sha256:")
        config_bytes = read_regular(config_name)
        if hashlib.sha256(config_bytes).hexdigest() != expected_config.removeprefix("sha256:"):
            fail("config 内容摘要不一致")
        if config_descriptor.get("size") != len(config_bytes):
            fail("config 描述尺寸与实际尺寸不一致")
        try:
            config = json.loads(config_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            fail(f"config JSON 无效：{exc}")

        if config.get("os") != "linux" or config.get("architecture") != "amd64":
            fail("config 平台不是 linux/amd64")
        labels = ((config.get("config") or {}).get("Labels") or {})
        if labels.get("version") != expected_release or labels.get("release") != expected_release:
            fail("config 中 MinIO version/release 标签不符合固定版本")

        layers = manifest.get("layers")
        if not isinstance(layers, list) or not layers:
            fail("manifest 没有镜像层")
        for position, layer in enumerate(layers, start=1):
            digest = layer.get("digest", "")
            if not isinstance(digest, str) or not digest.startswith("sha256:"):
                fail(f"第 {position} 层没有有效 SHA256 digest")
            layer_bytes = read_regular("blobs/sha256/" + digest.removeprefix("sha256:"))
            if hashlib.sha256(layer_bytes).hexdigest() != digest.removeprefix("sha256:"):
                fail(f"第 {position} 层内容摘要不一致")
            if layer.get("size") != len(layer_bytes):
                fail(f"第 {position} 层描述尺寸与实际尺寸不一致")
except (tarfile.TarError, OSError) as exc:
    fail(f"无法读取归档：{exc}")

print("[通过] OCI 索引、linux/amd64 manifest、config 和全部镜像层校验通过")
PY
}

validate_compose_config() {
  local config_json=$1

  python3 - "$config_json" \
    "$EXPECTED_COMPOSE_PROJECT" \
    "$MINIO_IMAGE" \
    "$EXPECTED_VOLUME_NAME" \
    "$MIN_MINIO_MEMORY_BYTES" \
    "$MIN_MINIO_RESERVATION_BYTES" <<'PY'
import json
import sys


def fail(message: str) -> None:
    print(f"错误：MinIO Compose 门禁失败：{message}", file=sys.stderr)
    raise SystemExit(1)


path, expected_project, expected_image, expected_volume, min_memory, min_reservation = sys.argv[1:]
try:
    with open(path, "r", encoding="utf-8") as stream:
        config = json.load(stream)
except (OSError, json.JSONDecodeError) as exc:
    fail(f"无法解析 Compose JSON：{exc}")

if config.get("name") != expected_project:
    fail(f"项目名必须为 {expected_project}")
service = (config.get("services") or {}).get("minio")
if not isinstance(service, dict):
    fail("缺少 minio 服务")
if service.get("image") != expected_image:
    fail(f"镜像必须固定为 {expected_image}")
if int(service.get("mem_limit", 0)) < int(min_memory):
    fail("mem_limit 必须至少为 1 GiB")
if int(service.get("mem_reservation", 0)) < int(min_reservation):
    fail("mem_reservation 必须至少为 512 MiB")

expected_ports = {
    ("127.0.0.1", 9000, "9000", "tcp"),
    ("127.0.0.1", 9001, "9001", "tcp"),
}
actual_ports = {
    (
        item.get("host_ip"),
        int(item.get("target", 0)),
        str(item.get("published", "")),
        item.get("protocol", "tcp"),
    )
    for item in service.get("ports", [])
}
if actual_ports != expected_ports:
    fail("9000/9001 必须且只能按原端口绑定 127.0.0.1")

data_mounts = [item for item in service.get("volumes", []) if item.get("target") == "/data"]
if len(data_mounts) != 1:
    fail("MinIO 必须且只能有一个 /data 挂载")
data_mount = data_mounts[0]
if data_mount.get("type") != "volume" or data_mount.get("source") != "public-minio-data":
    fail("/data 必须使用逻辑卷 public-minio-data")
volume = (config.get("volumes") or {}).get("public-minio-data")
if not isinstance(volume, dict) or volume.get("name") != expected_volume:
    fail(f"实际卷名必须为 {expected_volume}")

print("[通过] Compose 项目、固定镜像、内存、回环端口和卷名门禁通过")
PY
}

check_port_free() {
  local port=$1
  local listeners

  listeners=$(ss -H -ltn "sport = :$port" 2>/dev/null) ||
    die "无法检查 TCP $port 端口"
  [[ -z $listeners ]] || die "TCP $port 已被占用：$listeners"
  note "[通过] TCP $port 端口空闲"
}

read_data_free_bytes() {
  local path=$1

  df -B1 --output=avail -- "$path" |
    awk 'NR == 2 { print $1 }'
}

read_data_free_inodes() {
  local path=$1

  df --output=iavail -- "$path" |
    awk 'NR == 2 { print $1 }'
}

load_and_verify_minio_image() {
  local archive=$1
  local image_platform image_label version_output

  note '开始载入固定 MinIO 离线镜像；不会访问镜像仓库。'
  docker load --input "$archive"

  image_platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$MINIO_IMAGE") ||
    die "docker load 后找不到镜像：$MINIO_IMAGE"
  [[ $image_platform == 'linux/amd64' ]] ||
    die "载入镜像平台错误：$image_platform"
  image_label=$(docker image inspect --format '{{index .Config.Labels "version"}}' "$MINIO_IMAGE") ||
    die '无法读取 MinIO 镜像版本标签'
  [[ $image_label == "$MINIO_RELEASE" ]] ||
    die "MinIO 镜像版本标签错误：$image_label"

  version_output=$(docker run \
    --pull never \
    --rm \
    --network none \
    --entrypoint minio \
    "$MINIO_IMAGE" \
    --version 2>&1) || die '固定 MinIO 镜像的只读版本探针失败'
  [[ $version_output == *"$MINIO_RELEASE"* && $version_output == *'linux/amd64'* ]] ||
    die "MinIO 运行时版本或平台不符：$version_output"
  note "[通过] MinIO 镜像运行时版本为 $MINIO_RELEASE（linux/amd64）"
}

main() {
  while (($# > 0)); do
    case "$1" in
      --artifact-dir)
        (($# >= 2)) || die '--artifact-dir 缺少路径'
        ARTIFACT_DIR=$2
        shift 2
        ;;
      -h | --help)
        usage
        return 0
        ;;
      *)
        die "未知参数：$1"
        ;;
    esac
  done

  [[ $(id -u) -eq 0 ]] || die '请以 root 运行（需要安全安装 /usr/local/bin/mc 和访问 Docker）'
  for command_name in \
    awk bash chmod df docker findmnt id install mktemp python3 readlink rm sha256sum ss stat uname; do
    require_command "$command_name"
  done
  docker info >/dev/null 2>&1 || die 'Docker Engine 未就绪'
  docker compose version >/dev/null 2>&1 || die 'Docker Compose 插件不可用'
  [[ $(uname -m) == 'x86_64' ]] || die "主机架构必须为 x86_64，当前为 $(uname -m)"

  [[ -d $ARTIFACT_DIR && ! -L $ARTIFACT_DIR ]] ||
    die "离线文件目录不存在或是符号链接：$ARTIFACT_DIR"
  ARTIFACT_DIR=$(readlink -f -- "$ARTIFACT_DIR")
  require_root_owned_nonwritable_path "$ARTIFACT_DIR" '离线文件目录'
  MINIO_ARCHIVE="$ARTIFACT_DIR/$MINIO_ARCHIVE_NAME"
  MC_BINARY="$ARTIFACT_DIR/$MC_BINARY_NAME"

  note '=== Vibelo MinIO 离线目标准备 ==='
  require_regular_artifact \
    "$MINIO_ARCHIVE" "$MINIO_ARCHIVE_SIZE" "$MINIO_ARCHIVE_SHA256" 'MinIO 镜像归档'
  require_regular_artifact \
    "$MC_BINARY" "$MC_BINARY_SIZE" "$MC_BINARY_SHA256" 'mc 客户端'
  validate_oci_archive \
    "$MINIO_ARCHIVE" "$MINIO_MANIFEST_DIGEST" "$MINIO_CONFIG_DIGEST" "$MINIO_RELEASE"

  [[ -f $PREFLIGHT_SCRIPT ]] || die "缺少公网预检脚本：$PREFLIGHT_SCRIPT"
  note '=== 执行现有公网只读预检 ==='
  bash "$PREFLIGHT_SCRIPT"

  local docker_root data_target data_options data_free_bytes data_free_inodes
  docker_root=$(docker info --format '{{.DockerRootDir}}') || die '无法读取 DockerRoot'
  [[ $docker_root == "$EXPECTED_DOCKER_ROOT" ]] ||
    die "DockerRoot 必须为 $EXPECTED_DOCKER_ROOT，当前为 $docker_root"
  note "[通过] DockerRoot=$docker_root"

  data_target=$(findmnt -rn -o TARGET --target /data) || die '无法读取 /data 挂载点'
  [[ $data_target == '/data' ]] || die "/data 不是独立挂载点（当前落在 $data_target）"
  data_options=$(findmnt -rn -o OPTIONS --target /data) || die '无法读取 /data 挂载参数'
  [[ ,$data_options, != *,ro,* ]] || die '/data 是只读挂载'
  data_free_bytes=$(read_data_free_bytes /data)
  data_free_inodes=$(read_data_free_inodes /data)
  [[ $data_free_bytes =~ ^[0-9]+$ ]] || die '无法读取 /data 可用字节数'
  [[ $data_free_inodes =~ ^[0-9]+$ ]] || die '无法读取 /data 可用 inode 数'
  ((data_free_bytes >= MIN_DATA_FREE_BYTES)) ||
    die "/data 可用空间不足 101 GiB（当前 $data_free_bytes 字节）"
  ((data_free_inodes >= MIN_DATA_FREE_INODES)) ||
    die "/data 可用 inode 不足 2,000,000（当前 $data_free_inodes）"
  note "[通过] /data 可用空间不少于 101 GiB，可用 inode 不少于 2,000,000"

  [[ -f $ENV_FILE && ! -L $ENV_FILE ]] || die "缺少安全的环境文件：$ENV_FILE"
  [[ -f $COMPOSE_FILE && ! -L $COMPOSE_FILE ]] || die "缺少安全的 Compose 文件：$COMPOSE_FILE"
  local compose_json
  umask 077
  PREPARE_TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/vibelo-minio-prepare.XXXXXXXX") ||
    die '无法创建私有临时目录'
  chmod 700 "$PREPARE_TEMP_DIR"
  trap prepare_cleanup EXIT
  compose_json="$PREPARE_TEMP_DIR/compose.json"
  docker compose \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" \
    config --format json \
    >"$compose_json" || die 'Compose 配置无法展开'
  chmod 600 "$compose_json"
  validate_compose_config "$compose_json"

  local existing_container_ids
  existing_container_ids=$(docker ps -aq \
    --filter "label=com.docker.compose.project=$EXPECTED_COMPOSE_PROJECT" \
    --filter 'label=com.docker.compose.service=minio') ||
    die '无法检查既有 MinIO 容器'
  [[ -z $existing_container_ids ]] ||
    die "已存在该 Compose 项目的 MinIO 容器：$existing_container_ids"
  if docker container inspect "$EXPECTED_CONTAINER_NAME" >/dev/null 2>&1; then
    die "已存在目标容器名：$EXPECTED_CONTAINER_NAME"
  fi
  note '[通过] 不存在既有目标 MinIO 容器'

  if docker volume inspect "$EXPECTED_VOLUME_NAME" >/dev/null 2>&1; then
    die "已存在目标卷 $EXPECTED_VOLUME_NAME；为避免覆盖未知数据，脚本拒绝继续"
  fi
  note "[通过] 目标卷 $EXPECTED_VOLUME_NAME 尚不存在"
  check_port_free 9000
  check_port_free 9001
  check_port_free 19090

  if [[ -e $MC_INSTALL_PATH || -L $MC_INSTALL_PATH ]]; then
    [[ -f $MC_INSTALL_PATH && ! -L $MC_INSTALL_PATH ]] ||
      die "$MC_INSTALL_PATH 已存在但不是普通文件"
    local installed_mc_sha
    installed_mc_sha=$(sha256sum -- "$MC_INSTALL_PATH") || die '无法校验现有 mc'
    installed_mc_sha=${installed_mc_sha%% *}
    [[ ${installed_mc_sha,,} == "$MC_BINARY_SHA256" ]] ||
      die "$MC_INSTALL_PATH 已存在且不是本次固定版本；拒绝覆盖"
    note "[通过] $MC_INSTALL_PATH 已是固定 mc，无需覆盖"
  else
    install -o root -g root -m 0755 -- "$MC_BINARY" "$MC_INSTALL_PATH"
    note "[通过] 固定 mc 已安装到 $MC_INSTALL_PATH"
  fi
  local installed_mc_version
  installed_mc_version=$($MC_INSTALL_PATH --version 2>&1) || die '安装后的 mc 无法运行'
  [[ $installed_mc_version == *"$MC_RELEASE"* && $installed_mc_version == *'linux/amd64'* ]] ||
    die "安装后的 mc 版本或平台不符：$installed_mc_version"

  load_and_verify_minio_image "$MINIO_ARCHIVE"

  note '=== MinIO 离线目标准备完成 ==='
  note '固定 mc 与 MinIO 镜像已经就绪；没有构建、拉取或启动持久服务。'
  note '下一步单独运行 start-minio-target.sh 启动且只启动目标 MinIO。'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi
