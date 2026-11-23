from datetime import UTC, date, datetime, timedelta

import pytest

from app.sm2 import Schedule, schedule_review

TODAY = date(2026, 1, 1)


def test_success_sequence_uses_previous_ease_and_rounds_up():
    first = schedule_review(Schedule(), 5, TODAY)
    second = schedule_review(first.schedule, 5, first.due_date)
    third = schedule_review(second.schedule, 5, second.due_date)
    assert [
        first.schedule.interval_days,
        second.schedule.interval_days,
        third.schedule.interval_days,
    ] == [1, 6, 17]
    assert third.schedule.repetitions == 3
    assert third.due_date == second.due_date + timedelta(days=17)


@pytest.mark.parametrize("quality", range(3))
def test_failure_resets_repetitions(quality):
    state = Schedule(4, 40, 1.3)
    result = schedule_review(state, quality, TODAY)
    assert result.schedule == Schedule(0, 1, 1.3)
    assert result.due_date == TODAY + timedelta(days=1)
    assert state == Schedule(4, 40, 1.3)
    assert schedule_review(result.schedule, 3, result.due_date).schedule.repetitions == 1


@pytest.mark.parametrize(("quality", "ease"), [(3, 2.36), (4, 2.5), (5, 2.6)])
def test_passing_grade_ease(quality, ease):
    assert schedule_review(Schedule(), quality, TODAY).schedule == Schedule(1, 1, ease)


@pytest.mark.parametrize("quality", [-1, 6, True, 2.5, "5"])
def test_invalid_quality(quality):
    with pytest.raises(ValueError):
        schedule_review(Schedule(), quality, TODAY)


@pytest.mark.parametrize(
    "state",
    [
        Schedule(-1, 0, 2.5),
        Schedule(0, -1, 2.5),
        Schedule(0, 0, 1.29),
        Schedule(0, 0, float("nan")),
        Schedule(0, 0, float("inf")),
        Schedule(2, 0, 2.5),
    ],
)
def test_invalid_state(state):
    with pytest.raises(ValueError):
        schedule_review(state, 4, TODAY)


def test_rejects_datetime_as_reviewed_on():
    with pytest.raises(ValueError):
        schedule_review(Schedule(), 4, datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    ("reviewed_on", "expected_due"),
    [
        (date(2024, 2, 28), date(2024, 2, 29)),
        (date(2025, 2, 28), date(2025, 3, 1)),
        (date(2026, 12, 31), date(2027, 1, 1)),
    ],
)
def test_calendar_rollover_boundaries(reviewed_on, expected_due):
    assert schedule_review(Schedule(), 4, reviewed_on).due_date == expected_due
