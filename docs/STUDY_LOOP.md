# Study Loop, Templates, and Error Log

## Recall-safe study loop (`/study/*`)

- `GET /study/next?deck_id=` returns the next due card (`due_date <= today(UTC)`, ordered by `due_date, id`) **without** `back`, `accepted_answers`, or `explanation`, or `204` when nothing is due (`404` if the deck is missing).
- `POST /study/{card_id}/reveal` returns `back`, `accepted_answers`, and `explanation` (`404` if missing). Reveal is optional before grading.
- `POST /study/{card_id}/grade` accepts `{"quality": 0..5}` and applies the same atomic SM-2 path as `POST /reviews`.
- Existing `GET /decks/{deck_id}/due` (returns full `CardOut`) and `POST /reviews` remain unchanged.

## Read-only template catalog (`/templates`)

- Built-in generic catalog served from `app/templates.py` (never auto-creates cards on list, get, startup, or migration):
  - **STAR scaffolds** (`kind="behavioral"`): `star-troubleshooting`, `star-collaboration` — truthful prompts requiring real experiences without invented achievements.
  - **Networking explain prompts** (`kind="interview_phrase"`): `net-vpc`, `net-subnetting`, `net-dns`, `net-tcp-handshake` — generic technical prompts with follow-up questions.
- `GET /templates` and `GET /templates/{template_id}` read the catalog; `POST /templates/{template_id}/cards` with `{"deck_id": ...}` explicitly creates one card (`201`) with `source_label="template:<id>"` and default SM-2 schedule (`due_date=today(UTC)`).

## Error log (`/errors`)

- Follows the `/sources` lifecycle (`draft` -> `approved` or `discarded`), empty by default with no seed rows.
- `POST /errors`, `GET /errors` (optional `status`, `offset`, `limit`), `GET/PUT/DELETE /errors/{id}`, `POST /errors/{id}/discard`, `POST /errors/{id}/approve`.
- `POST /errors/{id}/approve` (`201`, `409` if not `draft`) atomically marks the error `approved`, creates a card (`kind` defaults to `interview_phrase`, `front`/`back`/`explanation` default from `attempted`/`corrected`/`rationale` with optional overrides), and links them (`error_logs.card_id` FK `ON DELETE SET NULL`, exposed as `error.card_id` and `card.error_id`).
- **Resolved field length validation (`422`):** `POST /errors/{id}/approve` validates the resolved card fields against existing `CardInput` limits (max 5,000 characters for `front`, `back`, and `explanation`) and returns `422` if exceeded — for example, a valid 5,000-character `attempted` makes the default `front` (`Correct: {attempted}`) exceed 5,000 characters. On `422`, the error remains `draft` and no card is created; pass a shorter `front` (or `back`/`explanation`) override and retry.
- **Privacy & deletion:** Local loopback / local PostgreSQL only with no third-party uploads. Do **not** store employer-confidential, client, or NDA material. Delete any entry with `DELETE /errors/{id}` (`204`); linked cards remain intact with `error_id: null`.

## Local study page (`/ui`)

The FastAPI app serves a loopback-only light-mode HTML study page at `GET /ui` (`GET /` redirects to `/ui`) with static assets under `/static/`. It uses same-origin requests to `/decks`, `/study/*`, `/templates`, and `/errors` without external CDNs, accounts, or build steps, and never calls `GET /decks/{deck_id}/due` during study.

Start the stack locally on loopback and open `http://127.0.0.1:8000/ui`:

```console
# Option A: Docker Compose (publishes API on 127.0.0.1:8000, DB on 127.0.0.1:5435)
docker compose up --build -d

# Option B: Host Python with uv (keeps Uvicorn's default 127.0.0.1 bind; never pass --host 0.0.0.0)
docker compose up db -d
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000/ui` in a browser on the same machine.
