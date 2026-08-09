#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

REPO_ROOT=${VIBELO_REPO_ROOT:-/opt/vibelo}
PUBLIC_ENV=$REPO_ROOT/.env.public
CONFIG_DIR=/etc/vibelo
JOB_ENV=$CONFIG_DIR/vector-job.env
DB_ENV=$CONFIG_DIR/vector-db.env
SERVICE_USER=vibelo-vectorize
SERVICE_GROUP=vibelo-vectorize
RECALL_USER=vibelo-vector-recall
RECALL_GROUP=vibelo-vector-recall
RUNTIME_GROUP=vibelo-vector-runtime
SUPPORTED_PROJECTION_VERSION=siglip-image-feature-l2-rp512-seed20260606-v1
SENSITIVE_SERVICE_GROUPS=(root docker sudo wheel adm lxd systemd-journal)
MIN_TOTAL_MEMORY_KB=15728640
BACKEND_CONTAINER_ID=''
BACKEND_GATEWAY=''
RECALL_PORT=8091
VALIDATING_RECALL=0
TEMP_JOB_ENV=''
TEMP_DB_ENV=''
TIMER_WAS_ACTIVE=0
TIMER_ENABLE_STATE=not-found
TIMER_QUIESCED=0
TIMER_ENABLED_BY_INSTALL=0
INSTALL_SUCCEEDED=0
CONFIG_PUBLISH_STARTED=0

