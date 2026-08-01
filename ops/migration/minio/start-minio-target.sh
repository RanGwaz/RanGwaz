#!/usr/bin/env bash
set -Eeuo pipefail

# 启动且只启动迁移目标 MinIO。固定门禁定义复用 prepare 脚本。

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=prepare-minio-target.sh
source "$SCRIPT_DIR/prepare-minio-target.sh"

ARTIFACT_DIR=$DEFAULT_ARTIFACT_DIR
COMPOSE_ARGS=()
START_TEMP_DIR=''
VERIFY_EXISTING=false

start_usage() {
  cat <<EOF
用法：
  sudo bash ops/migration/minio/start-minio-target.sh [--artifact-dir $DEFAULT_ARTIFACT_DIR]
  sudo bash ops/migration/minio/start-minio-target.sh --verify-existing [--artifact-dir $DEFAULT_ARTIFACT_DIR]

重新核对固定离线文件、已安装 mc、已载入镜像和 Compose 拓扑后，只执行：
  docker compose ... up -d --pull never --no-build --no-deps minio

随后验证健康状态、项目中唯一运行服务、回环端口及卷在 /data/docker 下的落点。

--verify-existing 仅对首次启动已留下的既有容器执行同等严格的只读验收；
不执行启动、重启、重建或删除。
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
if len(mounts) != 1 or len(data_mounts) != 1:
    fail("容器必须且只能有一个挂载，且目标必须为 /data")
mount = data_mounts[0]
if mount.get("Type") != "volume" or mount.get("Name") != expected_volume or not mount.get("RW"):
    fail(f"/data 必须以可写卷 {expected_volume} 挂载")

print(f"[通过] 容器 /data 使用可写卷 {expected_volume}")
PY
}

parse_compose_service_hash() {
  awk '
    NF == 2 && $1 == "minio" { print $2; found += 1; next }
    NF == 1 { print $1; found += 1; next }
    { invalid = 1 }
    END { if (invalid || found != 1) exit 1 }
  '
}

validate_runtime_identity() {
  local inspect_json=$1
  local expected_config_hash=$2
  local expected_image_id=$3

  python3 - "$inspect_json" \
    "$EXPECTED_CONTAINER_NAME" \
    "$EXPECTED_COMPOSE_PROJECT" \
    "$MINIO_IMAGE" \
    "$expected_image_id" \
    "$expected_config_hash" \
    "$MIN_MINIO_MEMORY_BYTES" \
    "$MIN_MINIO_RESERVATION_BYTES" <<'PY'
import json
import sys


def fail(message: str) -> None:
    print(f"错误：MinIO 运行容器门禁失败：{message}", file=sys.stderr)
    raise SystemExit(1)


(
    inspect_path,
    expected_name,
    expected_project,
    expected_image,
    expected_image_id,
    expected_config_hash,
    expected_memory,
    expected_reservation,
) = sys.argv[1:]

try:
    with open(inspect_path, "r", encoding="utf-8") as stream:
        values = json.load(stream)
except (OSError, json.JSONDecodeError) as exc:
    fail(f"无法解析容器状态：{exc}")

if not isinstance(values, list) or len(values) != 1:
    fail("容器 inspect 结果数量不是 1")
value = values[0]
labels = value.get("Config", {}).get("Labels") or {}
state = value.get("State") or {}
host_config = value.get("HostConfig") or {}

if value.get("Name") != f"/{expected_name}":
    fail("容器名称不符")
if labels.get("com.docker.compose.project") != expected_project:
    fail("Compose 项目标签不符")
if labels.get("com.docker.compose.service") != "minio":
    fail("Compose 服务标签不符")
if labels.get("com.docker.compose.container-number") != "1":
    fail("Compose 容器序号不是 1")
if labels.get("com.docker.compose.oneoff") not in (None, "False", "false"):
    fail("容器被标记为 Compose one-off")
if labels.get("com.docker.compose.config-hash") != expected_config_hash:
    fail("容器与当前 Compose/.env.public 配置哈希不一致")
if value.get("Config", {}).get("Image") != expected_image:
    fail("容器镜像标签不是固定值")
if value.get("Image") != expected_image_id:
    fail("容器实际镜像 ID 不是固定值")

if state.get("Status") != "running" or state.get("Running") is not True:
    fail("容器不在 running 状态")
if state.get("Restarting") is True or state.get("Dead") is True:
    fail("容器处于 restarting/dead 状态")
if state.get("OOMKilled") is True:
    fail("容器曾被 OOM 终止")
if state.get("Error") not in (None, ""):
    fail("容器运行状态包含错误")
if (state.get("Health") or {}).get("Status") != "healthy":
    fail("容器健康状态不是 healthy")

restart_name = (host_config.get("RestartPolicy") or {}).get("Name")
if restart_name != "unless-stopped":
    fail("容器重启策略不是 unless-stopped")
if int(host_config.get("Memory") or 0) != int(expected_memory):
    fail("容器内存上限不是 1 GiB")
if int(host_config.get("MemoryReservation") or 0) != int(expected_reservation):
    fail("容器内存保留不是 512 MiB")
if int(host_config.get("PidsLimit") or 0) != 256:
    fail("容器 PID 上限不是 256")

print("[通过] 容器身份、配置哈希、固定镜像、状态和资源门禁通过")
PY
}

