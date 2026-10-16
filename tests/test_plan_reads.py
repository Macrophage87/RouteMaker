# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""A plan's segment-table reads run under its clock (review speed-9; `routing.plan_cursor`).

A slow or blocked database used to hold a plan to gunicorn's 60 s kill and an empty 502.
Inside a plan each read has a statement timeout of the time left, and a read it cancels
is the plan running out of time (DeadlineExceeded, answered 503 with retry advice).
"""

from __future__ import annotations

import contextvars

import pytest
from django.db import OperationalError, connection, transaction

# The route tests' fixtures, by name.
from test_route_api import good_body, post, router, segments, standard_router  # noqa: F401

from core import routing


def in_a_plan(seconds_left: float, fn):
    def run():
        routing._plan_ends.set(routing.clock() + seconds_left)
        return fn()

    return contextvars.copy_context().run(run)


def statement_timeout() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('statement_timeout')")
        return cursor.fetchone()[0]


@pytest.mark.django_db(transaction=True)
def test_a_read_past_the_plans_time_is_the_plan_running_out() -> None:
    def slow():
        with routing.plan_cursor() as cursor:
            cursor.execute("SELECT pg_sleep(5)")

    with pytest.raises(routing.DeadlineExceeded):
        in_a_plan(0.3, slow)
    # The connection is usable after, with no timeout left behind.
    assert statement_timeout() == "0"


@pytest.mark.django_db(transaction=True)
def test_no_time_left_asks_nothing() -> None:
    def read():
        with routing.plan_cursor() as cursor:
            cursor.execute("SELECT 1")

    with pytest.raises(routing.DeadlineExceeded):
        in_a_plan(-1.0, read)


@pytest.mark.django_db
def test_inside_a_callers_transaction_the_timeout_ends_with_the_read() -> None:
    def read():
        with routing.plan_cursor() as cursor:
            cursor.execute("SELECT current_setting('statement_timeout')")
            return cursor.fetchone()[0]

    with transaction.atomic():
        before = statement_timeout()
        during = in_a_plan(20.0, read)
        assert during not in ("0", before)
        assert statement_timeout() == before


@pytest.mark.django_db
def test_outside_a_plan_a_read_has_no_timeout_of_its_own() -> None:
    with routing.plan_cursor() as cursor:
        cursor.execute("SELECT current_setting('statement_timeout')")
        assert cursor.fetchone()[0] == "0"


def test_a_plans_clock_ends_with_the_plan() -> None:
    marked = routing._own_context(lambda: routing._plan_ends.set(routing.clock() + 30))
    marked()
    assert routing._plan_ends.get() is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("weekday_clock")
def test_a_plan_whose_segment_read_runs_past_its_budget_answers_503(
    client, segments, router, monkeypatch
) -> None:
    """The plan sets its own clock (`_plan_ends`) and its reads run under it: a stuck
    segment read ends the plan at its budget with 503, not at gunicorn's kill."""
    router(standard_router())
    # Router calls get 1.5 s of a 4.5 s budget (the answer's reserve is 3 s); the read
    # may run to the end of the whole budget.
    monkeypatch.setattr(routing, "PLAN_BUDGET_S", 4.5)
    monkeypatch.setattr(routing, "ROUTER_TIMEOUT_S", 1.0)
    real = routing.classify
    seen = []

    def stuck(pieces, when, roadway_only=False):
        seen.append(routing._plan_ends.get())
        with routing.plan_cursor() as cursor:
            cursor.execute("SELECT pg_sleep(30)")
        return real(pieces, when, roadway_only)

    monkeypatch.setattr(routing, "classify", stuck)
    started = routing.clock()
    response = post(client, good_body())
    took = routing.clock() - started
    assert seen and seen[0] is not None, "the plan set its clock"
    assert response.status_code == 503, response.content
    assert took < 15, f"ended at the plan's budget, not the read's 30 s: {took:.1f} s"
    assert routing._plan_ends.get() is None


class _DriverError(Exception):
    def __init__(self, **codes):
        super().__init__("canceled")
        for name, value in codes.items():
            setattr(self, name, value)


@pytest.mark.parametrize(
    "cause",
    [_DriverError(sqlstate="57014"), _DriverError(pgcode="57014")],
    ids=["sqlstate", "pgcode"],
)
def test_a_cancel_is_seen_by_either_code(cause) -> None:
    error = OperationalError("canceling statement due to statement timeout")
    error.__cause__ = cause
    assert routing._canceled(error)


def test_psycopgs_own_query_canceled_is_a_cancel() -> None:
    from psycopg.errors import QueryCanceled

    assert routing._canceled(QueryCanceled("canceling statement"))
    assert not routing._canceled(OperationalError("server closed the connection"))
