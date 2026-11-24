"""Role-specific mock interview tracks and pluggable offline evaluator seam.

Replace get_interview_evaluator via dependency injection to integrate a hosted LLM strategy.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings
from app.schemas import InterviewRole, InterviewTurnType

MAX_PROMPT_CHARS = 5000

NON_BEHAVIORAL_STAR_NOTE = (
    "Non-behavioral turn (technical/follow-up): STAR structure not required; "
    "organize as symptom, root cause, and verification."
)

UNCERTAINTY_NOTE = (
    "Offline text-mode heuristic feedback only: this evaluation may miss valid technical "
    "nuance or phrasing variations, requires human review, and makes no hiring or CEFR "
    "level predictions."
)


@dataclass(frozen=True)
class RoleTurnTemplate:
    turn_index: int
    turn_type: InterviewTurnType
    prompt: str
    key_concepts: tuple[str, ...]


@dataclass(frozen=True)
class TurnFeedback:
    english_clarity: str
    technical_accuracy: str
    star_structure: str
    corrected_phrasing: str
    uncertainty_note: str


ROLE_TRACKS: dict[InterviewRole, tuple[RoleTurnTemplate, ...]] = {
    "cloud_support": (
        RoleTurnTemplate(
            turn_index=1,
            turn_type="technical",
            prompt=(
                "A customer reports intermittent 504 Gateway Timeout errors from a web "
                "application behind an AWS Application Load Balancer. How would you triage "
                "this issue step by step?"
            ),
            key_concepts=("logs", "health check", "security group", "timeout", "target"),
        ),
        RoleTurnTemplate(
            turn_index=2,
            turn_type="follow_up",
            prompt=(
                "Follow-up: The target instances appear healthy in ALB health checks, yet "
                "latency spikes persist for specific requests. What would you inspect next, "
                "and how would you verify the root cause before proposing a fix?"
            ),
            key_concepts=("metrics", "database", "latency", "reproduce", "verify"),
        ),
        RoleTurnTemplate(
            turn_index=3,
            turn_type="behavioral",
            prompt=(
                "Tell me about a real support incident or urgent technical issue you helped "
                "resolve under time pressure. Use STAR (Situation, Task, Action, Result) "
                "based only on a real experience; do not invent outcomes or metrics."
            ),
            key_concepts=("communication", "root cause", "handoff", "resolution"),
        ),
    ),
    "junior_aws": (
        RoleTurnTemplate(
            turn_index=1,
            turn_type="technical",
            prompt=(
                "An EC2 instance in a private subnet cannot reach an external HTTPS API, "
                "even though instances in the public subnet can. Explain how you would "
                "diagnose the VPC networking path."
            ),
            key_concepts=("vpc", "subnet", "route table", "nat gateway", "security group"),
        ),
        RoleTurnTemplate(
            turn_index=2,
            turn_type="follow_up",
            prompt=(
                "Follow-up: How does an IAM instance profile improve security compared to "
                "storing static access keys on the EC2 instance, and what trade-offs or "
                "failure modes would you watch for?"
            ),
            key_concepts=("iam", "least privilege", "temporary credentials", "policy", "audit"),
        ),
        RoleTurnTemplate(
            turn_index=3,
            turn_type="behavioral",
            prompt=(
                "Tell me about a real time you had to learn an unfamiliar cloud or "
                "infrastructure concept quickly to unblock a task. Use STAR (Situation, "
                "Task, Action, Result) using only a real experience; do not invent "
                "outcomes or metrics."
            ),
            key_concepts=("documentation", "testing", "trade-off", "learning"),
        ),
    ),
    "python_backend": (
        RoleTurnTemplate(
            turn_index=1,
            turn_type="technical",
            prompt=(
                "A FastAPI endpoint backed by PostgreSQL occasionally returns duplicate "
                "records or inconsistent state under concurrent requests. How would you "
                "diagnose and fix the concurrency issue?"
            ),
            key_concepts=("transaction", "lock", "constraint", "idempotency", "rollback"),
        ),
        RoleTurnTemplate(
            turn_index=2,
            turn_type="follow_up",
            prompt=(
                "Follow-up: Adding stricter database locking can protect consistency but "
                "may hurt throughput. How would you evaluate that trade-off and verify the "
                "fix with automated tests?"
            ),
            key_concepts=("index", "timeout", "latency", "test", "rollback"),
        ),
        RoleTurnTemplate(
            turn_index=3,
            turn_type="behavioral",
            prompt=(
                "Tell me about a real backend bug or API design trade-off you worked "
                "through with a teammate or reviewer. Use STAR (Situation, Task, Action, "
                "Result) grounded only in a real experience; do not invent outcomes or "
                "metrics."
            ),
            key_concepts=("code review", "trade-off", "tests", "outcome"),
        ),
    ),
}

PHRASE_CORRECTIONS: tuple[tuple[str, str], ...] = (
    ("depend of", "depend on"),
    ("depends of", "depends on"),
    ("consist in", "consist of"),
    ("consists in", "consists of"),
    ("explain me", "explain to me"),
    ("make a troubleshooting", "troubleshoot"),
    ("do a troubleshooting", "troubleshoot"),
    ("i am agree", "I agree"),
    ("in the other hand", "on the other hand"),
)

_COMPILED_PHRASE_CORRECTIONS: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (
        re.compile(
            r"\b" + r"\s+".join(re.escape(w) for w in source.split()) + r"\b", re.IGNORECASE
        ),
        source,
        replacement,
    )
    for source, replacement in PHRASE_CORRECTIONS
)

STAR_SIGNPOSTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("situation", ("situation", "context", "background")),
    ("task", ("task", "goal", "responsibility", "responsible for", "objective")),
    (
        "action",
        (
            "action",
            "steps i took",
            "i investigated",
            "i checked",
            "i diagnosed",
            "i implemented",
            "i fixed",
            "i updated",
            "i coordinated",
            "i resolved",
        ),
    ),
    ("result", ("result", "outcome", "takeaway", "as a result", "learned")),
)

_COMPILED_STAR_SIGNPOSTS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (
        component,
        tuple(
            re.compile(
                r"(?<!\w)" + r"[\s-]+".join(re.escape(w) for w in marker.split()) + r"(?!\w)",
                re.IGNORECASE,
            )
            for marker in markers
        ),
    )
    for component, markers in STAR_SIGNPOSTS
)


def _concept_pattern(concept: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in re.split(r"[\s-]+", concept.strip()) if part]
    body = r"[\s-]+".join(parts)
    if concept.endswith("s"):
        body = f"{body[:-1]}s?"
    elif concept.endswith("y"):
        body = f"{body[:-1]}(?:y|ies)"
    else:
        body = f"{body}(?:s|es)?"
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


_ROLE_TURN_CONCEPTS: dict[tuple[InterviewRole, int], tuple[tuple[str, re.Pattern[str]], ...]] = {
    (role, turn.turn_index): tuple((c, _concept_pattern(c)) for c in turn.key_concepts)
    for role, turns in ROLE_TRACKS.items()
    for turn in turns
}


def build_turn_prompt(base_prompt: str, source_label: str | None = None) -> str:
    label = source_label.strip() if source_label is not None else ""
    prompt = f"[Source: {label}] {base_prompt}" if label else base_prompt
    if not prompt or len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(
            f"interview turn prompt must be between 1 and {MAX_PROMPT_CHARS} characters"
        )
    return prompt


def get_role_track(role: InterviewRole) -> tuple[RoleTurnTemplate, ...]:
    return ROLE_TRACKS[role]


class InterviewEvaluator(Protocol):
    def evaluate(
        self,
        role: InterviewRole,
        turn_index: int,
        turn_type: InterviewTurnType,
        prompt: str,
        answer: str,
    ) -> TurnFeedback: ...


def _match_case(original: str, replacement: str) -> str:
    if original and original[0].isupper() and replacement and replacement[0].islower():
        return replacement[0].upper() + replacement[1:]
    return replacement


class MockInterviewEvaluator:
    def evaluate(
        self,
        role: InterviewRole,
        turn_index: int,
        turn_type: InterviewTurnType,
        prompt: str,
        answer: str,
    ) -> TurnFeedback:
        del prompt  # Offline heuristic evaluates directly against role/turn rubric and answer text.
        normalized = " ".join(answer.split())
        words = re.findall(r"[A-Za-z0-9']+", normalized)
        word_count = len(words)

        corrected = normalized
        matched_adjustments: list[str] = []
        for pattern, _source, replacement in _COMPILED_PHRASE_CORRECTIONS:
            matches = pattern.findall(corrected)
            if matches:
                observed = " ".join(matches[0].split())
                suggested = _match_case(observed, replacement)
                matched_adjustments.append(f"'{observed}' -> '{suggested}'")
                corrected = pattern.sub(
                    lambda m, repl=replacement: _match_case(m.group(0), repl),
                    corrected,
                )

        clarity_notes = [f"Response length: {word_count} word(s)."]
        if normalized.endswith((".", "!", "?")):
            clarity_notes.append("Ends with terminal punctuation.")
        else:
            clarity_notes.append("Consider ending with clear terminal punctuation.")
        if word_count < 15:
            clarity_notes.append(
                "Answer is brief; consider expanding into 2-3 complete sentences for clarity."
            )
        if matched_adjustments:
            clarity_notes.append(
                f"Observed phrasing adjustments: {'; '.join(matched_adjustments)}."
            )
        else:
            clarity_notes.append(
                "No rule-based B2 phrasing issues matched in the submitted text; "
                "review tone and clarity manually."
            )
        english_clarity = " ".join(clarity_notes)

        concept_patterns = _ROLE_TURN_CONCEPTS.get((role, turn_index), ())
        mentioned = [c for c, pat in concept_patterns if pat.search(normalized)]
        missing = [c for c, pat in concept_patterns if not pat.search(normalized)]
        mentioned_text = ", ".join(mentioned) if mentioned else "none"
        missing_text = ", ".join(missing) if missing else "none"
        technical_accuracy = f"Mentioned: {mentioned_text}; Consider covering: {missing_text}."

        if turn_type == "behavioral":
            present_star = [
                comp
                for comp, patterns in _COMPILED_STAR_SIGNPOSTS
                if any(pat.search(normalized) for pat in patterns)
            ]
            missing_star = [
                comp for comp, _patterns in _COMPILED_STAR_SIGNPOSTS if comp not in present_star
            ]
            present_text = ", ".join(present_star) if present_star else "none"
            missing_star_text = ", ".join(missing_star) if missing_star else "none"
            star_structure = (
                f"STAR components signposted: {present_text}; "
                f"Missing or implicit: {missing_star_text}. "
                "Use only real experiences and do not invent outcomes or metrics."
            )
        else:
            star_structure = NON_BEHAVIORAL_STAR_NOTE

        return TurnFeedback(
            english_clarity=english_clarity,
            technical_accuracy=technical_accuracy,
            star_structure=star_structure,
            corrected_phrasing=corrected,
            uncertainty_note=UNCERTAINTY_NOTE,
        )


def get_interview_evaluator() -> InterviewEvaluator:
    get_settings()  # Reject unsupported provider configuration rather than silently ignoring it.
    return MockInterviewEvaluator()
