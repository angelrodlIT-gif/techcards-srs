#!/usr/bin/env bash
# Disposable PostgreSQL 16 backup/restore drill for techcards-srs.
# Pins compose.yaml, clears Compose override env vars, uses fresh Compose projects
# (-p), ephemeral ports, exclusive owner-only dumps, and placeholder credentials.
# Never reads .env and never touches the live techcards-srs stack or volume.
set -euo pipefail
set -o noclobber
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE_PATH="${REPO_ROOT}/compose.yaml"
if [[ ! -f "$COMPOSE_FILE_PATH" || -L "$COMPOSE_FILE_PATH" ]]; then
  echo "Missing or non-regular compose file '${COMPOSE_FILE_PATH}'." >&2
  exit 1
fi

PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 (or python) is required to validate rendered Compose config." >&2
  exit 1
fi

# Obvious disposable local-test credentials (not real secrets).
export POSTGRES_USER="disposable_user"
export POSTGRES_PASSWORD="disposable-local-test-only"
export POSTGRES_DB="techcards_disposable"

RUN_ID="$(date -u +%Y%m%d%H%M%S)-$(od -An -tx1 -N6 /dev/urandom | tr -d ' \n')"
SRC_PROJECT="techcards-backup-src-${RUN_ID}"
DST_PROJECT="techcards-backup-dst-${RUN_ID}"
SRC_PORT="${SRC_PORT:-15435}"
DST_PORT="${DST_PORT:-15436}"

if [[ ! "$SRC_PORT" =~ ^[0-9]+$ || ! "$DST_PORT" =~ ^[0-9]+$ ]]; then
  echo "SRC_PORT and DST_PORT must be numeric." >&2
  exit 1
fi
if [[ "$SRC_PORT" == "5435" || "$DST_PORT" == "5435" || "$SRC_PORT" == "$DST_PORT" ]]; then
  echo "Use distinct disposable ports (not the default live port 5435)." >&2
  exit 1
fi

SRC_OWNED=0
DST_OWNED=0
DUMP_DIR=""
DUMP_FILE=""
DUMP_READY=0

run_compose() {
  local project="$1"
  local host_port="$2"
  shift 2
  env -u COMPOSE_FILE -u COMPOSE_PROFILES -u COMPOSE_PROJECT_NAME -u COMPOSE_PATH_SEPARATOR \
    POSTGRES_HOST_PORT="$host_port" \
    docker compose --env-file /dev/null --project-directory "$REPO_ROOT" -f "$COMPOSE_FILE_PATH" -p "$project" "$@"
}

compose_src() {
  run_compose "$SRC_PROJECT" "$SRC_PORT" "$@"
}

compose_dst() {
  run_compose "$DST_PROJECT" "$DST_PORT" "$@"
}

resolve_verified_db_volume() {
  local project="$1"
  local rendered_json="$2"
  "$PYTHON_BIN" -c '
import json, sys
project = sys.argv[1]
expected = f"{project}_postgres_data"
cfg = json.load(sys.stdin)
name = cfg.get("name")
if name != project:
    sys.exit(f"Rendered project name {name!r} does not match {project!r}.")
db_mounts = (cfg.get("services") or {}).get("db", {}).get("volumes") or []
if len(db_mounts) != 1 or db_mounts[0].get("type") != "volume" or db_mounts[0].get("source") != "postgres_data":
    sys.exit(f"Unexpected db volume mounts in rendered Compose config: {db_mounts!r}")
vol = (cfg.get("volumes") or {}).get("postgres_data")
if not isinstance(vol, dict) or vol.get("external"):
    sys.exit(f"Refusing missing or external postgres_data volume definition: {vol!r}")
resolved = vol.get("name")
if resolved != expected:
    sys.exit(f"Refusing non-project postgres_data volume name {resolved!r} (expected {expected!r}).")
print(resolved)
' "$project" <<<"$rendered_json"
}