die() { printf 'vector installer: %s\n' "$*" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

cleanup() {
  local status=$?
  [[ -z $TEMP_JOB_ENV ]] || rm -f -- "$TEMP_JOB_ENV"
  [[ -z $TEMP_DB_ENV ]] || rm -f -- "$TEMP_DB_ENV"
  if ((VALIDATING_RECALL == 1 && status != 0)); then
    systemctl disable --now vibelo-vector-recall.service >/dev/null 2>&1 || true
  fi
  if ((INSTALL_SUCCEEDED == 0 && TIMER_ENABLED_BY_INSTALL == 1)); then
    systemctl disable --now vibelo-vectorize.timer >/dev/null 2>&1 || true
  fi
  if ((INSTALL_SUCCEEDED == 0 && CONFIG_PUBLISH_STARTED == 1)); then
    systemctl disable --now vibelo-vectorize.timer >/dev/null 2>&1 || true
  elif ((INSTALL_SUCCEEDED == 0 && TIMER_QUIESCED == 1)); then
    restore_vector_timer_before_publish >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

ensure_service_identity() {
  local user group
  getent group "$RUNTIME_GROUP" >/dev/null || groupadd --system "$RUNTIME_GROUP"
  for user in "$SERVICE_USER" "$RECALL_USER"; do
    if [[ $user == "$SERVICE_USER" ]]; then group=$SERVICE_GROUP; else group=$RECALL_GROUP; fi
    getent group "$group" >/dev/null || groupadd --system "$group"
    if ! id -u "$user" >/dev/null 2>&1; then
      useradd \
        --system \
        --gid "$group" \
        --groups "$RUNTIME_GROUP" \
        --home-dir /nonexistent \
        --shell /usr/sbin/nologin \
        --no-create-home \
        "$user"
    else
      usermod --append --groups "$RUNTIME_GROUP" "$user"
    fi
    [[ $(id -u "$user") -ne 0 ]] || die "$user must not be root"
    [[ $(id -gn "$user") == "$group" ]] || die "$user has an unexpected primary group"
    assert_safe_service_groups "$user"
  done
}

assert_safe_service_groups() {
  local user=$1 membership sensitive
  membership=" $(id -nG "$user") "
  for sensitive in "${SENSITIVE_SERVICE_GROUPS[@]}"; do
    [[ $membership != *" $sensitive "* ]] || \
      die "$user must not belong to sensitive group $sensitive"
  done
}

required_env_line() {
  local file=$1
  local key=$2
  local line raw
  local -a matches=()

  while IFS= read -r line; do
    matches+=("${line%$'\r'}")
  done < <(grep -E "^${key}=" -- "$file" || true)
  ((${#matches[@]} == 1)) || die "$file must contain exactly one $key assignment"
  line=${matches[0]}
  raw=${line#*=}
  [[ -n $raw && $raw != "''" && $raw != '""' ]] || die "$key is empty"
  [[ ! $raw =~ ^\$\{[A-Za-z_][A-Za-z0-9_]*\}$ ]] || die "$key is an unresolved placeholder"
  printf '%s\n' "$line"
}

extract_minimal_db_env() {
  local target=$1
  local temporary
  local key

  temporary=$(mktemp "$CONFIG_DIR/.vector-db.env.XXXXXXXX")
  for key in VIBELO_DB_HOST VIBELO_DB_PORT VIBELO_DB_NAME VIBELO_DB_USER VIBELO_DB_PASSWORD; do
    required_env_line "$PUBLIC_ENV" "$key" >>"$temporary"
  done
  chown root:"$SERVICE_GROUP" "$temporary"
  chmod 0640 "$temporary"
  mv -f -- "$temporary" "$target"
}

plain_env_value() {
  local file=$1
  local key=$2
  local line value
  line=$(grep -E "^${key}=" -- "$file" | tail -n 1) || return 1
  value=${line#*=}
  value=${value%$'\r'}
  if [[ $value == '"'*'"' && ${#value} -ge 2 ]]; then
    value=${value:1:${#value}-2}
  elif [[ $value == "'"*"'" && ${#value} -ge 2 ]]; then
    value=${value:1:${#value}-2}
  fi
  printf '%s' "$value"
}

set_env_literal() {
  local file=$1
  local key=$2
  local value=$3
  local temporary
  temporary=$(mktemp "$CONFIG_DIR/.vector-job.env.XXXXXXXX")
  awk -v key="$key" -v value="$value" '
    BEGIN { found=0 }
    $0 ~ ("^" key "=") {
      if (!found) print key "=" value
      found=1
      next
    }
    { print }
    END { if (!found) print key "=" value }
  ' "$file" >"$temporary"
  chown root:"$RUNTIME_GROUP" "$temporary"
  chmod 0640 "$temporary"
  mv -f -- "$temporary" "$file"
}

validate_private_ipv4() {
  "$REPO_ROOT/.venv-vector/bin/python" - "$1" <<'PY'
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1])
private_networks = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
if address.version != 4 or address.is_loopback or not any(address in item for item in private_networks):
    raise SystemExit(1)
PY
}

assert_safe_vector_path() {
  local path=$1 resolved
  resolved=$(realpath -m -- "$path") || die "cannot resolve vector path: $path"
  [[ $resolved == "$path" && ! -L $path ]] || die "unsafe vector path or symlink: $path"
}

discover_backend_bridge() {
  local host_alias_ip network_name endpoint_gateway driver scope configured_gateway
  local -a backend_ids=()
  local -a host_alias_ips=()
  local -a network_rows=()
  local -a matches=()
  local -a bridge_networks=()
  local -a vector_urls=()

  mapfile -t backend_ids < <(
    docker ps \
      --filter 'label=com.docker.compose.project=vibelo-public' \
      --filter 'label=com.docker.compose.service=backend' \
      --format '{{.ID}}'
  )
  ((${#backend_ids[@]} == 1)) || die "expected exactly one running vibelo-public backend container"
  BACKEND_CONTAINER_ID=${backend_ids[0]}

  mapfile -t host_alias_ips < <(
    docker exec "$BACKEND_CONTAINER_ID" \
      awk '$2 == "host.docker.internal" { print $1 }' /etc/hosts
  )
  ((${#host_alias_ips[@]} == 1)) || die "backend must resolve host.docker.internal to exactly one address"
  host_alias_ip=${host_alias_ips[0]}
  validate_private_ipv4 "$host_alias_ip" || die "host.docker.internal is not a private IPv4 bridge address"

  mapfile -t network_rows < <(
    docker inspect --format \
      '{{range $name, $network := .NetworkSettings.Networks}}{{printf "%s|%s\n" $name $network.Gateway}}{{end}}' \
      "$BACKEND_CONTAINER_ID"
  )
  for row in "${network_rows[@]}"; do
    IFS='|' read -r network_name endpoint_gateway <<<"$row"
    [[ -n $network_name && $endpoint_gateway == "$host_alias_ip" ]] || continue
    driver=$(docker network inspect --format '{{.Driver}}' "$network_name")
    scope=$(docker network inspect --format '{{.Scope}}' "$network_name")
    [[ $driver == bridge && $scope == local ]] || continue
    matches+=("$endpoint_gateway")
  done

  # Docker Engine normally resolves host-gateway to the default `bridge`
  # gateway, which does not have to be attached to the Compose container.
  # Prefer an attached backend bridge above; otherwise prove that the alias is
  # the unique gateway of another local Docker bridge.
  if ((${#matches[@]} == 0)); then
    mapfile -t bridge_networks < <(docker network ls --filter driver=bridge --format '{{.Name}}')
    for network_name in "${bridge_networks[@]}"; do
      driver=$(docker network inspect --format '{{.Driver}}' "$network_name")
      scope=$(docker network inspect --format '{{.Scope}}' "$network_name")
      [[ $driver == bridge && $scope == local ]] || continue
      while IFS= read -r configured_gateway; do
        [[ $configured_gateway == "$host_alias_ip" ]] && matches+=("$configured_gateway")
      done < <(docker network inspect --format '{{range .IPAM.Config}}{{println .Gateway}}{{end}}' "$network_name")
    done
  fi
  ((${#matches[@]} == 1)) || die "cannot uniquely match host.docker.internal to the backend Compose bridge gateway"
  BACKEND_GATEWAY=${matches[0]}

  ip -o -4 addr show | awk '{print $4}' | cut -d/ -f1 | grep -Fxq -- "$BACKEND_GATEWAY" ||
    die "backend bridge gateway is not assigned on this host"

  mapfile -t vector_urls < <(
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$BACKEND_CONTAINER_ID" |
      sed -n 's/^VECTOR_SERVICE_URL=//p'
  )
  ((${#vector_urls[@]} == 1)) || die "backend must have exactly one VECTOR_SERVICE_URL"
  [[ ${vector_urls[0]} == "http://host.docker.internal:${RECALL_PORT}" ]] ||
    die "backend VECTOR_SERVICE_URL must be http://host.docker.internal:${RECALL_PORT}"
}

validate_job_env() {
  local file=${1:-$JOB_ENV}
  local key value resolved
  local -a cache_keys=(MODEL_CACHE_ROOT VIBELO_HF_HOME TORCH_HOME XDG_CACHE XDG_CACHE_HOME VIBELO_VECTOR_READY_MARKER)
  local -a offline_keys=(VIBELO_REQUIRE_DATA_CACHE VIBELO_MODEL_OFFLINE HF_HUB_OFFLINE TRANSFORMERS_OFFLINE HF_DATASETS_OFFLINE VIBELO_REQUIRE_VECTOR_READY_MARKER)

  if grep -Eq '^(VIBELO_DB_|SPRING_DATASOURCE_|MYSQL_|MINIO_|ALIYUN_|APP_AUTH_TOKEN_)' "$file"; then
    die "$file contains credentials that belong outside the shared runtime environment"
  fi
  for key in "${cache_keys[@]}"; do
    value=$(plain_env_value "$file" "$key") || die "$file is missing $key"
    resolved=$(realpath -m -- "$value")
    [[ $resolved == /data/* ]] || die "$key must resolve below /data"
  done
  for key in "${offline_keys[@]}"; do
    value=$(plain_env_value "$file" "$key") || die "$file is missing $key"
    [[ $value == 1 ]] || die "$key must be 1"
  done
  value=$(plain_env_value "$file" VIBELO_USE_HF_PROXY) || die "$file is missing VIBELO_USE_HF_PROXY"
  [[ $value == 0 ]] || die "VIBELO_USE_HF_PROXY must be 0"
  value=$(plain_env_value "$file" VIBELO_EMBED_PROJECTION_VERSION) || \
    die "$file is missing VIBELO_EMBED_PROJECTION_VERSION"
  [[ $value == "$SUPPORTED_PROJECTION_VERSION" ]] || \
    die "VIBELO_EMBED_PROJECTION_VERSION does not match this vector worker"
  value=$(plain_env_value "$file" VIBELO_EMBED_MODEL_PATH) || die "$file is missing VIBELO_EMBED_MODEL_PATH"
  resolved=$(realpath -m -- "$value")
  [[ $resolved == /data/* && -d $resolved ]] || die "the offline embedding model directory is missing below /data"
}

unit_active_state() {
  systemctl show --property=ActiveState --value "$1" 2>/dev/null || true
}

restore_vector_timer_before_publish() {
  case "$TIMER_ENABLE_STATE" in
    enabled)
      systemctl enable vibelo-vectorize.timer || return 1
      ;;
    enabled-runtime)
      systemctl enable --runtime vibelo-vectorize.timer || return 1
      ;;
    disabled|not-found|'')
      ;;
    *)
      return 1
      ;;
  esac
  if ((TIMER_WAS_ACTIVE == 1)); then
    systemctl start vibelo-vectorize.timer || return 1
  fi
}

pause_vector_timer() {
  local timer_state disabled_state service_state

  timer_state=$(unit_active_state vibelo-vectorize.timer)
  case "$timer_state" in
    active|activating|reloading) TIMER_WAS_ACTIVE=1 ;;
  esac

  TIMER_ENABLE_STATE=$(systemctl is-enabled vibelo-vectorize.timer 2>/dev/null || true)
  case "$TIMER_ENABLE_STATE" in
    enabled|enabled-runtime|disabled|not-found|'') ;;
    *) die "vibelo-vectorize.timer has unsupported enable state: $TIMER_ENABLE_STATE" ;;
  esac

  # Mark the restoration barrier before mutating systemd state. A failure
  # before the configuration publish boundary must attempt to restore the
  # exact enabled/active state captured above.
  TIMER_QUIESCED=1
  if [[ $TIMER_ENABLE_STATE == not-found || -z $TIMER_ENABLE_STATE ]]; then
    systemctl stop vibelo-vectorize.timer >/dev/null 2>&1 || true
  else
    systemctl disable --now vibelo-vectorize.timer || \
      die "cannot disable and stop vibelo-vectorize.timer"
  fi

  timer_state=$(unit_active_state vibelo-vectorize.timer)
  case "$timer_state" in
    active|activating|reloading)
      die "vibelo-vectorize.timer is still active after disable --now"
      ;;
  esac
  disabled_state=$(systemctl is-enabled vibelo-vectorize.timer 2>/dev/null || true)
  case "$disabled_state" in
    enabled|enabled-runtime)
      die "vibelo-vectorize.timer is still enabled after disable --now"
      ;;
  esac

  service_state=$(unit_active_state vibelo-vectorize.service)
  case "$service_state" in
    active|activating|reloading|deactivating)
      die "vibelo-vectorize.service is running; wait for it to finish before reinstalling"
      ;;
  esac
}

validate_ready_marker() {
  local file=${1:-$JOB_ENV}
  local marker model version collection projection_version
  marker=$(plain_env_value "$file" VIBELO_VECTOR_READY_MARKER) || die "$file is missing VIBELO_VECTOR_READY_MARKER"
  model=$(plain_env_value "$file" VIBELO_EMBED_MODEL) || die "$file is missing VIBELO_EMBED_MODEL"
  version=$(plain_env_value "$file" VIBELO_EMBED_VECTOR_VERSION) || die "$file is missing VIBELO_EMBED_VECTOR_VERSION"
  collection=$(plain_env_value "$file" VIBELO_MILVUS_COLLECTION) || die "$file is missing VIBELO_MILVUS_COLLECTION"
  projection_version=$(plain_env_value "$file" VIBELO_EMBED_PROJECTION_VERSION) || \
    die "$file is missing VIBELO_EMBED_PROJECTION_VERSION"
  [[ -f $marker && ! -L $marker ]] || die "full vector coverage marker is missing; finish vectorization before recall"
  runuser -u "$RECALL_USER" -- "$REPO_ROOT/.venv-vector/bin/python" - \
    "$marker" "$model" "$version" "$collection" "$projection_version" <<'PY' || \
    die "full vector coverage marker does not match the configured artifact"
import json
import sys

path, model, version, collection, projection_version = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    payload = json.load(stream)
if payload.get("model") != model or payload.get("vectorVersion") != version:
    raise SystemExit(1)
if payload.get("collection") != collection or payload.get("metric") != "COSINE":
    raise SystemExit(1)
if payload.get("projectionVersion") != projection_version:
    raise SystemExit(1)
if payload.get("dimension") != 512:
    raise SystemExit(1)
ready = payload.get("ready")
entities = payload.get("entities")
fingerprint = payload.get("idSetSha256")
if not isinstance(ready, int) or ready <= 0 or entities != ready:
    raise SystemExit(1)
if not isinstance(fingerprint, str) or len(fingerprint) != 64:
    raise SystemExit(1)
PY
}

verify_recall_listener() {
  local expected="${BACKEND_GATEWAY}:${RECALL_PORT}"
  local attempt
  local -a listeners=()

  for attempt in $(seq 1 30); do
    mapfile -t listeners < <(
      ss -H -ltn "sport = :${RECALL_PORT}" | awk '{print $4}' | sort -u
    )
    if ((${#listeners[@]} > 0)); then
      ((${#listeners[@]} == 1)) || die "recall port has multiple listeners"
      [[ ${listeners[0]} == "$expected" ]] || die "recall service bound ${listeners[0]} instead of $expected"
      return 0
    fi
    sleep 1
  done
  die "recall service did not listen on $expected"
}

main() {
  local total_memory_kb model_path
  local enable_recall=0

  while (($# > 0)); do
    case "$1" in
      --enable-recall) enable_recall=1 ;;
      --help)
        printf 'Usage: %s [--enable-recall]\n' "$0"
        printf 'Without --enable-recall, install the timer and recall unit but do not start recall.\n'
        return 0
        ;;
      *) die "unknown argument: $1" ;;
    esac
    shift
  done

  # An explicit recall validation request is fail-closed from this point on:
  # any later gate failure also stops and disables a previously running unit.
  ((enable_recall == 0)) || VALIDATING_RECALL=1

  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "run as root"
  for command in awk chmod chown cp cut docker find getent grep groupadd id install ip mapfile mktemp mountpoint mv realpath rm runuser sed seq sort ss systemctl tail useradd usermod; do
    require_command "$command"
  done
  total_memory_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
  [[ $total_memory_kb =~ ^[0-9]+$ ]] || die "cannot read host memory"
  ((total_memory_kb >= MIN_TOTAL_MEMORY_KB)) || die "vector services require at least 15 GiB RAM"
  mountpoint -q /data || die "/data is not an independent mount point"
  [[ -f $PUBLIC_ENV ]] || die "missing $PUBLIC_ENV"
  [[ -x $REPO_ROOT/.venv-vector/bin/python ]] || die "missing executable .venv-vector Python"
  [[ -r $REPO_ROOT/tools/vectorize_images.py && -r $REPO_ROOT/tools/vector_recall_service.py ]] ||
    die "vector scripts are missing"

  pause_vector_timer

  ensure_service_identity
  # /etc/vibelo is shared with other isolated job users. Keep the directory
  # traversable and protect secrets on each environment file instead.
  install -d -o root -g root -m 0755 "$CONFIG_DIR"
  TEMP_DB_ENV=$(mktemp "$CONFIG_DIR/.vector-db.candidate.XXXXXXXX")
  extract_minimal_db_env "$TEMP_DB_ENV"

  [[ ! -L $JOB_ENV ]] || die "$JOB_ENV must not be a symbolic link"
  TEMP_JOB_ENV=$(mktemp "$CONFIG_DIR/.vector-job.candidate.XXXXXXXX")
  if [[ -f $JOB_ENV ]]; then
    cp -- "$JOB_ENV" "$TEMP_JOB_ENV"
  elif [[ -e $JOB_ENV ]]; then
    die "$JOB_ENV must be a regular file"
  else
    cp -- "$REPO_ROOT/ops/jobs/vector-job.env.example" "$TEMP_JOB_ENV"
  fi
  chown root:"$RUNTIME_GROUP" "$TEMP_JOB_ENV"
  chmod 0640 "$TEMP_JOB_ENV"

  discover_backend_bridge
  if ((enable_recall == 0)) && systemctl is-active --quiet vibelo-vector-recall.service; then
    die "vector recall is already active; rerun with --enable-recall to validate it before preserving autostart"
  fi
  set_env_literal "$TEMP_JOB_ENV" VIBELO_VECTOR_RECALL_HOST "$BACKEND_GATEWAY"
  set_env_literal "$TEMP_JOB_ENV" VIBELO_VECTOR_RECALL_PORT "$RECALL_PORT"
  set_env_literal "$TEMP_JOB_ENV" VIBELO_VECTOR_RECALL_MAX_LIMIT 240
  set_env_literal "$TEMP_JOB_ENV" VIBELO_REQUIRE_PRIVATE_BRIDGE_BIND 1
  set_env_literal "$TEMP_JOB_ENV" MODEL_CACHE_ROOT /data/vibelo-vector/cache
  set_env_literal "$TEMP_JOB_ENV" VIBELO_HF_HOME /data/vibelo-vector/cache/huggingface
  set_env_literal "$TEMP_JOB_ENV" TORCH_HOME /data/vibelo-vector/cache/torch
  set_env_literal "$TEMP_JOB_ENV" VIBELO_TORCH_HOME /data/vibelo-vector/cache/torch
  set_env_literal "$TEMP_JOB_ENV" XDG_CACHE /data/vibelo-vector/cache/xdg
  set_env_literal "$TEMP_JOB_ENV" XDG_CACHE_HOME /data/vibelo-vector/cache/xdg
  set_env_literal "$TEMP_JOB_ENV" VIBELO_REQUIRE_DATA_CACHE 1
  set_env_literal "$TEMP_JOB_ENV" VIBELO_MODEL_OFFLINE 1
  set_env_literal "$TEMP_JOB_ENV" HF_HUB_OFFLINE 1
  set_env_literal "$TEMP_JOB_ENV" TRANSFORMERS_OFFLINE 1
  set_env_literal "$TEMP_JOB_ENV" HF_DATASETS_OFFLINE 1
  set_env_literal "$TEMP_JOB_ENV" VIBELO_REQUIRE_VECTOR_READY_MARKER 1
  set_env_literal "$TEMP_JOB_ENV" VIBELO_USE_HF_PROXY 0
  set_env_literal "$TEMP_JOB_ENV" VIBELO_EMBED_PROJECTION_VERSION "$SUPPORTED_PROJECTION_VERSION"
  validate_job_env "$TEMP_JOB_ENV"

  for path in \
    /data/vibelo-vector \
    /data/vibelo-vector/cache \
    /data/vibelo-vector/cache/huggingface \
    /data/vibelo-vector/cache/torch \
    /data/vibelo-vector/cache/xdg \
    /data/vibelo-vector/state; do
    assert_safe_vector_path "$path"
  done
  install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 /data/vibelo-vector
  install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 /data/vibelo-vector/cache
  install -d -o "$SERVICE_USER" -g "$RUNTIME_GROUP" -m 2750 /data/vibelo-vector/state
  for path in huggingface torch xdg; do
    install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 "/data/vibelo-vector/cache/$path"
  done

  if find /data/vibelo-vector/cache /data/vibelo-vector/state -xdev -type l -print -quit | grep -q .; then
    die "vector cache/state trees must not contain symbolic links"
  fi
  find /data/vibelo-vector/cache -xdev \( -type d -o -type f \) \
    -exec chown "$SERVICE_USER:$SERVICE_GROUP" -- {} +
  if [[ -e /data/vibelo-vector/state/ready.json ]]; then
    [[ -f /data/vibelo-vector/state/ready.json && ! -L /data/vibelo-vector/state/ready.json ]] || \
      die "vector ready marker must be a regular file"
    chown "$SERVICE_USER:$RUNTIME_GROUP" /data/vibelo-vector/state/ready.json
    chmod 0640 /data/vibelo-vector/state/ready.json
  fi

  model_path=$(plain_env_value "$TEMP_JOB_ENV" VIBELO_EMBED_MODEL_PATH)
  runuser -u "$SERVICE_USER" -- test -x "$REPO_ROOT/.venv-vector/bin/python" || die "service user cannot execute vector Python"
  runuser -u "$SERVICE_USER" -- test -r "$REPO_ROOT/tools/vectorize_images.py" || die "service user cannot read vector worker"
  runuser -u "$SERVICE_USER" -- test -r "$REPO_ROOT/tools/vector_recall_service.py" || die "service user cannot read recall service"
  runuser -u "$SERVICE_USER" -- test -r "$model_path" || die "service user cannot read embedding model"
  runuser -u "$SERVICE_USER" -- test -x "$model_path" || die "service user cannot traverse embedding model"
  runuser -u "$SERVICE_USER" -- test -r "$TEMP_DB_ENV" || die "vectorizer cannot read its database environment"
  runuser -u "$RECALL_USER" -- test -r "$TEMP_JOB_ENV" || die "recall user cannot read the shared non-secret environment"
  if runuser -u "$RECALL_USER" -- test -r "$TEMP_DB_ENV"; then
    die "recall user must not be able to read database credentials"
  fi
  ((enable_recall == 0)) || validate_ready_marker "$TEMP_JOB_ENV"

  # From this point a failure deliberately leaves the timer disabled. The two
  # environment files are separate filesystem objects and cannot be replaced
  # as one transaction, so restoring the old timer after only one successful
  # rename could run a mixed configuration.
  CONFIG_PUBLISH_STARTED=1
  mv -f -- "$TEMP_DB_ENV" "$DB_ENV"
  TEMP_DB_ENV=''
  mv -f -- "$TEMP_JOB_ENV" "$JOB_ENV"
  TEMP_JOB_ENV=''

  install -m 0644 "$REPO_ROOT/ops/jobs/systemd/vibelo-vectorize.service" /etc/systemd/system/
  install -m 0644 "$REPO_ROOT/ops/jobs/systemd/vibelo-vectorize.timer" /etc/systemd/system/
  install -m 0644 "$REPO_ROOT/ops/jobs/systemd/vibelo-vector-recall.service" /etc/systemd/system/
  systemctl daemon-reload
  TIMER_ENABLED_BY_INSTALL=1
  systemctl enable --now vibelo-vectorize.timer
  if ((enable_recall == 1)); then
    systemctl enable vibelo-vector-recall.service
    systemctl restart vibelo-vector-recall.service
    systemctl is-active --quiet vibelo-vector-recall.service || die "vector recall service failed to start"
    verify_recall_listener
    docker exec "$BACKEND_CONTAINER_ID" \
      wget -q -O - -T 10 "http://host.docker.internal:${RECALL_PORT}/health" |
      grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' || die "backend container cannot reach a ready vector recall service"
    VALIDATING_RECALL=0
    printf 'Vector recall is ready and binds only %s:%s.\n' "$BACKEND_GATEWAY" "$RECALL_PORT"
  else
    systemctl disable vibelo-vector-recall.service >/dev/null 2>&1 || \
      die "cannot disable unvalidated vector recall autostart"
    printf 'Vector timer installed; recall was not enabled or started before its collection is ready.\n'
    printf 'After the first vector index succeeds, run: sudo /usr/bin/bash %s --enable-recall\n' "$0"
  fi
  systemctl list-timers vibelo-vectorize.timer --no-pager
  INSTALL_SUCCEEDED=1
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi
