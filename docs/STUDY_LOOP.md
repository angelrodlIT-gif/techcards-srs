# Study Loop, Templates, and Error Log

## Recall-safe study loop (`/study/*`)

- `GET /study/next?deck_id=` returns the next due card (`due_date <= today(UTC)`, ordered by `due_date, id`) **without** `back`, `accepted_answers`, or `explanation`, or `204` when nothing is due (`404` if the deck is missing).
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
`uv run uvicorn app.main:app --host 127.0.0.1 --workers 1`. Use the
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

## Error log (`/errors`)

- Follows the `/sources` lifecycle (`draft` -> `approved` or `discarded`), empty by default with no seed rows.
- `POST /errors`, `GET /errors` (optional `status`, `offset`, `limit`), `GET/PUT/DELETE /errors/{id}`, `POST /errors/{id}/discard`, `POST /errors/{id}/approve`.
- `POST /errors/{id}/approve` (`201`, `409` if not `draft`) atomically marks the error `approved`, creates a card (`kind` defaults to `interview_phrase`, `front`/`back`/`explanation` default from `attempted`/`corrected`/`rationale` with optional overrides), and links them (`error_logs.card_id` FK `ON DELETE SET NULL`, exposed as `error.card_id` and `card.error_id`).
- **Privacy & deletion:** Local loopback / local PostgreSQL only with no third-party uploads. Do **not** store employer-confidential, client, or NDA material. Delete any entry with `DELETE /errors/{id}` (`204`); linked cards remain intact with `error_id: null`.
