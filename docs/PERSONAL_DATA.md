# Personal data controls

Use the API on the local TechCards instance. This app has no authentication.
Keep the API bound to loopback and protect exported files as you would database
backups.

## Export

`GET /personal-data/export` downloads a consistent version 1 JSON snapshot.

```bash
curl --fail http://127.0.0.1:8000/personal-data/export -o techcards-personal-data.json
```

The top-level `data` object contains `decks`, `cards`, `reviews`, `error_logs`,
and `sources`. Each row has an integer `id` and a stable `identity`. Timestamps
are in UTC. The export includes study content, schedules, interview answers and
tracked relationships. It excludes credentials, generator configuration and
temporary pronunciation audio. Download recordings separately while they are
available through the pronunciation API.

This JSON is for portability. For a complete database restore use
[Backup and restore](BACKUP_RESTORE.md). Older backups can still contain rows
erased from the live database.

## Delete a selected row

Use both values from the same exported row. A missing row or an identity
mismatch returns HTTP 404. SQLite may assign the old numeric ID to a new row,
so preserve the identity alongside the ID when saving a selection.

```bash
curl --fail -X DELETE \
  'http://127.0.0.1:8000/personal-data/reviews/42?identity=0123456789abcdef0123456789abcdef'
```

- Decks delete their cards and reviews. Cards delete their reviews and clear
  any error log link. Card deletions through these controls also purge the
  deleted card's recordings in the serving process.
- Sources and error logs delete their tracked derivative cards and those cards'
  reviews. Cards sharing only the same source label are independent.
- Deleting review history leaves the card's current schedule intact.
- Older source labels carry no verified provenance. Migration 0007 also clears
  pre-upgrade SQLite error-to-card links because earlier SQLite connections
  allowed a deleted card ID to be reused without clearing the original link.
  Review and delete any remaining legacy cards individually. The migration
  removes SQLite cards with missing decks and reviews with missing cards.
  An older orphan that already inherited a real parent ID is indistinguishable
  from valid data, so review old SQLite data before bulk deletion.

## Retention

POST a timezone-aware cutoff for `reviews` or `error_logs`. The cutoff is
exclusive. The default previews the matching row count. Send the same request
with `"apply": true` to recalculate and delete in one transaction. Matching error
logs also delete their tracked derivatives. Older error logs with unknown
creation dates require explicit selection.

```bash
curl --fail -X POST http://127.0.0.1:8000/personal-data/retention \
  -H 'Content-Type: application/json' \
  -d '{"collection":"error_logs","before":"2026-01-01T00:00:00Z","apply":false}'
```
