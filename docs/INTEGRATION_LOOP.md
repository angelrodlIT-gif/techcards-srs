# Agent Integration Loop

This document describes the six-pillar integration loop used for agent-assisted
pull requests in `techcards-srs`. See [AGENTS.md](../AGENTS.md) for the concise
role and rule reference.

All repository documentation, PR titles, PR bodies, and comments are written in
**English**.

## 1. Closed Assignments and One Writer per Branch

- Every agent task has a bounded, approved scope and runs on its own branch
  created from up-to-date `origin/main` (one writer per branch; no force-push).
- Issues labeled `good-first-for-angel` (currently `#6`–`#11`) are reserved for
  Angel Gabriel Rodríguez López himself and stay untouched by agents.

## 2. Local Verification Gate and Draft PRs

Before requesting review, the coder (**Neon**) runs the local gate:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

- When schema or migrations change, also run:
  ```bash
  uv run alembic upgrade head && uv run alembic check
  ```
- Use the `verify-techcards-srs` skill only when the change affects the API,
  Docker Compose, or runtime — skip it for docs-only PRs.
- Open the PR as a **draft** and keep it in draft until GitHub CI is green.
- The PR body must list the exact verification commands run and their results,
  state whether the change is UI/UX (`yes`/`no`), and include the Sol verdict
  line (initially `pending`).

## 3. Optional Pre-Review Helpers

- **Hydrogen** (`low` or `medium` effort, never `xhigh`) may optionally clean up
  a diff before review. Hydrogen never approves PRs.
- **Flash** (`low` effort) may optionally run a short mechanical checklist (diff
  size, command list present in the PR body). Flash never approves PRs.

## 4. Diff-Only Review by Sol

- **Sol (`gpt-6.2-sol`)** reviews **only** the exact diff
  (`git diff <base>...<head>`) — never the main thread, coding, planning, or
  research.
- Verdict format: must start with exactly `SOL APROBADO <sha>` or
  `SOL CAMBIOS <sha>` for the current head commit SHA.
- **Maximum 2 review rounds.**
- **Blockers only:** Sol blocks only on permissions, data, or regressions. Minor
  and style feedback is recorded as leftover debt rather than triggering another
  review round.
- **Read-only second opinion:** Request a second opinion from Neon in read-only
  mode **only** for PRs that touch security, permissions, or data/migrations.
- **Fallback reviewer:** If Sol / Codex is unavailable, Argon may perform a
  temporary review, explicitly marked `temporary Argon review`.

## 5. Readiness Label and Merge Rule

Once GitHub CI is green and Sol has issued `SOL APROBADO <sha>` matching the
current head SHA:

- Mark the PR ready for review (if still draft) and apply the `listo-para-angel`
  label.
- **Organizador Javier** (Angel's Grok Bot) may merge without Angel's explicit
  approval **only** when **all** of the following are true:
  1. The PR is **not** UI/UX.
  2. The PR is **not** labeled `no-auto`.
  3. GitHub CI is green.
  4. Sol gave `SOL APROBADO <sha>` on the **current head SHA**.
- **UI/UX PRs**, and any PR labeled **`no-auto`**, must wait for **Angel's
  explicit approval**.
- **No other agent** may merge a PR, approve it in GitHub, or enable auto-merge.

## 6. Small PRs and Conventional English Titles

- Keep PRs small and focused (target **~400 lines** or fewer).
- Use conventional English PR titles such as `docs(process): …`,
  `fix(api): …`, or `feat(srs): …`.
- Remember: `#6`–`#11` (`good-first-for-angel`) remain reserved for Angel and
  must not be implemented by agents.
