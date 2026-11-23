# Core API Study and Troubleshooting Runbook

This runbook walks through a complete local study session against the implemented
`techcards-srs` FastAPI backend, documents the exact SM-2, UTC, deletion, and
loopback rules enforced by the code, and provides a repeatable clean-install
checklist with pointers to existing troubleshooting and recovery guides.

Every request, response shape, and status code below was verified against the
current codebase (`app/main.py`, `app/models.py`, `app/schemas.py`, `app/sm2.py`,
`app/generator.py`, `compose.yaml`) and a disposable PostgreSQL 16 + FastAPI
Compose stack.

## Repeatable clean-install checklist

Use this checklist to bring up a fresh local stack (Linux, macOS, or Windows
PowerShell with Docker Compose v2; no local Python required):

1. **Clone and enter the repository:**
   ```console
   git clone https://github.com/angelrodlIT-gif/techcards-srs.git
   cd techcards-srs
   ```
2. **Start PostgreSQL, run migrations, and start the API:**
   ```console
   docker compose up --build -d
   ```
   Defaults work without creating `.env` (PostgreSQL on `127.0.0.1:5435`, API on
   `127.0.0.1:8000`, `GENERATOR_PROVIDER=mock`).
3. **Verify service states:**
   ```console
   docker compose ps -a
   ```
   Expected states:
   - `db`: `Up ... (healthy)`
   - `migrate`: `Exited (0)` — this one-shot service runs `alembic upgrade head`
     before `api` starts, so exiting with code `0` is expected.
   - `api`: `Up ... (healthy)`
4. **Verify migration head (optional explicit check):**
   ```console
   docker compose run --rm migrate alembic current
   ```
   Expected output includes `0001 (head)` (or the latest migration revision).
5. **Verify API liveness and OpenAPI docs:**
   ```console
   curl -i http://127.0.0.1:8000/health
   ```
   Expected response: `HTTP/1.1 200 OK` with `{"status":"ok"}`.
   Open `http://localhost:8000/docs` in a browser for Swagger UI (or fetch
   `http://127.0.0.1:8000/openapi.json` for the OpenAPI schema).
   > **Note:** `GET /health` checks API process liveness only — it does **not**
   > verify PostgreSQL connectivity. A `200 OK` from `/health` can still be
   > followed by database errors on data routes if `db` is stopped.
6. **Optional isolated test check:**
   ```console
   docker compose --profile test run --build --rm tests
   ```
   Runs `pytest` against in-memory SQLite and never connects to your PostgreSQL
   volume.
7. **Stop cleanly without losing study data:**
   ```console
   docker compose down
   ```
   Study data stays in the named Docker volume `postgres_data` (default full
   name: `techcards-srs_postgres_data`).

