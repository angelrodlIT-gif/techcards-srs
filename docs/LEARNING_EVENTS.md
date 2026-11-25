# Learning Event Semantics

`GET /analytics/learning` is a read-only summary of the current local database.
One review is one committed `reviews` row from `POST /reviews` or
`POST /study/{card_id}/grade`. Both record the same self-assessed `quality` and
server `reviewed_at`. The row does not identify the route, a reveal, the answer
given, or whether a review was due. Fetching a prompt, revealing an answer, and
creating a template card are uncounted. Practice formats share the same review
shape. The database has no separate interview, listening, or speaking outcomes.

## Review and correction counts

| Measure | Numerator | Denominator |
| --- | --- | --- |
| `reviews.recall` | Reviews graded 3–5 | All usable graded reviews in the window, including first attempts and repeats |
| `reviews.lapse` | Reviews graded 0–2 immediately after a passing review of the same card | Usable reviews in the window whose immediately prior stored review for that card was graded 3–5 |
| `error_correction.first_review_recall` | Currently approved error logs whose linked card's first stored review was graded 3–5 in the window | Currently approved error logs whose linked card had its first stored review in the window with a usable grade |

Review order is UTC timestamp, then review ID. A lapse can follow a passing
review outside the window. A failing first review and consecutive failures stay
in the recall denominator but are outside the lapse denominator. An unusable grade
breaks the chain to the next review and cannot be skipped to find a passing
grade or a first review. A missing timestamp makes the affected card's sequence
unknown, so that card is excluded from lapse and first-review correction counts.

An error correction is a logged attempted/corrected pair. Approval creates and
links a reviewable card. Draft, discarded, and approved counts describe current
status across all dates. An approved error without a linked card (for example,
after card deletion) remains in `current_approved` and is also counted in
`current_approved_without_card`. Unreviewed and unlinked corrections have no
measured outcome. First review recall measures performance on the linked card.
The error log stores no approval timestamp, and the API cannot measure time to
correction or changes in performance on the original mistake.

## Dates, sessions, and time

- `start` and `end` are inclusive `YYYY-MM-DD` dates in `America/Cancun`. Omit
  either for an open boundary. `first_review_at` and `last_review_at` are UTC
  instants; the corresponding Cancun dates come from converting those instants
  before taking the date. SQLite's timezone-less stored review times are UTC by
  the review writer's contract. SM-2 due dates remain UTC scheduling dates.
- A session is an inferred cluster of usable reviews across decks. The first
  in-window review opens a session. A gap strictly greater than 30 minutes opens
  another, even when the dates match. Midnight alone does not split a session.
  A date window can clip a session to its in-window reviews.
- `observed_span_seconds` sums the first-to-last elapsed span of each inferred
  session. A single-review session contributes zero. An empty window has a
  `null` span and `null` first/last dates. The span can include idle time and
  omits practice before the first and after the last review. Active study time,
  response time, and time spent on ungraded practice are unmeasured.

## Quality checks and baseline

- A usable review has a timestamp and an integer grade from 0 through 5.
  Undated rows are counted across all dates because they cannot be placed in
  the window. Invalid grades on dated rows are counted within the window.
- Distinct review IDs are separate persisted rows. Extra rows with the same
  card, UTC instant, and grade are flagged as possible duplicates and retained
  in the metrics. Retry requests can persist rows with different timestamps.
  There is no attempt key to reliably distinguish retries from repeat practice.
- The report exposes `semantics_version: 1`, independent of the database
  revision. Run Alembic to the app's supported revision before collecting.
  If a migration or instrumentation change affects eligibility or meaning,
  version the report and compare only compatible baselines. Leave historical
  fields unmeasured where the earlier schema did not capture them. Card and deck
  deletions cascade to review history, and error deletion removes its link.
- Choose a fixed Cancun date window before normal study, for example four weeks.
  After it closes, save the summary with the window, semantics version, source
  revision, and any interruptions or deletions. Use only actual recorded reviews
  and corrections. Compare like windows with visible numerator, denominator,
  and quality counts. A zero denominator means the rate is unavailable. Small
  counts and repeated reviews of the same cards can make rates swing sharply.
  Grades from this summary alone cannot establish proficiency or durable recall.
