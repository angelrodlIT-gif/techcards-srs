## Summary

- <!-- Brief description of the change and linked issue (e.g., Closes #N) -->

## UI/UX Change

- **UI/UX:** <!-- yes / no -->

## Verification Commands & Results

<!-- List the exact commands you ran locally and their results. -->

- `uv run ruff check .` — <!-- pass / fail -->
- `uv run ruff format --check .` — <!-- pass / fail -->
- `uv run pytest` — <!-- pass / fail -->
- `uv run alembic upgrade head && uv run alembic check` — <!-- pass / skipped (no schema/migrations changes) -->

## Review Verdict

- **Sol verdict:** `pending` <!-- Replace with `SOL APROBADO <sha>` or `SOL CAMBIOS <sha>` for the current head SHA -->
