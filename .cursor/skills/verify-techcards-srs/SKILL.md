---
name: verify-techcards-srs
description: Launch, verify, and capture proof against a live isolated TechCards SRS instance (local FastAPI HTTP JSON REST API with Swagger UI at /docs and PostgreSQL 16 via Docker Compose). Reach for this skill whenever you need end-to-end verification of deck/card CRUD, offline card generation, due queues, SM-2 review scheduling, Alembic migrations, or PostgreSQL side effects.
---

# Verify TechCards SRS

TechCards SRS is a loopback-only FastAPI HTTP JSON REST API backed by PostgreSQL 16 and Alembic migrations (`app/main.py`, `compose.yaml`). There is no custom frontend, no CLI/TUI, and no authentication. Users interact with the HTTP endpoints directly or through Swagger UI at `/docs` (OpenAPI spec at `/openapi.json`).

**Isolation matters:** `compose.yaml` binds the API to `127.0.0.1:8000` and PostgreSQL to `127.0.0.1:${POSTGRES_HOST_PORT:-5435}` under the default Compose project and `postgres_data` volume. A developer's live local instance may already own those ports and study data. Never drive or tear down the default project (`techcards-srs`). Always run verification through `.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh`, which allocates free loopback ports, uses an isolated Compose project (`verify-techcards-<run-id>`), mounts a fresh empty PostgreSQL volume, and leaves any existing local stack untouched. Multiple verification instances can run side by side safely.

## Launch

Run from the repository root (requires Docker with Compose v2, `curl`, and `python3`; no local Python virtualenv is needed because the app builds and runs inside Docker):

```bash
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh launch
```

Optional flags: `--run-id <id>`, `--api-port <port>`, `--db-port <port>`, `--evidence-dir <dir>`.

- `--run-id` must match `^[a-z0-9][a-z0-9_-]*$` so `run_id` maps 1-to-1 to Compose project `verify-techcards-<run-id>` (no two IDs can collide).
- `--evidence-dir` must not already exist and must be strictly outside the scratch state tree (`.../instances/`), so separate runs never mix evidence and cleanup can never delete proof files.

What `launch` does:
1. Atomically reserves the scratch directory (`${XDG_STATE_HOME:-$HOME/.local/state}/verify-techcards-srs/instances/<run-id>/`) and a fresh evidence directory, picks two unused `127.0.0.1` ports (leaving `8000` and `5435` untouched), writes JSON instance metadata (`instance.json`) and a scratch Compose override (`!override` on `db.ports` and `api.ports`), and passes fixed verification settings explicitly to `docker compose` (`POSTGRES_USER=techcards`, `POSTGRES_DB=techcards`, `GENERATOR_PROVIDER=mock`, unsetting `DATABASE_URL`) so exported shell variables cannot hijack the isolated run.
2. Runs `docker compose -p verify-techcards-<run-id> ... up --build -d` from the current checkout (`Dockerfile` target `runtime`) with an **empty** PostgreSQL volume (`verify-techcards-<run-id>_postgres_data`).
3. Waits for the full readiness chain, not just process startup:
   - `db` (`postgres:16-alpine`) container health is `healthy` (`pg_isready`).
   - `migrate` one-shot container (`alembic upgrade head`) has exited with code `0`.
   - `api` (`uvicorn app.main:app`) container health is `healthy`.
   - `GET /health` returns HTTP `200`.
   - `GET /decks` returns HTTP `200` (proving live PostgreSQL connectivity and migrated tables — `/health` alone does **not** touch the database).
4. Provisions a dedicated non-superuser `SELECT`-only PostgreSQL role (`techcards_ro`) inside the isolated verification database for `db-query`.
5. Prints `READY` along with `RUN_ID`, `COMPOSE_PROJECT`, `BASE_URL`, `DB_PORT`, and `EVIDENCE_DIR`.

There is no pre-loaded seed data; a fresh launch starts with empty `decks`, `cards`, and `reviews` tables. Verification journeys create their own data through the real HTTP endpoints.

To tear down the instance when finished (or after any failed attempt), always run:

```bash
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh cleanup <run-id>
```

## Doctor

Run this read-only check right after `launch`, and first whenever anything looks off:

