# Local Data Backup, Restore, and Migration Recovery

This runbook covers local PostgreSQL backup/restore verification, migration
failure recovery, and non-destructive Docker volume handling for `techcards-srs`.
It uses the repository's existing `compose.yaml` (`postgres:16-alpine` and the
`migrate` service) without adding a second database stack.

## Safety rules

- **Disposable data only for exercises:** Always run backup/restore drills with
  isolated Compose project names (`-p`) and dedicated loopback ports so the live
  `techcards-srs` stack and its `techcards-srs_postgres_data` volume are never
  touched.
- **No secrets:** Exercises use obvious disposable credentials
  (`disposable_user` / `disposable-local-test-only` / `techcards_disposable`).
  Never read `.env` during a drill, never pass passwords in CLI arguments, and
  never commit `.dump`, `.sql`, or `.env` files to Git.
- **Keep backups outside the repository:** Store real study backups in a local
  directory outside this checkout (for example, `~/backups/techcards-srs/`).

## Current storage and schema layout

From `compose.yaml` and `migrations/versions/0001_initial.py`:

- **Database engine:** `postgres:16-alpine` (service `db`, internal port `5432`,
  loopback host port `${POSTGRES_HOST_PORT:-5435}`).
- **Persistent volume:** Named Compose volume `postgres_data`, prefixed by the
  Compose project name (default: `techcards-srs_postgres_data`).
- **Migrations:** One-shot `migrate` service runs `alembic upgrade head`.
  `migrations/env.py` executes migrations inside `context.begin_transaction()`.
- **Tables and relationships:** `decks` -> `cards` (`deck_id` FK, `ON DELETE
  CASCADE`, check constraints on SM-2 fields) -> `reviews` (`card_id` FK,
  `ON DELETE CASCADE`, `quality` check constraint), plus `alembic_version`.

## Repeatable disposable backup/restore drill

To run the full automated exercise on two isolated disposable Compose projects
(Linux/macOS/WSL/Git Bash; leaves the live stack untouched and cleans up only
its own disposable projects on exit):

```bash
./scripts/verify_backup_restore.sh
```

### Step-by-step manual exercise

All commands run from the repository root using disposable credentials and
ephemeral loopback ports (`15435` and `15436`) so they do not conflict with the
live stack (`5435` / `8000`). Only `db` and `migrate` are started (`api` is not
started). On Windows PowerShell, set the environment variables with
`$env:NAME = "value"` and omit `--env-file /dev/null`.

1. **Set disposable variables (never real credentials):**

   ```bash
   export POSTGRES_USER=disposable_user
   export POSTGRES_PASSWORD=disposable-local-test-only
   export POSTGRES_DB=techcards_disposable
   export SRC_PROJECT=techcards-backup-src
   export DST_PROJECT=techcards-backup-dst
   export DUMP_DIR="$(mktemp -d)"
   ```

2. **Start a disposable source database and apply migrations:**

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

4. **Create and inspect a custom-format `pg_dump` backup:**

   ```bash
   POSTGRES_HOST_PORT=15435 docker compose --env-file /dev/null -p "$SRC_PROJECT" exec -T db \
     pg_dump --format=custom --no-owner --no-privileges \
     -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$DUMP_DIR/disposable.dump"

   POSTGRES_HOST_PORT=15435 docker compose --env-file /dev/null -p "$SRC_PROJECT" exec -T db \
     pg_restore --list < "$DUMP_DIR/disposable.dump" | head -n 25
   ```

5. **Start a fresh disposable target database and restore (without running `migrate` first):**

   ```bash
   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" up -d --wait db

   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" exec -T db \
     pg_restore --no-owner --no-privileges --single-transaction --exit-on-error \
     -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$DUMP_DIR/disposable.dump"
   ```

