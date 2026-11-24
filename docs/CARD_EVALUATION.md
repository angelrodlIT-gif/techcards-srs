# Generated Card Evaluation Workflow

Before generated flashcards enter the spaced-repetition review queue, `techcards-srs`
supports a **preview -> edit -> approve** workflow powered by offline categorical checks
in `app/evaluation.py`.

## Preview-edit-approve API

Existing `POST /cards/generate` behavior is unchanged. For reviewed intake:

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/cards/generate/preview` | Runs the configured `CardGenerator`, evaluates each draft against `text`, returns editable drafts + `evaluation` (`200`). Persists **zero** rows. |
| `POST` | `/cards/generate/approve` | Validates editable card fields (`CardInput` rules) and re-evaluates against `source_text`. Rejects unsupported cards with `422` (zero rows saved); persists supported drafts as due `Card` rows (`201`, `due_date = today(UTC)`). |

Both routes return `404` when `deck_id` does not exist and `422` on schema validation errors
(such as `text` / `source_text` outside 10–20,000 characters or containing NUL bytes).

## Categorical evaluation checks (no invented scores)

`evaluate_generated_card` returns categorical verdicts only — **no numeric scores,
percentages, or CEFR levels**:

- `status`: `"draft"` when all four checks pass or warn (`ready_for_review: true`), or
  `"rejected"` when any check fails (`ready_for_review: false`).
- `checks` (`"pass"` | `"warn"` | `"fail"`):
  - `english_usefulness`: rejects bare URLs, punctuation/number-only text, and single-token
    fragments on `front` or `back`.
  - `technical_accuracy`: rejects known technical contradictions (e.g., claiming AWS VPC
    security groups are stateless, NACLs are stateful, TCP is connectionless, UDP is
    connection-oriented, IAM roles use permanent keys, or contradicting `GLOSSARY` definitions)
    and rejects fabricated first-person metrics/achievement claims not grounded in
    `source_text`. Practice scaffolds (`Practice: ... [task]`, `Use STAR: ... do not invent an
    outcome`) are allowed with explicit uncertainty warnings.
  - `ambiguity`: fails on identical `front`/`back`, `< 2` words on either side, unresolved
    markers (`TODO`, `TBD`, `???`), or `kind="cloze"` without exactly one `____` blank. Warns
    when `cloze`/`es_en` cards have empty `accepted_answers` or when `[task]`-style scaffold
    placeholders remain.
  - `source_grounding`: fails on `MockGenerator`'s generic fallback placeholder
    (`"the technical responsibilities in this text"`), when the card shares no meaningful
    content tokens with `source_text`, or when `back` (the answer) is not grounded in
    `source_text` (or its matched glossary definition / grounded interview scaffold).
- `uncertainty`: explicit human-review notes (e.g., `[task]` placeholders, interview/behavioral
  truthfulness review, empty `accepted_answers`, and offline rule boundaries).
- `rejection_reasons`: concrete failure explanations when `status == "rejected"`.

## Reviewed fixture set and actual observations

`EVALUATION_FIXTURES` in `app/evaluation.py` contains 3 deterministic source fixtures
(`vacancy-cloud-support`, `aws-docs-vpc-iam`, `interview-networking-star`) with 12 reviewed
candidate cases (5 supported drafts, 7 rejected cases). Observed results from running
`MockGenerator` and `evaluate_generated_card` against the fixtures:

| Fixture (`category`) | `MockGenerator` output (`max_cards=10`) | Reviewed cases outcome |
| --- | --- | --- |
| `vacancy-cloud-support` (`vacancy`) | 8 drafts (6 `vocabulary` for `aws`, `python`, `postgresql`, `docker`, `linux`, `troubleshooting`; 1 `interview_phrase` with `ambiguity=warn` on `[task]`; 1 `behavioral`). Missed `FastAPI` and plural `APIs`. | 2 `draft` (`vocabulary`, scaffold with `ambiguity=warn`); 3 `rejected` (fabricated metrics, ungrounded Helm card, bare URL/non-text). |
| `aws-docs-vpc-iam` (`aws_docs`) | 3 drafts (only `aws` matched the 10-term glossary; `VPC`, `security groups`, `NACLs`, `EC2`, and `IAM` were missed). | 2 `draft` (valid `cloze`, `es_en` with `ambiguity=warn`); 2 `rejected` (stateless security groups, cloze missing `____`). |
| `interview-networking-star` (`interview`) | 4 drafts (`linux` and `troubleshooting` matched; `TCP`, `DNS`, and `timeout` were missed). | 1 `draft` (STAR scaffold); 2 `rejected` (TCP connectionless, identical front/back). |

When `MockGenerator` receives text with zero glossary matches (for example,
`"Amazon VPC security groups and IAM roles protect subnet workloads."`), it emits two fallback
cards referencing `"the technical responsibilities in this text"`. Both are now flagged as
`rejected` (`source_grounding="fail"`) in preview and blocked with `422` on approve.

## Limitations

- **Lexical grounding, not semantic entailment:** `source_grounding` checks content-token
  overlap and fallback phrases. A card that reuses one real source keyword alongside unrelated
  or subtle misstatements not covered by the contradiction rules still requires human review.
- **Bounded technical rule set:** `technical_accuracy` catches specific known AWS/networking/
  glossary contradictions and ungrounded first-person metrics/claims, not arbitrary domain
  errors.
- **No English fluency or level grading:** The evaluator checks structural usefulness (meaningful
  multi-word text, not bare URLs/fragments) and never infers CEFR levels or numeric quality
  scores.
- **Fixed `MockGenerator` vocabulary:** Until a richer generator is opted in, terms outside the
  10-word `GLOSSARY` (such as `VPC`, `IAM`, `TCP`, `DNS`, `FastAPI`) are only captured when
  edited or drafted manually before approval.