```bash
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh doctor <run-id>
```

Add `--save` to also write the diagnostic report to `<evidence-dir>/doctor.txt`.

`doctor` mutates nothing and checks 12 conditions (exits `0` only if all 12 pass):
1. `instance_state`: `<run-id>` resolves to an active `verify-techcards-*` Compose project.
2. `db_container`: PostgreSQL container is running and `healthy`.
3. `migrate_container`: `migrate` exited with code `0`.
4. `api_container`: API container is running and `healthy`.
5. `port_ownership`: `docker compose port api 8000` and `port db 5432` match this run's loopback ports (confirming you are not hitting another instance on `8000`/`5435`).
6. `auth_surface`: no auth is configured and both ports bind strictly to `127.0.0.1`.
7. `build_freshness`: the running container's `techcards.verify.source_hash` label matches the current working tree (`app/`, `migrations/`, `Dockerfile`, `compose.yaml`, `alembic.ini`, `pyproject.toml`, `uv.lock`). If you edited code without rebuilding, `doctor` fails with a stale-build error — run `cleanup` and `launch` again.
8. `health_endpoint`: `GET /health` returns HTTP `200` and `{"status":"ok"}`.
9. `openapi_identity`: `GET /openapi.json` returns HTTP `200` with `info.title == "TechCards SRS"` and all expected route paths.
10. `db_connectivity`: `GET /decks` returns HTTP `200` with a JSON array.
11. `migrations_head`: `alembic current` inside the `api` container matches `alembic heads` (currently `0001`).
12. `db_readonly_role`: `techcards_ro` connects read-only to the isolated database.

## Drive

Read [features/README.md](features/README.md) first: it is the maintained verification source for all user-facing journeys and contracts. Drive features through real HTTP requests and inspect PostgreSQL side effects read-only:

```bash
# Send a real HTTP request and capture request + status + headers + body
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh req <run-id> 01-create-deck \
  POST /decks '{"name":"Cloud interviews","description":"Technical English practice"}'

# Extract an ID while still recording the full HTTP transcript to evidence
DECK_ID="$(.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh req <run-id> 01-create-deck \
  POST /decks '{"name":"Cloud interviews","description":"Technical English practice"}' --body-only \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

# Query PostgreSQL read-only (non-superuser SELECT-only role techcards_ro + default_transaction_read_only=on)
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh db-query <run-id> 01-decks \
  "SELECT id, name, description FROM decks ORDER BY id;"

# Verify Swagger UI is served
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh req <run-id> 00-docs GET /docs

# Capture Compose logs (db, migrate, api) before cleanup
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh logs <run-id>
```

Stable handles to use across all journeys:
- HTTP route paths: `/health`, `/docs`, `/openapi.json`, `/decks`, `/decks/{deck_id}`, `/decks/{deck_id}/due`, `/cards`, `/cards/{card_id}`, `/cards/generate`, `/reviews`.
- JSON fields: `id`, `name`, `description`, `deck_id`, `front`, `back`, `kind`, `repetitions`, `interval_days`, `ease_factor`, `due_date`, `card_id`, `quality`, `reviewed_at`.
- PostgreSQL tables: `decks`, `cards`, `reviews`, `alembic_version`.

## Evidence

