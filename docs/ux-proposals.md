# Study pilot UX priorities

| Priority | Problem observed | Change and expected impact | This round |
| --- | --- | --- | --- |
| 1 | A long ID could select a neighboring deck. A pending deck refresh could also undo a deliberate selection of the blank option. | Preserve exact IDs from the keyboard and API. Invalidate older requests on either deck control so the visible card and the next action agree. | Implemented and covered in Chrome. |
| 2 | English controls and grade labels make a Spanish-speaking learner translate the interface while practicing technical English. Empty queues and intermediate states give little guidance. | Use Spanish for controls, accessible names and feedback. Distinguish no decks from a completed queue and point to a next action. Keep the original exercise text and API diagnostics. | Implemented. |
| 3 | Revealing an answer disables the focused button. Repeated grading then requires navigating the whole page. | Keep keyboard focus in the study loop, expose shortcuts only inside the card, and explain the six grades. Keep native button activation for touch and keyboard. | Implemented. |
| 4 | Multiple controls share short wrapped rows on phones. Long IDs need room. | Use full-width deck controls and a two-column grade grid on narrow screens. Preserve the centered desktop layout. | Implemented and checked at 320 CSS pixels. |
| 5 | New users must leave study for API docs to create a deck. The picker only lists the first API page. | Add inline deck creation and a searchable, paginated picker so first-time users and large collections can start from the same screen. | Pending. |
| 6 | Template selection previews content, but the destination is above the fold. | Show the destination deck beside the create and approve buttons before the write, particularly on mobile. | Pending. |

Further validation with Angel should cover grade wording, screen-reader announcements, mobile Safari and the original Figma overlay.
