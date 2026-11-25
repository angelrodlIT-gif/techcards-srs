# Study pilot UX priorities

| Priority | Problem observed | Change and expected impact | This round |
| --- | --- | --- | --- |
| 1 | A long ID could select a neighboring deck. A pending deck refresh could also undo a deliberate selection of the blank option. | Preserve exact IDs from the keyboard and API. Keep the latest deck selection when older list, card or reveal requests finish. | Implemented and covered in Chrome. |
| 2 | English controls and grade labels make a Spanish-speaking learner translate the interface while practicing technical English. Empty queues and intermediate states give little guidance. | Use Spanish for controls, accessible names and feedback. Distinguish no decks from a completed queue and point to a next action. Keep the original exercise text and API diagnostics. | Implemented. |
| 3 | Revealing an answer disables the focused button. Repeated grading then requires navigating the whole page. | Keep keyboard focus in the study loop, expose shortcuts only inside the card, and explain the six grades. Keep native button activation for touch and keyboard. | Implemented. |
| 4 | Multiple controls share short wrapped rows on phones. Long IDs need room. | Use full-width deck controls and a two-column grade grid on narrow screens. Preserve the centered desktop layout. | Implemented and checked at 320 CSS pixels. |
| 5 | New users must leave study for API docs to create a deck. The picker only lists the first API page. | Add inline deck creation and a searchable, paginated picker so first-time users and large collections can start from the same screen. | Implemented. |
| 6 | Template selection previews content, but the destination is above the fold. | Show the destination deck beside the create and approve buttons before the write, particularly on mobile. | Implemented. |

The picker reads the offset-based API in pages of 100 and searches the complete catalog locally by name or decimal ID. Filtering keeps the current deck selected. Template creation and error approval show the exact destination ID and the deck name when available. A manually entered ID outside the catalog is labeled by ID.

The UI reads integer ID tokens before numeric conversion, including on engines without JSON reviver source support. During the current page session, another click cannot repeat a successful or uncertain template write to the same deck. After an uncertain result, inspect the destination deck before reloading. These guards are local to the page; the API does not provide cross-tab or persistent idempotency.

## Run the pilot

From the pilot worktree with the default Compose database settings:

```bash
export POSTGRES_HOST_PORT=55431
docker compose -p techcards-codex-pilot up -d --wait db
export DATABASE_URL="$(docker compose -p techcards-codex-pilot exec -T db sh -c 'printf "postgresql+psycopg://%s:%s@127.0.0.1:55431/%s" "$POSTGRES_USER" "$POSTGRES_PASSWORD" "$POSTGRES_DB"')"
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Open [the study UI](http://127.0.0.1:8001/ui), expand **Crear un mazo**, then add a card from **Plantillas**.

Further validation with Angel should cover grade wording, screen-reader announcements, mobile Safari and the original Figma overlay.
