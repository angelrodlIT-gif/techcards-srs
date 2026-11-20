from datetime import date, timedelta

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


def test_invalid_state():
    with pytest.raises(ValueError):
        schedule_review(Schedule(-1, 0, 2.5), 4, TODAY)
