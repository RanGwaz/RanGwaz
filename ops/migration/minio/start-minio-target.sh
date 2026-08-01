#!/usr/bin/env bash
set -Eeuo pipefail

# 启动且只启动迁移目标 MinIO。固定门禁定义复用 prepare 脚本。

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=prepare-minio-target.sh
source "$SCRIPT_DIR/prepare-minio-target.sh"

ARTIFACT_DIR=$DEFAULT_ARTIFACT_DIR
COMPOSE_ARGS=()
START_TEMP_DIR=''

start_usage() {
  cat <<EOF
用法：
  sudo bash ops/migration/minio/start-minio-target.sh [--artifact-dir $DEFAULT_ARTIFACT_DIR]

重新核对固定离线文件、已安装 mc、已载入镜像和 Compose 拓扑后，只执行：
  docker compose ... up -d --pull never --no-build --no-deps minio

随后验证健康状态、项目中唯一运行服务、回环端口及卷在 /data/docker 下的落点。
EOF
}

start_cleanup() {
  if [[ -n ${START_TEMP_DIR:-} && -d ${START_TEMP_DIR:-} ]]; then
    case "$START_TEMP_DIR" in
      "${TMPDIR:-/tmp}"/vibelo-minio-start.*)
        rm -rf -- "$START_TEMP_DIR"
        ;;
    esac
  fi
  START_TEMP_DIR=''
}

start_minio_service() {
  docker compose "${COMPOSE_ARGS[@]}" \
    up -d --pull never --no-build --no-deps minio
}

validate_runtime_ports() {
  local ports_json=$1

  python3 - "$ports_json" <<'PY'
import json
import sys


def fail(message: str) -> None:
    print(f"错误：MinIO 运行端口门禁失败：{message}", file=sys.stderr)
    raise SystemExit(1)


try:
    with open(sys.argv[1], "r", encoding="utf-8") as stream:
        ports = json.load(stream)
except (OSError, json.JSONDecodeError) as exc:
    fail(f"无法解析容器端口：{exc}")

expected = {
    "9000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9000"}],
    "9001/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9001"}],
}
if ports != expected:
    fail("9000/9001 必须且只能绑定到主机 127.0.0.1 的同名端口")

print("[通过] 容器运行端口仅绑定 127.0.0.1:9000/9001")
PY
}

validate_runtime_mounts() {
  local mounts_json=$1

  python3 - "$mounts_json" "$EXPECTED_VOLUME_NAME" <<'PY'
import json
import sys


def fail(message: str) -> None:
    print(f"错误：MinIO 运行卷门禁失败：{message}", file=sys.stderr)
    raise SystemExit(1)


try:
    with open(sys.argv[1], "r", encoding="utf-8") as stream:
        mounts = json.load(stream)
except (OSError, json.JSONDecodeError) as exc:
    fail(f"无法解析容器挂载：{exc}")

expected_volume = sys.argv[2]
data_mounts = [mount for mount in mounts if mount.get("Destination") == "/data"]
if len(data_mounts) != 1:
    fail("容器必须且只能有一个 /data 挂载")
mount = data_mounts[0]
if mount.get("Type") != "volume" or mount.get("Name") != expected_volume or not mount.get("RW"):
    fail(f"/data 必须以可写卷 {expected_volume} 挂载")

print(f"[通过] 容器 /data 使用可写卷 {expected_volume}")
PY
}

