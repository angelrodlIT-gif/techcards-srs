"""Pure SM-2 scheduling; the caller supplies the review date."""

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil


@dataclass(frozen=True)
class Schedule:
    repetitions: int = 0
    interval_days: int = 0
    ease_factor: float = 2.5


@dataclass(frozen=True)
class ReviewResult:
    schedule: Schedule
    due_date: date


def schedule_review(state: Schedule, quality: int, reviewed_on: date) -> ReviewResult:
    if isinstance(quality, bool) or not isinstance(quality, int) or not 0 <= quality <= 5:
        raise ValueError("quality must be an integer from 0 to 5")
    if state.repetitions < 0 or state.interval_days < 0 or state.ease_factor < 1.3:
        raise ValueError("invalid scheduling state")
    if quality < 3:
        repetitions, interval = 0, 1
    else:
        interval = (
            1
            if state.repetitions == 0
            else 6
            if state.repetitions == 1
            else ceil(state.interval_days * state.ease_factor)
        )
        repetitions = state.repetitions + 1
    ease = max(1.3, state.ease_factor + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    updated = Schedule(repetitions, interval, round(ease, 8))
    return ReviewResult(updated, reviewed_on + timedelta(days=interval))
