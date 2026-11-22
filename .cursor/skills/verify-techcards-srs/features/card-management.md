# Manage flashcards

Manage flashcards lets a learner manually create cards inside a deck, list and filter cards by deck, edit card text, kind, or deck assignment without losing spaced-repetition scheduling state, and delete individual cards along with their review history.

## Sub-features

- `card-create` creates a card with `deck_id`, `front`, `back`, and `kind` (`vocabulary`, `interview_phrase`, or `behavioral`, default `vocabulary`), initialized due today (UTC) with `repetitions=0`, `interval_days=0`, `ease_factor=2.5`.
- `card-list-filter` lists all cards or filters by `deck_id` with `offset`/`limit` pagination, returning `404` if a filtered `deck_id` does not exist.
- `card-read` fetches a single card by `card_id` or returns `404` when absent.
- `card-update-preserve-schedule` replaces `deck_id`, `front`, `back`, and `kind` (including moving a card to another existing deck) while keeping `repetitions`, `interval_days`, `ease_factor`, and `due_date` unchanged.
- `card-validate` rejects blank `front`/`back`, invalid `kind`, or nonexistent `deck_id` (`422` for validation, `404` for missing deck).
- `card-delete-cascade` deletes a card (`204`) and cascades deletion to its `reviews` rows in PostgreSQL.

## How to get to it (user POV)

- Send `POST /cards`, `GET /cards`, `GET /cards?deck_id={deck_id}`, `GET /cards/{card_id}`, `PUT /cards/{card_id}`, and `DELETE /cards/{card_id}` to the loopback API.
- Open `/docs` in a browser and use **Try it out** on the `POST /cards`, `GET /cards`, `GET /cards/{card_id}`, `PUT /cards/{card_id}`, and `DELETE /cards/{card_id}` operations.

## Driving it with control-techcards.sh

Preconditions:

- An isolated TechCards SRS instance is running (`RUN_ID` set) and `doctor "$RUN_ID" --save` passed.
- `CTRL=.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh`.

- **Create two decks for card creation and move checks.** Run `DECK_A=$("$CTRL" req "$RUN_ID" 01-deck-a POST /decks '{"name":"Networking"}' --body-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')` and `DECK_B=$("$CTRL" req "$RUN_ID" 02-deck-b POST /decks '{"name":"Backend"}' --body-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')`. Both return HTTP `201`.
- **Create a flashcard.** Add a card to `DECK_A`. Run `CARD_ID=$("$CTRL" req "$RUN_ID" 03-create-card POST /cards "{\"deck_id\":$DECK_A,\"front\":\"Explain DNS\",\"back\":\"Translates domain names to IP addresses\",\"kind\":\"vocabulary\"}" --body-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')`. Response is HTTP `201` with `repetitions: 0`, `interval_days: 0`, `ease_factor: 2.5`, and `due_date` equal to today (UTC).
- **List unfiltered cards with pagination, then filter by deck.** Fetch unfiltered cards (including offset and invalid limit checks), then filter to `DECK_A`, `DECK_B`, and a missing deck. Run `"$CTRL" req "$RUN_ID" 04-list-all GET "/cards?offset=0&limit=10"`, `"$CTRL" req "$RUN_ID" 05-list-all-offset GET "/cards?offset=100&limit=10"`, `"$CTRL" req "$RUN_ID" 06-list-bad-limit GET "/cards?limit=101"`, `"$CTRL" req "$RUN_ID" 07-list-deck-a GET "/cards?deck_id=$DECK_A"`, `"$CTRL" req "$RUN_ID" 08-list-deck-b GET "/cards?deck_id=$DECK_B"`, and `"$CTRL" req "$RUN_ID" 09-list-missing-deck GET "/cards?deck_id=999999"`. Step `04` and `07` return a 1-element list containing `CARD_ID`, steps `05` and `08` return `[]`, step `06` returns HTTP `422`, and step `09` returns HTTP `404`.
- **Record a review so scheduling state is non-default.** Run `"$CTRL" req "$RUN_ID" 10-review-card POST /reviews "{\"card_id\":$CARD_ID,\"quality\":5}"`. Response is HTTP `201` with `repetitions: 1`, `interval_days: 1`, `ease_factor: 2.6`, and tomorrow's UTC `due_date`.
- **Edit and move the card across decks.** Replace fields and move the card to `DECK_B`. Run `"$CTRL" req "$RUN_ID" 11-update-card PUT "/cards/$CARD_ID" "{\"deck_id\":$DECK_B,\"front\":\"Explain HTTP idempotency\",\"back\":\"Repeating a request produces the same state\",\"kind\":\"interview_phrase\"}"` and re-read via `"$CTRL" req "$RUN_ID" 12-read-after-update GET "/cards/$CARD_ID"`. Both return HTTP `200` with `deck_id: DECK_B`, updated `front`/`back`/`kind`, and **unchanged** `repetitions: 1`, `interval_days: 1`, `ease_factor: 2.6`, and tomorrow's `due_date`.
- **Verify validation and missing-resource errors.** Run `"$CTRL" req "$RUN_ID" 13-blank-front POST /cards "{\"deck_id\":$DECK_B,\"front\":\"   \",\"back\":\"Answer\"}"`, `"$CTRL" req "$RUN_ID" 14-bad-kind POST /cards "{\"deck_id\":$DECK_B,\"front\":\"Q\",\"back\":\"A\",\"kind\":\"audio\"}"`, and `"$CTRL" req "$RUN_ID" 15-missing-deck POST /cards '{"deck_id":999999,"front":"Q","back":"A"}'`. The first two return HTTP `422`; the third returns HTTP `404`.
- **Delete the card and confirm review cascade.** Run `"$CTRL" req "$RUN_ID" 16-delete-card DELETE "/cards/$CARD_ID"`, `"$CTRL" req "$RUN_ID" 17-read-deleted-card GET "/cards/$CARD_ID"`, and `"$CTRL" db-query "$RUN_ID" 18-card-cascade-check "SELECT (SELECT count(*) FROM cards WHERE id=$CARD_ID) AS cards, (SELECT count(*) FROM reviews WHERE card_id=$CARD_ID) AS reviews;"`. `DELETE` returns HTTP `204`, follow-up `GET` returns HTTP `404`, and PostgreSQL counts are `0 | 0`.
- **Proof.** Capture logs with `"$CTRL" logs "$RUN_ID"`, clean up with `"$CTRL" cleanup "$RUN_ID"`, and verify `doctor.txt`, all `steps/01-*` through `steps/17-*`, `db/18-card-cascade-check.txt`, and `logs/compose.log` survive in `<evidence-dir>`.

## Gotchas

- `PUT /cards/{card_id}` requires `deck_id`, `front`, and `back` in every call; omitting `kind` resets it to the default `"vocabulary"`.
- Passing a nonexistent `deck_id` to `GET /cards?deck_id=...` returns HTTP `404`, not an empty list `[]`.
- Always check scheduling fields (`repetitions`, `interval_days`, `ease_factor`, `due_date`) after `PUT /cards/{card_id}` on a previously reviewed card; editing a fresh unreviewed card would hide a schedule-reset bug.
- Review cascade deletion on `DELETE /cards/{card_id}` is not visible through any HTTP endpoint — always inspect the PostgreSQL `reviews` table via `db-query`.
