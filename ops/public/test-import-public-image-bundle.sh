#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
IMPORTER=$SCRIPT_DIR/import-public-image-bundle.sh
RELEASE=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
BACKEND_IMAGE="vibelo-public-backend:$RELEASE"
FRONTEND_IMAGE="vibelo-public-frontend:$RELEASE"
TEMP_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TEMP_ROOT"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

image_id_for_ref() {
  local ref=$1
  printf '%s' "$ref" | sha256sum | awk '{print "sha256:" $1}'
}

write_fixture() {
  local target=$1
  local manifest=$target/vibelo-public-$RELEASE-images.tsv
  local bundle=$target/vibelo-public-$RELEASE-linux-amd64.tar
  local -a refs=(
    'nginx:1.27-alpine'
    "$FRONTEND_IMAGE"
    "$BACKEND_IMAGE"
    'redis:7.4-alpine'
    'docker.elastic.co/elasticsearch/elasticsearch:8.14.3'
    'confluentinc/cp-zookeeper:7.6.1'
    'confluentinc/cp-kafka:7.6.1'
    'minio/minio:RELEASE.2025-04-22T22-12-26Z'
  )

  mkdir -p -- "$target"
  python3 - "$bundle" "$manifest" "${refs[@]}" <<'PY'
import hashlib
import io
import json
import pathlib
import sys
import tarfile

bundle = pathlib.Path(sys.argv[1])
manifest_path = pathlib.Path(sys.argv[2])
refs = sys.argv[3:]


def json_bytes(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("ascii")


docker_manifest = []
oci_descriptors = []
blobs = {}
tsv_lines = ["ref\timage_id\tos\tarch"]
for ref in refs:
    config_blob = json_bytes({
        "architecture": "amd64",
        "config": {},
        "fixtureRef": ref,
        "os": "linux",
        "rootfs": {"diff_ids": [], "type": "layers"},
    })
    config_hex = hashlib.sha256(config_blob).hexdigest()
    config_digest = "sha256:" + config_hex
    platform_blob = json_bytes({
        "config": {
            "digest": config_digest,
            "mediaType": "application/vnd.docker.container.image.v1+json",
            "size": len(config_blob),
        },
        "layers": [],
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "schemaVersion": 2,
    })
    platform_hex = hashlib.sha256(platform_blob).hexdigest()
    image_id = "sha256:" + platform_hex
    config_name = "blobs/sha256/" + config_hex
    platform_name = "blobs/sha256/" + platform_hex
    blobs[config_name] = config_blob
    blobs[platform_name] = platform_blob
    docker_manifest.append({"Config": config_name, "RepoTags": [ref], "Layers": []})
    oci_descriptors.append({
        "annotations": {"io.containerd.image.name": ref},
        "digest": image_id,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "platform": {"architecture": "amd64", "os": "linux"},
        "size": len(platform_blob),
    })
    tsv_lines.append(f"{ref}\t{image_id}\tlinux\tamd64")

manifest_path.write_text("\n".join(tsv_lines) + "\n", encoding="ascii", newline="\n")

with tarfile.open(bundle, "w") as archive:
    files = {
        "manifest.json": json_bytes(docker_manifest),
        "index.json": json_bytes({
            "manifests": oci_descriptors,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "schemaVersion": 2,
        }),
        "oci-layout": json_bytes({"imageLayoutVersion": "1.0.0"}),
        **blobs,
    }
    for name, payload in files.items():
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
PY

  (
    cd -- "$target"
    sha256sum "$(basename -- "$bundle")" "$(basename -- "$manifest")" >SHA256SUMS
  )
}

refresh_checksums() {
  local target=$1
  (
    cd -- "$target"
    sha256sum \
      "vibelo-public-$RELEASE-linux-amd64.tar" \
      "vibelo-public-$RELEASE-images.tsv" >SHA256SUMS
  )
}

invoke_importer_fixture() {
  local target=$1

  export VIBELO_TEST_MANIFEST_PATH=$target/vibelo-public-$RELEASE-images.tsv
  set +e
  IMPORT_OUTPUT=$(
    "$IMPORTER" \
      --release "$RELEASE" \
      --target-directory "$target" \
      --docker-command "$FAKE_DOCKER" 2>&1
  )
  IMPORT_RC=$?
  set -e
}

FAKE_DOCKER=$TEMP_ROOT/fake-docker
cat >"$FAKE_DOCKER" <<'BASH'
#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${1-} == image && ${2-} == load && ${3-} == --input ]]; then
  printf 'load\n' >>"$VIBELO_TEST_DOCKER_LOG"
  printf 'Loaded fixture bundle\n'
  exit 0
fi

if [[ ${1-} == image && ${2-} == inspect ]]; then
  platform=''
  while (($#)); do
    if [[ $1 == --platform && $# -ge 2 ]]; then
      platform=$2
      break
    fi
    shift
  done
  [[ $platform == linux/amd64 ]] || {
    printf '%s\n' 'inspect must explicitly select linux/amd64' >&2
    exit 91
  }
  ref=${@: -1}
  image_id=$(
    awk -F '\t' -v expected_ref="$ref" \
      '$1 == expected_ref { print $2; found = 1; exit } END { if (!found) exit 1 }' \
      "$VIBELO_TEST_MANIFEST_PATH"
  )
  os=linux
  arch=amd64
  if [[ $ref == "${VIBELO_TEST_WRONG_ID_IMAGE-}" ]]; then
    image_id=sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
  fi
  if [[ $ref == "${VIBELO_TEST_WRONG_PLATFORM_IMAGE-}" ]]; then
    arch=arm64
  fi
  printf '%s|%s|%s\n' "$image_id" "$os" "$arch"
  exit 0
fi

printf 'unexpected docker arguments: %s\n' "$*" >&2
exit 90
BASH
chmod 700 "$FAKE_DOCKER"

TARGET=$TEMP_ROOT/release
DOCKER_LOG=$TEMP_ROOT/docker.log
: >"$DOCKER_LOG"
write_fixture "$TARGET"
export VIBELO_TEST_DOCKER_LOG=$DOCKER_LOG

invoke_importer_fixture "$TARGET"
((IMPORT_RC == 0)) || fail "fixture import should succeed; output: $IMPORT_OUTPUT"
[[ $(cat "$DOCKER_LOG") == load ]] || fail 'fixture should invoke exactly one docker image load'
[[ $IMPORT_OUTPUT == *"VIBELO_BACKEND_IMAGE=$BACKEND_IMAGE"* ]] || fail 'import output should provide the ECS backend image variable'
[[ $IMPORT_OUTPUT == *"VIBELO_FRONTEND_IMAGE=$FRONTEND_IMAGE"* ]] || fail 'import output should provide the ECS frontend image variable'

CHECKSUM_TARGET=$TEMP_ROOT/checksum-mismatch
write_fixture "$CHECKSUM_TARGET"
printf 'tampered' >>"$CHECKSUM_TARGET/vibelo-public-$RELEASE-linux-amd64.tar"
: >"$DOCKER_LOG"
invoke_importer_fixture "$CHECKSUM_TARGET"
((IMPORT_RC != 0)) || fail 'bundle SHA256 mismatch should be rejected'
[[ ! -s $DOCKER_LOG ]] || fail 'checksum failure must happen before docker image load'

EXTRA_FILE_TARGET=$TEMP_ROOT/extra-file
write_fixture "$EXTRA_FILE_TARGET"
: >"$EXTRA_FILE_TARGET/unexpected.txt"
: >"$DOCKER_LOG"
invoke_importer_fixture "$EXTRA_FILE_TARGET"
((IMPORT_RC != 0)) || fail 'an extra package file should be rejected'
[[ ! -s $DOCKER_LOG ]] || fail 'extra-file failure must happen before docker image load'

MISSING_IMAGE_TARGET=$TEMP_ROOT/missing-image
write_fixture "$MISSING_IMAGE_TARGET"
sed -i '$d' "$MISSING_IMAGE_TARGET/vibelo-public-$RELEASE-images.tsv"
refresh_checksums "$MISSING_IMAGE_TARGET"
: >"$DOCKER_LOG"
invoke_importer_fixture "$MISSING_IMAGE_TARGET"
((IMPORT_RC != 0)) || fail 'a missing manifest image should be rejected'
[[ ! -s $DOCKER_LOG ]] || fail 'missing-image failure must happen before docker image load'

EXTRA_IMAGE_TARGET=$TEMP_ROOT/extra-image
write_fixture "$EXTRA_IMAGE_TARGET"
extra_id=$(image_id_for_ref 'busybox:1.37')
printf 'busybox:1.37\t%s\tlinux\tamd64\n' "$extra_id" \
  >>"$EXTRA_IMAGE_TARGET/vibelo-public-$RELEASE-images.tsv"
refresh_checksums "$EXTRA_IMAGE_TARGET"
: >"$DOCKER_LOG"
invoke_importer_fixture "$EXTRA_IMAGE_TARGET"
((IMPORT_RC != 0)) || fail 'an extra manifest image should be rejected'
[[ ! -s $DOCKER_LOG ]] || fail 'extra-image failure must happen before docker image load'

ARCHIVE_EXTRA_TARGET=$TEMP_ROOT/archive-extra-image
write_fixture "$ARCHIVE_EXTRA_TARGET"
python3 - "$ARCHIVE_EXTRA_TARGET/vibelo-public-$RELEASE-linux-amd64.tar" <<'PY'
import io
import hashlib
import json
import pathlib
import tarfile
import sys

bundle = pathlib.Path(sys.argv[1])
with tarfile.open(bundle, "r") as source:
    manifest = json.load(source.extractfile("manifest.json"))
    files = {}
    for member in source.getmembers():
        if member.name == "manifest.json" or not member.isfile():
            continue
        files[member.name] = source.extractfile(member).read()

extra_payload = b"{}"
extra_config = hashlib.sha256(extra_payload).hexdigest() + ".json"
manifest.append({"Config": extra_config, "RepoTags": ["busybox:1.37"], "Layers": []})
files[extra_config] = extra_payload
with tarfile.open(bundle, "w") as target:
    payload = json.dumps(manifest, separators=(",", ":")).encode("ascii")
    info = tarfile.TarInfo("manifest.json")
    info.size = len(payload)
    target.addfile(info, io.BytesIO(payload))
    for name, payload in files.items():
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        target.addfile(info, io.BytesIO(payload))
PY
refresh_checksums "$ARCHIVE_EXTRA_TARGET"
: >"$DOCKER_LOG"
invoke_importer_fixture "$ARCHIVE_EXTRA_TARGET"
((IMPORT_RC != 0)) || fail 'an extra image inside the bundle should be rejected'
[[ ! -s $DOCKER_LOG ]] || fail 'archive-set failure must happen before docker image load'

WRONG_ID_TARGET=$TEMP_ROOT/wrong-loaded-id
write_fixture "$WRONG_ID_TARGET"
export VIBELO_TEST_WRONG_ID_IMAGE='redis:7.4-alpine'
: >"$DOCKER_LOG"
invoke_importer_fixture "$WRONG_ID_TARGET"
((IMPORT_RC != 0)) || fail 'a loaded image ID mismatch should be rejected'
[[ $(cat "$DOCKER_LOG") == load ]] || fail 'post-load image ID validation should run after one load'
unset VIBELO_TEST_WRONG_ID_IMAGE

WRONG_PLATFORM_TARGET=$TEMP_ROOT/wrong-loaded-platform
write_fixture "$WRONG_PLATFORM_TARGET"
export VIBELO_TEST_WRONG_PLATFORM_IMAGE='confluentinc/cp-kafka:7.6.1'
: >"$DOCKER_LOG"
invoke_importer_fixture "$WRONG_PLATFORM_TARGET"
((IMPORT_RC != 0)) || fail 'a loaded image platform mismatch should be rejected'
[[ $(cat "$DOCKER_LOG") == load ]] || fail 'post-load platform validation should run after one load'
unset VIBELO_TEST_WRONG_PLATFORM_IMAGE

printf '%s\n' 'Public image bundle import fixture tests passed.'