validate_runtime_volume() {
  local inspect_json=$1
  local expected_mountpoint="$EXPECTED_DOCKER_ROOT/volumes/$EXPECTED_VOLUME_NAME/_data"

  python3 - "$inspect_json" \
    "$EXPECTED_VOLUME_NAME" \
    "$EXPECTED_COMPOSE_PROJECT" \
    "$expected_mountpoint" <<'PY'
import json
import sys


def fail(message: str) -> None:
    print(f"错误：MinIO 运行卷门禁失败：{message}", file=sys.stderr)
    raise SystemExit(1)


inspect_path, expected_name, expected_project, expected_mountpoint = sys.argv[1:]
try:
    with open(inspect_path, "r", encoding="utf-8") as stream:
        values = json.load(stream)
except (OSError, json.JSONDecodeError) as exc:
    fail(f"无法解析卷状态：{exc}")

if not isinstance(values, list) or len(values) != 1:
    fail("卷 inspect 结果数量不是 1")
value = values[0]
labels = value.get("Labels") or {}
if value.get("Name") != expected_name:
    fail("卷名称不符")
if value.get("Driver") != "local" or value.get("Scope") != "local":
    fail("卷必须是 local driver/local scope")
if value.get("Options") not in (None, {}):
    fail("卷不得带有 local-driver bind 或其他自定义 Options")
if labels.get("com.docker.compose.project") != expected_project:
    fail("卷项目标签不符")
if labels.get("com.docker.compose.volume") != "public-minio-data":
    fail("卷逻辑名标签不符")
if value.get("Mountpoint") != expected_mountpoint:
    fail(f"卷未落在预期数据盘路径 {expected_mountpoint}")

print(f"[通过] 目标卷身份和实际落点通过：{expected_mountpoint}")
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
      --verify-existing)
        VERIFY_EXISTING=true
        shift
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

  local image_platform image_label expected_image_id
  image_platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$MINIO_IMAGE" 2>/dev/null) ||
    die "尚未载入固定镜像 $MINIO_IMAGE；请先运行 prepare-minio-target.sh"
  [[ $image_platform == 'linux/amd64' ]] || die "MinIO 镜像平台错误：$image_platform"
  image_label=$(docker image inspect --format '{{index .Config.Labels "version"}}' "$MINIO_IMAGE") ||
    die '无法读取 MinIO 镜像版本标签'
  [[ $image_label == "$MINIO_RELEASE" ]] || die "MinIO 镜像版本标签错误：$image_label"
  expected_image_id=$(docker image inspect --format '{{.Id}}' "$MINIO_IMAGE") ||
    die '无法读取 MinIO 镜像 ID'
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

  local expected_config_hash
  expected_config_hash=$(docker compose "${COMPOSE_ARGS[@]}" \
    config --hash minio | parse_compose_service_hash) ||
    die '无法读取当前 MinIO Compose 配置哈希'
  [[ $expected_config_hash =~ ^[0-9a-f]{64}$ ]] ||
    die 'MinIO Compose 配置哈希格式异常'

  local existing_container_ids container_id named_container_id
  existing_container_ids=$(docker ps -aq --no-trunc \
    --filter "label=com.docker.compose.project=$EXPECTED_COMPOSE_PROJECT" \
    --filter 'label=com.docker.compose.service=minio') ||
    die '无法检查既有 MinIO 容器'

  if [[ $VERIFY_EXISTING == true ]]; then
    [[ -n $existing_container_ids && $existing_container_ids != *$'\n'* ]] ||
      die '--verify-existing 要求该 Compose 项目恰好存在一个 MinIO 容器'
    named_container_id=$(docker container inspect \
      --format '{{.Id}}' "$EXPECTED_CONTAINER_NAME" 2>/dev/null) ||
      die "既有 MinIO 容器名称不是 $EXPECTED_CONTAINER_NAME"
    [[ $named_container_id == "$existing_container_ids" ]] ||
      die '既有 MinIO 容器的名称与 Compose 标签不属于同一容器'
    container_id=$existing_container_ids
    note '开始只读验收既有 MinIO；不会启动、重启、重建或删除。'
  else
    [[ -z $existing_container_ids ]] ||
      die "已存在该 Compose 项目的 MinIO 容器：$existing_container_ids；如需只读验收请使用 --verify-existing"
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
    container_id=$(docker compose "${COMPOSE_ARGS[@]}" ps -q minio) ||
      die '无法取得 MinIO 容器 ID'
    [[ -n $container_id && $container_id != *$'\n'* ]] ||
      die 'MinIO 容器数量不是 1'
  fi

  local health_status container_status container_running container_oom container_error deadline

  deadline=$((SECONDS + 180))
  while :; do
    container_status=$(docker container inspect --format '{{.State.Status}}' "$container_id") ||
      die '无法读取 MinIO 运行状态'
    container_running=$(docker container inspect --format '{{.State.Running}}' "$container_id") ||
      die '无法读取 MinIO 运行标志'
    container_oom=$(docker container inspect --format '{{.State.OOMKilled}}' "$container_id") ||
      die '无法读取 MinIO OOM 状态'
    container_error=$(docker container inspect --format '{{.State.Error}}' "$container_id") ||
      die '无法读取 MinIO 错误状态'
    [[ $container_oom == 'false' ]] ||
      die 'MinIO 容器曾被 OOM 终止；不要迁移数据'
    [[ -z $container_error ]] ||
      die 'MinIO 容器运行状态包含错误；请先查看日志'
    [[ $container_status == 'running' && $container_running == 'true' ]] ||
      die "MinIO 容器未运行（状态 $container_status）；只读验收不会自动启动或重启"
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
      missing)
        die 'MinIO 容器缺少必需的健康检查'
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
  project_running_ids=$(docker ps -q --no-trunc \
    --filter "label=com.docker.compose.project=$EXPECTED_COMPOSE_PROJECT") ||
    die '无法检查项目运行容器'
  [[ $project_running_ids == "$container_id" ]] ||
    die '该 Compose 项目运行容器数量不为 1，或唯一容器不是 MinIO'
  note '[通过] 该 Compose 项目唯一运行服务为 minio'

  local container_json="$START_TEMP_DIR/container.json"
  local ports_json="$START_TEMP_DIR/ports.json"
  local mounts_json="$START_TEMP_DIR/mounts.json"
  local volume_json="$START_TEMP_DIR/volume.json"
  docker container inspect "$container_id" >"$container_json" ||
    die '无法读取 MinIO 容器身份'
  docker container inspect --format '{{json .NetworkSettings.Ports}}' "$container_id" \
    >"$ports_json" || die '无法读取 MinIO 运行端口'
  docker container inspect --format '{{json .Mounts}}' "$container_id" \
    >"$mounts_json" || die '无法读取 MinIO 运行挂载'
  docker volume inspect "$EXPECTED_VOLUME_NAME" >"$volume_json" ||
    die "无法读取目标卷：$EXPECTED_VOLUME_NAME"
  chmod 600 "$container_json" "$ports_json" "$mounts_json" "$volume_json"
  validate_runtime_identity "$container_json" "$expected_config_hash" "$expected_image_id"
  validate_runtime_ports "$ports_json"
  validate_runtime_mounts "$mounts_json"
  validate_runtime_volume "$volume_json"

  local volume_container_ids
  volume_container_ids=$(docker ps -aq --no-trunc \
    --filter "volume=$EXPECTED_VOLUME_NAME") ||
    die '无法检查目标卷的容器使用情况'
  [[ $volume_container_ids == "$container_id" ]] ||
    die '目标卷被 MinIO 之外的容器使用，或使用容器数量不是 1'
  note '[通过] 目标卷只由当前 MinIO 容器使用'

  if [[ $VERIFY_EXISTING == true ]]; then
    note '=== 既有迁移目标 MinIO 只读验收通过 ==='
    note '本次没有启动、重启、重建或删除容器/数据卷。'
  else
    note '=== 迁移目标 MinIO 已安全启动 ==='
    note '只运行了 minio；没有拉取、构建或启动其他服务。'
  fi
  note '9000/9001 仅回环可达，安全组不要开放 9000、9001、19090。'
  note '现在可以建立反向隧道并运行 minio-migrate.sh。'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  start_main "$@"
fi