assert_fresh_project() {
  local project="$1"
  local host_port="$2"
  local rendered_json resolved_vol exact_vol containers volumes_by_name volumes_by_label networks
  if [[ "$project" != techcards-backup-src-?* && "$project" != techcards-backup-dst-?* ]]; then
    echo "Refusing unexpected Compose project name '${project}'." >&2
    exit 1
  fi
  rendered_json="$(run_compose "$project" "$host_port" config --format json)"
  resolved_vol="$(resolve_verified_db_volume "$project" "$rendered_json")"
  if [[ "$resolved_vol" != "${project}_postgres_data" ]]; then
    echo "Refusing unexpected resolved volume '${resolved_vol}' for project '${project}'." >&2
    exit 1
  fi
  exact_vol="$(docker volume ls -q --filter "name=^${resolved_vol}$")"
  containers="$(docker ps -aq --filter "label=com.docker.compose.project=${project}")"
  volumes_by_name="$(docker volume ls -q --filter "name=^${project}_")"
  volumes_by_label="$(docker volume ls -q --filter "label=com.docker.compose.project=${project}")"
  networks="$(docker network ls -q --filter "label=com.docker.compose.project=${project}")"
  if [[ -n "${exact_vol}${containers}${volumes_by_name}${volumes_by_label}${networks}" ]]; then
    echo "Refusing to reuse existing Compose project '${project}' or volume '${resolved_vol}'." >&2
    exit 1
  fi
}

assert_regular_dump_target() {
  local path="$1"
  if [[ -z "$DUMP_DIR" || -z "$path" || "$path" != "${DUMP_DIR}/"* || -L "$path" || -p "$path" || ! -f "$path" ]]; then
    echo "Refusing non-regular or unowned dump path '${path}'." >&2
    exit 1
  fi
}

assert_ready_dump() {
  if [[ "$DUMP_READY" != "1" ]]; then
    echo "Refusing to inspect or restore: dump was not completed in this run." >&2
    exit 1
  fi
  assert_regular_dump_target "$DUMP_FILE"
  if [[ ! -s "$DUMP_FILE" ]]; then
    echo "Refusing to inspect or restore empty dump '${DUMP_FILE}'." >&2
    exit 1
  fi
}

cleanup() {
  local exit_code=$?
  set +e
  if [[ "$SRC_OWNED" == "1" ]]; then
    echo "==> Cleaning up owned disposable stack (${SRC_PROJECT})..."
    compose_src down --volumes --remove-orphans --rmi local >/dev/null 2>&1
  fi
  if [[ "$DST_OWNED" == "1" ]]; then
    echo "==> Cleaning up owned disposable stack (${DST_PROJECT})..."
    compose_dst down --volumes --remove-orphans --rmi local >/dev/null 2>&1
  fi
  if [[ -n "$DUMP_DIR" && -d "$DUMP_DIR" && ! -L "$DUMP_DIR" ]]; then
    rm -rf "$DUMP_DIR"
  fi
  exit "$exit_code"
}
trap cleanup EXIT

DUMP_DIR="$(mktemp -d)"
chmod 700 "$DUMP_DIR"
if [[ ! -d "$DUMP_DIR" || -L "$DUMP_DIR" ]]; then
  echo "Invalid temporary dump directory '${DUMP_DIR}'." >&2
  exit 1
fi

assert_fresh_project "$SRC_PROJECT" "$SRC_PORT"
SRC_OWNED=1
echo "==> Starting disposable source PostgreSQL (${SRC_PROJECT}, port ${SRC_PORT})..."
compose_src up -d --wait db

echo "==> Building and running Alembic migrations on disposable source..."
compose_src build migrate >/dev/null
compose_src run --rm migrate

echo "==> Seeding disposable personal data..."
compose_src exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
INSERT INTO decks (name, description) VALUES
  ('Cloud Interviews', 'Disposable AWS & Linux vocabulary'),
  ('Python Backend', 'Disposable FastAPI & PostgreSQL practice');

