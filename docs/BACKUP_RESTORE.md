# Local Data Backup, Restore, and Migration Recovery

This runbook covers local PostgreSQL backup/restore verification, migration
failure recovery, and non-destructive Docker volume handling for `techcards-srs`.
It uses the existing `compose.yaml` (`postgres:16-alpine` and `migrate`) without
adding a second database stack.

## Safety rules

- **Fresh disposable projects only:** Generate unique Compose project names
  (`-p`) per run and verify no existing containers, volumes, or networks match
  those names before starting or tearing them down. Never touch the live
  `techcards-srs` stack or `techcards-srs_postgres_data` during practice.
- **No secrets:** Exercises use obvious disposable credentials
  (`disposable_user` / `disposable-local-test-only` / `techcards_disposable`).
  Never read `.env` during a drill, never pass passwords in CLI arguments, and
  never commit `.dump`, `.sql`, or `.env` files to Git.
- **Owner-only backups outside the repo:** Store real study backups outside this
  checkout with `umask 077` and `0700` directory / `0600` file permissions.

## Current storage and schema layout

From `compose.yaml` and `migrations/versions/0001_initial.py`:

- **Engine & volume:** `postgres:16-alpine` (`db:5432`, loopback `${POSTGRES_HOST_PORT:-5435}`) with named volume `postgres_data` (default: `techcards-srs_postgres_data`).
- **Migrations:** One-shot `migrate` service runs `alembic upgrade head`; `migrations/env.py` wraps migrations in `context.begin_transaction()`.
- **Schema:** `decks` -> `cards` (`deck_id` FK, `ON DELETE CASCADE`, SM-2 check constraints) -> `reviews` (`card_id` FK, `ON DELETE CASCADE`, `quality` check constraint), plus `alembic_version`.

## Repeatable disposable backup/restore drill

Run the automated exercise on two fresh disposable Compose projects (Linux/macOS/WSL/Git Bash; checks both names are unused before claiming ownership and cleans up only owned projects):

```bash
./scripts/verify_backup_restore.sh
```

### Step-by-step manual exercise

Run from the repo root with disposable credentials and ports (`15435`/`15436`; `api` is not started). On PowerShell, set `$env:NAME = "value"` and omit `--env-file /dev/null`.

1. **Generate fresh disposable project names and verify they are unused:**

   ```bash
   export POSTGRES_USER=disposable_user
   export POSTGRES_PASSWORD=disposable-local-test-only
   export POSTGRES_DB=techcards_disposable
   export RUN_ID="$(date -u +%Y%m%d%H%M%S)-$(od -An -tx1 -N6 /dev/urandom | tr -d ' \n')"
   export SRC_PROJECT="techcards-backup-src-${RUN_ID}"
   export DST_PROJECT="techcards-backup-dst-${RUN_ID}"
   export DUMP_DIR="$(umask 077 && mktemp -d)"

   # All checks must exit 0 (empty output) before starting or later cleaning up:
   for p in "$SRC_PROJECT" "$DST_PROJECT"; do
     out="$(docker ps -aq --filter "label=com.docker.compose.project=$p")" && test -z "$out"
     out="$(docker volume ls -q --filter "name=^${p}_")" && test -z "$out"
     out="$(docker volume ls -q --filter "label=com.docker.compose.project=$p")" && test -z "$out"
     out="$(docker network ls -q --filter "label=com.docker.compose.project=$p")" && test -z "$out"
   done
   ```

2. **Start the fresh disposable source database and apply migrations:**

   ```bash
   POSTGRES_HOST_PORT=15435 docker compose --env-file /dev/null -p "$SRC_PROJECT" up -d --wait db
   POSTGRES_HOST_PORT=15435 docker compose --env-file /dev/null -p "$SRC_PROJECT" run --rm --build migrate
   ```

3. **Seed disposable decks, cards, and reviews:**

   ```bash
   POSTGRES_HOST_PORT=15435 docker compose --env-file /dev/null -p "$SRC_PROJECT" exec -T db \
     psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
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
   ```

4. **Create and inspect a custom-format `pg_dump` backup (owner-only file):**

   ```bash
   (umask 077 && POSTGRES_HOST_PORT=15435 docker compose --env-file /dev/null -p "$SRC_PROJECT" exec -T db \
     pg_dump --format=custom --no-owner --no-privileges \
     -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$DUMP_DIR/disposable.dump")

   POSTGRES_HOST_PORT=15435 docker compose --env-file /dev/null -p "$SRC_PROJECT" exec -T db \
     pg_restore --list < "$DUMP_DIR/disposable.dump" | head -n 25
   ```

5. **Start the fresh disposable target database and restore (without running `migrate` first):**

   ```bash
   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" up -d --wait db

   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" exec -T db \
     pg_restore --no-owner --no-privileges --single-transaction --exit-on-error \
     -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$DUMP_DIR/disposable.dump"
   ```

