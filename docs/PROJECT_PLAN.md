# TechCards SRS — Personal English Learning Plan

## Product vision and user

Build an end-to-end personal English learning system for Angel Gabriel Rodríguez
López: a B2 learner, native Spanish speaker in Mexico, Network Engineer / CCNA,
open to remote US time zones. His goal is a remote US role by May 2027 in Cloud
Support / junior AWS Cloud Engineering or Python backend (FastAPI + PostgreSQL),
with openness to Cloud, Software Development and Data.

The product connects real material, deliberate practice, spaced review and interview
rehearsal. Success means Angel can use what he studies to explain technical decisions,
troubleshoot aloud and tell truthful work stories in English. A job offer is an external
goal, not a promised product outcome. Saturday is the main development block.

The [implemented MVP](MVP.md) remains the foundation: deck/card CRUD, SM-2,
review events, offline mock generation, PostgreSQL, migrations, Docker and CI.
This plan extends that scope; the learning interface, hosted AI, audio, deployment
and analytics below are planned capabilities, not claims about the current API.

## Learning loop

1. **Collect:** paste relevant vacancies, AWS documentation and interview questions.
   Keep source links/labels and select useful excerpts; avoid uploading private employer
   material. Prioritize the vocabulary and explanations Angel needs for target roles.
2. **Curate:** draft cards, check meaning and context, edit and approve before review.
   Preserve an offline/manual path. Hosted generation requires explicit opt-in.
3. **Practice:** present due cards through an accessible personal study interface;
   recall before revealing, answer aloud when appropriate, grade and reschedule.
4. **Apply:** rehearse technical explanations and behavioral stories, then run mock
   interviews grounded in a chosen role/vacancy. AI suggestions require human judgment.
5. **Repair:** capture Angel's actual mistakes in an error log, correct them with an
   explanation, convert approved corrections into cards, then revisit them in interviews.
6. **Reflect:** review collected evidence on Saturdays and choose the next learning
   focus and a bounded development issue. Daily study can be brief and flexible;
   missing a day must not lose data or create punitive goals.

### Card and practice repertoire

| Format | Learning use |
| --- | --- |
| Vocabulary | Meaning, technical context and a useful example |
| Collocations | Natural combinations such as “resolve an incident” |
| Phrasal verbs | Contextual use such as “rule out” or “set up” |
| Sentence mining | A useful sentence from a linked source, with an explanation |
| Cloze | Recall a missing word/phrase with an unambiguous accepted answer |
| ES→EN translation | Produce natural English from a Spanish situation; allow valid alternatives |
| Listening with Polly audio | Listen before revealing a transcript; replay and check comprehension |
| Pronunciation | Listen, shadow, record and compare selected words/sentences |
| Speaking prompts | Give a spoken answer before consulting a model response |
| STAR / behavioral | Prepare truthful Situation, Task, Action, Result stories without invented results |
| Technical explanation drills | Explain VPC, subnetting, DNS and the TCP handshake; follow up with troubleshooting and tradeoffs |
| Mock interview | Role-specific technical and behavioral turns with AI feedback on English and technical clarity |
| Error-derived cards | Correct Angel's own recorded mistakes with context, rationale and follow-up practice |

Speaking prompts and STAR text templates start in M2; AI interview feedback arrives
in M3; recording, listening and pronunciation workflows arrive in M4. Feedback must
separate language issues from technical correctness and mark uncertainty.

## Progress evidence (collect before reporting)

There are no measured learning, adoption, retention or business outcomes to report.
Define event semantics, establish a baseline with Angel and only then set targets.
Track due/completed reviews, recall grades, lapses, overdue load and study time when
reliably captured. Compare by card format and topic with denominators and date ranges.
Track repeated errors, corrected errors recalled later, and coverage of selected vacancy
requirements. Use consistent rubrics for technical accuracy, clarity, English phrasing,
STAR structure, listening comprehension and intelligibility, with self/human review
alongside AI suggestions. Do not infer a CEFR change from app usage or AI scores.
Record mock interview samples only with consent and a deletion/export policy.
Small samples and self-reported ratings must remain visible limitations.

