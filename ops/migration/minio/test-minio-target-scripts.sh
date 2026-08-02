#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
PREPARE_SCRIPT="$SCRIPT_DIR/prepare-minio-target.sh"
START_SCRIPT="$SCRIPT_DIR/start-minio-target.sh"
TUNNEL_SCRIPT="$SCRIPT_DIR/Start-MinioReverseTunnel.ps1"
COMMON_SCRIPT="$SCRIPT_DIR/minio-common.sh"

TEMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/vibelo-minio-target-test.XXXXXXXX")
trap 'rm -rf -- "$TEMP_ROOT"' EXIT

fail() {
  printf '失败：%s\n' "$*" >&2
  exit 1
}

assert_file_contains() {
  local file=$1
  local literal=$2
  local label=$3

  grep -F -- "$literal" "$file" >/dev/null || fail "$label"
}

"$BASH" -n "$PREPARE_SCRIPT"
"$BASH" -n "$START_SCRIPT"
"$BASH" -n "$COMMON_SCRIPT"
"$BASH" "$PREPARE_SCRIPT" --help >/dev/null
"$BASH" "$START_SCRIPT" --help >/dev/null

assert_file_contains "$COMMON_SCRIPT" \
  'read -r -s -p "$label Access Key（隐藏输入）: "' \
  'MinIO Access Key 输入未启用终端隐藏'
assert_file_contains "$COMMON_SCRIPT" \
  'read -r -s -p "$label Secret Key（隐藏输入）: "' \
  'MinIO Secret Key 输入未启用终端隐藏'
if grep -F -- 'Access Key（不回显到日志）' "$COMMON_SCRIPT" >/dev/null; then
  fail 'MinIO Access Key 仍使用会回显的旧提示或读取方式'
fi

assert_file_contains "$TUNNEL_SCRIPT" \
  '"-o", "BatchMode=yes"' '指定 SSH 私钥时缺少批处理失败即退门禁'
assert_file_contains "$TUNNEL_SCRIPT" \
  '"-o", "IdentitiesOnly=yes"' '指定 SSH 私钥时缺少单一身份门禁'

assert_file_contains "$PREPARE_SCRIPT" \
  "MINIO_ARCHIVE_SIZE=64023552" '缺少固定 MinIO 归档尺寸'
assert_file_contains "$PREPARE_SCRIPT" \
  "MINIO_ARCHIVE_SHA256='c220e4e0ef61abe83a084fdc4942af30c9f00e539fabc63b619ef73f01429d0f'" \
  '缺少固定 MinIO 归档 SHA256'
assert_file_contains "$PREPARE_SCRIPT" \
  "MINIO_MANIFEST_DIGEST='sha256:3f97c5651cb6662b880c787a232b6b34fec8d8922e08d6617b25d241a21164bb'" \
  '缺少固定 linux/amd64 manifest digest'
assert_file_contains "$PREPARE_SCRIPT" \
  "MINIO_CONFIG_DIGEST='sha256:9d668e47f1fc60ea49af4203deee87a657eb1aa0e2761fee2c7c2d1df282c880'" \
  '缺少固定 config digest'
assert_file_contains "$PREPARE_SCRIPT" \
  "MC_BINARY_SIZE=30535864" '缺少固定 mc 尺寸'
assert_file_contains "$PREPARE_SCRIPT" \
  "MC_BINARY_SHA256='01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891'" \
  '缺少固定 mc SHA256'
assert_file_contains "$PREPARE_SCRIPT" \
  'MIN_DATA_FREE_BYTES=$((101 * 1024 * 1024 * 1024))' '缺少 101 GiB 空间门禁'
assert_file_contains "$PREPARE_SCRIPT" \
  'MIN_DATA_FREE_INODES=2000000' '缺少 200 万 inode 门禁'

if grep -E '^[[:space:]]*docker[[:space:]]+(pull|build)([[:space:]]|$)' \
  "$PREPARE_SCRIPT" "$START_SCRIPT" >/dev/null; then
  fail '目标脚本中出现了 docker pull/build 执行命令'
fi

# shellcheck source=start-minio-target.sh
source "$START_SCRIPT"

