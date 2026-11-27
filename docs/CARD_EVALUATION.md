# Generated Card Evaluation

Before generated flashcards enter the personal SM-2 review queue, `techcards-srs`
supports an offline categorical **preview -> edit -> approve** flow so
low-quality, contradictory, ambiguous, or ungrounded drafts are caught before
persistence (`app/evaluation.py`, `app/main.py`, `app/schemas.py`).

## Preview, edit, and approve flow

1. **Preview (`POST /cards/generate/preview` -> `200 OK`):**
   - Verifies that `deck_id` exists, releases the read transaction (`db.rollback()`)
     before calling the configured `CardGenerator`, and re-verifies the deck
     before returning evaluated `GeneratedCardDraftOut` items.
   - Persists **zero** `Card` rows.
   - Every returned draft includes `evaluation`:
     - `status`: `"draft"` when `ready_for_review` is `true` (no check is
       `"fail"`), or `"rejected"` when `ready_for_review` is `false`.
     - `checks`: categorical status (`"pass"`, `"warn"`, or `"fail"`) across all
       four dimensions.
     - `uncertainty`: explicit caveats (bracketed placeholders, missing
       `accepted_answers` on `cloze`/`es_en`, practice scaffolds requiring
       truthful personal history, glossary-derived wording, and offline rule
       scope).
     - `rejection_reasons`: concrete reasons for every `"fail"` check (empty on
       `"draft"` items).
2. **Edit locally (client-side):**
   - Review warnings and uncertainty notes, replace bracketed placeholders such
     as `[task]` with truthful details, add `accepted_answers` or `explanation`,
     or discard `"rejected"` drafts.
3. **Approve (`POST /cards/generate/approve` -> `201 Created`):**
   - Validates the card payload (`GeneratedCardApproveInput`, inheriting all
     `CardInput` rules plus `source_text`) and re-runs
     `evaluate_generated_card(...)`.
   - If `evaluation.ready_for_review` is `false`, returns `422 Unprocessable
     Entity` with the joined `rejection_reasons` and persists **zero** rows.
   - If `evaluation.ready_for_review` is `true`, persists the `Card` with
     `due_date = today(UTC)` and returns `{"card": ..., "evaluation": ...}`.

`POST /cards/generate` remains unchanged for direct generation without the
preview/approve gate.

## Evaluation dimensions

All four checks emit categorical statuses (`pass` | `warn` | `fail`). The
evaluator intentionally does **not** produce numeric quality scores,
percentages, or CEFR proficiency labels.

| Dimension | `fail` conditions | `warn` conditions |
| --- | --- | --- |
| `english_usefulness` | NUL bytes in any field; field over 5,000 chars (`back` over 1,000 chars for `listening`); bare URLs or missing meaningful alphabetic English words (`[A-Za-z][A-Za-z0-9]+`); fewer than 2 words in `front`/`explanation` or fewer than `min_back_words` (`1` for `cloze`, `2` otherwise) in `back`/`accepted_answers`. | None (categorical `pass`/`fail`). |
| `technical_accuracy` | Known technical contradictions checked per clause across all fields (e.g., stateless AWS security groups, stateful NACLs, connectionless/unreliable TCP, connection-oriented UDP or UDP 3-way handshake, permanent/static IAM role credentials, NoSQL PostgreSQL/SQL, or misclassified Docker/Python/Linux/Terraform); ungrounded metrics (comma-separated, decimal, currency, or unit metrics not present in `source_text`); first-person achievement claims (`I led`, `we reduced`, etc.) not supported within a single clause of `source_text` (exact claim phrase, content tokens without glossary expansion, and exact numbers). Only `back` on `behavioral`/`interview_phrase` cards with an explicit practice scaffold hint and strictly generic `worked with` phrasing is exempted. | None (categorical `pass`/`fail`). |
| `ambiguity` | `back`, `explanation`, or any `accepted_answers` entry equals `front`; word count below minimums; unresolved markers (`TODO`, `TBD`, `???`) in any field; `cloze` card whose `front` does not contain exactly one `____` blank. | Bracketed placeholder (e.g., `[task]`, `[project]`) in any field, or `cloze`/`es_en` card with empty `accepted_answers` (when no `fail` triggered). |
| `source_grounding` | Generic fallback topic (`"the technical responsibilities in this text"`) in any field; zero content-token overlap (`len >= 2`, stopwords excluded) between `source_text` and `front | back`; ungrounded `back`, `explanation`, or `accepted_answers` against `source_text` plus glossary definitions for terms present in `source_text` (except explicit `behavioral`/`interview_phrase` practice scaffolds whose `front` is grounded in `source_text`). | None (categorical `pass`/`fail`). |

