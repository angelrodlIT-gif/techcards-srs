# Local Data Backup, Restore, and Migration Recovery

This runbook documents local PostgreSQL backup/restore verification, migration
failure recovery, and non-destructive Docker volume handling for `techcards-srs`.
It uses the repository's existing `compose.yaml` (`postgres:16-alpine` and the
`migrate` service) without adding a second database stack.

## Safety rules

- **Disposable data and fresh projects only:** Backup/restore exercises run
  exclusively through `scripts/verify_backup_restore.sh`, which generates fresh
  Compose project names (`-p`) per run, verifies no pre-existing containers,
  volumes, or networks match those names, and only tears down stacks created and
  owned by that run. Never run drills against the live `techcards-srs` stack or
  its `techcards-srs_postgres_data` volume.
- **No secrets:** The drill ignores `.env` (`--env-file /dev/null`) and uses
  obvious disposable placeholder credentials (`disposable_user` /
  `disposable-local-test-only` / `techcards_disposable`). Never pass passwords
  in CLI arguments and never commit `.dump`, `.sql`, or `.env` files to Git.
- **Exclusive owner-only dump files:** Dumps must be created exclusively as
  regular files (`0600`) inside an owner-only (`0700`) directory outside the
  repository (`umask 077`, `mktemp`), refusing symlinks, FIFOs, or pre-existing
  files.

## Current storage and schema layout

From `compose.yaml` and `migrations/versions/0001_initial.py`:

- **Engine and volume:** `postgres:16-alpine` (`db:5432`, loopback host port
  `${POSTGRES_HOST_PORT:-5435}`) persisting data in named Compose volume
  `postgres_data` (default full name: `techcards-srs_postgres_data`).
- **Migrations:** One-shot `migrate` service runs `alembic upgrade head`.
  `migrations/env.py` wraps migrations in `context.begin_transaction()`.
- **Tables and relationships:** `decks` -> `cards` (`deck_id` FK, `ON DELETE
  CASCADE`, SM-2 check constraints) -> `reviews` (`card_id` FK, `ON DELETE
  CASCADE`, `quality` check constraint), plus `alembic_version`.

## Disposable backup/restore verification drill

### Prerequisites

- Docker with Compose v2
- Bash (Linux, macOS, WSL, or Git Bash) and Python 3
- Run from the repository root (the live `techcards-srs` stack may stay running
  on ports `5435`/`8000`; the drill starts only disposable `db` and `migrate`
  services on separate loopback ports)

### Run the drill

Use `scripts/verify_backup_restore.sh` as the single supported drill path (do
not maintain a separate manual shell sequence that can diverge or leave stale
shell state):

```bash
./scripts/verify_backup_restore.sh
```

### Options

- `SRC_PORT` (default `15435`): loopback port for the disposable source DB.
- `DST_PORT` (default `15436`): loopback port for the disposable target DB.
- Both ports must be numeric, distinct, and must not be `5435` (the default
  live PostgreSQL port).

### What the script verifies

1. Pins Compose explicitly to the repository's `compose.yaml` (`-f` and
   `--project-directory`) while clearing `COMPOSE_FILE`, `COMPOSE_PROFILES`,
   and `COMPOSE_PROJECT_NAME` so local override files or inherited env vars
   cannot redirect `postgres_data`. Generates unique timestamp+random Compose
   project names (`techcards-backup-src-*` and `techcards-backup-dst-*`),
   inspects the rendered Compose config to verify `postgres_data` resolves to
   `<project>_postgres_data`, and fails closed if any Docker query fails or any
   container, volume, or network already exists before claiming ownership or
   running startup/cleanup.
2. Starts the disposable source PostgreSQL 16 database, runs `alembic upgrade
   head`, and seeds disposable `decks`, `cards`, and `reviews`.
3. Creates a private `0700` temporary directory (`umask 077`, `mktemp -d`) and
   an exclusive `0600` regular dump file (`mktemp`), refusing non-regular targets
   (such as FIFOs or symlinks), and writes a `pg_dump --format=custom` backup.
4. Marks the dump ready only after `pg_dump` succeeds and produces a non-empty
   regular file; inspection (`pg_restore --list`) and restore (`pg_restore
   --single-transaction --exit-on-error`) refuse to run without a verified dump
   from the current run.