FIXTURE_RELEASE='RELEASE.test'
python3 - "$TEMP_ROOT/fixture.tar" "$TEMP_ROOT/fixture-digests.tsv" "$FIXTURE_RELEASE" <<'PY'
import hashlib
import io
import json
import sys
import tarfile


archive_path, digest_path, release = sys.argv[1:]


def encoded(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


layer = b"fixture-layer-content\n"
layer_digest = hashlib.sha256(layer).hexdigest()
config = encoded({
    "architecture": "amd64",
    "os": "linux",
    "config": {"Labels": {"release": release, "version": release}},
    "rootfs": {"type": "layers", "diff_ids": []},
})
config_digest = hashlib.sha256(config).hexdigest()
manifest = encoded({
    "schemaVersion": 2,
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "config": {
        "mediaType": "application/vnd.oci.image.config.v1+json",
        "digest": f"sha256:{config_digest}",
        "size": len(config),
    },
    "layers": [{
        "mediaType": "application/vnd.oci.image.layer.v1.tar",
        "digest": f"sha256:{layer_digest}",
        "size": len(layer),
    }],
})
manifest_digest = hashlib.sha256(manifest).hexdigest()
index = encoded({
    "schemaVersion": 2,
    "mediaType": "application/vnd.oci.image.index.v1+json",
    "manifests": [{
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": f"sha256:{manifest_digest}",
        "size": len(manifest),
        "platform": {"architecture": "amd64", "os": "linux"},
    }],
})

files = {
    "index.json": index,
    f"blobs/sha256/{manifest_digest}": manifest,
    f"blobs/sha256/{config_digest}": config,
    f"blobs/sha256/{layer_digest}": layer,
}
with tarfile.open(archive_path, mode="w") as bundle:
    for name, content in files.items():
        info = tarfile.TarInfo(name)
        info.size = len(content)
        info.mode = 0o644
        bundle.addfile(info, io.BytesIO(content))

with open(digest_path, "w", encoding="utf-8") as stream:
    stream.write(f"sha256:{manifest_digest}\tsha256:{config_digest}\n")
PY

IFS=$'\t' read -r FIXTURE_MANIFEST FIXTURE_CONFIG <"$TEMP_ROOT/fixture-digests.tsv"
FIXTURE_CONFIG=${FIXTURE_CONFIG%$'\r'}
validate_oci_archive \
  "$TEMP_ROOT/fixture.tar" "$FIXTURE_MANIFEST" "$FIXTURE_CONFIG" "$FIXTURE_RELEASE" \
  >/dev/null

cat >"$TEMP_ROOT/compose.json" <<'JSON'
{
  "name": "vibelo-public",
  "services": {
    "minio": {
      "image": "minio/minio:RELEASE.2025-04-22T22-12-26Z",
      "mem_limit": "1073741824",
      "mem_reservation": "536870912",
      "ports": [
        {"host_ip": "127.0.0.1", "target": 9000, "published": "9000", "protocol": "tcp"},
        {"host_ip": "127.0.0.1", "target": 9001, "published": "9001", "protocol": "tcp"}
      ],
      "volumes": [
        {"type": "volume", "source": "public-minio-data", "target": "/data", "volume": {}}
      ]
    }
  },
  "volumes": {
    "public-minio-data": {"name": "vibelo-public_public-minio-data"}
  }
}
JSON
validate_compose_config "$TEMP_ROOT/compose.json" >/dev/null

python3 - "$TEMP_ROOT/compose.json" "$TEMP_ROOT/compose-invalid.json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as stream:
    value = json.load(stream)
value["services"]["minio"]["ports"][0]["host_ip"] = "0.0.0.0"
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    json.dump(value, stream)
PY
if validate_compose_config "$TEMP_ROOT/compose-invalid.json" >/dev/null 2>&1; then
  fail 'Compose fixture 的公网 MinIO 端口未被拒绝'
fi

cat >"$TEMP_ROOT/ports.json" <<'JSON'
{
  "9000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9000"}],
  "9001/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9001"}]
}
JSON
validate_runtime_ports "$TEMP_ROOT/ports.json" >/dev/null

