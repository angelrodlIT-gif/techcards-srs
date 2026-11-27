# Generated card evaluation

1. Send `deck_id`, pasted `text`, and optionally `max_cards` and `source_label`
   to `POST /cards/generate/preview`. The response gives editable drafts.
   Each draft rates English usefulness, technical accuracy, ambiguity, and
   source grounding as `pass`, `warn`, or `fail`. Preview writes zero cards.
2. Read `uncertainty` and `rejection_reasons` and edit the draft. Keep its
   `deck_incarnation` and include the original pasted text as `source_text`.
   Send the result to `POST /cards/generate/approve`.
3. Approval evaluates the submitted text again. It returns `201` and makes the
   card due today in UTC, or returns `422` with the failed checks and reasons.
   A draft tied to a deleted deck returns `404`, even if its integer ID has been
   reused. An approval submitted independently of preview targets the deck
   present when approval starts. Approval stores the card fields and source
   label. The raw source text is used for evaluation only.

The old `POST /cards/generate` remains available for existing clients and
inserts cards directly. New clients should use preview and approve.

## Reviewed fixtures

The fixtures use synthetic vacancy and interview text and a short AWS VPC
documentation summary. The evaluation tests exercise the same cases through
the evaluator and approval endpoint.

| Input | Observation |
| --- | --- |
| Cloud support vacancy | The AWS interview practice template passed with an ambiguity warning for the placeholder. A template with an added migration claim was rejected. |
| AWS VPC documentation | The two-letter cloze answer `IP` passed. A quoted sentence about stateless ACLs was rejected when the prompt asked which AWS control is stateful. [VPC infrastructure security](https://docs.aws.amazon.com/vpc/latest/userguide/infrastructure-security.html), [route table concepts](https://docs.aws.amazon.com/vpc/latest/userguide/RouteTables.html) |
| Interview notes | The exact statement `I saved $50,000.` passed. Reassigned AWS/GCP counts, reversed latency measurements, and a colleague's work recast as the speaker's were rejected. |

The evaluator checks wording offline and recognizes a limited set of technical
contradictions. It expects answers to use a complete sentence from the source
or a built-in glossary definition for a term in both the prompt and source.
A non-cloze answer or alternative must contain a sentence that addresses the
prompt's subject and requested detail. For example, a property question needs
the stated property, a quantity question needs a number, and a why question
needs wording that indicates a reason. Cloze answers are checked as completed
prompts. Practice templates must match the prompt they were designed for.
First-person claims and metrics need matching source wording. Correct
paraphrases and partial quotes can be rejected. A passing result depends on the
supplied source and still calls for human review. The evaluator reports no
numeric quality or proficiency scores.
