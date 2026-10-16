"""A plan's segment-table reads run under its clock (review speed-9; `routing.plan_cursor`).

A slow or blocked database used to hold a plan to gunicorn's 60 s kill and an empty 502.
Inside a plan each read has a statement timeout of the time left, and a read it cancels
is the plan running out of time (DeadlineExceeded, answered 503 with retry advice).
"""

from __future__ import annotations

import contextvars

import pytest
from django.db import connection, transaction

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