cat >"$TEMP_ROOT/mounts.json" <<'JSON'
[
  {
    "Type": "volume",
    "Name": "vibelo-public_public-minio-data",
    "Destination": "/data",
    "RW": true
  }
]
JSON
validate_runtime_mounts "$TEMP_ROOT/mounts.json" >/dev/null

cat >"$TEMP_ROOT/mounts-extra.json" <<'JSON'
[
  {
    "Type": "volume",
    "Name": "vibelo-public_public-minio-data",
    "Destination": "/data",
    "RW": true
  },
  {
    "Type": "bind",
    "Source": "/tmp/unexpected",
    "Destination": "/unexpected",
    "RW": false
  }
]
JSON
if validate_runtime_mounts "$TEMP_ROOT/mounts-extra.json" >/dev/null 2>&1; then
  fail '运行挂载门禁未拒绝额外挂载'
fi

EXPECTED_TEST_CONFIG_HASH=$(printf 'a%.0s' {1..64})
EXPECTED_TEST_IMAGE_ID='sha256:runtime-image-id'
actual_config_hash=$(printf 'minio %s\n' "$EXPECTED_TEST_CONFIG_HASH" |
  parse_compose_service_hash)
[[ $actual_config_hash == "$EXPECTED_TEST_CONFIG_HASH" ]] ||
  fail 'Compose 服务配置哈希解析错误'
if printf 'minio %s\nextra value\n' "$EXPECTED_TEST_CONFIG_HASH" |
  parse_compose_service_hash >/dev/null 2>&1; then
  fail 'Compose 服务配置哈希解析未拒绝多行输出'
fi

python3 - "$TEMP_ROOT/container.json" \
  "$EXPECTED_CONTAINER_NAME" \
  "$EXPECTED_COMPOSE_PROJECT" \
  "$MINIO_IMAGE" \
  "$EXPECTED_TEST_IMAGE_ID" \
  "$EXPECTED_TEST_CONFIG_HASH" \
  "$MIN_MINIO_MEMORY_BYTES" \
  "$MIN_MINIO_RESERVATION_BYTES" <<'PY'
import json
import sys

(
    path,
    name,
    project,
    image,
    image_id,
    config_hash,
    memory,
    reservation,
) = sys.argv[1:]
value = [{
    "Name": f"/{name}",
    "Image": image_id,
    "Config": {
        "Image": image,
        "Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.service": "minio",
            "com.docker.compose.container-number": "1",
            "com.docker.compose.oneoff": "False",
            "com.docker.compose.config-hash": config_hash,
        },
    },
    "State": {
        "Status": "running",
        "Running": True,
        "Restarting": False,
        "Dead": False,
        "OOMKilled": False,
        "Error": "",
        "Health": {"Status": "healthy"},
    },
    "HostConfig": {
        "RestartPolicy": {"Name": "unless-stopped"},
        "Memory": int(memory),
        "MemoryReservation": int(reservation),
        "PidsLimit": 256,
    },
}]
with open(path, "w", encoding="utf-8") as stream:
    json.dump(value, stream)
PY
validate_runtime_identity \
  "$TEMP_ROOT/container.json" \
  "$EXPECTED_TEST_CONFIG_HASH" \
  "$EXPECTED_TEST_IMAGE_ID" >/dev/null

python3 - "$TEMP_ROOT/container.json" "$TEMP_ROOT/container-invalid.json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as stream:
    value = json.load(stream)
value[0]["Config"]["Labels"]["com.docker.compose.config-hash"] = "stale"
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    json.dump(value, stream)
PY
if validate_runtime_identity \
  "$TEMP_ROOT/container-invalid.json" \
  "$EXPECTED_TEST_CONFIG_HASH" \
  "$EXPECTED_TEST_IMAGE_ID" >/dev/null 2>&1; then
  fail '既有容器验收未拒绝 Compose 配置漂移'
fi

cat >"$TEMP_ROOT/volume.json" <<JSON
[
  {
    "Name": "$EXPECTED_VOLUME_NAME",
    "Driver": "local",
    "Scope": "local",
    "Mountpoint": "$EXPECTED_DOCKER_ROOT/volumes/$EXPECTED_VOLUME_NAME/_data",
    "Labels": {
      "com.docker.compose.project": "$EXPECTED_COMPOSE_PROJECT",
      "com.docker.compose.volume": "public-minio-data"
    }
  }
]
JSON
validate_runtime_volume "$TEMP_ROOT/volume.json" >/dev/null