6. **Verify counts, relationships, and Alembic parity on the target:**

   ```bash
   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" exec -T db \
     psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
   SELECT 'decks' AS tbl, COUNT(*) FROM decks
   UNION ALL SELECT 'cards', COUNT(*) FROM cards
   UNION ALL SELECT 'reviews', COUNT(*) FROM reviews;

   SELECT d.id, d.name, COUNT(DISTINCT c.id) AS card_count, COUNT(r.id) AS review_count
   FROM decks d LEFT JOIN cards c ON c.deck_id = d.id LEFT JOIN reviews r ON r.card_id = c.id
   GROUP BY d.id, d.name ORDER BY d.id;

   SELECT
     (SELECT COUNT(*) FROM reviews r JOIN cards c ON c.id = r.card_id JOIN decks d ON d.id = c.deck_id) AS joined_reviews,
     (SELECT COUNT(*) FROM cards c LEFT JOIN decks d ON d.id = c.deck_id WHERE d.id IS NULL) AS orphan_cards,
     (SELECT COUNT(*) FROM reviews r LEFT JOIN cards c ON c.id = r.card_id WHERE c.id IS NULL) AS orphan_reviews;
   SQL

   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" run --rm --build migrate alembic current
   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" run --rm migrate alembic check
   ```

   Expected observations: `decks=2`, `cards=4`, `reviews=5`; `joined_reviews=5`,
   `orphan_cards=0`, `orphan_reviews=0`; `alembic current` reports `0001 (head)`
   and `alembic check` reports no new upgrade operations.

7. **Tear down only the fresh projects created in this session:**

   ```bash
   # Run only for the fresh $SRC_PROJECT and $DST_PROJECT verified in step 1:
   POSTGRES_HOST_PORT=15435 docker compose --env-file /dev/null -p "$SRC_PROJECT" down --volumes --remove-orphans --rmi local
   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" down --volumes --remove-orphans --rmi local
   rm -rf "$DUMP_DIR"
   ```

## Taking a read-only backup of your live local database

Before applying a schema migration to real study data, dump the running `db`
service into a private directory **outside** the Git repository. Setting
`umask 077` in a subshell and `chmod 700` on the target directory ensures the
backup directory (`0700`) and dump file (`0600`) are owner-only from creation:

```bash
(
  set -e
  umask 077
  BACKUP_DIR="$HOME/backups/techcards-srs"
  mkdir -p "$BACKUP_DIR"
  chmod 700 "$BACKUP_DIR"
  DUMP_PATH="$BACKUP_DIR/techcards-$(date -u +%Y%m%dT%H%M%SZ).dump"
  docker compose exec -T db sh -c \
    'pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    > "$DUMP_PATH"
)
```

Verify the backup by restoring it into a fresh **disposable** Compose project
(`-p`) as shown above before running the migration.

## Migration failure recovery

Because `migrations/env.py` wraps `context.run_migrations()` in
`context.begin_transaction()`, standard PostgreSQL DDL errors inside a single
revision roll back atomically. Failures across multiple revisions or inside an
`autocommit_block()` (for example, `CREATE INDEX CONCURRENTLY`) can still leave
the schema partially updated.

If `docker compose up` or `docker compose run --rm migrate` fails:

1. **Stop and protect data.** Do **not** run `docker compose down --volumes` or
   `docker volume rm`. Leave the volume intact and run `docker compose stop api`
   if needed.
2. **Inspect the failure and current revision:**

   ```bash
   docker compose logs migrate
   docker compose run --rm migrate alembic current
   docker compose run --rm migrate alembic history --verbose
   docker compose exec -T db sh -c \
     'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version;" -c "\dt"'
   ```

3. **Take a private safety dump of the current state** (using the `umask 077`
   pattern above with a distinct `pre-recovery-<timestamp>.dump` filename)
   before making manual changes.
4. **Recover based on what `alembic current` and `\dt` show:**
   - **Clean rollback (`alembic_version` stayed at the prior revision and no
     partial objects exist):** Revert to the previous commit if you need the app
     running now, fix the migration, and rehearse `pg_restore` + `alembic
     upgrade head` + `alembic check` on a fresh disposable project before
     retrying on the real volume.
   - **Partial migration or schema drift:** Restore your pre-migration backup
     into a **fresh target volume / new Compose project** (`-p`), verify counts,
     relationships, and `alembic current`, fix and test the upgrade on that
     copy, and only then cut over.
5. **Avoid destructive shortcuts:**
   - Never run `alembic downgrade base` on real study data:
     `migrations/versions/0001_initial.py` drops `reviews`, `cards`, and `decks`.
   - Never run `alembic stamp <rev>` unless you verified the schema matches that
     revision and confirmed zero drift with `alembic check`.

## Non-destructive volume handling

`compose.yaml` stores PostgreSQL data in the named volume `postgres_data`
(default full name: `techcards-srs_postgres_data`).

- **Avoid destructive commands during routine work or recovery:**
  `docker compose down --volumes` (`-v`), `docker volume rm`,
  `docker system prune --volumes`, and `pg_restore --clean` against the live DB
  without a verified backup.
- **Preferred non-destructive workflow:** Inspect volumes with `docker volume ls`
  and `docker volume inspect techcards-srs_postgres_data`; stop containers
  without deleting data via `docker compose stop` or `docker compose down`;
  test restores and migrations in a fresh Compose project (`-p`); and keep the
  prior volume stopped as a fallback until counts and relationships are verified
  in the new stack.
- **Destructive cleanup is opt-in and last-resort only:** Run `down --volumes`
  or `docker volume rm` only after confirming the exact `-p` project or volume
  name, verifying ownership, and confirming no unbacked-up study data remains.
