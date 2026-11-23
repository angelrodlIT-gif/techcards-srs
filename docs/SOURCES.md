# Manual Source-to-Card Curation Pipeline

`/sources` provides manual, offline source-to-card curation so you can save
selected vacancies, documentation links, and excerpts as drafts, edit or discard
them, and approve only reviewed material into scheduled study cards.

## Intake and lifecycle

- **Manual/API intake only:** The pipeline starts empty and performs **no
  scraping, crawling, HTTP fetches of source URLs, background ingestion, or seed
  content**.
- **Statuses:** New sources start as `draft` and transition one-way to
  `approved` or `discarded`. Nonexistent IDs return `404`; invalid payloads
  return `422`; editing, approving, or discarding a non-`draft` source returns
  `409`.

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` / `GET` | `/sources` | Create `draft` (`201`) / list (optional `status`, `offset`, `limit`) |
| `GET` / `PUT` / `DELETE` | `/sources/{id}` | Read / edit `draft` (`409` otherwise) / delete in any status (`204`) |
| `POST` | `/sources/{id}/approve` | `draft` -> `approved`; creates one `Card` (`201`) with `source_label = source.label` and default SM-2 schedule (`due_date = today(UTC)`) |
| `POST` | `/sources/{id}/discard` | `draft` -> `discarded` (`200`); terminal, creates no card |

## URL normalization, duplicates, and no auto-merge

- `url` is optional (blank -> `null`) and must be an absolute `http` or `https`
  URL without whitespace, control characters, or credentials (`422` otherwise).
- Deterministic `normalized_url` (while keeping trimmed input in `url`): trim;
  lowercase scheme and host; drop default ports (`80`/`443`); drop `#fragment`;
  normalize empty path to `/` and remove a trailing `/` on non-root paths; keep
  path case, query string, and `www` as-is.
- **Duplicates (`409`):** A partial unique index on non-null `normalized_url`
  blocks duplicate URLs on create and draft edit (including against existing
  approved/discarded rows until deleted). Multiple URL-less (`url: null`)
  sources are allowed, even with the same label.
- **No auto-merge:** Creating always inserts a new row and `PUT` replaces the
  draft's fields; excerpts are never merged or concatenated across sources.

## Privacy and deletion

- **Local-only:** Sources stay on loopback / local PostgreSQL with no
  third-party uploads.
- **Confidentiality warning:** Do **not** ingest employer-owned, client, or
  confidential material (NDA docs, internal tickets, proprietary code, customer
  data, or credentials).
- **Deletion:** `DELETE /sources/{id}` (`204`, any status) hard-deletes the
  source row only. Cards already created from it stay intact with their
  `source_label` and SM-2 schedule unchanged, and the deleted URL is freed.