## Reviewed fixtures and actual observations

`EVALUATION_FIXTURES` in `app/evaluation.py` contains 3 reviewed fixtures and 12
labeled cases exercised in `tests/test_card_evaluation.py`:

| Fixture ID | Category | Cases | Observed outcomes |
| --- | --- | --- | --- |
| `vacancy-cloud-support` | Job vacancy | 4 | Clean glossary-backed `postgresql` vocabulary card -> `draft` (all `pass`, glossary-reliance uncertainty); `MockGenerator`-style `interview_phrase` with `[task]` -> `draft` (`ambiguity: warn`, placeholder uncertainty); fabricated `70% / 200 servers / $50,000` claim -> `rejected` (`technical_accuracy: fail`); generic fallback topic card -> `rejected` (`source_grounding: fail`, `ambiguity: warn`). |
| `aws-docs-vpc-iam` | AWS VPC & IAM docs | 4 | `cloze` with 2-character answer `"IP"` and no `accepted_answers` -> `draft` (`ambiguity: warn`, preserves `"IP"` token); `cloze` on IAM temporary credentials with grounded `accepted_answers` and `explanation` -> `draft` (all `pass`); stateless security group contradiction -> `rejected` (`technical_accuracy: fail`); bare documentation URLs -> `rejected` (`english_usefulness`, `ambiguity`, and `source_grounding` all `fail`). |
| `interview-networking-star` | Interview prep & STAR notes | 4 | Valid TCP vs. UDP contrast -> `draft` (all `pass`, no contradiction false positive); single-sentence grounded claim with comma-separated `1,170ms` -> `draft` (all `pass`); UDP three-way handshake contradiction -> `rejected` (`technical_accuracy: fail`); cross-sentence `"I led the Docker migration"` + suffix metric `170ms` + `TODO` -> `rejected` (`technical_accuracy: fail`, `ambiguity: fail`). |

Additional targeted observations verified in `tests/test_card_evaluation.py`:

- **Comma-separated and decimal metrics:** `1,170%` does not match `170%` or
  `2,170%`; `1.70%` does not match `70%`; trailing sentence punctuation on
  `$50,000.` or `$50,000,` preserves `$50,000` without backtracking to `$50`.
- **Per-clause claim grounding:** Splitting on sentence boundaries (without
  breaking decimal numbers) and clause boundaries (`while`, `whereas`, `but`,
  `although`, `though`, `, and`, and two-subject `and`) prevents recombining
  `"I led ..."` from one sentence with `"Docker migration"` from another.
- **Placeholder and scaffold boundaries:** Bracketed placeholders (`[project]`)
  in `explanation` or `accepted_answers` never exempt unsupported first-person
  claims on any card kind, and still emit `ambiguity: warn` + placeholder
  `uncertainty` when no claim fails.

## Limitations (offline lexical and rule checks)

- **No semantic or factual oracle:** `technical_accuracy` only detects the
  explicit contradiction patterns in `TECHNICAL_CONTRADICTIONS`, ungrounded
  metrics, and unsupported first-person achievement claims. Subtle domain errors
  outside those rules can still receive `pass`.
- **Lexical grounding only:** `source_grounding` checks token overlap
  (lowercased alphanumeric tokens of length >= 2 minus stopwords, plus glossary
  definitions for matched glossary terms). Valid paraphrases that share no
  surface tokens with `source_text` can be rejected, while an answer that reuses
  one source token alongside mostly off-topic prose can pass grounding.
- **Clause heuristics:** Clause splitting relies on punctuation and common
  English conjunctions; complex nested clauses, passive voice, or implied
  ownership without first-person verbs (`I`/`we`) are not modeled.
- **English-focused tokenization:** Word-count and meaningful-word checks target
  ASCII Latin technical English (`[A-Za-z][A-Za-z0-9]*`). For `es_en` cards,
  Spanish prompts with diacritics still pass when they contain ASCII letter
  sequences, but pure non-Latin scripts are not supported.
- **No invented scores or proficiency estimates:** A `"draft"` verdict means the
  card passed deterministic guardrails and is safe to review and edit — it does
  not guarantee pedagogical quality or estimate CEFR level.