start_main() {
  while (($# > 0)); do
    case "$1" in
      --artifact-dir)
        (($# >= 2)) || die '--artifact-dir 缺少路径'
        ARTIFACT_DIR=$2
        shift 2
        ;;
      -h | --help)
        start_usage
        return 0
        ;;
      *)
        die "未知参数：$1"
        ;;
    esac
  done

  [[ $(id -u) -eq 0 ]] || die '请以 root 运行（需要访问 Docker）'
  for command_name in awk bash chmod curl docker id mktemp python3 readlink rm sha256sum sleep ss stat; do
    require_command "$command_name"
  done
  docker info >/dev/null 2>&1 || die 'Docker Engine 未就绪'
  docker compose version >/dev/null 2>&1 || die 'Docker Compose 插件不可用'

  [[ -d $ARTIFACT_DIR && ! -L $ARTIFACT_DIR ]] ||
    die "离线文件目录不存在或是符号链接：$ARTIFACT_DIR"
  ARTIFACT_DIR=$(readlink -f -- "$ARTIFACT_DIR")
  require_root_owned_nonwritable_path "$ARTIFACT_DIR" '离线文件目录'
  local minio_archive="$ARTIFACT_DIR/$MINIO_ARCHIVE_NAME"
  local mc_binary="$ARTIFACT_DIR/$MC_BINARY_NAME"

  note '=== 启动 Vibelo 迁移目标 MinIO ==='
  require_regular_artifact \
    "$minio_archive" "$MINIO_ARCHIVE_SIZE" "$MINIO_ARCHIVE_SHA256" 'MinIO 镜像归档'
  require_regular_artifact \
    "$mc_binary" "$MC_BINARY_SIZE" "$MC_BINARY_SHA256" 'mc 客户端'

  [[ -f $MC_INSTALL_PATH && ! -L $MC_INSTALL_PATH ]] ||
    die "固定 mc 尚未安全安装：$MC_INSTALL_PATH"
  local installed_mc_sha installed_mc_version
  installed_mc_sha=$(sha256sum -- "$MC_INSTALL_PATH") || die '无法校验已安装 mc'
  installed_mc_sha=${installed_mc_sha%% *}
  [[ ${installed_mc_sha,,} == "$MC_BINARY_SHA256" ]] ||
    die '已安装 mc 的 SHA256 不是固定值；请重新运行 prepare-minio-target.sh'
  installed_mc_version=$($MC_INSTALL_PATH --version 2>&1) || die '已安装 mc 无法运行'
  [[ $installed_mc_version == *"$MC_RELEASE"* && $installed_mc_version == *'linux/amd64'* ]] ||
    die "已安装 mc 版本或平台不符：$installed_mc_version"
  note "[通过] 已安装固定 mc：$MC_RELEASE（linux/amd64）"

  local image_platform image_label
  image_platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$MINIO_IMAGE" 2>/dev/null) ||
    die "尚未载入固定镜像 $MINIO_IMAGE；请先运行 prepare-minio-target.sh"
  [[ $image_platform == 'linux/amd64' ]] || die "MinIO 镜像平台错误：$image_platform"
  image_label=$(docker image inspect --format '{{index .Config.Labels "version"}}' "$MINIO_IMAGE") ||
    die '无法读取 MinIO 镜像版本标签'
  [[ $image_label == "$MINIO_RELEASE" ]] || die "MinIO 镜像版本标签错误：$image_label"
  note "[通过] 已载入固定 MinIO 镜像：$MINIO_RELEASE（linux/amd64）"

  [[ -f $PREFLIGHT_SCRIPT ]] || die "缺少公网预检脚本：$PREFLIGHT_SCRIPT"
  note '=== 再次执行公网只读预检 ==='
  bash "$PREFLIGHT_SCRIPT"

  local docker_root
  docker_root=$(docker info --format '{{.DockerRootDir}}') || die '无法读取 DockerRoot'
  [[ $docker_root == "$EXPECTED_DOCKER_ROOT" ]] ||
    die "DockerRoot 必须为 $EXPECTED_DOCKER_ROOT，当前为 $docker_root"

  [[ -f $ENV_FILE && ! -L $ENV_FILE ]] || die "缺少安全的环境文件：$ENV_FILE"
  [[ -f $COMPOSE_FILE && ! -L $COMPOSE_FILE ]] || die "缺少安全的 Compose 文件：$COMPOSE_FILE"
  umask 077
  START_TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/vibelo-minio-start.XXXXXXXX") ||
    die '无法创建私有临时目录'
  chmod 700 "$START_TEMP_DIR"
  trap start_cleanup EXIT
  local compose_json="$START_TEMP_DIR/compose.json"
  docker compose \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" \
    config --format json \
    >"$compose_json" || die 'Compose 配置无法展开'
  chmod 600 "$compose_json"
  validate_compose_config "$compose_json"
  COMPOSE_ARGS=(--env-file "$ENV_FILE" -f "$COMPOSE_FILE")

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
  if docker volume inspect "$EXPECTED_VOLUME_NAME" >/dev/null 2>&1; then
    die "已存在目标卷 $EXPECTED_VOLUME_NAME；拒绝覆盖未知数据"
  fi
  check_port_free 9000
  check_port_free 9001
  check_port_free 19090

  note '只启动 MinIO；明确禁止拉取、构建和启动依赖服务。'
  start_minio_service

  local container_id health_status deadline
  container_id=$(docker compose "${COMPOSE_ARGS[@]}" ps -q minio) ||
    die '无法取得 MinIO 容器 ID'
  [[ -n $container_id && $container_id != *$'\n'* ]] ||
    die 'MinIO 容器数量不是 1'

  deadline=$((SECONDS + 180))
  while :; do
    health_status=$(docker container inspect \
      --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
      "$container_id") || die '无法读取 MinIO 健康状态'
    case "$health_status" in
      healthy)
        break
        ;;
      unhealthy)
        die 'MinIO 健康检查已进入 unhealthy；请先查看容器日志，不要迁移数据'
        ;;
    esac
    ((SECONDS < deadline)) ||
      die "等待 MinIO 健康超时，最后状态为 $health_status"
    sleep 2
  done
  curl --fail --silent --show-error --max-time 5 \
    'http://127.0.0.1:9000/minio/health/ready' \
    >/dev/null || die 'MinIO 回环健康接口不可用'
  note '[通过] MinIO 容器和回环健康接口均为 healthy'

  local running_services project_running_ids
  running_services=$(docker compose "${COMPOSE_ARGS[@]}" ps \
    --status running --services | awk 'NF { print }') ||
    die '无法列出 Compose 运行服务'
  [[ $running_services == 'minio' ]] ||
    die "该 Compose 项目运行了 MinIO 之外的服务：${running_services:-无}"
  project_running_ids=$(docker ps -q \
    --filter "label=com.docker.compose.project=$EXPECTED_COMPOSE_PROJECT") ||
    die '无法检查项目运行容器'
  [[ $project_running_ids == "$container_id" ]] ||
    die '该 Compose 项目运行容器数量不为 1，或唯一容器不是 MinIO'
  note '[通过] 该 Compose 项目唯一运行服务为 minio'

  local ports_json="$START_TEMP_DIR/ports.json"
  local mounts_json="$START_TEMP_DIR/mounts.json"
  docker container inspect --format '{{json .NetworkSettings.Ports}}' "$container_id" \
    >"$ports_json" || die '无法读取 MinIO 运行端口'
  docker container inspect --format '{{json .Mounts}}' "$container_id" \
    >"$mounts_json" || die '无法读取 MinIO 运行挂载'
  chmod 600 "$ports_json" "$mounts_json"
  validate_runtime_ports "$ports_json"
  validate_runtime_mounts "$mounts_json"

  local volume_mountpoint volume_project_label volume_logical_label expected_mountpoint
  volume_mountpoint=$(docker volume inspect \
    --format '{{.Mountpoint}}' "$EXPECTED_VOLUME_NAME") ||
    die "无法读取目标卷：$EXPECTED_VOLUME_NAME"
  volume_project_label=$(docker volume inspect \
    --format '{{index .Labels "com.docker.compose.project"}}' "$EXPECTED_VOLUME_NAME") ||
    die '无法读取目标卷项目标签'
  volume_logical_label=$(docker volume inspect \
    --format '{{index .Labels "com.docker.compose.volume"}}' "$EXPECTED_VOLUME_NAME") ||
    die '无法读取目标卷逻辑名标签'
  [[ $volume_project_label == "$EXPECTED_COMPOSE_PROJECT" ]] ||
    die "目标卷项目标签错误：$volume_project_label"
  [[ $volume_logical_label == 'public-minio-data' ]] ||
    die "目标卷逻辑名标签错误：$volume_logical_label"
  expected_mountpoint="$EXPECTED_DOCKER_ROOT/volumes/$EXPECTED_VOLUME_NAME/_data"
  [[ $volume_mountpoint == "$expected_mountpoint" ]] ||
    die "目标卷未落在预期数据盘路径：期望 $expected_mountpoint，实际 $volume_mountpoint"
  note "[通过] 目标卷实际落点：$volume_mountpoint"

  note '=== 迁移目标 MinIO 已安全启动 ==='
  note '只运行了 minio；没有拉取、构建或启动其他服务。'
  note '9000/9001 仅回环可达，安全组不要开放 9000、9001、19090。'
  note '现在可以建立反向隧道并运行 minio-migrate.sh。'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  start_main "$@"
fi