## Saturday milestones

Dates are Saturday calendar deadlines in America/Cancun. Each Saturday: select an
issue, implement a small slice, verify it, merge through CI and record a short learning
note. Sequence work within each milestone by dependencies; resize scope transparently
if available Saturdays or evidence require it. No dates have been shifted.

| Milestone | Deadline | Deliverable / exit evidence |
| --- | --- | --- |
| M1 Core SRS solid | 2026-12-26 | Documented local setup, scheduling/transaction confidence, recovery runbook and Angel's six exercises |
| M2 Personal content & card types | 2027-01-30 | Source-to-card curation, varied text formats, STAR/technical prompts and usable study/error-log loop |
| M3 AI generation + interview mode | 2027-02-27 | Opt-in pluggable generator, reviewed outputs, mock interview and actionable feedback |
| M4 Audio / speaking | 2027-03-27 | Polly listening, pronunciation and recorded speaking practice with privacy controls |
| M5 AWS deploy with Terraform + GitHub Actions | 2027-04-24 | Secured AWS deployment, reproducible infrastructure, OIDC delivery and recovery evidence |
| M6 Stats/data & polish | 2027-05-29 | Honest progress views, data export, usability polish and portfolio walkthrough |

M1 starts in December 2026. Optional runner setup can happen earlier when Angel has
his VM ready; no milestone depends on it. Review interview readiness throughout,
especially before May applications; M6 is polish, not a prerequisite to applying.

## Definition of done

An issue has clear acceptance criteria and evidence from relevant tests or a repeatable
manual walkthrough. Schema changes include migrations and data compatibility checks.
Learning content is reviewed for useful English and technical correctness; generated
claims and STAR outcomes are never fabricated. Document settings, limits and user
flows. Preserve local data and provide appropriate export/deletion controls for new
personal/audio data. Public exposure requires authentication, secrets management and
access controls. CI passes, the linked PR is reviewed according to repository rules,
and the change is merged before closing the issue. Plans and issue status reflect
what actually shipped; proposed features remain visibly deferred.

## Branching and PR workflow

Use **issue → branch from current main → focused PR → CI → merge**. Name branches
`type/short-description` (for example `infra/postgres-host-port-5435`); link issues
with `Closes #N`. Include behavior, verification and limitations in the PR. Never
commit credentials. Keep unrelated features separate. Angel's
[Saturday exercises](NEXT_STEPS.md) are for him to implement, one focused branch at
a time; creating their issues does not implement them.

## Repository labels and planning

- Types: `type:feature`, `type:bug`, `type:docs`, `type:infra`, `type:learning`.
- Areas: `area:api`, `area:srs`, `area:ai`, `area:aws`, `area:data`, `area:ci`.
- Priority: `priority:high`, `priority:medium`, `priority:low`.
- `good-first-for-angel`: bounded exercises reserved for Angel's own coding practice.

Use one primary type plus relevant area and priority labels. Milestones group
outcomes; issues group reviewable Saturday work rather than individual code edits.
A Project board is optional; issues and milestones are the source of truth.

## CI and the optional VM runner

Keep GitHub-hosted CI as the fallback until Angel's self-hosted Ubuntu VM is ready
and its security controls are verified. Track setup in an early M1 infrastructure
issue so Angel can configure it whenever convenient. The public repository makes
untrusted fork code particularly dangerous on persistent runners: require fork PR
approval, restrict self-hosted execution to trusted main pushes/collaborator code,
and isolate the VM from personal machines, networks and credentials. Approval alone
is not isolation. Never store registration tokens in the repository. Runner setup
and any later workflow routing are separate future work, not part of the port fix.
