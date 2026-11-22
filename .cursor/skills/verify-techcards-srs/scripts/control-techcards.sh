#!/usr/bin/env bash
set -euo pipefail

# Isolated verification harness for TechCards SRS.
# Manages dedicated Docker Compose projects (db + migrate + api) on free loopback
# ports so verification never interferes with a running local dev stack, drives
# real HTTP endpoints with curl, inspects PostgreSQL side effects via a dedicated
# read-only role, captures proof artifacts (including failed transport attempts),
# and tears down only what it started.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
VERIFY_STATE_ROOT="${VERIFY_STATE_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/verify-techcards-srs}"
INSTANCES_ROOT="$VERIFY_STATE_ROOT/instances"
DEFAULT_EVIDENCE_ROOT="$VERIFY_STATE_ROOT/evidence"

# Fixed verification-only Compose settings (never inherited from caller's exported env).
VERIFY_POSTGRES_USER="techcards"
VERIFY_POSTGRES_PASSWORD="local-development-only"
VERIFY_POSTGRES_DB="techcards"
VERIFY_DB_RO_USER="techcards_ro"
VERIFY_GENERATOR_PROVIDER="mock"

usage() {
  cat <<'EOF'
Usage: control-techcards.sh <command> [args...]

Commands:
  launch [--run-id ID] [--api-port PORT] [--db-port PORT] [--evidence-dir DIR]
      Start an isolated Docker Compose stack (fresh Postgres volume -> migrate -> api),
      provision a read-only DB inspection role, and wait until DB, migrations, and API
      are fully usable.
      Run IDs must match ^[a-z0-9][a-z0-9_-]*$ (1-to-1 with Compose project names).
      Evidence directories must be fresh (not already existing) and outside scratch state.

  doctor <run-id> [--save]
      Read-only health, build-freshness, port-ownership, DB, and migration check.
      Pass --save to also record the report to <evidence-dir>/doctor.txt.

  req <run-id> <step-name> <METHOD> <PATH> [JSON_BODY] [--body-only]
      Send a real HTTP request via curl and save request + status + headers + body
      (or transport error details if curl fails) under
      <evidence-dir>/steps/<step-name>.http.txt and .body.json.
      Pass --body-only to print only the response body to stdout.

  db-query <run-id> <label> <SQL>
      Run a read-only SQL query against the isolated Postgres container using the
      dedicated non-superuser SELECT-only role (techcards_ro), save the query and
      output to <evidence-dir>/db/<label>.txt, and print to stdout.

  logs <run-id> [service...]
      Capture Docker Compose logs (default: db migrate api) to
      <evidence-dir>/logs/compose.log.

  env <run-id>
      Print key paths and connection values for an active run (no credentials).

  cleanup <run-id>
      Tear down ONLY the Compose project, containers, network, volume, and scratch
      state for <run-id>. Preserves <evidence-dir> untouched.
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

resolve_repo_root() {
  if git -C "$DEFAULT_REPO_ROOT" rev-parse --show-toplevel >/dev/null 2>&1; then
    git -C "$DEFAULT_REPO_ROOT" rev-parse --show-toplevel
  else
    echo "$DEFAULT_REPO_ROOT"
  fi
}

validate_run_id() {
  local run_id="$1"
  if [[ ! "$run_id" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    die "Invalid run-id '$run_id' (must match ^[a-z0-9][a-z0-9_-]*$; lowercase letters, digits, _, - only so project names are strictly 1-to-1)"
  fi
}

assert_disjoint_paths() {
  local scratch_path="$1"
  local evidence_path="$2"
  python3 - "$scratch_path" "$evidence_path" <<'PY'
import os
import pathlib
import sys

scratch = pathlib.Path(os.path.realpath(sys.argv[1]))
evidence = pathlib.Path(os.path.realpath(sys.argv[2]))

if evidence == scratch or scratch in evidence.parents or evidence in scratch.parents:
    print(
        f"ERROR: evidence directory '{evidence}' overlaps scratch directory '{scratch}'. "
        "Choose an evidence directory outside the scratch state tree.",
        file=sys.stderr,
    )
    sys.exit(1)
PY
}

compute_source_hash() {
  local repo_root="$1"
  python3 - "$repo_root" <<'PY'
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
targets = [
    root / "Dockerfile",
    root / "alembic.ini",
    root / "compose.yaml",
    root / "pyproject.toml",
    root / "uv.lock",
]
for directory in ("app", "migrations"):
    base = root / directory
    if base.is_dir():
        for path in sorted(base.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                targets.append(path)

hasher = hashlib.sha256()
for path in sorted(set(targets)):
    if path.is_file():
        rel = path.relative_to(root).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
print(hasher.hexdigest()[:16])
PY
}

pick_free_port() {
  local exclude="${1:-0}"
  python3 - "$exclude" <<'PY'
import socket
import sys

exclude = int(sys.argv[1])
for _ in range(50):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        if port != exclude:
            print(port)
            sys.exit(0)
sys.exit(1)
PY
}

port_is_free() {
  local port="$1"
  python3 - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sys.exit(1)
sys.exit(0)
PY
}

load_instance() {
  local run_id="$1"
  validate_run_id "$run_id"
  local meta_file="$INSTANCES_ROOT/$run_id/instance.json"
  [[ -f "$meta_file" ]] || die "No active verification instance found for run-id '$run_id' (missing $meta_file)"

  local fields=()
  while IFS= read -r -d '' field; do
    fields+=("$field")
  done < <(python3 - "$meta_file" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
keys = [
    "run_id",
    "compose_project",
    "repo_root",
    "instance_dir",
    "evidence_dir",
    "api_port",
    "db_port",
    "base_url",
    "git_sha",
    "source_hash",
    "postgres_user",
    "postgres_db",
    "db_ro_user",
    "generator_provider",
    "created_at_utc",
]
for key in keys:
    if key not in data:
        print(f"Missing key '{key}' in {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(str(data[key]))
    sys.stdout.write("\0")
PY
  )

  [[ ${#fields[@]} -eq 15 ]] || die "Corrupt instance metadata in $meta_file"

  RUN_ID="${fields[0]}"
  COMPOSE_PROJECT="${fields[1]}"
  REPO_ROOT="${fields[2]}"
  INSTANCE_DIR="${fields[3]}"
  EVIDENCE_DIR="${fields[4]}"
  API_PORT="${fields[5]}"
  DB_PORT="${fields[6]}"
  BASE_URL="${fields[7]}"
  GIT_SHA="${fields[8]}"
  SOURCE_HASH="${fields[9]}"
  POSTGRES_USER="${fields[10]}"
  POSTGRES_DB="${fields[11]}"
  DB_RO_USER="${fields[12]}"
  GENERATOR_PROVIDER="${fields[13]}"
  CREATED_AT="${fields[14]}"

  [[ "$COMPOSE_PROJECT" == "verify-techcards-${RUN_ID}" ]] || die "Refusing to operate on unexpected Compose project: $COMPOSE_PROJECT"
}

compose_cmd() {
  # Explicitly override exported Compose variables so caller's shell env cannot
  # hijack POSTGRES_*, GENERATOR_PROVIDER, or DATABASE_URL for this isolated run.
  env \
    -u DATABASE_URL \
    COMPOSE_ANSI=never \
    BUILDKIT_PROGRESS=plain \
    POSTGRES_USER="$POSTGRES_USER" \
    POSTGRES_PASSWORD="$VERIFY_POSTGRES_PASSWORD" \
    POSTGRES_DB="$POSTGRES_DB" \
    POSTGRES_HOST_PORT="$DB_PORT" \
    GENERATOR_PROVIDER="$GENERATOR_PROVIDER" \
    docker compose \
    --progress=plain \
    -p "$COMPOSE_PROJECT" \
    --env-file "$INSTANCE_DIR/verify.env" \
    -f "$REPO_ROOT/compose.yaml" \
    -f "$INSTANCE_DIR/compose.override.yaml" \
    "$@"
}

provision_readonly_role() {
  compose_cmd exec -T db \
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL >/dev/null
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_RO_USER}') THEN
    CREATE ROLE ${DB_RO_USER} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END \$\$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE ${POSTGRES_DB} FROM ${DB_RO_USER};
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${DB_RO_USER};
REVOKE ALL ON SCHEMA public FROM ${DB_RO_USER};
GRANT USAGE ON SCHEMA public TO ${DB_RO_USER};
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ${DB_RO_USER};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${DB_RO_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT SELECT ON TABLES TO ${DB_RO_USER};
SQL
}

cmd_launch() {
  require_cmd docker
  require_cmd curl
  require_cmd python3

  local run_id=""
  local api_port="${VERIFY_API_PORT:-}"
  local db_port="${VERIFY_DB_PORT:-}"
  local evidence_dir="${VERIFY_EVIDENCE_DIR:-}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run-id)
        [[ $# -ge 2 ]] || die "--run-id requires a value"
        run_id="$2"
        shift 2
        ;;
      --api-port)
        [[ $# -ge 2 ]] || die "--api-port requires a value"
        api_port="$2"
        shift 2
        ;;
      --db-port)
        [[ $# -ge 2 ]] || die "--db-port requires a value"
        db_port="$2"
        shift 2
        ;;
      --evidence-dir)
        [[ $# -ge 2 ]] || die "--evidence-dir requires a value"
        evidence_dir="$2"
        shift 2
        ;;
      *)
        die "Unknown launch option: $1"
        ;;
    esac
  done

  if [[ -z "$run_id" ]]; then
    local suffix
    suffix="$(python3 -c 'import secrets; print(secrets.token_hex(2))')"
    run_id="v-$(date -u +%Y%m%d-%H%M%S)-$suffix"
  fi
  validate_run_id "$run_id"

  if [[ -z "$evidence_dir" ]]; then
    evidence_dir="$DEFAULT_EVIDENCE_ROOT/$run_id"
  fi

  mkdir -p "$INSTANCES_ROOT"
  local instance_dir="$INSTANCES_ROOT/$run_id"

  # Reject any evidence path overlapping the scratch state tree before reserving directories.
  assert_disjoint_paths "$INSTANCES_ROOT" "$evidence_dir"
  assert_disjoint_paths "$instance_dir" "$evidence_dir"

  if [[ -z "$api_port" ]]; then
    api_port="$(pick_free_port 0)"
  else
    port_is_free "$api_port" || die "Requested API port 127.0.0.1:$api_port is already in use"
  fi

  if [[ -z "$db_port" ]]; then
    db_port="$(pick_free_port "$api_port")"
  else
    [[ "$db_port" != "$api_port" ]] || die "API port and DB port must differ"
    port_is_free "$db_port" || die "Requested DB port 127.0.0.1:$db_port is already in use"
  fi

  # Atomically reserve both the scratch instance directory and a fresh evidence directory
  # so concurrent launches with the same run-id or reused evidence paths cannot collide.
  if ! mkdir "$instance_dir" 2>/dev/null; then
    die "Instance '$run_id' already exists or is currently launching ($instance_dir)"
  fi

  mkdir -p "$(dirname "$evidence_dir")"
  if ! mkdir "$evidence_dir" 2>/dev/null; then
    rmdir "$instance_dir" 2>/dev/null || true
    die "Evidence directory already exists ($evidence_dir). Use a fresh --run-id or --evidence-dir so runs are never mixed."
  fi

  # Re-verify canonicalized disjointness now that both directories exist on disk.
  if ! assert_disjoint_paths "$INSTANCES_ROOT" "$evidence_dir"; then
    rmdir "$evidence_dir" "$instance_dir" 2>/dev/null || true
    exit 1
  fi

  local repo_root git_sha source_hash compose_project base_url created_at
  repo_root="$(resolve_repo_root)"
  git_sha="$(git -C "$repo_root" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  source_hash="$(compute_source_hash "$repo_root")"
  compose_project="verify-techcards-${run_id}"
  base_url="http://127.0.0.1:${api_port}"
  created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  mkdir -p "$evidence_dir/steps" "$evidence_dir/db" "$evidence_dir/logs"

  cat >"$instance_dir/verify.env" <<EOF
POSTGRES_USER=${VERIFY_POSTGRES_USER}
POSTGRES_PASSWORD=${VERIFY_POSTGRES_PASSWORD}
POSTGRES_DB=${VERIFY_POSTGRES_DB}
POSTGRES_HOST_PORT=${db_port}
GENERATOR_PROVIDER=${VERIFY_GENERATOR_PROVIDER}
EOF

  cat >"$instance_dir/compose.override.yaml" <<EOF
services:
  db:
    ports: !override
      - "127.0.0.1:${db_port}:5432"
    labels:
      techcards.verify.run_id: "${run_id}"
      techcards.verify.git_sha: "${git_sha}"
      techcards.verify.source_hash: "${source_hash}"
  migrate:
    labels:
      techcards.verify.run_id: "${run_id}"
      techcards.verify.git_sha: "${git_sha}"
      techcards.verify.source_hash: "${source_hash}"
  api:
    ports: !override
      - "127.0.0.1:${api_port}:8000"
    labels:
      techcards.verify.run_id: "${run_id}"
      techcards.verify.git_sha: "${git_sha}"
      techcards.verify.source_hash: "${source_hash}"
EOF

  python3 - \
    "$instance_dir/instance.json" \
    "$evidence_dir/run-meta.json" \
    "$run_id" \
    "$compose_project" \
    "$repo_root" \
    "$instance_dir" \
    "$evidence_dir" \
    "$api_port" \
    "$db_port" \
    "$base_url" \
    "$git_sha" \
    "$source_hash" \
    "$VERIFY_POSTGRES_USER" \
    "$VERIFY_POSTGRES_DB" \
    "$VERIFY_DB_RO_USER" \
    "$VERIFY_GENERATOR_PROVIDER" \
    "$created_at" <<'PY'
import json
import pathlib
import sys

(
    instance_json,
    evidence_json,
    run_id,
    compose_project,
    repo_root,
    instance_dir,
    evidence_dir,
    api_port,
    db_port,
    base_url,
    git_sha,
    source_hash,
    pg_user,
    pg_db,
    db_ro_user,
    gen_provider,
    created_at,
) = sys.argv[1:]

instance_meta = {
    "run_id": run_id,
    "compose_project": compose_project,
    "repo_root": repo_root,
    "instance_dir": instance_dir,
    "evidence_dir": evidence_dir,
    "api_port": int(api_port),
    "db_port": int(db_port),
    "base_url": base_url,
    "git_sha": git_sha,
    "source_hash": source_hash,
    "postgres_user": pg_user,
    "postgres_db": pg_db,
    "db_ro_user": db_ro_user,
    "generator_provider": gen_provider,
    "created_at_utc": created_at,
}
pathlib.Path(instance_json).write_text(json.dumps(instance_meta, indent=2) + "\n", encoding="utf-8")

evidence_meta = {
    "run_id": run_id,
    "compose_project": compose_project,
    "repo_root": repo_root,
    "base_url": base_url,
    "api_port": int(api_port),
    "db_port": int(db_port),
    "git_sha": git_sha,
    "source_hash": source_hash,
    "postgres_user": pg_user,
    "postgres_db": pg_db,
    "db_ro_user": db_ro_user,
    "generator_provider": gen_provider,
    "created_at_utc": created_at,
}
pathlib.Path(evidence_json).write_text(json.dumps(evidence_meta, indent=2) + "\n", encoding="utf-8")
PY

  load_instance "$run_id"

  echo "Launching isolated TechCards SRS stack ($COMPOSE_PROJECT) on $BASE_URL (db 127.0.0.1:$DB_PORT)..."
  if ! compose_cmd up --build -d; then
    echo "Launch failed; capturing diagnostic logs to $EVIDENCE_DIR/logs/launch-failure.log" >&2
    compose_cmd ps -a >"$EVIDENCE_DIR/logs/launch-failure.log" 2>&1 || true
    compose_cmd logs --no-color >>"$EVIDENCE_DIR/logs/launch-failure.log" 2>&1 || true
    die "docker compose up failed. Run: $0 cleanup $run_id"
  fi

  local deadline=$((SECONDS + 90))
  local ready=0
  while (( SECONDS < deadline )); do
    local db_cid api_cid migrate_cid db_health api_health migrate_status migrate_exit
    db_cid="$(compose_cmd ps -q db 2>/dev/null || true)"
    api_cid="$(compose_cmd ps -q api 2>/dev/null || true)"
    migrate_cid="$(compose_cmd ps -a -q migrate 2>/dev/null || true)"

    db_health="$([[ -n "$db_cid" ]] && docker inspect -f '{{.State.Health.Status}}' "$db_cid" 2>/dev/null || echo missing)"
    api_health="$([[ -n "$api_cid" ]] && docker inspect -f '{{.State.Health.Status}}' "$api_cid" 2>/dev/null || echo missing)"
    migrate_status="$([[ -n "$migrate_cid" ]] && docker inspect -f '{{.State.Status}}' "$migrate_cid" 2>/dev/null || echo missing)"
    migrate_exit="$([[ -n "$migrate_cid" ]] && docker inspect -f '{{.State.ExitCode}}' "$migrate_cid" 2>/dev/null || echo -1)"

    if [[ "$db_health" == "healthy" && "$migrate_status" == "exited" && "$migrate_exit" == "0" && "$api_health" == "healthy" ]]; then
      local health_code decks_code
      health_code="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_URL/health" 2>/dev/null || echo 000)"
      decks_code="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_URL/decks" 2>/dev/null || echo 000)"
      if [[ "$health_code" == "200" && "$decks_code" == "200" ]]; then
        ready=1
        break
      fi
    fi
    sleep 1
  done

  if (( ready == 0 )); then
    compose_cmd ps -a >"$EVIDENCE_DIR/logs/launch-timeout.log" 2>&1 || true
    compose_cmd logs --no-color >>"$EVIDENCE_DIR/logs/launch-timeout.log" 2>&1 || true
    die "Timed out waiting for stack readiness (see $EVIDENCE_DIR/logs/launch-timeout.log). Run: $0 cleanup $run_id"
  fi

  if ! provision_readonly_role; then
    compose_cmd logs --no-color >"$EVIDENCE_DIR/logs/launch-role-failure.log" 2>&1 || true
    die "Failed to provision read-only DB role '$DB_RO_USER'. Run: $0 cleanup $run_id"
  fi

  echo "READY"
  echo "RUN_ID=$RUN_ID"
  echo "COMPOSE_PROJECT=$COMPOSE_PROJECT"
  echo "BASE_URL=$BASE_URL"
  echo "DB_PORT=$DB_PORT"
  echo "EVIDENCE_DIR=$EVIDENCE_DIR"
}

cmd_doctor() {
  require_cmd docker
  require_cmd curl
  require_cmd python3

  local run_id=""
  local save_report=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --save)
        save_report=1
        shift
        ;;
      -*)
        die "Unknown doctor option: $1"
        ;;
      *)
        if [[ -z "$run_id" ]]; then
          run_id="$1"
          shift
        else
          die "Unexpected argument: $1"
        fi
        ;;
    esac
  done
  [[ -n "$run_id" ]] || die "Usage: control-techcards.sh doctor <run-id> [--save]"

  load_instance "$run_id"

  local report=""
  local failures=0

  record() {
    local status="$1"
    local name="$2"
    local detail="$3"
    local line
    line="$(printf '[%s] %-20s %s' "$status" "$name" "$detail")"
    report+="${line}"$'\n'
    if [[ "$status" == "FAIL" ]]; then
      failures=$((failures + 1))
    fi
  }

  record "PASS" "instance_state" "run_id=$RUN_ID project=$COMPOSE_PROJECT"

  local db_cid migrate_cid api_cid
  db_cid="$(compose_cmd ps -q db 2>/dev/null || true)"
  migrate_cid="$(compose_cmd ps -a -q migrate 2>/dev/null || true)"
  api_cid="$(compose_cmd ps -q api 2>/dev/null || true)"

  local db_health="missing"
  if [[ -n "$db_cid" ]]; then
    db_health="$(docker inspect -f '{{.State.Health.Status}}' "$db_cid" 2>/dev/null || echo unknown)"
  fi
  if [[ "$db_health" == "healthy" ]]; then
    record "PASS" "db_container" "id=${db_cid:0:12} health=$db_health"
  else
    record "FAIL" "db_container" "id=${db_cid:-none} health=$db_health"
  fi

  local migrate_status="missing" migrate_exit="-1"
  if [[ -n "$migrate_cid" ]]; then
    migrate_status="$(docker inspect -f '{{.State.Status}}' "$migrate_cid" 2>/dev/null || echo unknown)"
    migrate_exit="$(docker inspect -f '{{.State.ExitCode}}' "$migrate_cid" 2>/dev/null || echo -1)"
  fi
  if [[ "$migrate_status" == "exited" && "$migrate_exit" == "0" ]]; then
    record "PASS" "migrate_container" "id=${migrate_cid:0:12} status=$migrate_status exit_code=$migrate_exit"
  else
    record "FAIL" "migrate_container" "id=${migrate_cid:-none} status=$migrate_status exit_code=$migrate_exit"
  fi

  local api_status="missing" api_health="missing"
  if [[ -n "$api_cid" ]]; then
    api_status="$(docker inspect -f '{{.State.Status}}' "$api_cid" 2>/dev/null || echo unknown)"
    api_health="$(docker inspect -f '{{.State.Health.Status}}' "$api_cid" 2>/dev/null || echo unknown)"
  fi
  if [[ "$api_status" == "running" && "$api_health" == "healthy" ]]; then
    record "PASS" "api_container" "id=${api_cid:0:12} status=$api_status health=$api_health"
  else
    record "FAIL" "api_container" "id=${api_cid:-none} status=$api_status health=$api_health"
  fi

  local mapped_api mapped_db
  mapped_api="$(compose_cmd port api 8000 2>/dev/null || true)"
  mapped_db="$(compose_cmd port db 5432 2>/dev/null || true)"
  if [[ "$mapped_api" == "127.0.0.1:${API_PORT}" && "$mapped_db" == "127.0.0.1:${DB_PORT}" ]]; then
    record "PASS" "port_ownership" "api=$mapped_api db=$mapped_db"
  else
    record "FAIL" "port_ownership" "expected api=127.0.0.1:${API_PORT} db=127.0.0.1:${DB_PORT}; got api=${mapped_api:-none} db=${mapped_db:-none}"
  fi

  if [[ "$mapped_api" == 127.0.0.1:* && "$mapped_db" == 127.0.0.1:* ]]; then
    record "PASS" "auth_surface" "no auth configured (loopback-only MVP; ports bound strictly to 127.0.0.1)"
  else
    record "FAIL" "auth_surface" "ports not bound exclusively to 127.0.0.1"
  fi

  local running_hash current_hash
  running_hash="$([[ -n "$api_cid" ]] && docker inspect -f '{{index .Config.Labels "techcards.verify.source_hash"}}' "$api_cid" 2>/dev/null || echo missing)"
  current_hash="$(compute_source_hash "$REPO_ROOT")"
  if [[ "$running_hash" == "$current_hash" ]]; then
    record "PASS" "build_freshness" "source_hash=$running_hash git_sha=$GIT_SHA"
  else
    record "FAIL" "build_freshness" "stale build (running=$running_hash checkout=$current_hash); cleanup and relaunch"
  fi

  local health_tmp openapi_tmp decks_tmp
  health_tmp="$(mktemp)"
  openapi_tmp="$(mktemp)"
  decks_tmp="$(mktemp)"

  local health_code
  health_code="$(curl -sS -o "$health_tmp" -w '%{http_code}' "$BASE_URL/health" 2>/dev/null || echo 000)"
  if [[ "$health_code" == "200" ]] && python3 - "$health_tmp" <<'PY'
import json, pathlib, sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
sys.exit(0 if data == {"status": "ok"} else 1)
PY
  then
    record "PASS" "health_endpoint" "GET /health -> 200 {\"status\":\"ok\"}"
  else
    record "FAIL" "health_endpoint" "GET /health -> HTTP $health_code"
  fi

  local openapi_code openapi_info
  openapi_code="$(curl -sS -o "$openapi_tmp" -w '%{http_code}' "$BASE_URL/openapi.json" 2>/dev/null || echo 000)"
  if [[ "$openapi_code" == "200" ]] && openapi_info="$(python3 - "$openapi_tmp" <<'PY'
import json, pathlib, sys
doc = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
info = doc.get("info", {})
paths = set(doc.get("paths", {}).keys())
required = {"/health", "/decks", "/decks/{deck_id}", "/decks/{deck_id}/due", "/cards", "/cards/{card_id}", "/cards/generate", "/reviews"}
if info.get("title") != "TechCards SRS" or not required.issubset(paths):
    sys.exit(1)
print(f"title={info.get('title')!r} version={info.get('version')!r} routes={len(paths)}")
PY
  )"; then
    record "PASS" "openapi_identity" "$openapi_info"
  else
    record "FAIL" "openapi_identity" "GET /openapi.json -> HTTP $openapi_code or unexpected schema"
  fi

  local decks_code decks_count
  decks_code="$(curl -sS -o "$decks_tmp" -w '%{http_code}' "$BASE_URL/decks" 2>/dev/null || echo 000)"
  if [[ "$decks_code" == "200" ]] && decks_count="$(python3 - "$decks_tmp" <<'PY'
import json, pathlib, sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(data, list):
    sys.exit(1)
print(len(data))
PY
  )"; then
    record "PASS" "db_connectivity" "GET /decks -> 200 (decks=$decks_count)"
  else
    record "FAIL" "db_connectivity" "GET /decks -> HTTP $decks_code"
  fi

  rm -f "$health_tmp" "$openapi_tmp" "$decks_tmp"

  local alembic_current alembic_head
  alembic_current="$(compose_cmd exec -T api alembic current 2>/dev/null | awk 'NF {print $1; exit}' || true)"
  alembic_head="$(compose_cmd exec -T api alembic heads 2>/dev/null | awk 'NF {print $1; exit}' || true)"
  if [[ -n "$alembic_current" && "$alembic_current" == "$alembic_head" ]]; then
    record "PASS" "migrations_head" "alembic_current=$alembic_current matches head=$alembic_head"
  else
    record "FAIL" "migrations_head" "alembic_current=${alembic_current:-none} head=${alembic_head:-none}"
  fi

  local ro_check
  ro_check="$(compose_cmd exec -T -e PGOPTIONS="-c default_transaction_read_only=on" db \
    psql -At -v ON_ERROR_STOP=1 -U "$DB_RO_USER" -d "$POSTGRES_DB" -c "SELECT current_user;" 2>/dev/null || true)"
  if [[ "$ro_check" == "$DB_RO_USER" ]]; then
    record "PASS" "db_readonly_role" "role=$DB_RO_USER connected to db=$POSTGRES_DB"
  else
    record "FAIL" "db_readonly_role" "failed to connect as read-only role '$DB_RO_USER'"
  fi

  printf '%s' "$report"
  if (( failures == 0 )); then
    echo "DOCTOR: HEALTHY (12/12 checks passed)"
  else
    echo "DOCTOR: UNHEALTHY ($failures check(s) failed)"
  fi

  if (( save_report == 1 )); then
    mkdir -p "$EVIDENCE_DIR"
    {
      echo "# Doctor report ($RUN_ID) at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      printf '%s' "$report"
      if (( failures == 0 )); then
        echo "DOCTOR: HEALTHY (12/12 checks passed)"
      else
        echo "DOCTOR: UNHEALTHY ($failures check(s) failed)"
      fi
    } >"$EVIDENCE_DIR/doctor.txt"
  fi

  return $(( failures == 0 ? 0 : 1 ))
}

cmd_req() {
  require_cmd curl
  require_cmd python3

  local body_only=0
  local positional=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --body-only)
        body_only=1
        shift
        ;;
      *)
        positional+=("$1")
        shift
        ;;
    esac
  done

  [[ ${#positional[@]} -ge 4 && ${#positional[@]} -le 5 ]] || die "Usage: control-techcards.sh req <run-id> <step-name> <METHOD> <PATH> [JSON_BODY] [--body-only]"

  local run_id="${positional[0]}"
  local step_name="${positional[1]}"
  local method="${positional[2]}"
  local path="${positional[3]}"
  local json_body="${positional[4]:-}"

  if [[ ! "$step_name" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    die "Invalid step-name '$step_name' (allowed: letters, digits, ., _, -)"
  fi

  load_instance "$run_id"
  mkdir -p "$EVIDENCE_DIR/steps"

  local url="${BASE_URL}${path}"
  local hdr_tmp body_tmp err_tmp
  hdr_tmp="$(mktemp)"
  body_tmp="$(mktemp)"
  err_tmp="$(mktemp)"

  local curl_args=(-sS -D "$hdr_tmp" -o "$body_tmp" -X "$method")
  if [[ -n "$json_body" ]]; then
    curl_args+=(-H "Content-Type: application/json" --data-raw "$json_body")
  fi

  local http_code="000"
  local curl_rc=0
  http_code="$(curl "${curl_args[@]}" -w '%{http_code}' "$url" 2>"$err_tmp")" || curl_rc=$?

  local transcript="$EVIDENCE_DIR/steps/${step_name}.http.txt"
  local body_file="$EVIDENCE_DIR/steps/${step_name}.body.json"
  local timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  {
    echo "=== REQUEST (${timestamp}) ==="
    echo "${method} ${url}"
    if [[ -n "$json_body" ]]; then
      echo "Content-Type: application/json"
      echo ""
      echo "$json_body"
    fi
    echo ""
    if (( curl_rc != 0 )); then
      echo "=== TRANSPORT ERROR (curl exit ${curl_rc}, HTTP ${http_code}) ==="
      if [[ -s "$err_tmp" ]]; then
        cat "$err_tmp"
      else
        echo "<no stderr output>"
      fi
      if [[ -s "$hdr_tmp" ]]; then
        echo ""
        echo "=== PARTIAL HEADERS ==="
        tr -d '\r' <"$hdr_tmp"
      fi
    else
      echo "=== RESPONSE (HTTP ${http_code}) ==="
      tr -d '\r' <"$hdr_tmp"
    fi
    if [[ -s "$body_tmp" ]]; then
      python3 - "$body_tmp" <<'PY'
import json, pathlib, sys
raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
try:
    print(json.dumps(json.loads(raw), indent=2))
except Exception:
    print(raw)
PY
    else
      echo "<empty body>"
    fi
  } >"$transcript"

  if [[ -s "$body_tmp" ]]; then
    python3 - "$body_tmp" "$body_file" <<'PY'
import json, pathlib, sys
raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
out = pathlib.Path(sys.argv[2])
try:
    out.write_text(json.dumps(json.loads(raw), indent=2) + "\n", encoding="utf-8")
except Exception:
    out.write_text(raw, encoding="utf-8")
PY
  else
    : >"$body_file"
  fi

  local err_msg=""
  if [[ -s "$err_tmp" ]]; then
    err_msg="$(cat "$err_tmp")"
  fi
  rm -f "$hdr_tmp" "$body_tmp" "$err_tmp"

  if (( curl_rc != 0 )); then
    echo "ERROR: curl transport failed (exit $curl_rc, HTTP $http_code) for $method $path -> recorded $transcript" >&2
    if [[ -n "$err_msg" ]]; then
      echo "$err_msg" >&2
    fi
    return "$curl_rc"
  fi

  if (( body_only == 1 )); then
    cat "$body_file"
  else
    echo "HTTP $http_code ($method $path) -> saved $transcript"
    if [[ -s "$body_file" ]]; then
      cat "$body_file"
    else
      echo "<empty body>"
    fi
  fi
}

cmd_db_query() {
  require_cmd docker
  [[ $# -eq 3 ]] || die "Usage: control-techcards.sh db-query <run-id> <label> <SQL>"

  local run_id="$1"
  local label="$2"
  local sql="$3"

  if [[ ! "$label" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    die "Invalid label '$label' (allowed: letters, digits, ., _, -)"
  fi

  load_instance "$run_id"
  mkdir -p "$EVIDENCE_DIR/db"

  local out_file="$EVIDENCE_DIR/db/${label}.txt"
  local timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  local result
  result="$(compose_cmd exec -T -e PGOPTIONS="-c default_transaction_read_only=on" db \
    psql -v ON_ERROR_STOP=1 -U "$DB_RO_USER" -d "$POSTGRES_DB" -c "$sql")"

  {
    echo "=== DB QUERY (${timestamp}, role=${DB_RO_USER}) ==="
    echo "$sql"
    echo ""
    echo "=== RESULT ==="
    printf '%s\n' "$result"
  } >"$out_file"

  printf '%s\n' "$result"
}

cmd_logs() {
  require_cmd docker
  [[ $# -ge 1 ]] || die "Usage: control-techcards.sh logs <run-id> [service...]"
  local run_id="$1"
  shift

  load_instance "$run_id"
  mkdir -p "$EVIDENCE_DIR/logs"

  local out_file="$EVIDENCE_DIR/logs/compose.log"
  if [[ $# -eq 0 ]]; then
    compose_cmd logs --no-color db migrate api >"$out_file" 2>&1
  else
    compose_cmd logs --no-color "$@" >"$out_file" 2>&1
  fi

  local lines
  lines="$(wc -l <"$out_file" | tr -d ' ')"
  echo "Saved $lines log lines to $out_file"
}

cmd_env() {
  [[ $# -eq 1 ]] || die "Usage: control-techcards.sh env <run-id>"
  load_instance "$1"
  cat <<EOF
RUN_ID=$RUN_ID
COMPOSE_PROJECT=$COMPOSE_PROJECT
BASE_URL=$BASE_URL
API_PORT=$API_PORT
DB_PORT=$DB_PORT
EVIDENCE_DIR=$EVIDENCE_DIR
REPO_ROOT=$REPO_ROOT
GIT_SHA=$GIT_SHA
SOURCE_HASH=$SOURCE_HASH
POSTGRES_USER=$POSTGRES_USER
POSTGRES_DB=$POSTGRES_DB
DB_RO_USER=$DB_RO_USER
GENERATOR_PROVIDER=$GENERATOR_PROVIDER
EOF
}

cmd_cleanup() {
  require_cmd docker
  require_cmd python3
  [[ $# -eq 1 ]] || die "Usage: control-techcards.sh cleanup <run-id>"
  local run_id="$1"

  load_instance "$run_id"

  # Defensive guard: never delete scratch if evidence overlaps it.
  assert_disjoint_paths "$INSTANCE_DIR" "$EVIDENCE_DIR"

  echo "Tearing down isolated Compose project '$COMPOSE_PROJECT'..."
  compose_cmd down --volumes --remove-orphans --rmi local

  local remaining
  remaining="$(docker ps -a --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" -q)"
  if [[ -n "$remaining" ]]; then
    die "Cleanup incomplete: containers still remain for $COMPOSE_PROJECT: $remaining"
  fi

  rm -rf "$INSTANCE_DIR"

  if [[ -d "$EVIDENCE_DIR" ]]; then
    local artifact_count
    artifact_count="$(find "$EVIDENCE_DIR" -type f | wc -l | tr -d ' ')"
    echo "CLEANUP COMPLETE"
    echo "SCRATCH_REMOVED=$INSTANCE_DIR"
    echo "EVIDENCE_PRESERVED=$EVIDENCE_DIR ($artifact_count file(s))"
  else
    echo "CLEANUP COMPLETE (no evidence directory was created at $EVIDENCE_DIR)"
  fi
}

main() {
  [[ $# -ge 1 ]] || { usage; exit 1; }
  local cmd="$1"
  shift
  case "$cmd" in
    launch)   cmd_launch "$@" ;;
    doctor)   cmd_doctor "$@" ;;
    req)      cmd_req "$@" ;;
    db-query) cmd_db_query "$@" ;;
    logs)     cmd_logs "$@" ;;
    env)      cmd_env "$@" ;;
    cleanup)  cmd_cleanup "$@" ;;
    -h|--help|help) usage ;;
    *) die "Unknown command: $cmd (run with --help)" ;;
  esac
}

main "$@"
