# Study Loop, Templates, and Error Log

## Recall-safe study loop (`/study/*`)

- `GET /study/next?deck_id=` returns the next due card (`due_date <= today(UTC)`, ordered by `due_date, id`) **without** `back`, `accepted_answers`, or `explanation`, or `204` when nothing is due (`404` if the deck is missing). Includes `error_id` (`null` for non-remediation cards) and supports optional filters `kind` (e.g., `behavioral`, `interview_phrase`) and `remediation_only=true` (only cards linked to an `error_logs` entry) to practice corrected explanations and STAR responses in later sessions.
- `POST /study/{card_id}/reveal` returns `back`, `accepted_answers`, and `explanation` (`404` if missing). Reveal is optional before grading.
- `POST /study/{card_id}/grade` accepts `{"quality": 0..5}` and applies the same atomic SM-2 path as `POST /reviews`.
- Existing `GET /decks/{deck_id}/due` (returns full `CardOut`) and `POST /reviews` remain unchanged.

## Listening cards

Create a card with `kind: "listening"`, a cue in `front` (e.g. “What does DNS
cache?”), and the English transcript in `back`. Use the study endpoints to keep
the transcript hidden until the learner chooses to reveal it.

1. Call `GET /study/next?deck_id=…` to get the cue and card ID.
2. When the learner chooses to listen, send `POST /study/{card_id}/audio`
   with the header `Polly-Opt-In: true`. Play the returned `audio/mpeg` bytes.
   Replay the same bytes locally or repeat the request to use the server cache.
3. Call `POST /study/{card_id}/reveal` to read the transcript in `back`.
   For text-only study, skip audio or reveal immediately when audio returns
   `429` (budget exhausted) or `503` (disabled, busy, or unavailable).
4. Grade with `POST /study/{card_id}/grade`.

Audio is off by default. To enable it, set `POLLY_ENABLED=true`,
`POLLY_REGION` to a Polly region such as `us-east-1`, and `POLLY_VOICE_ID`
to a Standard US English voice such as `Joanna`. For AWS profile or role
credentials, run the API on the host with
`uv run uvicorn app.main:app --host 127.0.0.1 --workers 1 --no-proxy-headers`.
Connect directly on loopback and keep the audio endpoint off reverse proxies.
Use the
[AWS SDK credential chain](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html)
with `polly:SynthesizeSpeech` permission. The default Compose setup stays
offline for audio. On a cache miss, Polly receives the transcript as plain
text. Use transcripts you are permitted to send to AWS.

Each worker allows at most 20 synthesis attempts per rolling hour (including
failures), at most 1,000 characters per attempt, and zero SDK synthesis retries.
The Standard engine synthesizes MP3. Each worker keeps up to 64 successful
clips in RAM, capped at 512 KiB each. Clips are reused by transcript, region
and voice, expire after 24 hours and are purged on the next enabled audio
request. Least recently used clips are evicted at capacity. Restarting the
worker clears both the cache and budget. Use one worker for a single shared
limit. Deleted or edited cards stop serving the old clip for that card, but
the bytes may remain in memory until expiry, eviction, or restart.

## Pronunciation and shadowing practice

Practice pronunciation and shadowing on `pronunciation` cards as well as
`vocabulary`, `sentence`, `interview_phrase`, and `listening` cards whose `back`
is 1–1,000 characters (`409` for `behavioral`, `cloze`, `es_en`, or longer
backs). All `/study/.../pronunciation/...` endpoints require a direct loopback
connection (`127.0.0.1`, `::1`, or `localhost` without `Forwarded` or
`X-Forwarded-For` proxy headers; `403` otherwise).

1. **Listen:** Call `POST /study/{card_id}/pronunciation/audio` with
   `Polly-Opt-In: true` to fetch the reference `audio/mpeg` (`Cache-Control: no-store`).
   It shares the Polly cache and hourly budget with listening cards and returns
   `429` or `503` with a fallback message to use `/pronunciation/compare` or
   `/reveal` for text-only practice.
2. **Shadow:** Repeat the target word or mined sentence aloud in real time,
   matching content-word stress and clause pauses.
3. **Record & replay (or microphone-denied fallback):**
   - With explicit consent, upload a short local clip via
     `POST /study/{card_id}/pronunciation/recording` (`201`) with header
     `Recording-Consent: true` (`422` if missing or not `"true"`), a supported
     `Content-Type` (`audio/webm`, `audio/ogg`, `audio/wav`, `audio/x-wav`,
     `audio/mpeg`, `audio/mp4`; `415` otherwise), and 1–524,288 bytes (`422` if
     empty, `413` if over 512 KiB). Replay via
     `GET /study/{card_id}/pronunciation/recording` (`Cache-Control: no-store`).
   - If microphone permission is denied or unavailable, skip recording and call
     `POST /study/{card_id}/pronunciation/compare` with
     `{"microphone_available": false}` (optionally including
     `spoken_transcript` and/or `learner_notes`).
4. **Compare & self-grade:** Call `POST /study/{card_id}/pronunciation/compare`
   to receive deterministic intelligibility feedback (`matched_terms`,
   `missing_terms`, `extra_terms`, `intelligibility_focus`, actionable
   `pronunciation_notes` covering technical acronyms, initial s-clusters,
   regular `-ed` endings, voiced `/v/` and `/z/`, card notes, and self-check
   notes, plus a 4-step workflow summary). When `microphone_available` is `true`,
   either an active recording or a non-empty `spoken_transcript` is required
   (`409` otherwise). Feedback intentionally avoids unsupported numeric scores,
   percentages, phoneme grades, or CEFR levels. Finish by self-grading with
   `POST /study/{card_id}/grade`.

**Privacy, retention, and delete controls:** Learner recordings are held
exclusively in worker RAM (never written to disk or PostgreSQL), bounded to 32
clips of up to 512 KiB each with a 1-hour TTL and LRU eviction. A background
expiration timer automatically purges expired clips from RAM once their 1-hour
TTL elapses even while the worker is idle with no incoming requests, and worker
shutdown clears all remaining clips. Recordings are automatically invalidated
when a card's `deck_id`, `kind`, or `back` changes, or when the card, deck, or
linked error (`delete_card=true`) is deleted; in-flight uploads whose card
changes or is invalidated during upload are rejected (`409` or `404`) without
storing stale audio. Delete a single recording at any time with
`DELETE /study/{card_id}/pronunciation/recording` (`204`) or clear all
in-memory recordings with `DELETE /study/pronunciation/recordings` (`204`).

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
