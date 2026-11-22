# Study due cards and record SM-2 reviews

Study due cards and record SM-2 reviews lets a learner inspect cards due on or before today (UTC) in a deck, submit a recall quality grade from `0` to `5`, advance or reset the card's SM-2 schedule atomically, and persist each review event in PostgreSQL.

## Sub-features

- `due-queue` returns cards in a deck whose `due_date <= today(UTC)` ordered by `due_date, id`, with `offset`/`limit` pagination (`404` if the deck does not exist).
- `review-pass-progression` advances passing grades (`3`, `4`, `5`) through SM-2 intervals (`1` day on first pass, `6` days on second pass, then `ceil(interval * ease)`), updates `ease_factor` with a `1.3` floor, and removes the card from today's due queue.
- `review-fail-reset` resets failing grades (`0`, `1`, `2`) to `repetitions=0`, schedules `interval_days=1` (`due_date = today(UTC) + 1 day`), lowers `ease_factor` (floored at `1.3`), and removes the card from today's due queue.
- `review-non-idempotent` records each repeated `POST /reviews` call for the same card as a separate review event and recomputes the schedule from the updated state.
- `review-validation-and-missing` rejects non-integer or out-of-range `quality` values (including booleans, floats, strings, `-1`, `6`) with `422` and nonexistent `card_id` with `404`.
- `review-atomic-persistence` commits both the updated `cards` row and the new `reviews` history row together in PostgreSQL.

## How to get to it (user POV)

- Send `GET /decks/{deck_id}/due`, `POST /reviews`, and `GET /cards/{card_id}` to the loopback API.
- Open `/docs` in a browser and use **Try it out** on `GET /decks/{deck_id}/due`, `POST /reviews`, and `GET /cards/{card_id}`.

## Driving it with control-techcards.sh

Preconditions:

- An isolated TechCards SRS instance is running (`RUN_ID` set) and `doctor "$RUN_ID" --save` passed.
- `CTRL=.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh`.
- Note current UTC dates: `TODAY_UTC=$(date -u +%Y-%m-%d)`, `TOMORROW_UTC=$(date -u -d '+1 day' +%Y-%m-%d)`, `PLUS6_UTC=$(date -u -d '+6 days' +%Y-%m-%d)` (use Python `datetime.now(UTC)` on macOS/BSD if `date -d` is unavailable).

