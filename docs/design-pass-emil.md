# Study UI design pass

| Skill | Before | After | Why |
| --- | --- | --- | --- |
| emil-design-eng | The question and reveal action had the same visual weight as setup controls. | Larger question text, more space inside the study card, a soft shadow and a dark reveal button. | Make the current question and its next action easy to locate. Settings keep their existing borders. |
| emil-design-eng | Enabled buttons had no explicit hover or press feedback. | Fine pointers get a hover fill. Pressing an enabled button shows an inset ring. | Feedback starts on contact. Disabled controls retain a distinct state. |
| break-ui | An accepted email address overflowed its list at 320px. At double text size the source label overflowed too, and the header, deck grid and grade labels exceeded their available space. | Wrap long card metadata and answers, let the header wrap, allow the deck track to shrink and give grade buttons fewer columns as text grows. | The complete source, answer and ID matter when studying. |
| mobile-native | Fixed page gutters ignored safe areas. Buttons combined the browser tap highlight with custom feedback. | The page uses a 100dvh minimum height and pads all four safe areas. Fields have a 16px font floor. Buttons use touch-action manipulation and their own press feedback. | Keep controls clear of device chrome, preserve pinch zoom and keep long cards scrollable. |
| find-animation-opportunities | Reveal, grade, next card and occasional form submissions were candidates. | Only presses on the create-deck and save-draft buttons qualified. | Submission feedback confirms contact. Reveal and grade repeat throughout a session, and a next-card transition delays reading. Keyboard actions should be instant. |
| animate | Form presses had static feedback only. | CSS transitions scale the pressed button to 0.97 using cubic-bezier(0.23, 1, 0.32, 1). | A transform can reverse on early release without changing layout or delaying submission. Reduced-motion and keyboard users get the inset ring. |
| review-animations | The first recipe took 160ms in both directions. | Retained the 160ms press and shortened release to 100ms. | The system should settle promptly after release. Playwright checks pointer, keyboard and reduced-motion paths. |

The Playwright case `test_long_study_content_fits` includes a test-only **Demo data / Worst case / Empty** picker. The worst case combines an emoji-prefixed deck name, an email address, 2,147,483,647 repetitions and an ID above JavaScript's safe integer range. It checks 320px and 1024px layouts and double-size text at 320px. Existing tests cover empty queues and exact IDs in writes.

Verification used Chrome. Physical iPhone safe areas, software-keyboard zoom and tap feel still need a hardware check.
