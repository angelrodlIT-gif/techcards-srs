"""Deterministic offline interview remediation heuristics (no external network calls)."""

import re
from dataclasses import dataclass

from app.schemas import ErrorCategory, Kind

MAX_ATTEMPTED_CHARS = 4991
MAX_TEXT_CHARS = 5000
STAR_PREFIX = "[STAR remediation]"
TECH_PREFIX = "[Technical remediation]"
STAR_MARKERS = ("situation", "task", "action", "result")

# Each replacement is <= pattern length so cleaning never expands past MAX_TEXT_CHARS.
PHRASE_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (re.compile(rf"\b{pat}\b", re.IGNORECASE), repl, f"'{pat}' -> '{repl}'")
    for pat, repl in (
        ("did not responded", "did not respond"),
        ("didn't responded", "didn't respond"),
        ("i am agree", "I agree"),
        ("depend of", "depend on"),
        ("depends of", "depends on"),
        ("in monday", "on Monday"),
    )
)


@dataclass(frozen=True)
class RemediationDraft:
    attempted: str
    corrected: str
    rationale: str
    suggested_kind: Kind


def build_remediation_draft(
    *,
    answer: str,
    prompt: str | None,
    category: ErrorCategory,
    corrected: str | None,
    rationale: str | None,
) -> RemediationDraft:
    attempted = f"Prompt: {prompt}\nAnswer: {answer}" if prompt is not None else answer
    if len(attempted) > MAX_ATTEMPTED_CHARS:
        raise ValueError(f"attempted text must be at most {MAX_ATTEMPTED_CHARS} characters")

    cleaned, fixes = answer, []
    for pattern, replacement, label in PHRASE_RULES:
        cleaned, count = pattern.subn(replacement, cleaned)
        if count:
            fixes.append(label)

    if category == "star":
        suggested_kind: Kind = "behavioral"
        missing = [m.title() for m in STAR_MARKERS if m not in answer.lower()]
        gap = f"Add missing STAR parts ({', '.join(missing)})" if missing else "Tighten STAR"
        resolved_corrected = (
            corrected
            if corrected is not None
            else (
                "Truthful STAR scaffold (use real experiences only; do not invent achievements). "
                f"{gap}: {cleaned}"
            )
        )
        if rationale is not None:
            resolved_rationale = (
                rationale if rationale.startswith(STAR_PREFIX) else f"{STAR_PREFIX} {rationale}"
            )
        else:
            notes = ([f"Fixes: {'; '.join(fixes)}."] if fixes else []) + [
                f"Missing STAR elements: {', '.join(missing)}."
                if missing
                else "All STAR elements (Situation, Task, Action, Result) referenced.",
                "Use real experiences only; offline heuristic requires human review.",
            ]
            resolved_rationale = f"{STAR_PREFIX} {' '.join(notes)}"
    else:
        suggested_kind = "interview_phrase"
        resolved_corrected = (
            corrected
            if corrected is not None
            else (cleaned if cleaned != answer else f"Refined technical explanation: {cleaned}")
        )
        detail = (
            f"Fixes: {'; '.join(fixes)}."
            if fixes
            else "No mechanical phrasing issue detected; refine technical clarity."
        )
        resolved_rationale = (
            rationale
            if rationale is not None
            else f"{TECH_PREFIX} {detail} Offline heuristic requires human review."
        )

    if len(resolved_corrected) > MAX_TEXT_CHARS:
        raise ValueError(f"suggested corrected text must be at most {MAX_TEXT_CHARS} characters")
    if len(resolved_rationale) > MAX_TEXT_CHARS:
        raise ValueError(f"suggested rationale must be at most {MAX_TEXT_CHARS} characters")

    return RemediationDraft(attempted, resolved_corrected, resolved_rationale, suggested_kind)
