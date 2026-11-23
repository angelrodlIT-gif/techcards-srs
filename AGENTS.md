# Agent Guidelines (`techcards-srs`)

Repository language is **English** (documentation, PR titles, PR bodies, and comments).

## Roles

- **Neon (coder):** Implements bounded, approved tasks on a dedicated branch.
- **gpt-6.2-sol / Sol (reviewer):** Reviews **only** `git diff <base>...<head>` — never the main thread, coding, planning, or research.
  - Maximum **2 review rounds**.
  - Blocks **only** on permissions, data, or regressions. Minor and style issues are recorded as leftover debt, not a new review round.
  - Verdict must begin with exactly `SOL APROBADO <sha>` or `SOL CAMBIOS <sha>` for the current head commit SHA.
- **Hydrogen (optional cleanup):** Runs at `low` or `medium` effort (never `xhigh`) to optionally clean a diff. Never approves.
- **Flash (optional checklist):** Runs at `low` effort to optionally run a short mechanical checklist (diff size, command list in the PR body). Never approves.

## Local Verification Gate

Run the local gate before asking for review:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

- If schema or migrations are touched, also run:
  ```bash
  uv run alembic upgrade head && uv run alembic check
  ```
- Use the `verify-techcards-srs` skill **only** when the change affects the API, Docker Compose, or runtime — **not** for docs-only PRs.

## Pull Requests

- Keep PRs in **draft** until GitHub CI is green.
- Every PR body must list the commands run and their results, state whether the PR is UI/UX (`yes`/`no`), and include the Sol verdict line (or `pending`).
- See [docs/INTEGRATION_LOOP.md](docs/INTEGRATION_LOOP.md) for the full six-pillar workflow.

## Merge Rule

- **Organizador Javier** (Angel's Grok Bot) may merge a PR without Angel's explicit approval **only** when **all** of the following hold:
  1. The PR is **not** UI/UX.
  2. The PR does **not** carry the `no-auto` label.
  3. GitHub CI is green.
  4. Sol gave `SOL APROBADO <sha>` matching the **current head SHA**.
- **UI/UX PRs**, and any PR labeled **`no-auto`**, require **Angel's explicit approval**.
- **No other agent** may merge a PR, submit a GitHub approval, or enable auto-merge.

## Reserved Issues

- Issues labeled `good-first-for-angel` (currently `#6`–`#11`) are reserved for Angel Gabriel Rodríguez López himself. **No agent may implement them.**
