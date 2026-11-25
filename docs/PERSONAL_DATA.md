# Personal data controls

Use these endpoints on the trusted, single-user loopback API at
`http://127.0.0.1:8000`. The API has no accounts or authentication.

## Export

Save the version 1 UTF-8 JSON attachment to a private location.

```sh
umask 077
set -C
curl --fail --silent --show-error http://127.0.0.1:8000/personal-data/export > personal-data.json
```

The response contains `format_version: 1` and a `data` object with one array
per table. All rows come from one database snapshot and are ordered by ID.
Dates use ISO 8601 and timestamps are in UTC. Nullable fields retain their
`null` values. Use the IDs to join records.

| Array | Contents |
| --- | --- |
| `decks` | Deck names and descriptions |
| `cards` | Prompts, answers, explanations, scheduling state, deck IDs, source labels and linked source IDs |
| `reviews` | Card IDs, grades, review timestamps, and scheduling state recorded at each review |
| `error_logs` | Attempts, corrections, rationale, status, linked card IDs and creation times where known |
| `sources` | Labels, URLs, excerpts, and status |

The complete snapshot is held in memory for this local API. It contains raw
personal text and any sensitive data a user entered into these fields. The API
sends `Cache-Control: no-store` and does not log export or request bodies.
Store the file privately and review its contents before sharing. Configuration,
environment secrets, server logs, static templates and raw generator inputs
that were never stored in a listed table are outside the format.

JSON is for portability and inspection. For a restorable database backup, use
PostgreSQL's dump/restore workflow. The disposable drill compares exports from
the source and restored databases using `./scripts/verify_backup_restore.sh`.
See the [backup and restore runbook](BACKUP_RESTORE.md).

## Delete selected rows

Find the row ID in the export and call
`DELETE /personal-data/{collection}/{id}`. The collection uses the array name
from the table above. A successful operation returns `204`. A missing row
returns `404`. Selected rows and their linked derivatives are removed in one
transaction.

| Selection | Effect |
| --- | --- |
| Deck | Deletes its cards and reviews. Clears their card links from retained error logs. |
| Card | Deletes the card and its reviews. Clears its card link from a retained error log. |
| Review | Deletes the history event and retains the card's current schedule. Delete the card to remove that state too. |
| Error log | Deletes the error log, its linked card, and the card's reviews. |
| Source | Deletes the source, cards with its stored source ID, and their reviews. |

Source approvals after migration 0006 record the source ID. Older approvals,
generated cards from pasted text, and manually assigned labels can lack a
stored link. Inspect the export and delete their card IDs explicitly when
needed. Source labels may be shared or edited, so deletion does not infer links
from matching text. The existing `DELETE /sources/{id}` and
`DELETE /errors/{id}` routes preserve cards. Use the personal-data routes for
the linked deletion above.

Deletion changes the active database. Previously saved backups and JSON files
keep their original contents and must be managed separately.

## Apply retention

Send an explicit cutoff to `POST /personal-data/retention`. Supported
collections are `reviews` (review time) and `error_logs` (creation time).
The cutoff must include a timezone, and rows exactly at it are retained.

```sh
curl --fail --silent --show-error http://127.0.0.1:8000/personal-data/retention \
  -H 'Content-Type: application/json' \
  -d '{"collection":"error_logs","before":"2026-01-01T00:00:00Z"}'
```

The response reports `matched` (selected rows, excluding derivatives),
`applied`, the collection and the UTC cutoff. This request previews the count.
To delete, send the same request with `"apply":true`. Apply evaluates the
cutoff against current data and follows the linked deletion rules above,
including deletion of any reviews on a removed error-derived card regardless
of their date. No scheduled retention job is installed. Error logs created
before migration 0006 have an unknown age and require explicit deletion by ID.
Decks, cards and sources have no creation timestamp and use explicit deletion.

## Future recordings and derivatives

When recordings, interview turns, transcripts, feedback or derived cards are
stored, keep durable links from derivatives to their owners. Extend the
`EXPORT_FIELDS` allowlist in `app/personal_data.py` and document any required
media packaging and version changes. Add an age field and define which rows
and files retention deletes. For files outside the database, use durable,
retryable cleanup so an interrupted request can finish unlinking and removing
both originals and derivatives. Verify export, linked deletion and recovery
with disposable data, and keep private answers and secrets out of logs.
