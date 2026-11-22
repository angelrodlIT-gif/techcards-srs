# Manage study decks

Manage study decks lets a learner create, list, inspect, rename or edit, and delete flashcard decks, with deck deletion cascading to remove all cards and review history belonging to that deck.

## Sub-features

- `deck-create` creates a deck with a required trimmed `name` (1–120 chars) and optional `description` (0–5000 chars, default `""`).
- `deck-list` lists decks in ascending `id` order with `offset` (>= 0) and `limit` (1–100) pagination.
- `deck-read` fetches a single deck by `deck_id` or returns `404` when absent.
- `deck-update` replaces both `name` and `description` on an existing deck.
- `deck-validate` rejects blank names and out-of-range pagination parameters with `422`.
- `deck-delete-cascade` deletes a deck (`204`) and cascades deletion to all child cards and their review records.

## How to get to it (user POV)

- Send `POST /decks`, `GET /decks`, `GET /decks/{deck_id}`, `PUT /decks/{deck_id}`, and `DELETE /decks/{deck_id}` to the loopback API.
- Open `/docs` in a browser and use **Try it out** on the `POST /decks`, `GET /decks`, `GET /decks/{deck_id}`, `PUT /decks/{deck_id}`, and `DELETE /decks/{deck_id}` operations.

## Driving it with control-techcards.sh

Preconditions:

- An isolated TechCards SRS instance is running (`RUN_ID` set) and `doctor "$RUN_ID" --save` passed.
- `CTRL=.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh`.

- **Create a deck.** Submit a titled deck with a description. Run `DECK_ID=$("$CTRL" req "$RUN_ID" 01-create-deck POST /decks '{"name":"Cloud interviews","description":"Technical English practice"}' --body-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')`. The saved step returns HTTP `201` with `id`, `name: "Cloud interviews"`, and `description: "Technical English practice"`.
- **List and paginate decks.** Fetch the deck list and test pagination offset. Run `"$CTRL" req "$RUN_ID" 02-list-decks GET "/decks?offset=0&limit=10"` and `"$CTRL" req "$RUN_ID" 03-list-decks-offset GET "/decks?offset=100&limit=10"`. The first returns HTTP `200` containing `DECK_ID`; the second returns HTTP `200` with `[]`.
- **Read and update the deck.** Read the deck by ID, then replace its `name` and `description`. Run `"$CTRL" req "$RUN_ID" 04-get-deck GET "/decks/$DECK_ID"` followed by `"$CTRL" req "$RUN_ID" 05-update-deck PUT "/decks/$DECK_ID" '{"name":"AWS Cloud Support","description":"Updated scope"}'`, then re-read with `"$CTRL" req "$RUN_ID" 06-get-deck-after-update GET "/decks/$DECK_ID"`. Both `PUT` and the follow-up `GET` return HTTP `200` with the updated `name` and `description`.
- **Verify validation errors.** Submit a whitespace-only name and an oversized page limit. Run `"$CTRL" req "$RUN_ID" 07-invalid-deck POST /decks '{"name":"   "}'` and `"$CTRL" req "$RUN_ID" 08-invalid-limit GET "/decks?limit=101"`. Both return HTTP `422`.
- **Create a child card and review before cascade delete.** Add one card and record one review so cascade deletion has real child rows to remove. Run `CARD_ID=$("$CTRL" req "$RUN_ID" 09-create-child-card POST /cards "{\"deck_id\":$DECK_ID,\"front\":\"What is IAM?\",\"back\":\"Identity and Access Management\"}" --body-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')` and `"$CTRL" req "$RUN_ID" 10-create-child-review POST /reviews "{\"card_id\":$CARD_ID,\"quality\":4}"`. Both return HTTP `201`.
- **Delete deck and verify cascade.** Delete the deck, then check HTTP reads and PostgreSQL tables. Run `"$CTRL" req "$RUN_ID" 11-delete-deck DELETE "/decks/$DECK_ID"`, `"$CTRL" req "$RUN_ID" 12-get-deleted-deck GET "/decks/$DECK_ID"`, `"$CTRL" req "$RUN_ID" 13-get-deleted-card GET "/cards/$CARD_ID"`, and `"$CTRL" db-query "$RUN_ID" 14-cascade-check "SELECT (SELECT count(*) FROM decks WHERE id=$DECK_ID) AS decks, (SELECT count(*) FROM cards WHERE deck_id=$DECK_ID) AS cards, (SELECT count(*) FROM reviews WHERE card_id=$CARD_ID) AS reviews;"`. `DELETE` returns HTTP `204` with an empty body, both `GET`s return HTTP `404`, and the PostgreSQL counts are `0 | 0 | 0`.
- **Proof.** Capture Compose logs with `"$CTRL" logs "$RUN_ID"`, tear down with `"$CTRL" cleanup "$RUN_ID"`, and confirm `doctor.txt`, all `steps/01-*` through `steps/13-*` transcripts, `db/14-cascade-check.txt`, and `logs/compose.log` exist in `<evidence-dir>`.

## Gotchas

- `PUT /decks/{deck_id}` is a full replacement: omitting `description` resets it to `""` rather than preserving the prior value.
- Leading and trailing whitespace is trimmed from `name`, so `"   "` becomes empty and returns `422`.
- HTTP `204` from `DELETE /decks/{deck_id}` alone does not prove review history was removed; verify `cards` and `reviews` row counts in PostgreSQL.
- Fetching or deleting a nonexistent deck returns `404` (`{"detail": "Deck not found"}`), whereas `limit=0` or `limit=101` returns `422`.