INSERT INTO sources (label, excerpt, status) VALUES ('Disposable source', 'Example excerpt', 'approved');

INSERT INTO cards (deck_id, front, back, kind, repetitions, interval_days, ease_factor, due_date) VALUES
  (1, 'rule out', 'eliminate a possible root cause during troubleshooting', 'vocabulary', 2, 6, 2.6, DATE '2026-11-28'),
  (1, 'walk through an outage', 'explain incident timeline, impact, and mitigation', 'interview_phrase', 1, 1, 2.5, DATE '2026-11-23'),
  (2, 'idempotent endpoint', 'safe to retry without duplicating side effects', 'vocabulary', 3, 15, 2.6, DATE '2026-12-07'),
  (2, 'SELECT ... FOR UPDATE', 'row-level lock that serializes concurrent updates', 'vocabulary', 0, 0, 2.5, DATE '2026-11-22');

UPDATE cards SET source_id = 1, source_label = 'Disposable source' WHERE id = 1;
INSERT INTO error_logs (attempted, corrected, rationale, status, card_id, created_at) VALUES
  ('Example error', 'Example correction', 'Example rationale', 'approved', 2, TIMESTAMPTZ '2026-11-20T14:00:00Z'),
  ('Legacy example', 'Legacy correction', 'Unknown creation time', 'draft', NULL, NULL);

INSERT INTO reviews (card_id, quality, reviewed_at, interval_days, ease_factor, repetitions, due_date) VALUES
  (1, 4, TIMESTAMPTZ '2026-11-20T14:00:00Z', 1, 2.5, 1, DATE '2026-11-21'),
  (1, 5, TIMESTAMPTZ '2026-11-22T14:00:00Z', 6, 2.6, 2, DATE '2026-11-28'),
  (2, 4, TIMESTAMPTZ '2026-11-22T14:05:00Z', 1, 2.5, 1, DATE '2026-11-23'),
  (3, 5, TIMESTAMPTZ '2026-11-21T15:00:00Z', 6, 2.6, 2, DATE '2026-11-27'),
  (3, 4, TIMESTAMPTZ '2026-11-22T15:00:00Z', 15, 2.6, 3, DATE '2026-12-07');
SQL

SUMMARY_SQL="
SELECT (SELECT COUNT(*) FROM decks), (SELECT COUNT(*) FROM cards), (SELECT COUNT(*) FROM reviews),
  (SELECT COUNT(*) FROM reviews r JOIN cards c ON c.id = r.card_id JOIN decks d ON d.id = c.deck_id),
  (SELECT COUNT(*) FROM cards c LEFT JOIN decks d ON d.id = c.deck_id WHERE d.id IS NULL),
  (SELECT COUNT(*) FROM reviews r LEFT JOIN cards c ON c.id = r.card_id WHERE c.id IS NULL);"

BREAKDOWN_SQL="
SELECT d.id, d.name, COUNT(DISTINCT c.id), COUNT(r.id)
FROM decks d LEFT JOIN cards c ON c.deck_id = d.id LEFT JOIN reviews r ON r.card_id = c.id
GROUP BY d.id, d.name ORDER BY d.id;"

SRC_SUMMARY="$(compose_src exec -T db psql -At -F '|' -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$SUMMARY_SQL")"
SRC_BREAKDOWN="$(compose_src exec -T db psql -At -F '|' -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$BREAKDOWN_SQL")"
echo "Source summary (decks|cards|reviews|joined_reviews|orphan_cards|orphan_reviews): ${SRC_SUMMARY}"

capture_personal_export() {
  "$1" run --rm --no-deps -T migrate python -c '
import json
from fastapi import Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from app.db import get_engine
from app.personal_data import export_personal_data

with Session(get_engine()) as session:
    export = export_personal_data(session, Response())
print(json.dumps(jsonable_encoder(export), sort_keys=True))
'
}

capture_personal_export compose_src > "${DUMP_DIR}/source.json"

