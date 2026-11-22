# TechCards SRS Feature Map

This directory is the maintained verification source for TechCards SRS. Every user-facing feature in the live API has a dedicated entry here describing what users can do, every user entry point, how to drive it through `control-techcards.sh`, and what observable proof confirms it works. A verification run that only exercises one convenient route when the feature file lists additional entry points or side effects is incomplete.

## Baseline preconditions

Before driving any feature file in this directory:

- Launch a fresh isolated instance with `.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh launch` and record its `RUN_ID` and `EVIDENCE_DIR`.
- Confirm all 12 checks pass with `.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh doctor "$RUN_ID" --save`.
- Start from an empty database (0 rows in `decks`, `cards`, `reviews`), or isolate each journey inside its own newly created deck.
- Never target the developer's default `http://127.0.0.1:8000` or `127.0.0.1:5435` stack.

## Driving conventions

- Run commands from the repository root with `CTRL=.cursor/skills/verify-techcards-srs/scripts/control-techcards.sh`.
- Send all HTTP actions through `"$CTRL" req "$RUN_ID" <step-name> <METHOD> <PATH> [JSON_BODY]` so every action and response is recorded in `<evidence-dir>/steps/`.
- Confirm database side effects (especially `reviews` rows and `ON DELETE CASCADE` removals) with read-only `"$CTRL" db-query "$RUN_ID" <label> "<SQL>"`.
- Before teardown, save Compose logs with `"$CTRL" logs "$RUN_ID"`.
- Always finish with `"$CTRL" cleanup "$RUN_ID"` and confirm `<evidence-dir>` survived cleanup.
- Compare all `due_date` expectations against the current **UTC** date (`date -u +%Y-%m-%d`), not local time.

## Proof and skip reporting

- A passing proof must capture: `doctor.txt`, every HTTP step transcript (both outgoing request and incoming response), follow-up read verification, PostgreSQL side-effect query outputs, `logs/compose.log`, and confirmation that `<evidence-dir>` remains intact after `cleanup`.
- If a precondition is missing or an expected behavior fails, report a **failure** and record the reason in that feature's `Gotchas` section. Never weaken a journey or skip an assertion to make a run pass.
- If a sub-feature cannot be driven in the current environment, report it explicitly as **skipped** with the exact sub-feature ID and blocking reason; do not fold skipped sub-features into a passing summary.

## Feature entry contract

Every feature file in this directory must follow this exact structure:

- One H1 title followed by a single paragraph describing the user-visible behavior.
- Exactly four H2 sections in this order:
  1. `Sub-features` — short kebab-case IDs with one line per behavior.
  2. `How to get to it (user POV)` — every user entry point (HTTP endpoints and Swagger UI `/docs` operations).
  3. `Driving it with control-techcards.sh` — starts with `Preconditions:` followed by labeled bullets pairing each user action with an exact command and observable result, ending with a `Proof` bullet.
  4. `Gotchas` — concrete traps that can waste or invalidate a verification run.

Keep internal implementation details out of feature files; name only user paths, stable handles, required state, exact commands, and observable proof.

## Features

- [Manage study decks](deck-management.md)
- [Manage flashcards](card-management.md)
- [Generate flashcards from pasted text](card-generation.md)
- [Study due cards and record SM-2 reviews](study-reviews.md)
