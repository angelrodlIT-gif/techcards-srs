# Generate flashcards from pasted text

Generate flashcards from pasted text turns a job description, article excerpt, or interview notes into persisted vocabulary, interview-phrase, and behavioral flashcards inside a chosen deck using the deterministic offline generator.

## Sub-features

- `generate-glossary-and-templates` matches known technical terms in fixed glossary order (`aws`, `python`, `postgresql`, `docker`, `linux`, `terraform`, `monitoring`, `troubleshooting`, `api`, `sql`) into `vocabulary` cards and appends one `interview_phrase` and one `behavioral` template card.
- `generate-bounded` enforces `max_cards` (1–20, default `6`) as an upper bound and returns up to `max_cards` persisted cards.
- `generate-fallback` handles unrecognized text (no glossary matches) by creating the two generic `interview_phrase` and `behavioral` practice cards.
- `generate-deterministic` produces identical `(front, back, kind)` output for identical input text and `max_cards`, while persisting new card rows on each call.
- `generate-validate-and-missing-deck` rejects text shorter than 10 or longer than 20,000 trimmed characters and `max_cards` outside 1–20 with `422`, and returns `404` for a nonexistent `deck_id`.

## How to get to it (user POV)

- Send `POST /cards/generate` with `{"deck_id": <id>, "text": "<text>", "max_cards": <1-20>}` to the loopback API.
- Open `/docs` in a browser and use **Try it out** on `POST /cards/generate`.

## Driving it with control-techcards.sh

Preconditions:

- An isolated TechCards SRS instance is running (`RUN_ID` set) and `doctor "$RUN_ID" --save` passed.
- `GENERATOR_PROVIDER=mock` is active (the default and only implemented provider).
- `CTRL=.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh`.

- **Create a target deck.** Run `DECK_ID=$("$CTRL" req "$RUN_ID" 01-create-deck POST /decks '{"name":"Job descriptions"}' --body-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')`. Response is HTTP `201`.
- **Generate cards from text with known glossary terms.** Run `"$CTRL" req "$RUN_ID" 02-generate-known POST /cards/generate "{\"deck_id\":$DECK_ID,\"text\":\"AWS support role using Python, Linux and troubleshooting\",\"max_cards\":6}"`. Response is HTTP `201` with 6 cards: 4 `vocabulary` cards (`aws`, `python`, `linux`, `troubleshooting`), 1 `interview_phrase` card on `aws`, and 1 `behavioral` STAR card on `aws`, all due today (UTC) with `repetitions: 0`, `interval_days: 0`, `ease_factor: 2.5`.
- **Replay identical input and `max_cards` to verify determinism and non-idempotent persistence.** Run `"$CTRL" req "$RUN_ID" 03-generate-replay POST /cards/generate "{\"deck_id\":$DECK_ID,\"text\":\"AWS support role using Python, Linux and troubleshooting\",\"max_cards\":6}"`. Response is HTTP `201` with 6 newly persisted cards having distinct `id`s and the exact same ordered `(front, back, kind)` values as step `02`.
- **Verify `max_cards` truncation.** Run `"$CTRL" req "$RUN_ID" 04-generate-capped POST /cards/generate "{\"deck_id\":$DECK_ID,\"text\":\"AWS support role using Python, Linux and troubleshooting\",\"max_cards\":2}"`. Response is HTTP `201` with exactly 2 cards matching the first 2 `(front, back, kind)` entries from step `02`.
- **Verify unrecognized-text fallback in the same deck.** Run `"$CTRL" req "$RUN_ID" 05-generate-fallback POST /cards/generate "{\"deck_id\":$DECK_ID,\"text\":\"Coordinating quarterly stakeholder presentations across teams\",\"max_cards\":6}"`. Response is HTTP `201` with exactly 2 cards (`interview_phrase` and `behavioral`) referencing `"the technical responsibilities in this text"`.
- **Verify validation and missing deck errors.** Run `"$CTRL" req "$RUN_ID" 06-text-too-short POST /cards/generate "{\"deck_id\":$DECK_ID,\"text\":\"too short\"}"`, `"$CTRL" req "$RUN_ID" 07-bad-max-cards POST /cards/generate "{\"deck_id\":$DECK_ID,\"text\":\"AWS Python Linux role\",\"max_cards\":21}"`, and `"$CTRL" req "$RUN_ID" 08-missing-deck POST /cards/generate '{"deck_id":999999,"text":"AWS Python Linux role"}'`. Steps `06` and `07` return HTTP `422`; step `08` returns HTTP `404`.
- **Confirm persistence via HTTP and PostgreSQL.** Run `"$CTRL" req "$RUN_ID" 09-due-cards GET "/decks/$DECK_ID/due"` and `"$CTRL" db-query "$RUN_ID" 10-generated-rows "SELECT id, kind, left(front, 60) AS front_preview, due_date FROM cards WHERE deck_id=$DECK_ID ORDER BY id;"`. Both show all 16 newly persisted cards (6 + 6 + 2 + 2) in `$DECK_ID`, all due today (UTC), and no raw source-text table exists.
- **Proof.** Capture logs with `"$CTRL" logs "$RUN_ID"`, clean up with `"$CTRL" cleanup "$RUN_ID"`, and verify `doctor.txt`, `steps/01-*` through `steps/09-*`, `db/10-generated-rows.txt`, and `logs/compose.log` remain in `<evidence-dir>`.

## Gotchas

- `max_cards` is a maximum, not an exact count: text with zero glossary matches produces only 2 cards even when `max_cards` is `6` or `20`.
- `POST /cards/generate` is not idempotent: calling it twice with identical input persists a second set of duplicate cards with new IDs.
- Leading and trailing whitespace is stripped before enforcing the 10-character minimum (`"   short   "` fails with `422`).
- The generator runs strictly offline with a fixed 10-term glossary; do not expect LLM summarization or outbound network calls, and do not report deterministic template output as a bug.