echo "==> Dumping disposable source with pg_dump --format=custom..."
DUMP_FILE="$(mktemp "${DUMP_DIR}/disposable-${RUN_ID}-XXXXXX")"
chmod 600 "$DUMP_FILE"
assert_regular_dump_target "$DUMP_FILE"
compose_src exec -T db pg_dump --format=custom --no-owner --no-privileges \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" >| "$DUMP_FILE"
assert_regular_dump_target "$DUMP_FILE"
if [[ ! -s "$DUMP_FILE" ]]; then
  echo "ERROR: pg_dump produced an empty file." >&2
  exit 1
fi
DUMP_READY=1

assert_ready_dump
DUMP_TOC_LINES="$(compose_src exec -T db pg_restore --list < "$DUMP_FILE" | wc -l | tr -d ' ')"
echo "Dump created (${DUMP_TOC_LINES} TOC entries)."

assert_fresh_project "$DST_PROJECT" "$DST_PORT"
DST_OWNED=1
echo "==> Starting fresh disposable target PostgreSQL (${DST_PROJECT}, port ${DST_PORT})..."
compose_dst up -d --wait db

echo "==> Restoring dump into disposable target..."
assert_ready_dump
compose_dst exec -T db pg_restore --no-owner --no-privileges --single-transaction --exit-on-error \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$DUMP_FILE"

echo "==> Verifying restored counts, relationships, sequences, and Alembic parity..."
DST_SUMMARY="$(compose_dst exec -T db psql -At -F '|' -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$SUMMARY_SQL")"
DST_BREAKDOWN="$(compose_dst exec -T db psql -At -F '|' -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$BREAKDOWN_SQL")"
echo "Target summary (decks|cards|reviews|joined_reviews|orphan_cards|orphan_reviews): ${DST_SUMMARY}"

if [[ "$SRC_SUMMARY" != "2|4|5|5|0|0" || "$DST_SUMMARY" != "$SRC_SUMMARY" || "$DST_BREAKDOWN" != "$SRC_BREAKDOWN" ]]; then
  echo "ERROR: Count or relationship verification mismatch." >&2
  exit 1
fi
echo "Per-deck breakdown (id|name|cards|reviews):"
echo "$DST_BREAKDOWN"

compose_dst build migrate >/dev/null
capture_personal_export compose_dst > "${DUMP_DIR}/restored.json"
if ! cmp -s "${DUMP_DIR}/source.json" "${DUMP_DIR}/restored.json"; then
  echo "ERROR: Personal data exports differ after restore." >&2
  exit 1
fi
echo "Personal JSON exports match before backup and after restore."

compose_dst exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL' >/dev/null
BEGIN;
WITH new_deck AS (INSERT INTO decks (name, description) VALUES ('Probe Deck', 'Rolled back') RETURNING id),
new_card AS (
  INSERT INTO cards (deck_id, front, back, kind, repetitions, interval_days, ease_factor, due_date)
  SELECT id, 'probe front', 'probe back', 'vocabulary', 0, 0, 2.5, DATE '2026-11-22' FROM new_deck RETURNING id
)
INSERT INTO reviews (card_id, quality, reviewed_at, interval_days, ease_factor, repetitions, due_date)
SELECT id, 4, TIMESTAMPTZ '2026-11-22T16:00:00Z', 1, 2.5, 1, DATE '2026-11-23' FROM new_card;
ROLLBACK;
SQL
echo "Sequence and FK/check-constraint probe passed (rolled back)."

ALEMBIC_CURRENT="$(compose_dst run --rm migrate alembic current | tr -d '\r')"
echo "Restored Alembic revision: ${ALEMBIC_CURRENT}"
if [[ "$ALEMBIC_CURRENT" != *"(head)"* ]]; then
  echo "ERROR: Restored database is not at Alembic head." >&2
  exit 1
fi
compose_dst run --rm migrate alembic check
echo "==> Disposable backup/restore verification PASSED."
