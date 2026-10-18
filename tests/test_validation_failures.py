"""VALIDATE_SEGMENTS names every failing check in one run, not the first: a cloud
rebuild costs hours, and v0.8.2 and v0.8.3 each spent one to find one sentinel."""

from types import SimpleNamespace

import pytest

from pipeline.run import ValidationFailed, _Failures, assert_calm_runs


def _fail(message: str) -> None:
    raise ValidationFailed(message)


def test_every_check_runs_and_all_failures_are_raised_together() -> None:
    failures = _Failures()
    ran = []
    failures.check(_fail, "the first sentinel")
    failures.check(ran.append, "the check after it still ran")
    failures.check(_fail, "the second sentinel")
    assert ran == ["the check after it still ran"]
    with pytest.raises(ValidationFailed) as raised:
        failures.raise_if_any()
    assert str(raised.value) == (
        "2 checks failed:\n  1. the first sentinel\n  2. the second sentinel"
    )


def test_one_failure_keeps_its_own_message_and_none_raises_nothing() -> None:
    failures = _Failures()
    failures.raise_if_any()
    failures.check(_fail, "only this")
    with pytest.raises(ValidationFailed, match="^only this$"):
        failures.raise_if_any()


def test_other_errors_are_not_swallowed() -> None:
    def broken() -> None:
        raise KeyError("a bug, not a failed check")

    with pytest.raises(KeyError):
        _Failures().check(broken)


def test_the_calm_runs_name_every_short_sentinel_and_the_floors() -> None:
    summary = SimpleNamespace(unset_named=0, sentinels={8: 0}, path_rows=0, street_rows=0)
    with pytest.raises(ValidationFailed) as raised:
        assert_calm_runs(summary, (9,), (8,), (1, 1))
    message = str(raised.value)
    assert "path sentinel way 9 is not in the segment table" in message
    assert "road sentinel way 8 came out at a run of 0 m" in message
    assert "floors of 1 and 1" in message
