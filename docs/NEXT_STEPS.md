# Saturday learning tasks

The MVP is complete. These are optional extensions for Angel to implement himself,
one at a time on a feature branch. Do not add a paid LLM or AWS deployment yet.

All six exercises are tracked in M1 with `good-first-for-angel`; Angel will implement
them himself. See the [project plan](PROJECT_PLAN.md) for the broader learning roadmap.

1. **Add card source labels.** ([#6](https://github.com/angelrodlIT-gif/techcards-srs/issues/6)) Write an Alembic migration for a nullable `source_label`,
   expose it in card input/output, and test create/update/read without changing scheduling.
2. **Expose review history.** ([#7](https://github.com/angelrodlIT-gif/techcards-srs/issues/7)) Implement `GET /cards/{id}/reviews` with pagination and
   chronological ordering. Test missing cards and multiple reviews; explain deletion behavior.
3. **Expand the offline glossary.** ([#8](https://github.com/angelrodlIT-gif/techcards-srs/issues/8)) Add five networking terms and word-boundary tests
   (for example, `api` must not match `capital`). Keep output order deterministic.
4. **Add a deck summary endpoint.** ([#9](https://github.com/angelrodlIT-gif/techcards-srs/issues/9)) Return total cards and cards due today using SQL
   aggregates. Test empty decks and a card scheduled tomorrow; use UTC consistently.
5. **Strengthen a scheduling test.** ([#10](https://github.com/angelrodlIT-gif/techcards-srs/issues/10)) Write a long review sequence that reaches the ease
   floor, then recovers after successful recalls. Explain the expected intervals by hand.
6. **Document a troubleshooting exercise.** ([#11](https://github.com/angelrodlIT-gif/techcards-srs/issues/11)) Stop the database, reproduce a failed API
   request, inspect Compose logs, restore the service and document the commands and
   observations in `docs/TROUBLESHOOTING.md`. Use only disposable local data.

For each task: write the code yourself, run lint/tests, inspect the diff, commit a
focused change, and explain what you learned. Report observations, not invented impact.