6. **Verify counts, relationships, sequences, and Alembic parity on the target:**

   ```bash
   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" exec -T db \
     psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
   SELECT 'decks' AS tbl, COUNT(*) FROM decks
   UNION ALL SELECT 'cards', COUNT(*) FROM cards
   UNION ALL SELECT 'reviews', COUNT(*) FROM reviews;

   SELECT d.id, d.name,
          COUNT(DISTINCT c.id) AS card_count,
          COUNT(r.id) AS review_count
   FROM decks d
   LEFT JOIN cards c ON c.deck_id = d.id
   LEFT JOIN reviews r ON r.card_id = c.id
   GROUP BY d.id, d.name
   ORDER BY d.id;

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

7. **Tear down only the disposable projects and temp directory:**

   ```bash
   POSTGRES_HOST_PORT=15435 docker compose --env-file /dev/null -p "$SRC_PROJECT" down --volumes --remove-orphans --rmi local
   POSTGRES_HOST_PORT=15436 docker compose --env-file /dev/null -p "$DST_PROJECT" down --volumes --remove-orphans --rmi local
   rm -rf "$DUMP_DIR"
   ```

## Taking a read-only backup of your live local database

Before applying any new schema migration to real study data, dump the running
`db` service into a timestamped file **outside** the Git repository (this uses
the container's existing `POSTGRES_USER` and `POSTGRES_DB` environment variables
over the local socket, so no secrets appear in shell history):

```bash
mkdir -p ~/backups/techcards-srs
docker compose exec -T db sh -c \
  'pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "$HOME/backups/techcards-srs/techcards-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

Verify the backup by restoring it into a **disposable** Compose project (`-p`)
as shown above before running the migration.

## Migration failure recovery

Because `migrations/env.py` wraps `context.run_migrations()` in
`context.begin_transaction()`, standard PostgreSQL DDL errors inside a single
revision roll back atomically. Failures across multiple revisions or inside an
`autocommit_block()` (for example, `CREATE INDEX CONCURRENTLY`) can still leave
the schema partially updated.

If `docker compose up` or `docker compose run --rm migrate` fails:

1. **Stop and protect data.** Do **not** run `docker compose down --volumes` or
   `docker volume rm`. Leave the volume intact and stop the API if needed
   (`docker compose stop api`).
2. **Inspect the failure and current revision:**

   ```bash
   docker compose logs migrate
   docker compose run --rm migrate alembic current
   docker compose run --rm migrate alembic history --verbose
   docker compose exec -T db sh -c \
     'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version;" -c "\dt"'
   ```

3. **Take a safety dump of the current state** before touching anything manually
   (use a distinct filename such as `pre-recovery-<timestamp>.dump` outside the
   repo).
4. **Choose the recovery path based on what `alembic current` and `\dt` show:**
   - **Clean transaction rollback (`alembic_version` stayed at the previous
     revision and no partial objects exist):** Revert to the previous working
     commit if you need the app running immediately, fix the migration bug, and
     rehearse `pg_restore` + `alembic upgrade head` + `alembic check` on a
     disposable Compose project before retrying on the real volume.
   - **Partial migration or schema drift:** Restore your pre-migration backup
     into a **fresh target volume / new Compose project** (`-p`), verify table
     counts, relationships, and `alembic current`, fix the migration, test the
     upgrade on that restored copy, and only then cut over.
5. **Avoid destructive shortcuts:**
   - Never run `alembic downgrade base` against real study data:
     `migrations/versions/0001_initial.py`'s `downgrade()` drops `reviews`,
     `cards`, and `decks`.
   - Never run `alembic stamp <rev>` to silence an error unless you have
     verified the actual PostgreSQL schema matches that revision and confirmed
     zero drift with `alembic check`.

## Non-destructive volume handling

`compose.yaml` stores PostgreSQL data in the named volume `postgres_data`
(default full name: `techcards-srs_postgres_data`).

- **Avoid these destructive commands during routine work or recovery:**
  - `docker compose down --volumes` (or `-v`) on the live project
  - `docker volume rm techcards-srs_postgres_data`
  - `docker system prune --volumes`
  - `pg_restore --clean` against the live database without a verified backup
- **Preferred non-destructive workflow:**
  - Inspect volumes read-only with `docker volume ls` and
    `docker volume inspect techcards-srs_postgres_data`.
  - Stop containers without deleting data using `docker compose stop` or
    `docker compose down` (without `--volumes`).
  - Always test restores and new migrations in a **separate** Compose project
    (`-p`) with its own fresh volume and `POSTGRES_HOST_PORT`.
  - When cutting over to a restored volume, keep the old volume stopped as a
    fallback until you have verified decks, cards, and reviews in the new stack.
- **Destructive cleanup is opt-in and last-resort only:** Only run
  `down --volumes` or `docker volume rm` after confirming the exact `-p`
  project name or volume name and verifying that no unbacked-up study data
  remains in it.