- **Confirm Swagger UI is reachable.** Run `"$CTRL" req "$RUN_ID" 00-swagger-docs GET /docs`. Response is HTTP `200` with Swagger UI HTML referencing `/openapi.json`.
- **Create a study deck and two due cards.** Run `DECK_ID=$("$CTRL" req "$RUN_ID" 01-create-deck POST /decks '{"name":"SM-2 Study Session","description":"End-to-end review verification"}' --body-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')`, `CARD_PASS=$("$CTRL" req "$RUN_ID" 02-create-card-pass POST /cards "{\"deck_id\":$DECK_ID,\"front\":\"Explain PostgreSQL transactions\",\"back\":\"Atomic unit of work with ACID guarantees\",\"kind\":\"vocabulary\"}" --body-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')`, and `CARD_FAIL=$("$CTRL" req "$RUN_ID" 03-create-card-fail POST /cards "{\"deck_id\":$DECK_ID,\"front\":\"Explain Docker layers\",\"back\":\"Read-only filesystem diffs cached per instruction\",\"kind\":\"vocabulary\"}" --body-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')`. All three return HTTP `201`.
- **Inspect today's due queue.** Run `"$CTRL" req "$RUN_ID" 04-due-before GET "/decks/$DECK_ID/due"`. Response is HTTP `200` listing `[CARD_PASS, CARD_FAIL]` in ascending `id` order, both with `due_date == TODAY_UTC`, `repetitions: 0`, `interval_days: 0`, `ease_factor: 2.5`.
- **Record first passing review (quality 5).** Run `"$CTRL" req "$RUN_ID" 05-review-pass-1 POST /reviews "{\"card_id\":$CARD_PASS,\"quality\":5}"`. Response is HTTP `201` with `quality: 5`, `repetitions: 1`, `interval_days: 1`, `ease_factor: 2.6`, `due_date == TOMORROW_UTC`, and a UTC `reviewed_at` timestamp.
- **Verify reviewed card left today's due queue and persisted updated state.** Run `"$CTRL" req "$RUN_ID" 06-due-after-first GET "/decks/$DECK_ID/due"` and `"$CTRL" req "$RUN_ID" 07-card-pass-after-1 GET "/cards/$CARD_PASS"`. Due queue now contains ONLY `CARD_FAIL`; `GET /cards/$CARD_PASS` confirms `repetitions: 1`, `interval_days: 1`, `ease_factor: 2.6`, `due_date == TOMORROW_UTC`.
- **Replay the identical review payload (quality 5) on the same card to verify progression and non-idempotency.** Run `"$CTRL" req "$RUN_ID" 08-review-pass-2-identical POST /reviews "{\"card_id\":$CARD_PASS,\"quality\":5}"`. Response is HTTP `201` with a new review `id`, `quality: 5`, `repetitions: 2`, `interval_days: 6`, `ease_factor: 2.7`, and `due_date == PLUS6_UTC` (proving both second-pass SM-2 progression and that identical repeat requests are not deduplicated).
- **Establish a nonzero repetition count on the second card before testing failure reset.** Run `"$CTRL" req "$RUN_ID" 09-review-fail-setup-pass POST /reviews "{\"card_id\":$CARD_FAIL,\"quality\":4}"`, `"$CTRL" req "$RUN_ID" 10-card-fail-before-reset GET "/cards/$CARD_FAIL"`, and `"$CTRL" req "$RUN_ID" 11-due-after-second-pass GET "/decks/$DECK_ID/due"`. The review returns HTTP `201` with `repetitions: 1`, `interval_days: 1`, `ease_factor: 2.5`, and `due_date == TOMORROW_UTC`; `GET /cards/$CARD_FAIL` confirms `repetitions: 1`; `GET /decks/$DECK_ID/due` now returns `[]`.
- **Record a failing review (quality 1) on the second card and verify reset from `repetitions: 1` to `0`.** Run `"$CTRL" req "$RUN_ID" 12-review-fail-reset POST /reviews "{\"card_id\":$CARD_FAIL,\"quality\":1}"`, `"$CTRL" req "$RUN_ID" 13-card-fail-after-reset GET "/cards/$CARD_FAIL"`, and `"$CTRL" req "$RUN_ID" 14-due-after-fail GET "/decks/$DECK_ID/due"`. The review returns HTTP `201` with `repetitions: 0`, `interval_days: 1`, `ease_factor: 1.96`, and `due_date == TOMORROW_UTC`; `GET /cards/$CARD_FAIL` confirms `repetitions: 0` and `ease_factor: 1.96`; `GET /decks/$DECK_ID/due` remains `[]`.
- **Verify strict quality validation and missing-card handling.** Run `"$CTRL" req "$RUN_ID" 15-invalid-quality-str POST /reviews "{\"card_id\":$CARD_PASS,\"quality\":\"5\"}"`, `"$CTRL" req "$RUN_ID" 16-invalid-quality-bool POST /reviews "{\"card_id\":$CARD_PASS,\"quality\":true}"`, `"$CTRL" req "$RUN_ID" 17-invalid-quality-range POST /reviews "{\"card_id\":$CARD_PASS,\"quality\":6}"`, and `"$CTRL" req "$RUN_ID" 18-missing-card POST /reviews '{"card_id":999999,"quality":4}'`. Steps `15`–`17` return HTTP `422`; step `18` returns HTTP `404`.
- **Verify PostgreSQL side effects (`cards` and `reviews` tables).** Run `"$CTRL" db-query "$RUN_ID" 19-cards-and-reviews "SELECT id, repetitions, interval_days, ease_factor, due_date FROM cards WHERE deck_id=$DECK_ID ORDER BY id; SELECT id, card_id, quality, repetitions, interval_days, ease_factor, due_date, reviewed_at FROM reviews WHERE card_id IN ($CARD_PASS, $CARD_FAIL) ORDER BY id;"`. PostgreSQL shows 2 updated `cards` rows (`CARD_PASS` at `repetitions=2, interval_days=6, ease_factor=2.7, due_date=PLUS6_UTC`; `CARD_FAIL` at `repetitions=0, interval_days=1, ease_factor=1.96, due_date=TOMORROW_UTC`) AND 4 persisted `reviews` rows (two identical `quality=5` rows for `CARD_PASS`; one `quality=4` setup row followed by one `quality=1` reset row for `CARD_FAIL`).
- **Proof.** Capture Compose logs with `"$CTRL" logs "$RUN_ID"`, tear down with `"$CTRL" cleanup "$RUN_ID"`, and verify `doctor.txt`, `steps/00-*` through `steps/18-*`, `db/19-cards-and-reviews.txt`, `run-meta.json`, and `logs/compose.log` survive in `<evidence-dir>`.

## Gotchas

- Due-date filtering and new `due_date` calculations use **server UTC date**, not local timezone; near UTC midnight, computing expected dates in local time causes false mismatches.
- Failing a card (`quality` `0`, `1`, or `2`) still moves `due_date` to tomorrow (UTC), so the failed card immediately disappears from `GET /decks/{deck_id}/due`; same-session relearning is intentionally outside this API.
- `POST /reviews` has no idempotency key: retrying a review request creates another `reviews` row and advances or resets the schedule a second time.
- `quality` uses strict integer validation: JSON `true`, `2.5`, and `"5"` all return `422` rather than being coerced.
- Review history has no HTTP read endpoint yet; verifying `GET /cards/{card_id}` alone misses whether the `reviews` table recorded the event — always run `db-query` on `reviews`.
- `GET /health` only confirms the API process is alive, not that PostgreSQL is reachable; always check `doctor` (which queries `GET /decks` and `alembic current`) before attributing review failures to scheduling logic.
