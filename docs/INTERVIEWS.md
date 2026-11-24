# Role-Specific Mock Interview Sessions (`/interviews`)

Text-mode mock interview practice aligned to three deterministic role tracks (`cloud_support`, `junior_aws`, and `python_backend`), designed to stay fully usable before M4 audio features arrive.

## Role tracks and turn flow

Each new session starts in `active` status and seeds three ordered turns:

1. `turn_index: 1`, `turn_type: "technical"` — core technical scenario for the selected role.
2. `turn_index: 2`, `turn_type: "follow_up"` — follow-up troubleshooting or trade-off question on that scenario.
3. `turn_index: 3`, `turn_type: "behavioral"` — truthful STAR behavioral prompt explicitly reminding the learner to use real experiences without inventing outcomes or metrics.

Optionally pass `source_id` when creating a session to prefix each turn prompt with `[Source: <source.label>]`. Sources in `discarded` status return `409`; missing sources return `404`. Deleting a linked source sets `interview_sessions.source_id` to `null` (`ON DELETE SET NULL`) without deleting the session.

## Endpoints

- `POST /interviews` (`201`) — create an `active` session (`{"role": "cloud_support" | "junior_aws" | "python_backend", "source_id": null | int}`) and seed its 3 ordered turns.
- `GET /interviews` (`200`) — list sessions ordered by `id` (each with turns ordered by `turn_index`), with optional `role`, `status`, `offset`, and `limit` (`1..100`) query parameters.
- `GET /interviews/{session_id}` (`200`, `404` if missing) — fetch one session and its ordered turns.
- `POST /interviews/{session_id}/turns/{turn_id}/answer` (`200`) — submit a text answer (`1..5000` trimmed chars, no NUL bytes) in strict sequential order (`409` if the session is not `active`, the turn was already answered, or an earlier turn is still unanswered). Runs the pluggable `InterviewEvaluator` and sets `human_review_status = "pending"`.
- `POST /interviews/{session_id}/turns/{turn_id}/review` (`200`) — record human review on an answered turn (`409` before answering) with `human_review_status` (`"accepted"`, `"edited"`, or `"dismissed"`), optional `corrected_phrasing` (applied when `"edited"`), and optional `human_notes`.
- `POST /interviews/{session_id}/complete` (`200`) — mark an `active` session `completed` with a UTC `completed_at` timestamp once all turns have been answered (`409` if any turn is unanswered or the session is already `completed`).
- `DELETE /interviews/{session_id}` (`204`, `404` if missing) — hard-delete the session and cascade-delete all of its `interview_turns`.

## Evaluation rubric and evaluator seam

The evaluator behind `InterviewEvaluator` / `get_interview_evaluator()` in `app/interview.py` (defaulting to deterministic offline `MockInterviewEvaluator`) separates feedback into five explicit fields:

- `english_clarity`: evidence-based notes referencing response length, terminal punctuation, and any matched whole-word B2 Spanish-to-English phrasing patterns (for example, `"depend of"` -> `"depend on"`, `"consist in"` -> `"consist of"`, `"explain me"` -> `"explain to me"`, `"make a troubleshooting"` -> `"troubleshoot"`).
- `technical_accuracy`: lists which role/turn key concepts were mentioned vs. not yet covered (`Mentioned: ...; Consider covering: ...`).
- `star_structure`: checks explicit STAR signposts (`situation`, `task`, `action`, `result`) on `behavioral` turns with a truthful-experience reminder; notes that STAR is not required on `technical` and `follow_up` turns.
- `corrected_phrasing`: grounded revision of the learner's own answer applying matched phrase adjustments and whitespace cleanup without inventing facts or metrics.
- `uncertainty_note`: explicit disclaimer on every answered turn.

## Uncertainty, human review, and non-claims policy

- **Human review required:** Every evaluated turn starts with `human_review_status: "pending"` so the learner can explicitly `accepted`, `edited`, or `dismissed` the suggested phrasing and attach `human_notes`.
- **No hiring or CEFR predictions:** Feedback is an offline text-mode heuristic meant for practice only. It never predicts hiring outcomes, pass/fail interview decisions, or CEFR proficiency levels.
- **Local privacy and deletion:** Sessions stay in local PostgreSQL with no external uploads. Avoid storing employer-confidential or NDA material, and remove any session permanently with `DELETE /interviews/{session_id}`.