5. Starts a fresh disposable target PostgreSQL 16 database (without running
   `migrate` first), restores the dump, and verifies:
   - Exact source/target counts (`decks=2`, `cards=4`, `reviews=5`).
   - Foreign-key relationships (3-table inner join `reviews -> cards -> decks`
     matches `5`; `0` orphan cards; `0` orphan reviews; per-deck counts match).
   - Sequence and FK/check-constraint integrity via a rolled-back probe insert.
   - Alembic parity (`alembic current` at `0001 (head)` and `alembic check`
     reporting no schema drift).
6. Tears down only disposable stacks owned by the current run and removes the
   temporary dump directory on exit.

### Expected successful output

A passing run prints:

- `Source summary (decks|cards|reviews|joined_reviews|orphan_cards|orphan_reviews): 2|4|5|5|0|0`
- `Dump created (43 TOC entries).`
- `Target summary (decks|cards|reviews|joined_reviews|orphan_cards|orphan_reviews): 2|4|5|5|0|0`
- Per-deck breakdown: `1|Cloud Interviews|2|3` and `2|Python Backend|2|2`
- `Sequence and FK/check-constraint probe passed (rolled back).`
- `Restored Alembic revision: 0001 (head)` and `No new upgrade operations detected.`
- `==> Disposable backup/restore verification PASSED.` followed by cleanup lines
  for both owned disposable stacks.

## Migration failure recovery

Because `migrations/env.py` wraps `context.run_migrations()` in
`context.begin_transaction()`, standard PostgreSQL DDL errors inside a single
revision roll back atomically. Multi-revision upgrades or operations inside an
`autocommit_block()` (for example, `CREATE INDEX CONCURRENTLY`) can still leave
partial schema changes.

If a migration fails on real study data:

1. **Stop and protect the volume.** Do not remove Docker volumes. Stop the API
   service if needed while leaving PostgreSQL data intact.
2. **Inspect the state read-only.** Check `migrate` logs, inspect the current
   Alembic revision (`alembic current` and `alembic history --verbose`), and
   compare `alembic_version` with the actual PostgreSQL tables and constraints.
3. **Capture an exclusive private safety backup** outside the Git repository
   (`0700` directory, exclusively created `0600` regular file) before making any
   manual change.
4. **Recover without touching live data blindly:**
   - **Clean rollback (`alembic_version` stayed at the prior revision with no
     partial objects):** Revert to the prior working revision if you need the
     app running immediately, fix the migration, and rehearse restore +
     `alembic upgrade head` + `alembic check` against a fresh disposable project
     before retrying on the real volume.
   - **Partial migration or schema drift:** Restore your pre-migration backup
     into a fresh volume / new Compose project, verify deck/card/review counts,
     relationships, and `alembic current`, fix and verify the upgrade on that
     copy, and only then cut over.
5. **Avoid destructive shortcuts:**
   - Never run `alembic downgrade base` against real study data:
     `migrations/versions/0001_initial.py`'s `downgrade()` drops `reviews`,
     `cards`, and `decks`.
   - Never run `alembic stamp <rev>` to silence an error unless you have
     verified the actual PostgreSQL schema matches that revision and confirmed
     zero drift with `alembic check`.

## Non-destructive volume handling

`compose.yaml` stores study data in the named volume `postgres_data` (default
full name: `techcards-srs_postgres_data`).

- **Avoid destructive commands during routine work or recovery:** Never run
  `docker compose down --volumes` (`-v`), `docker volume rm`,
  `docker system prune --volumes`, or `pg_restore --clean` against a volume that
  may contain real study data.
- **Preferred non-destructive workflow:** Inspect volumes read-only (`docker
  volume ls`, `docker volume inspect`), stop containers without removing data
  (`docker compose stop` or `docker compose down`), test restores and migrations
  in a fresh isolated Compose project, and keep the previous volume stopped as a
  fallback until counts and relationships are verified in the replacement stack.
- **Destructive cleanup is opt-in and last-resort only:** Delete a volume only
  after confirming its exact project/volume name, verifying ownership, and
  confirming that no unbacked-up study data remains.
