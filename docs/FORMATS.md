# Card Practice Formats

Cards support eight `kind` values across `POST /cards`, `PUT /cards/{id}`, and
`POST /sources/{id}/approve` (default remains `vocabulary`):

- Existing kinds: `vocabulary`, `interview_phrase`, `behavioral`.
- `sentence`: contextual sentence mining (`front` is the sentence/prompt; `back`
  is the target word, phrase, or meaning).
- `cloze`: unambiguous cloze (`front` must contain **exactly one** `____`
  four-underscore blank; `0` blanks, `2+` blanks, or runs of 5+ underscores
  return `422`; `back` is the primary completion).
- `es_en`: ES→EN production (`front` is the Spanish prompt; `back` is the
  primary English production).
- `listening`: technical English comprehension. Use `front` for a prompt that
  keeps the transcript hidden and `back` for the English transcript (1–1,000
  characters after trimming). See [Listening cards](STUDY_LOOP.md#listening-cards).
- `pronunciation`: technical English pronunciation and shadowing practice. Use
  `front` for the word/phrase cue and `back` for the reference word or mined
  English sentence (1–1,000 characters after trimming). See
  [Pronunciation and shadowing practice](STUDY_LOOP.md#pronunciation-and-shadowing-practice).

## Alternatives and explanations

Both optional fields work on every card `kind`:

- `accepted_answers`: list of valid alternative answers/translations (default
  `[]`, max 20 items, each 1–5,000 chars after trimming, blanks dropped, NUL
  bytes rejected with `422`). Uniqueness is exact and case-sensitive (no
  case-folding, no auto-merge on `PUT`). `back` is the primary answer and does
  not need to be duplicated.
- `explanation`: optional answer note (trimmed; blank/whitespace normalizes to
  `null`; max 5,000 chars; NUL bytes rejected with `422`).

## Boundaries and migration safety

- **No auto-grading:** `POST /reviews` stays integer `quality` (`0`–`5`) with
  identical SM-2 scheduling across all kinds. `accepted_answers` and
  `explanation` are stored for learner self-review, not scored by the API.
- **Generator unchanged:** `POST /cards/generate` (`MockGenerator`) continues to
  emit only `vocabulary`, `interview_phrase`, and `behavioral`.
- **Safe migration (`0004`):** adds nullable `accepted_answers` (JSON) and
  `explanation` (Text) to `cards` without rewriting existing rows or schedules.
  Pre-migration rows with SQL `NULL` serialize as `accepted_answers: []` and
  `explanation: null`. `PUT /cards/{id}` preserves scheduling fields. Rolling
  back (`downgrade` to `0003`) performs a lossy remap of `sentence`, `cloze`,
  and `es_en` rows to `kind = 'vocabulary'` before dropping the new columns so
  rolled-back cards remain readable on the pre-`0004` API (original kinds are
  not recovered on a later re-upgrade).
