# Study Loop, Templates, and Error Log

## Recall-safe study loop (`/study/*`)

- `GET /study/next?deck_id=` returns the next due card (`due_date <= today(UTC)`, ordered by `due_date, id`) **without** `back`, `accepted_answers`, or `explanation`, or `204` when nothing is due (`404` if the deck is missing). Includes `error_id` (`null` for non-remediation cards) and supports optional filters `kind` (e.g., `behavioral`, `interview_phrase`) and `remediation_only=true` (only cards linked to an `error_logs` entry) to practice corrected explanations and STAR responses in later sessions.
- `POST /study/{card_id}/reveal` returns `back`, `accepted_answers`, and `explanation` (`404` if missing). Reveal is optional before grading.
- `POST /study/{card_id}/grade` accepts `{"quality": 0..5}` and applies the same atomic SM-2 path as `POST /reviews`.
- Existing `GET /decks/{deck_id}/due` (returns full `CardOut`) and `POST /reviews` remain unchanged.

## Read-only template catalog (`/templates`)

- Built-in generic catalog served from `app/templates.py` (never auto-creates cards on list, get, startup, or migration):
  - **STAR scaffolds** (`kind="behavioral"`): `star-troubleshooting`, `star-collaboration` — truthful prompts requiring real experiences without invented achievements.
  - **Networking explain prompts** (`kind="interview_phrase"`): `net-vpc`, `net-subnetting`, `net-dns`, `net-tcp-handshake` — generic technical prompts with follow-up questions.
- `GET /templates` and `GET /templates/{template_id}` read the catalog; `POST /templates/{template_id}/cards` with `{"deck_id": ...}` explicitly creates one card (`201`) with `source_label="template:<id>"` and default SM-2 schedule (`due_date=today(UTC)`).

## Error log & interview remediation loop (`/errors`)

- Follows the `/sources` lifecycle (`draft` -> `approved` or `discarded`), empty by default with no seed rows.
- `POST /errors/suggest` (`201`) turns a submitted interview `answer` (with optional `prompt`, `category` = `"technical"` or `"star"`, optional `corrected`/`rationale` overrides, and strict boolean `consent: true`) into a `draft` `error_logs` entry plus a `suggested_card` preview (`front`, `back`, `kind`, `explanation`) using deterministic offline heuristics (no network calls, never invents STAR achievements or metrics). It **never** creates a card until the learner approves it. Combined `attempted` text must be `<= 4991` chars (`422` otherwise, and `422` if `consent` is not strictly `true`).
- `POST /errors`, `GET /errors` (optional `status`, `offset`, `limit`), `GET/PUT/DELETE /errors/{id}`, `POST /errors/{id}/discard`, `POST /errors/{id}/approve`.
- `POST /errors/{id}/approve` (`201`, `409` if not `draft`) atomically marks the error `approved`, creates a card (`kind` defaults to `behavioral` when omitted on `[STAR remediation]` entries and `interview_phrase` otherwise; explicit `kind`, `front`, `back`, `explanation` overrides are honored), and links them (`error_logs.card_id` FK `ON DELETE SET NULL`, exposed as `error.card_id` and `card.error_id`).
- `GET /errors/export` (optional `status`, `offset`, `limit` `1..1000`) returns a UTC-timestamped JSON snapshot (`exported_at`, `count`, `items`) preserving each original `attempted` answer alongside its linked `card` schedule snapshot (or `null`).
- **Consent, privacy, and retention:** Submitted interview text is stored only after explicit `consent: true`, exclusively in local loopback PostgreSQL (`127.0.0.1`) with zero third-party uploads. Do **not** submit employer-confidential, client, PII, or NDA material. Entries are retained locally until the learner deletes them (`GET /errors/export` is a read-only snapshot and does not delete stored rows): `DELETE /errors/{id}` (`204`) removes only the error log (keeping the card with `error_id: null`), while `DELETE /errors/{id}?delete_card=true` (`204`) atomically hard-deletes both the error log and its linked card (cascading that card's reviews).