Proof artifacts are written to a fresh directory per run:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/verify-techcards-srs/evidence/<run-id>/
```

(Override with `--evidence-dir <dir>` or `VERIFY_EVIDENCE_DIR`; the target directory must not already exist and must lie outside the scratch `instances/` tree.)

Saved end-to-end proof runs on the author's host (outside the repository, surviving cleanup):
- Latest verified proof (`features/study-reviews.md`): `~/.local/state/verify-techcards-srs/evidence/proof-study-reviews-v2/`
- Initial proof run (`features/study-reviews.md`): `~/.local/state/verify-techcards-srs/evidence/proof-study-reviews/`

What every proof run captures in `<evidence-dir>/`:
- `run-meta.json`: run ID, Compose project, git SHA, source hash, base URL, loopback ports, database/role/provider settings, UTC timestamp (no credentials).
- `doctor.txt`: output of `doctor <run-id> --save`.
- `steps/<step-name>.http.txt` and `steps/<step-name>.body.json`: exact HTTP method, URL, request JSON body, and either response status code, headers, and formatted body OR full `curl` transport-error details if the connection failed mid-request.
- `db/<label>.txt`: read-only SQL query (executed as the non-superuser `techcards_ro` `SELECT`-only role) and PostgreSQL result table confirming persisted rows and cascade deletions.
- `logs/compose.log`: `db`, `migrate`, and `api` logs proving `alembic upgrade head` ran from an empty database and requests hit the live Uvicorn process.

Proof standards (mandatory for every verification run):
- **Exercise the real user path**, not internal setters, direct SQL writes, or test-only endpoints (`TestClient` or `app.dependency_overrides` are unit tests, not live proof).
- **Capture the action and the resulting state**, not just the final screen: every `req` transcript records both the outgoing request payload and the returned response, and mutations are confirmed via follow-up reads (`GET /decks/{id}`, `GET /cards/{id}`, `GET /decks/{id}/due`).
- **Verify side effects alongside what is visible**: inspect PostgreSQL rows (`decks`, `cards`, `reviews`) via `db-query` to confirm atomic inserts, `reviews` history persistence (which has no HTTP read endpoint), and `ON DELETE CASCADE` removals.
- **Mocks only where a production boundary already isolates the external system**: `GENERATOR_PROVIDER=mock` is the only implemented production generator behind the `CardGenerator` protocol in `app/generator.py` and makes no external network calls. Do not inject test doubles or override dependencies when verifying the live app.
- **When the safe path is a dry-run or test mode, verify what it actually skips by observing rather than trusting its name**: for example, `uv run pytest` uses in-memory SQLite (skipping PostgreSQL `FOR UPDATE` row locks, Alembic migrations, and Docker runtime packaging), and `GET /health` skips database connectivity. Observe the real PostgreSQL stack and DB-backed routes directly instead of inferring coverage from liveness or unit-test names.

## Cleanup

Always tear down every verification instance you launched — including after failed runs — so containers, volumes, and ports are never stranded:

```bash
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh cleanup <run-id>
```

Cleanup rules enforced by the script:
- **Never kill by process name** (`pkill uvicorn`, `docker rm -f` by image, or `docker compose down` in the repo root are forbidden — they can destroy the user's running local stack).
- Refuses to act unless the recorded Compose project starts with `verify-techcards-`.
- Runs `docker compose -p verify-techcards-<run-id> ... down --volumes --remove-orphans --rmi local` to remove ONLY that run's containers, network, fresh database volume, and project-scoped image tags.
- Deletes ONLY the scratch instance state directory (`.../instances/<run-id>/`).
- **Never deletes `<evidence-dir>`** (`.../evidence/<run-id>/`) and verifies path disjointness before removing scratch state.

After cleanup, confirm that the instance is gone and the evidence survived:

```bash
docker ps -a --filter "label=com.docker.compose.project=verify-techcards-<run-id>"
ls -la "${XDG_STATE_HOME:-$HOME/.local/state}/verify-techcards-srs/evidence/<run-id>/"
```

## Helpers

| Script | Purpose |
| --- | --- |
| [.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh](scripts/control-techcards.sh) | Executable bash harness for isolated Compose lifecycle, read-only health/freshness checks, evidence-capturing HTTP requests, read-only PostgreSQL queries, log collection, and safe cleanup. |

Subcommand reference:

```bash
# 1. Start isolated stack from empty DB (migrations + API)
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh launch [--run-id ID] [--api-port PORT] [--db-port PORT] [--evidence-dir DIR]

# 2. Read-only health, build-freshness, port-ownership, DB, and migration check
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh doctor <run-id> [--save]

# 3. Print active run metadata (no credentials)
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh env <run-id>

# 4. Send real HTTP request and record full request+response evidence
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh req <run-id> <step-name> <METHOD> <PATH> [JSON_BODY] [--body-only]

# 5. Run read-only SQL against isolated Postgres and record evidence
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh db-query <run-id> <label> "<SQL>"

# 6. Save Compose logs (db, migrate, api) to <evidence-dir>/logs/compose.log
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh logs <run-id> [service...]

# 7. Tear down isolated stack and scratch state while preserving <evidence-dir>
.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh cleanup <run-id>
```
