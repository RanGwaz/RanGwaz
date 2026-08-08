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

add_valid_attestation() {
  local target=$1

  python3 - "$target/vibelo-public-$RELEASE-linux-amd64.tar" <<'PY'
import hashlib
import io
import json
import pathlib
import sys
import tarfile

bundle = pathlib.Path(sys.argv[1])


def json_bytes(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("ascii")


with tarfile.open(bundle, "r") as source:
    files = {
        member.name: source.extractfile(member).read()
        for member in source.getmembers()
        if member.isfile()
    }

index = json.loads(files["index.json"])
target_digest = index["manifests"][0]["digest"]
target_hex = target_digest.removeprefix("sha256:")
predicate_type = "https://slsa.dev/provenance/v0.2"
statement = json_bytes({
    "_type": "https://in-toto.io/Statement/v1",
    "predicate": {"fixture": True},
    "predicateType": predicate_type,
    "subject": [{"digest": {"sha256": target_hex}, "name": "_"}],
})
statement_digest = "sha256:" + hashlib.sha256(statement).hexdigest()
config = json_bytes({
    "architecture": "unknown",
    "config": {},
    "os": "unknown",
    "rootfs": {"diff_ids": [statement_digest], "type": "layers"},
})
config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
attestation = json_bytes({
    "config": {
        "digest": config_digest,
        "mediaType": "application/vnd.oci.image.config.v1+json",
        "size": len(config),
    },
    "layers": [{
        "annotations": {"in-toto.io/predicate-type": predicate_type},
        "digest": statement_digest,
        "mediaType": "application/vnd.in-toto+json",
        "size": len(statement),
    }],
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "schemaVersion": 2,
})
attestation_digest = "sha256:" + hashlib.sha256(attestation).hexdigest()
index["manifests"].append({
    "annotations": {
        "vnd.docker.reference.digest": target_digest,
        "vnd.docker.reference.type": "attestation-manifest",
    },
    "digest": attestation_digest,
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "platform": {"architecture": "unknown", "os": "unknown"},
    "size": len(attestation),
})
files["index.json"] = json_bytes(index)
files["blobs/sha256/" + statement_digest.removeprefix("sha256:")] = statement
files["blobs/sha256/" + config_digest.removeprefix("sha256:")] = config
files["blobs/sha256/" + attestation_digest.removeprefix("sha256:")] = attestation

with tarfile.open(bundle, "w") as target:
    for name, payload in files.items():
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        target.addfile(info, io.BytesIO(payload))
PY

  refresh_checksums "$target"
}

mutate_attestation() {
  local target=$1
  local mutation=$2

  python3 - "$target/vibelo-public-$RELEASE-linux-amd64.tar" "$mutation" <<'PY'
import hashlib
import io
import json
import pathlib
import sys
import tarfile

bundle = pathlib.Path(sys.argv[1])
mutation = sys.argv[2]


def json_bytes(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("ascii")


def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def blob_name(value_digest):
    return "blobs/sha256/" + value_digest.removeprefix("sha256:")


with tarfile.open(bundle, "r") as source:
    files = {
        member.name: source.extractfile(member).read()
        for member in source.getmembers()
        if member.isfile()
    }

index = json.loads(files["index.json"])
target_descriptor = index["manifests"][0]
attestation_descriptor = index["manifests"][-1]
attestation = json.loads(files[blob_name(attestation_descriptor["digest"])])

if mutation == "containerd-legacy":
    del attestation_descriptor["platform"]
    attestation_descriptor["annotations"] = {
        "io.containerd.manifest.subject": target_descriptor["digest"]
    }
    layer = attestation["layers"][0]
    statement = json.loads(files[blob_name(layer["digest"])])
    statement["_type"] = "https://in-toto.io/Statement/v0.1"
    statement_blob = json_bytes(statement)
    statement_digest = digest(statement_blob)
    layer["digest"] = statement_digest
    layer["size"] = len(statement_blob)
    files[blob_name(statement_digest)] = statement_blob
    config_descriptor = attestation["config"]
    config = json.loads(files[blob_name(config_descriptor["digest"])])
    config["rootfs"]["diff_ids"] = [statement_digest]
    config_blob = json_bytes(config)
    config_digest = digest(config_blob)
    config_descriptor["digest"] = config_digest
    config_descriptor["size"] = len(config_blob)
    files[blob_name(config_digest)] = config_blob
elif mutation == "wrong-containerd-target":
    attestation_descriptor["annotations"]["io.containerd.manifest.subject"] = "sha256:" + "f" * 64
elif mutation == "wrong-containerd-platform":
    attestation_descriptor["platform"] = {"architecture": "unknown", "os": "unknown"}
elif mutation == "wrong-descriptor-target":
    attestation_descriptor["annotations"]["vnd.docker.reference.digest"] = "sha256:" + "f" * 64
elif mutation == "wrong-descriptor-type":
    attestation_descriptor["annotations"]["vnd.docker.reference.type"] = "runnable-image"
elif mutation == "wrong-statement-subject":
    layer = attestation["layers"][0]
    statement = json.loads(files[blob_name(layer["digest"])])
    statement["subject"][0]["digest"]["sha256"] = "f" * 64
    statement_blob = json_bytes(statement)
    statement_digest = digest(statement_blob)
    layer["digest"] = statement_digest
    layer["size"] = len(statement_blob)
    files[blob_name(statement_digest)] = statement_blob
elif mutation == "wrong-statement-type":
    layer = attestation["layers"][0]
    statement = json.loads(files[blob_name(layer["digest"])])
    statement["_type"] = "https://example.invalid/Statement/v9"
    statement_blob = json_bytes(statement)
    statement_digest = digest(statement_blob)
    layer["digest"] = statement_digest
    layer["size"] = len(statement_blob)
    files[blob_name(statement_digest)] = statement_blob
elif mutation in {"wrong-containerd-config", "wrong-containerd-diff-ids"}:
    config_descriptor = attestation["config"]
    config = json.loads(files[blob_name(config_descriptor["digest"])])
    if mutation == "wrong-containerd-config":
        config["architecture"] = "amd64"
    else:
        config["rootfs"]["diff_ids"] = ["sha256:" + "f" * 64]
    config_blob = json_bytes(config)
    config_digest = digest(config_blob)
    config_descriptor["digest"] = config_digest
    config_descriptor["size"] = len(config_blob)
    files[blob_name(config_digest)] = config_blob
elif mutation == "wrong-containerd-layer":
    attestation["layers"][0]["mediaType"] = "application/octet-stream"
elif mutation == "oci-artifact":
    empty_config = b"{}"
    empty_config_digest = digest(empty_config)
    files[blob_name(empty_config_digest)] = empty_config
    attestation["artifactType"] = "application/vnd.docker.attestation.manifest.v1+json"
    attestation["config"] = {
        "data": "e30=",
        "digest": empty_config_digest,
        "mediaType": "application/vnd.oci.empty.v1+json",
        "size": len(empty_config),
    }
    attestation["subject"] = {
        "digest": target_descriptor["digest"],
        "mediaType": target_descriptor["mediaType"],
        "platform": target_descriptor["platform"],
        "size": target_descriptor["size"],
    }
elif mutation == "wrong-oci-subject":
    attestation["subject"]["digest"] = "sha256:" + "f" * 64
else:
    raise SystemExit("unknown attestation fixture mutation")

if mutation in {
    "containerd-legacy",
    "wrong-statement-subject",
    "wrong-statement-type",
    "wrong-containerd-config",
    "wrong-containerd-diff-ids",
    "wrong-containerd-layer",
    "oci-artifact",
    "wrong-oci-subject",
}:
    attestation_blob = json_bytes(attestation)
    attestation_digest = digest(attestation_blob)
    attestation_descriptor["digest"] = attestation_digest
    attestation_descriptor["size"] = len(attestation_blob)
    files[blob_name(attestation_digest)] = attestation_blob

files["index.json"] = json_bytes(index)
with tarfile.open(bundle, "w") as target:
    for name, payload in files.items():
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        target.addfile(info, io.BytesIO(payload))
PY

  refresh_checksums "$target"
}

write_containerd_attestation_fixture() {
  local target=$1

  write_fixture "$target"
  add_valid_attestation "$target"
  mutate_attestation "$target" containerd-legacy
}

add_extra_runnable_descriptor() {
  local target=$1

  python3 - "$target/vibelo-public-$RELEASE-linux-amd64.tar" <<'PY'
import hashlib
import io
import json
import pathlib
import sys
import tarfile

bundle = pathlib.Path(sys.argv[1])


def json_bytes(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("ascii")


with tarfile.open(bundle, "r") as source:
    files = {
        member.name: source.extractfile(member).read()
        for member in source.getmembers()
        if member.isfile()
    }

config = json_bytes({
    "architecture": "amd64",
    "config": {},
    "fixtureRef": "malicious-extra:latest",
    "os": "linux",
    "rootfs": {"diff_ids": [], "type": "layers"},
})
config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
manifest = json_bytes({
    "config": {
        "digest": config_digest,
        "mediaType": "application/vnd.oci.image.config.v1+json",
        "size": len(config),
    },
    "layers": [],
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "schemaVersion": 2,
})
manifest_digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
index = json.loads(files["index.json"])
index["manifests"].append({
    "annotations": {"io.containerd.image.name": "malicious-extra:latest"},
    "digest": manifest_digest,
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "platform": {"architecture": "amd64", "os": "linux"},
    "size": len(manifest),
})
files["index.json"] = json_bytes(index)
files["blobs/sha256/" + config_digest.removeprefix("sha256:")] = config
files["blobs/sha256/" + manifest_digest.removeprefix("sha256:")] = manifest

with tarfile.open(bundle, "w") as target:
    for name, payload in files.items():
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        target.addfile(info, io.BytesIO(payload))
PY

  refresh_checksums "$target"
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

VALID_ATTESTATION_TARGET=$TEMP_ROOT/valid-attestation
write_fixture "$VALID_ATTESTATION_TARGET"
add_valid_attestation "$VALID_ATTESTATION_TARGET"
: >"$DOCKER_LOG"
invoke_importer_fixture "$VALID_ATTESTATION_TARGET"
((IMPORT_RC == 0)) || fail "a valid Docker attestation should be accepted; output: $IMPORT_OUTPUT"
[[ $(cat "$DOCKER_LOG") == load ]] || fail 'valid attestation fixture should invoke exactly one docker image load'

CONTAINERD_ATTESTATION_TARGET=$TEMP_ROOT/valid-containerd-legacy-attestation
write_containerd_attestation_fixture "$CONTAINERD_ATTESTATION_TARGET"
: >"$DOCKER_LOG"
invoke_importer_fixture "$CONTAINERD_ATTESTATION_TARGET"
((IMPORT_RC == 0)) || fail "a valid containerd legacy attestation should be accepted; output: $IMPORT_OUTPUT"
[[ $(cat "$DOCKER_LOG") == load ]] || fail 'containerd legacy attestation fixture should invoke exactly one docker image load'

CONTAINERD_WRONG_TARGET=$TEMP_ROOT/containerd-wrong-target
write_containerd_attestation_fixture "$CONTAINERD_WRONG_TARGET"
mutate_attestation "$CONTAINERD_WRONG_TARGET" wrong-containerd-target
: >"$DOCKER_LOG"
invoke_importer_fixture "$CONTAINERD_WRONG_TARGET"
((IMPORT_RC != 0)) || fail 'a forged containerd subject annotation should be rejected'
[[ $IMPORT_OUTPUT == *'attestation does not reference a runnable image manifest'* ]] || fail 'forged containerd annotation should fail at the target gate'
[[ ! -s $DOCKER_LOG ]] || fail 'forged containerd annotation must fail before docker image load'

CONTAINERD_WRONG_PLATFORM=$TEMP_ROOT/containerd-wrong-platform
write_containerd_attestation_fixture "$CONTAINERD_WRONG_PLATFORM"
mutate_attestation "$CONTAINERD_WRONG_PLATFORM" wrong-containerd-platform
: >"$DOCKER_LOG"
invoke_importer_fixture "$CONTAINERD_WRONG_PLATFORM"
((IMPORT_RC != 0)) || fail 'a containerd attachment with a forged platform should be rejected'
[[ $IMPORT_OUTPUT == *'unsupported non-runnable descriptor'* ]] || fail 'forged containerd platform should fail at the descriptor gate'
[[ ! -s $DOCKER_LOG ]] || fail 'forged containerd platform must fail before docker image load'

CONTAINERD_WRONG_CONFIG=$TEMP_ROOT/containerd-wrong-config
write_containerd_attestation_fixture "$CONTAINERD_WRONG_CONFIG"
mutate_attestation "$CONTAINERD_WRONG_CONFIG" wrong-containerd-config
: >"$DOCKER_LOG"
invoke_importer_fixture "$CONTAINERD_WRONG_CONFIG"
((IMPORT_RC != 0)) || fail 'a containerd attachment with a runnable config should be rejected'
[[ $IMPORT_OUTPUT == *'containerd attestation config shape is invalid'* ]] || fail 'forged containerd config should fail at the config gate'
[[ ! -s $DOCKER_LOG ]] || fail 'forged containerd config must fail before docker image load'

CONTAINERD_WRONG_DIFF_IDS=$TEMP_ROOT/containerd-wrong-diff-ids
write_containerd_attestation_fixture "$CONTAINERD_WRONG_DIFF_IDS"
mutate_attestation "$CONTAINERD_WRONG_DIFF_IDS" wrong-containerd-diff-ids
: >"$DOCKER_LOG"
invoke_importer_fixture "$CONTAINERD_WRONG_DIFF_IDS"
((IMPORT_RC != 0)) || fail 'a containerd attachment whose config does not bind its layers should be rejected'
[[ $IMPORT_OUTPUT == *'containerd attestation config does not match its layers'* ]] || fail 'containerd diff_ids mismatch should fail at the config-layer gate'
[[ ! -s $DOCKER_LOG ]] || fail 'containerd diff_ids mismatch must fail before docker image load'

CONTAINERD_WRONG_LAYER=$TEMP_ROOT/containerd-wrong-layer
write_containerd_attestation_fixture "$CONTAINERD_WRONG_LAYER"
mutate_attestation "$CONTAINERD_WRONG_LAYER" wrong-containerd-layer
: >"$DOCKER_LOG"
invoke_importer_fixture "$CONTAINERD_WRONG_LAYER"
((IMPORT_RC != 0)) || fail 'a containerd attachment with a non-attestation layer should be rejected'
[[ $IMPORT_OUTPUT == *'attestation layer media type is invalid'* ]] || fail 'forged containerd layer should fail at the layer gate'
[[ ! -s $DOCKER_LOG ]] || fail 'forged containerd layer must fail before docker image load'

CONTAINERD_WRONG_SUBJECT=$TEMP_ROOT/containerd-wrong-in-toto-subject
write_containerd_attestation_fixture "$CONTAINERD_WRONG_SUBJECT"
mutate_attestation "$CONTAINERD_WRONG_SUBJECT" wrong-statement-subject
: >"$DOCKER_LOG"
invoke_importer_fixture "$CONTAINERD_WRONG_SUBJECT"
((IMPORT_RC != 0)) || fail 'a containerd attachment with a forged in-toto subject should be rejected'
[[ $IMPORT_OUTPUT == *'in-toto attestation subject does not match its runnable image'* ]] || fail 'forged containerd in-toto subject should fail at the subject gate'
[[ ! -s $DOCKER_LOG ]] || fail 'forged containerd in-toto subject must fail before docker image load'

CONTAINERD_WRONG_TYPE=$TEMP_ROOT/containerd-wrong-in-toto-type
write_containerd_attestation_fixture "$CONTAINERD_WRONG_TYPE"
mutate_attestation "$CONTAINERD_WRONG_TYPE" wrong-statement-type
: >"$DOCKER_LOG"
invoke_importer_fixture "$CONTAINERD_WRONG_TYPE"
((IMPORT_RC != 0)) || fail 'a containerd attachment with an unknown statement type should be rejected'
[[ $IMPORT_OUTPUT == *'in-toto attestation statement type is invalid'* ]] || fail 'unknown in-toto statement type should fail at the type gate'
[[ ! -s $DOCKER_LOG ]] || fail 'unknown in-toto statement type must fail before docker image load'

OCI_ATTESTATION_TARGET=$TEMP_ROOT/valid-oci-artifact-attestation
write_fixture "$OCI_ATTESTATION_TARGET"
add_valid_attestation "$OCI_ATTESTATION_TARGET"
mutate_attestation "$OCI_ATTESTATION_TARGET" oci-artifact
: >"$DOCKER_LOG"
invoke_importer_fixture "$OCI_ATTESTATION_TARGET"
((IMPORT_RC == 0)) || fail "a valid OCI artifact attestation should be accepted; output: $IMPORT_OUTPUT"
[[ $(cat "$DOCKER_LOG") == load ]] || fail 'OCI artifact attestation fixture should invoke exactly one docker image load'

WRONG_OCI_SUBJECT=$TEMP_ROOT/wrong-oci-artifact-subject
write_fixture "$WRONG_OCI_SUBJECT"
add_valid_attestation "$WRONG_OCI_SUBJECT"
mutate_attestation "$WRONG_OCI_SUBJECT" oci-artifact
mutate_attestation "$WRONG_OCI_SUBJECT" wrong-oci-subject
: >"$DOCKER_LOG"
invoke_importer_fixture "$WRONG_OCI_SUBJECT"
((IMPORT_RC != 0)) || fail 'an OCI artifact attestation with a mismatched subject should be rejected'
[[ $IMPORT_OUTPUT == *'attestation subject does not match its runnable image'* ]] || fail 'wrong OCI subject should fail at the subject gate'
[[ ! -s $DOCKER_LOG ]] || fail 'wrong OCI subject must fail before docker image load'

WRONG_ATTESTATION_TARGET=$TEMP_ROOT/wrong-attestation-target
write_fixture "$WRONG_ATTESTATION_TARGET"
add_valid_attestation "$WRONG_ATTESTATION_TARGET"
mutate_attestation "$WRONG_ATTESTATION_TARGET" wrong-descriptor-target
: >"$DOCKER_LOG"
invoke_importer_fixture "$WRONG_ATTESTATION_TARGET"
((IMPORT_RC != 0)) || fail 'an attestation for an unknown manifest should be rejected'
[[ $IMPORT_OUTPUT == *'attestation does not reference a runnable image manifest'* ]] || fail 'wrong attestation target should fail at the target gate'
[[ ! -s $DOCKER_LOG ]] || fail 'wrong attestation target must fail before docker image load'

WRONG_ATTESTATION_TYPE=$TEMP_ROOT/wrong-attestation-type
write_fixture "$WRONG_ATTESTATION_TYPE"
add_valid_attestation "$WRONG_ATTESTATION_TYPE"
mutate_attestation "$WRONG_ATTESTATION_TYPE" wrong-descriptor-type
: >"$DOCKER_LOG"
invoke_importer_fixture "$WRONG_ATTESTATION_TYPE"
((IMPORT_RC != 0)) || fail 'an unknown/unknown runnable descriptor disguised as metadata should be rejected'
[[ $IMPORT_OUTPUT == *'unsupported non-runnable descriptor'* ]] || fail 'wrong attestation type should fail at the descriptor gate'
[[ ! -s $DOCKER_LOG ]] || fail 'wrong attestation type must fail before docker image load'

WRONG_ATTESTATION_SUBJECT=$TEMP_ROOT/wrong-attestation-subject
write_fixture "$WRONG_ATTESTATION_SUBJECT"
add_valid_attestation "$WRONG_ATTESTATION_SUBJECT"
mutate_attestation "$WRONG_ATTESTATION_SUBJECT" wrong-statement-subject
: >"$DOCKER_LOG"
invoke_importer_fixture "$WRONG_ATTESTATION_SUBJECT"
((IMPORT_RC != 0)) || fail 'an attestation with a mismatched in-toto subject should be rejected'
[[ $IMPORT_OUTPUT == *'in-toto attestation subject does not match its runnable image'* ]] || fail 'wrong in-toto subject should fail at the subject gate'
[[ ! -s $DOCKER_LOG ]] || fail 'wrong in-toto subject must fail before docker image load'

EXTRA_RUNNABLE_TARGET=$TEMP_ROOT/extra-runnable-descriptor
write_fixture "$EXTRA_RUNNABLE_TARGET"
add_extra_runnable_descriptor "$EXTRA_RUNNABLE_TARGET"
: >"$DOCKER_LOG"
invoke_importer_fixture "$EXTRA_RUNNABLE_TARGET"
((IMPORT_RC != 0)) || fail 'an extra linux/amd64 runnable descriptor should be rejected'
[[ $IMPORT_OUTPUT == *'extra or missing image descriptor'* ]] || fail 'extra runnable image should fail at the exact descriptor-set gate'
[[ ! -s $DOCKER_LOG ]] || fail 'extra runnable descriptor must fail before docker image load'

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
