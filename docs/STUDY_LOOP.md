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

## Read-only template catalog (`/templates`)

- Built-in generic catalog served from `app/templates.py` (never auto-creates cards on list, get, startup, or migration):
  - **STAR scaffolds** (`kind="behavioral"`): `star-troubleshooting`, `star-collaboration` — truthful prompts requiring real experiences without invented achievements.
  - **Networking explain prompts** (`kind="interview_phrase"`): `net-vpc`, `net-subnetting`, `net-dns`, `net-tcp-handshake` — generic technical prompts with follow-up questions.
- `GET /templates` and `GET /templates/{template_id}` read the catalog; `POST /templates/{template_id}/cards` with `{"deck_id": ...}` explicitly creates one card (`201`) with `source_label="template:<id>"` and default SM-2 schedule (`due_date=today(UTC)`).

## Error log & interview remediation loop (`/errors`)

- Follows the `/sources` lifecycle (`draft` -> `approved` or `discarded`), empty by default with no seed rows.
- `POST /errors/suggest` (`201`) turns a submitted interview `answer` (with optional `prompt`, `category` = `"technical"` or `"star"`, optional `corrected`/`rationale` overrides, and strict boolean `consent: true`) into a `draft` `error_logs` entry plus a `suggested_card` preview (`front`, `back`, `kind`, `explanation`) using deterministic offline heuristics (no network calls, never invents STAR achievements or metrics). It **never** creates a card until the learner approves it. Combined `attempted` text must be `<= 4991` chars (`422` otherwise, and `422` if `consent` is not strictly `true`).
- `POST /errors`, `GET /errors` (optional `status`, `offset`, `limit`), `GET/PUT/DELETE /errors/{id}`, `POST /errors/{id}/discard`, `POST /errors/{id}/approve`.
- `POST /errors/{id}/approve?identity=<identity>` (use the identity from the draft response, `201`, `409` if not `draft`) atomically marks the error `approved`, creates a card (`kind` defaults to `behavioral` when omitted on `[STAR remediation]` entries and `interview_phrase` otherwise; explicit `kind`, `front`, `back`, `explanation` overrides are honored), and links them (`error_logs.card_id` FK `ON DELETE SET NULL`, exposed as `error.card_id` and `card.error_id`).
- `GET /errors/export` (optional `status`, `offset`, `limit` `1..1000`) returns a UTC-timestamped JSON snapshot (`exported_at`, `count`, `items`) preserving each original `attempted` answer alongside its linked `card` schedule snapshot (or `null`).
- **Consent, privacy, and retention:** Submitted interview text is stored only after explicit `consent: true`, exclusively in local loopback PostgreSQL (`127.0.0.1`) with zero third-party uploads. Do **not** submit employer-confidential, client, PII, or NDA material. Entries are retained locally until the learner deletes them (`GET /errors/export` is a read-only snapshot and does not delete stored rows): `DELETE /errors/{id}` (`204`) removes only the error log (keeping the card with `error_id: null`), while `DELETE /errors/{id}?delete_card=true` (`204`) atomically hard-deletes both the error log and its linked card (cascading that card's reviews).

## Pronunciation practice

For pronunciation, vocabulary, sentence, interview phrase, and listening cards
with references up to 1,000 characters, use `/study/{card_id}/pronunciation`:

- **Listen and shadow.** Send `POST /audio` with `Polly-Opt-In: true` to hear
  the reference when Polly is configured. Repeat along with the clip, or read
  the reference aloud if audio is unavailable.
- **Record and replay.** With the learner's consent, send the audio bytes to
  `POST /recording` with `Recording-Consent: true` and an audio content type
  (WebM, Ogg, WAV, MPEG, or MP4). The limit is 512 KiB. Use `GET /recording`
  to replay and `DELETE /recording` to discard the active attempt.
- **Compare.** Send `POST /compare` with your `spoken_transcript` and optional
  `learner_notes`. If the microphone is unavailable, send
  `{"microphone_available": false}` to practice without a recording. Term
  feedback compares the supplied text. Listen to the recording to assess your
  speech, then use the study grade endpoint to self-grade.

These endpoints require a direct loopback connection to the API process.
Forwarded requests and requests arriving through the Docker bridge are
rejected. For local clients on the host, run the API directly on loopback.
Recording bytes stay in the serving worker's memory for up to one hour, with
a limit of 32 clips per worker. Use one worker if you need to replay across
requests. Changing the reference, deck, or kind, or deleting the card, makes
its prior clips inaccessible. Superseded bytes expire from memory or are
evicted. Restarting the worker clears its recordings.