python3 - "$TEMP_ROOT/volume.json" "$TEMP_ROOT/volume-invalid.json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as stream:
    value = json.load(stream)
value[0]["Options"] = {"type": "none", "o": "bind", "device": "/unexpected"}
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    json.dump(value, stream)
PY
if validate_runtime_volume "$TEMP_ROOT/volume-invalid.json" >/dev/null 2>&1; then
  fail '既有卷验收未拒绝 local-driver bind 卷'
fi

assert_file_contains "$START_SCRIPT" \
  '--verify-existing' '缺少既有 MinIO 只读验收入口'
assert_file_contains "$START_SCRIPT" \
  '本次没有启动、重启、重建或删除容器/数据卷。' \
  '缺少既有 MinIO 只读验收成功声明'

python3 - "$START_SCRIPT" <<'PY'
import re
import sys

with open(sys.argv[1], "r", encoding="utf-8") as stream:
    source = stream.read()

anchor = source.index("  local existing_container_ids container_id named_container_id")
branch_start = source.index("  if [[ $VERIFY_EXISTING == true ]]; then", anchor)
branch_else = source.index("\n  else\n", branch_start)
branch_end = source.index("\n  fi\n\n  local health_status", branch_else)
verify_branch = source[branch_start:branch_else]
common_verification = source[branch_end:source.index("\n}\n\nif [[ ${BASH_SOURCE[0]}", branch_end)]

forbidden = re.compile(
    r"^\s*(?:start_minio_service|docker\s+(?:start|restart|rm|container\s+rm|volume\s+rm))\b",
    re.MULTILINE,
)
if forbidden.search(verify_branch) or forbidden.search(common_verification):
    raise SystemExit("只读验收路径出现 Docker 变更命令")
if "start_minio_service" not in source[branch_else:branch_end]:
    raise SystemExit("首次启动路径丢失单服务启动调用")
PY

MOCK_BIN="$TEMP_ROOT/bin"
mkdir -p "$MOCK_BIN"
cat >"$MOCK_BIN/df" <<'MOCK_DF'
#!/usr/bin/env bash
set -Eeuo pipefail
case "$*" in
  '-B1 --output=avail -- /data')
    printf '%s\n' 'Avail' '108447924224'
    ;;
  '--output=iavail -- /data')
    printf '%s\n' 'IFree' '2000000'
    ;;
  *)
    printf '不兼容的 df 参数：%s\n' "$*" >&2
    exit 64
    ;;
esac
MOCK_DF
chmod +x "$MOCK_BIN/df"

actual_free_bytes=$(PATH="$MOCK_BIN:$PATH" read_data_free_bytes /data)
actual_free_inodes=$(PATH="$MOCK_BIN:$PATH" read_data_free_inodes /data)
[[ $actual_free_bytes == '108447924224' ]] ||
  fail "可用字节读取错误：$actual_free_bytes"
[[ $actual_free_inodes == '2000000' ]] ||
  fail "可用 inode 读取错误：$actual_free_inodes"

cat >"$MOCK_BIN/docker" <<'MOCK_DOCKER'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"$MOCK_DOCKER_LOG"
MOCK_DOCKER
chmod +x "$MOCK_BIN/docker"
COMPOSE_ARGS=(--env-file /private/env -f /repo/infra/docker-compose.public.yml)
MOCK_DOCKER_LOG="$TEMP_ROOT/docker.log" \
  PATH="$MOCK_BIN:$PATH" \
  start_minio_service
expected_start='compose --env-file /private/env -f /repo/infra/docker-compose.public.yml up -d --pull never --no-build --no-deps minio'
actual_start=$(<"$TEMP_ROOT/docker.log")
[[ $actual_start == "$expected_start" ]] ||
  fail "启动参数不安全；期望 <$expected_start>，实际 <$actual_start>"

printf '%s\n' 'MinIO 离线准备与单服务启动脚本回归测试通过。'