> **Warning:** `docker compose down --volumes` (or `-v`) **permanently deletes
> local study data** in `postgres_data`. Use it only for an intentional reset of
> disposable data. See [Non-destructive volume handling](BACKUP_RESTORE.md#non-destructive-volume-handling).

## Local study session walkthrough

All examples target `http://127.0.0.1:8000` (you can run the same payloads via
**Try it out** at `http://localhost:8000/docs`). Always pass the actual `id`
values returned by the API rather than assuming `1` on an existing database.

### 1. Create a deck (`POST /decks`)

```console
curl -i -X POST http://127.0.0.1:8000/decks \
  -H "Content-Type: application/json" \
  -d '{"name":"Cloud interviews","description":"Technical English practice"}'
```

Response: `201 Created`

```json
{"name":"Cloud interviews","description":"Technical English practice","id":1}
```

Validation: `name` is whitespace-trimmed, 1–120 characters; `description`
defaults to `""` (max 5,000 characters). Whitespace-only names return `422`.

### 2. Generate flashcards from pasted text (`POST /cards/generate`)

Use the `id` from step 1 as `deck_id`:

```console
curl -i -X POST http://127.0.0.1:8000/cards/generate \
  -H "Content-Type: application/json" \
  -d '{"deck_id":1,"text":"AWS support role using Python, Linux and troubleshooting","max_cards":6}'
```

Response: `201 Created` (returns 6 cards — IDs `1`–`4` `vocabulary` for `aws`,
`python`, `linux`, and `troubleshooting`, ID `5` `interview_phrase`, and ID `6`
`behavioral`; trimmed below to show all three card kinds):

```json
[
  {
    "deck_id": 1,
    "front": "Explain 'aws' in technical English.",
    "back": "Amazon Web Services: a cloud platform offering compute, storage and networking.",
    "kind": "vocabulary",
    "id": 1,
    "repetitions": 0,
    "interval_days": 0,
    "ease_factor": 2.5,
    "due_date": "2026-11-23"
  },
  {
    "deck_id": 1,
    "front": "How would you discuss your experience with aws?",
    "back": "Practice: I have worked with aws to [task]. Use a truthful example and explain your contribution.",
    "kind": "interview_phrase",
    "id": 5,
    "repetitions": 0,
    "interval_days": 0,
    "ease_factor": 2.5,
    "due_date": "2026-11-23"
  },
  {
    "deck_id": 1,
    "front": "Tell me about a time you solved a problem involving aws.",
    "back": "Use STAR: describe the Situation, Task, Action and Result. Choose a real experience; do not invent an outcome.",
    "kind": "behavioral",
    "id": 6,
    "repetitions": 0,
    "interval_days": 0,
    "ease_factor": 2.5,
    "due_date": "2026-11-23"
  }
]
```

Key generator behaviors (`app/generator.py` and `app/schemas.py`):

- `text` is trimmed and must be 10–20,000 characters; `max_cards` is 1–20
  (default `6`). Omitting `deck_id` returns `422`; a supplied `deck_id` with no
  matching deck returns `404` (`{"detail":"Deck not found"}`).
- `MockGenerator` is deterministic and offline: it matches whole lowercase ASCII
  words against a fixed 10-term glossary (`aws`, `python`, `postgresql`, `docker`,
  `linux`, `terraform`, `monitoring`, `troubleshooting`, `api`, `sql`), then
  appends one `interview_phrase` and one `behavioral` prompt, truncated to
  `max_cards`.
- It returns **up to** `max_cards` cards. Text with no glossary matches falls
  back to up to 2 generic practice prompts (`interview_phrase`, then
  `behavioral`), still truncated to `max_cards` (for example, `max_cards: 1`
  returns only the `interview_phrase` prompt).
- Pasted source `text` is not stored in the database, though matched terms appear
  in generated cards. You can also create single cards manually via `POST /cards`.

### 3. List cards due today (`GET /decks/{deck_id}/due`)

```console
curl -i "http://127.0.0.1:8000/decks/1/due?offset=0&limit=100"
```

Response: `200 OK` with a JSON array of `CardOut` objects where
`due_date <= today(UTC)`, ordered by `(due_date, id)`. All 6 newly generated
cards appear immediately because new cards start with `due_date = today(UTC)`.
Pagination accepts `offset >= 0` (default `0`) and `limit` 1–100 (default `100`).

### 4. Submit a review (`POST /reviews`) and verify updated state

Answer the card aloud, then submit `card_id` and integer `quality` (`0`–`5`):

```console
curl -i -X POST http://127.0.0.1:8000/reviews \
  -H "Content-Type: application/json" \
  -d '{"card_id":1,"quality":4}'
```

Response: `201 Created`

```json
{
  "id": 1,
  "card_id": 1,
  "quality": 4,
  "reviewed_at": "2026-11-23T02:36:49.294228Z",
  "interval_days": 1,
  "ease_factor": 2.5,
  "repetitions": 1,
  "due_date": "2026-11-24"
}
```

Inspect the updated card and confirm it left today's due queue:

```console
curl -i http://127.0.0.1:8000/cards/1
curl -i http://127.0.0.1:8000/decks/1/due
```

- `GET /cards/1` returns `200 OK` with `repetitions: 1`, `interval_days: 1`,
  `ease_factor: 2.5`, and `due_date: "2026-11-24"`.
- `GET /decks/1/due` now returns only the remaining 5 cards (IDs `2`–`6`).
- Editing a card with `PUT /cards/{card_id}` replaces `deck_id`, `front`, `back`,
  and `kind` while preserving `repetitions`, `interval_days`, `ease_factor`, and
  `due_date`.
- Review events are stored in PostgreSQL `reviews`, but no `GET` review history
  endpoint is implemented yet (tracked in issue `#7`).
- **Retry caution:** `POST /reviews` is intentionally **not idempotent**. Every
  accepted call appends another `reviews` row and advances or resets the schedule
  again. Do not blindly auto-retry after a timeout or `5xx`; check
  `GET /cards/{card_id}` first. See
  [Review transactions and retry semantics](MVP.md#review-transactions-and-retry-semantics).

### Common error responses

- `404 Not Found`: nonexistent deck or card ID — e.g. `{"detail":"Card not found"}`
  or `{"detail":"Deck not found"}`. Never mutates state.
- `422 Unprocessable Entity`: validation error with FastAPI's `{"detail":[...]}`
  list — for example, an omitted required field such as `deck_id`, `quality: 6`,
  `quality: "4"`, `quality: true`, `text` shorter than 10 characters, or
  `limit > 100`. Never mutates state.

## Grades (0–5) and SM-2 scheduling

`POST /reviews` requires `quality` to be a strict JSON integer from `0` to `5`
(strings, floats, and booleans fail with `422`). Scheduling is computed by
`schedule_review` in `app/sm2.py` with starting `ease_factor = 2.5`, minimum
floor `1.3`, and ease formula `ease + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)`
rounded to 8 decimal places:

| Grade | Meaning | Outcome | Ease delta | Resulting `repetitions` / `interval_days` |
| --- | --- | --- | --- | --- |
| `0` | Complete blackout | Fail | `-0.80` | `0` / `1` day |
| `1` | Incorrect response | Fail | `-0.54` | `0` / `1` day |
| `2` | Incorrect, but felt familiar | Fail | `-0.32` | `0` / `1` day |
| `3` | Correct with difficulty | Pass | `-0.14` | `+1` / SM-2 progression |
| `4` | Correct with hesitation | Pass | `0.00` | `+1` / SM-2 progression |
| `5` | Easy, confident recall | Pass | `+0.10` | `+1` / SM-2 progression |

- **Passing reviews (`3`–`5`):** increment `repetitions` by `1`. The next
  `interval_days` is `1` when prior `repetitions == 0`, `6` when prior
  `repetitions == 1`, and `ceil(prior_interval_days * prior_ease_factor)` for
  later reviews (using the card's ease factor *before* applying the current
  review's ease delta).
- **Failing reviews (`0`–`2`):** reset `repetitions` to `0`, set
  `interval_days = 1`, adjust ease (down to floor `1.3`), and schedule `due_date`
  for tomorrow UTC. For example, reviewing a card at `ease_factor: 2.6`,
  `repetitions: 1` with `quality: 2` produces `repetitions: 0`,
  `interval_days: 1`, `ease_factor: 2.28`, and tomorrow's UTC `due_date`.
- **No same-session relearning queue:** Unlike the original paper's UI loop, this
  API schedules failed cards for tomorrow UTC rather than keeping them in
  `GET /decks/{deck_id}/due` for the same UTC day.
- **Atomicity and concurrency:** `POST /reviews` locks the target `cards` row
  with `SELECT ... FOR UPDATE`, updates `cards` and inserts `reviews` in one
  transaction, and rolls back both on any error.

## UTC dates, `reviewed_at`, and `due_date`

All scheduling dates come from the server's UTC clock (`datetime.now(UTC)`,
normalized in `app/main.py` via `normalize_utc`, which rejects naive datetimes):

- **Card creation:** `POST /cards` and `POST /cards/generate` set
  `due_date = today(UTC)` so new cards are due immediately.
- **Due queue:** `GET /decks/{deck_id}/due` returns cards where
  `due_date <= today(UTC)`.
- **Review timestamps and next due date:** `POST /reviews` stores a
  timezone-aware UTC `reviewed_at` (for example, `2026-11-23T02:36:49.294228Z`)
  and computes `due_date = reviewed_at.date() + timedelta(days=interval_days)`.
- **UTC midnight boundary and local timezones:** A review at `23:59:59Z`
  schedules from that UTC date; at `00:00:00Z` the server rolls over immediately
  to the next UTC date and cards due on that date enter `/due`. If you study in
  the evening in a negative-offset timezone (for example, `21:36` at `UTC-5` is
  `02:36Z` the next day), created cards and review schedules already use the next
  UTC calendar date.
- **Early and overdue reviews:** Both are accepted and scheduled forward from the
  current UTC review date.

## Deletion cascades (`decks` -> `cards` -> `reviews`)

Both foreign keys in `app/models.py` and `migrations/versions/0001_initial.py`
declare `ON DELETE CASCADE` (`cards.deck_id -> decks.id` and
`reviews.card_id -> cards.id`). Deletions are hard deletes with no undo:

- **`DELETE /cards/{card_id}` (`204 No Content`):** deletes the card and cascades
  to every `reviews` row for that `card_id`. The parent deck and sibling cards
  remain intact.
- **`DELETE /decks/{deck_id}` (`204 No Content`):** deletes the deck, cascades to
  all `cards` in that deck, and cascades to all `reviews` belonging to those
  cards.
- **After deletion:** `GET /decks/{deck_id}`, `GET /cards/{card_id}`, and
  `POST /reviews` for deleted IDs return `404 Not Found`.

Observed in a disposable PostgreSQL 16 session: starting from `(decks=1, cards=6,
reviews=3)` where card `1` had 1 review and card `2` had 2 reviews,
`DELETE /cards/1` left `(1, 5, 2)` and `DELETE /decks/1` left `(0, 0, 0)`.

## Unauthenticated loopback limits

`techcards-srs` is a local single-operator API with **no authentication, no user
accounts, no authorization checks, no rate limiting, and no TLS**:

- `compose.yaml` publishes PostgreSQL on `127.0.0.1:${POSTGRES_HOST_PORT:-5435}:5432`
  and the API on `127.0.0.1:8000:8000`. Inside the container `uvicorn` listens on
  `0.0.0.0:8000` so Docker port forwarding works; the loopback restriction comes
  from the `127.0.0.1:` host binding in `compose.yaml`.
- If you run `uv run uvicorn app.main:app --reload` on the host, keep Uvicorn's
  default `127.0.0.1` bind and do not pass `--host 0.0.0.0`.
- **Impact on local study sessions:** Any local process or user able to reach
  `127.0.0.1:8000` can read, edit, review, or permanently delete all decks and
  cards without credentials. Do not expose port `8000` or `5435` on a LAN, public
  interface, or unauthenticated reverse proxy.

## Troubleshooting and recovery references

- **Startup, port conflicts, credentials, and logs:** See
  [README troubleshooting](../README.md#project-map-and-troubleshooting) and
  [Configuration and provider seam](../README.md#configuration-and-provider-seam)
  for `docker compose ps -a`, `docker compose logs db migrate api`, busy ports
  (`5435` / `8000`), and credential mismatches on an existing volume.
- **Backups, restores, migration failures, and volume safety:** See
  [Backup, restore, and migration recovery](BACKUP_RESTORE.md) for the disposable
  `./scripts/verify_backup_restore.sh` drill, [migration recovery](BACKUP_RESTORE.md#migration-failure-recovery),
  and [non-destructive volume handling](BACKUP_RESTORE.md#non-destructive-volume-handling).
- **Hands-on troubleshooting and API exercises:** See
  [Saturday learning tasks](NEXT_STEPS.md), including exercise 6
  ([#11](https://github.com/angelrodlIT-gif/techcards-srs/issues/11)) for
  reproducing and documenting a database-down failure against disposable local
  data (reserved for Angel in `docs/TROUBLESHOOTING.md`), and exercise 2
  ([#7](https://github.com/angelrodlIT-gif/techcards-srs/issues/7)) for exposing
  review history.
- **Design boundaries and concurrency/retry semantics:** See
  [MVP design](MVP.md) and
  [Review transactions and retry semantics](MVP.md#review-transactions-and-retry-semantics).
