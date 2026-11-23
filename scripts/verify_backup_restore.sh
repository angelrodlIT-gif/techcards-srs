#!/usr/bin/env bash
# Disposable PostgreSQL 16 backup/restore drill for techcards-srs.
# Uses fresh Compose projects (-p), ephemeral ports, owner-only permissions, and
# non-secret placeholder credentials. Never reads .env or touches techcards-srs.
set -euo pipefail
set -o noclobber
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Obvious disposable local-test credentials (not real secrets).
export POSTGRES_USER="disposable_user"
export POSTGRES_PASSWORD="disposable-local-test-only"
export POSTGRES_DB="techcards_disposable"

RUN_ID="$(date -u +%Y%m%d%H%M%S)-$(od -An -tx1 -N6 /dev/urandom | tr -d ' \n')"
SRC_PROJECT="techcards-backup-src-${RUN_ID}"
DST_PROJECT="techcards-backup-dst-${RUN_ID}"
SRC_PORT="${SRC_PORT:-15435}"
DST_PORT="${DST_PORT:-15436}"

if [[ "$SRC_PORT" == "5435" || "$DST_PORT" == "5435" || "$SRC_PORT" == "$DST_PORT" ]]; then
  echo "Use distinct disposable ports (not the default live port 5435)." >&2
  exit 1
fi

SRC_OWNED=0
DST_OWNED=0
DUMP_DIR=""

compose_src() {
  POSTGRES_HOST_PORT="$SRC_PORT" docker compose --env-file /dev/null -p "$SRC_PROJECT" "$@"
}

compose_dst() {
  POSTGRES_HOST_PORT="$DST_PORT" docker compose --env-file /dev/null -p "$DST_PROJECT" "$@"
}

assert_fresh_project() {
  local project="$1"
  local containers volumes_by_name volumes_by_label networks
  if [[ "$project" != techcards-backup-src-?* && "$project" != techcards-backup-dst-?* ]]; then
    echo "Refusing unexpected Compose project name '${project}'." >&2
    exit 1
  fi
  containers="$(docker ps -aq --filter "label=com.docker.compose.project=${project}")"
  volumes_by_name="$(docker volume ls -q --filter "name=^${project}_")"
  volumes_by_label="$(docker volume ls -q --filter "label=com.docker.compose.project=${project}")"
  networks="$(docker network ls -q --filter "label=com.docker.compose.project=${project}")"
  if [[ -n "${containers}${volumes_by_name}${volumes_by_label}${networks}" ]]; then
    echo "Refusing to reuse existing Compose project '${project}'." >&2
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
  if [[ -n "$DUMP_DIR" ]]; then
    rm -rf "$DUMP_DIR"
  fi
  exit "$exit_code"
}
trap cleanup EXIT

DUMP_DIR="$(mktemp -d)"
DUMP_FILE="${DUMP_DIR}/disposable-${RUN_ID}.dump"

assert_fresh_project "$SRC_PROJECT"
SRC_OWNED=1
echo "==> Starting disposable source PostgreSQL (${SRC_PROJECT}, port ${SRC_PORT})..."
compose_src up -d --wait db

echo "==> Building and running Alembic migrations on disposable source..."
compose_src build migrate >/dev/null
compose_src run --rm migrate

echo "==> Seeding disposable decks, cards, and reviews..."
compose_src exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
INSERT INTO decks (name, description) VALUES
  ('Cloud Interviews', 'Disposable AWS & Linux vocabulary'),
  ('Python Backend', 'Disposable FastAPI & PostgreSQL practice');

INSERT INTO cards (deck_id, front, back, kind, repetitions, interval_days, ease_factor, due_date) VALUES
  (1, 'rule out', 'eliminate a possible root cause during troubleshooting', 'vocabulary', 2, 6, 2.6, DATE '2026-11-28'),
  (1, 'walk through an outage', 'explain incident timeline, impact, and mitigation', 'interview_phrase', 1, 1, 2.5, DATE '2026-11-23'),
  (2, 'idempotent endpoint', 'safe to retry without duplicating side effects', 'vocabulary', 3, 15, 2.6, DATE '2026-12-07'),
  (2, 'SELECT ... FOR UPDATE', 'row-level lock that serializes concurrent updates', 'vocabulary', 0, 0, 2.5, DATE '2026-11-22');

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

echo "==> Dumping disposable source with pg_dump --format=custom..."
compose_src exec -T db pg_dump --format=custom --no-owner --no-privileges \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$DUMP_FILE"
DUMP_TOC_LINES="$(compose_src exec -T db pg_restore --list < "$DUMP_FILE" | wc -l | tr -d ' ')"
echo "Dump created (${DUMP_TOC_LINES} TOC entries)."

assert_fresh_project "$DST_PROJECT"
DST_OWNED=1
echo "==> Starting fresh disposable target PostgreSQL (${DST_PROJECT}, port ${DST_PORT})..."
compose_dst up -d --wait db

echo "==> Restoring dump into disposable target..."
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

compose_dst build migrate >/dev/null
ALEMBIC_CURRENT="$(compose_dst run --rm migrate alembic current | tr -d '\r')"
echo "Restored Alembic revision: ${ALEMBIC_CURRENT}"
if [[ "$ALEMBIC_CURRENT" != *"(head)"* ]]; then
  echo "ERROR: Restored database is not at Alembic head." >&2
  exit 1
fi
compose_dst run --rm migrate alembic check
echo "==> Disposable backup/restore verification PASSED."
