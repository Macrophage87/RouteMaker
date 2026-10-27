"""A superseded Go plan cancelled server-side (routing audit S7, option B; core.plan_cancel).

The owner, 2026-10-27, approved reversing the scheduler's "one request at a time" rule for
this: the page names each plan (X-Plan-Id), cancels a full plan it replaces (POST
/api/route/cancel) and sends the new plan at once (X-Plan-Replaces). The plan stops at its
next router call; the new plan may wait a moment for the slot the old one gives back."""

from __future__ import annotations

import json
import threading
from concurrent.futures import Future

import pytest
from django.test import override_settings
from test_route_api import (  # noqa: F401 - fixtures
    good_body,
    hold_slots,
    our_advisory_locks,
    post,
    router,
    segments,
    standard_router,
)

from core import api, parallel, plan_cancel, ratelimit, routing, timing

db = pytest.mark.django_db(transaction=True)
pytestmark = pytest.mark.usefixtures("weekday_clock")

CANCEL_PATH = "/api/route/cancel"
PLAN = "0123456789abcdef0123456789abcdef"
OTHER_PLAN = "fedcba9876543210fedcba9876543210"


@pytest.fixture
def store(monkeypatch):
    """The cancel store, in memory: the keys flagged, and how often each was read."""
    flagged: set[str] = set()
    reads: list[str] = []

    def read(key: str) -> bool:
        reads.append(key)
        return key in flagged

    monkeypatch.setattr(plan_cancel, "flagged", read)
    monkeypatch.setattr(plan_cancel.connection, "in_atomic_block", False, raising=False)
    return flagged, reads


class TestThePlanStops:
    def test_a_cancelled_plan_makes_no_router_call_and_counts_it_failed(
        self, store, monkeypatch
    ) -> None:
        flagged, _reads = store
        flagged.add("k")
        sent = []
        monkeypatch.setattr(routing, "_transport", lambda *a: sent.append(a) or {})
        timings = timing.Timings()
        token = timing.start(timings)
        watching = routing.watch_cancel(plan_cancel.Watch("k"))
        try:
            with pytest.raises(routing.PlanCancelled):
                routing._call("standard", "route", {}, routing.Deadline(routing.clock() + 30, 30))
        finally:
            routing.unwatch_cancel(watching)
            timing.stop(token)
        assert sent == []
        # A failed call: the answer cache never keeps what a cancelled plan answered.
        assert timings.failures == 1

    def test_a_cancel_is_a_deadline_so_every_step_gives_way_as_for_time(self) -> None:
        assert issubclass(routing.PlanCancelled, routing.DeadlineExceeded)

    def test_a_plan_not_cancelled_calls_the_router(self, store, monkeypatch) -> None:
        monkeypatch.setattr(routing, "_transport", lambda *a: {"ok": True})
        watching = routing.watch_cancel(plan_cancel.Watch("k"))
        try:
            answer = routing._call(
                "standard", "route", {}, routing.Deadline(routing.clock() + 30, 30)
            )
        finally:
            routing.unwatch_cancel(watching)
        assert answer == {"ok": True}

    def test_no_watch_no_read(self, store, monkeypatch) -> None:
        _flagged, reads = store
        monkeypatch.setattr(routing, "_transport", lambda *a: {})
        routing._call("standard", "route", {}, routing.Deadline(routing.clock() + 30, 30))
        assert reads == []

    def test_the_store_is_read_at_most_every_poll(self, store, monkeypatch) -> None:
        _flagged, reads = store
        now = [100.0]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        watch = plan_cancel.Watch("k")
        watch.check()
        watch.check()
        assert len(reads) == 1
        now[0] += plan_cancel.POLL_S
        watch.check()
        assert len(reads) == 2

    def test_once_seen_it_raises_without_reading_again(self, store) -> None:
        flagged, reads = store
        flagged.add("k")
        watch = plan_cancel.Watch("k")
        with pytest.raises(routing.PlanCancelled):
            watch.check()
        with pytest.raises(routing.PlanCancelled):
            watch.check(poll=False)
        assert len(reads) == 1

    def test_a_pool_thread_never_reads_the_store(self, store, monkeypatch) -> None:
        flagged, reads = store
        flagged.add("k")
        monkeypatch.setattr(parallel, "inside", lambda: True)
        plan_cancel.Watch("k").check()
        assert reads == []

    def test_a_store_that_fails_lets_the_plan_go_on(self, monkeypatch) -> None:
        from django.db import DatabaseError

        def broken(key):
            raise DatabaseError("down")

        monkeypatch.setattr(plan_cancel, "flagged", broken)
        monkeypatch.setattr(plan_cancel.connection, "in_atomic_block", False, raising=False)
        watch = plan_cancel.Watch("k")
        watch.check()
        assert not watch.cancelled


class TestWaitingOnThePool:
    """The request's thread, blocked on calls it gave the pool (refine's wide routes, the
    traces), sees a cancel while it waits instead of after every call submitted has run."""

    def test_a_cancel_seen_while_waiting_raises_and_drops_the_call(self, store) -> None:
        flagged, _reads = store
        pending: Future = Future()
        watch = plan_cancel.Watch("k")
        watching = routing.watch_cancel(watch)
        timer = threading.Timer(0.15, lambda: flagged.add("k"))
        timer.start()
        began = routing.clock()
        try:
            with pytest.raises(routing.PlanCancelled):
                routing.await_future(pending)
        finally:
            routing.unwatch_cancel(watching)
            timer.cancel()
        # Never answered: it was the cancel that ended the wait, within a poll or two.
        assert routing.clock() - began < 2.0
        assert pending.cancelled()
        assert watch.cancelled

    def test_an_answer_is_given_as_it_would_be(self, store) -> None:
        _flagged, reads = store
        pending: Future = Future()
        watching = routing.watch_cancel(plan_cancel.Watch("k"))
        timer = threading.Timer(0.15, lambda: pending.set_result({"trip": {}}))
        timer.start()
        try:
            assert routing.await_future(pending) == {"trip": {}}
        finally:
            routing.unwatch_cancel(watching)
            timer.cancel()
        assert reads, "the store was asked while waiting"

    def test_a_failed_call_raises_its_own_error(self, store) -> None:
        pending: Future = Future()
        pending.set_exception(routing.RouterRefused(400, 442, "no route"))
        watching = routing.watch_cancel(plan_cancel.Watch("k"))
        try:
            with pytest.raises(routing.RouterRefused):
                routing.await_future(pending)
        finally:
            routing.unwatch_cancel(watching)

    def test_no_watch_no_read(self, store) -> None:
        _flagged, reads = store
        assert routing.await_future(parallel.done({"ok": True})) == {"ok": True}
        assert reads == []


class TestIds:
    @pytest.mark.parametrize("value", [PLAN, "abcd-EF_12", " " + PLAN + " "])
    def test_good_ids(self, value) -> None:
        assert plan_cancel.plan_id(value) == value.strip()

    @pytest.mark.parametrize("value", [None, "", "short", "x" * 65, "a b c d e f g h", "abc/defgh"])
    def test_other_values_are_no_id(self, value) -> None:
        assert plan_cancel.plan_id(value) is None

    def test_the_key_takes_the_clients_address(self, rf) -> None:
        mine = rf.post("/", REMOTE_ADDR="198.51.100.30")
        theirs = rf.post("/", REMOTE_ADDR="198.51.100.31")
        assert plan_cancel._key(mine, PLAN) != plan_cancel._key(theirs, PLAN)
        assert plan_cancel._key(mine, PLAN) == plan_cancel._key(mine, PLAN)
        # A digest, never the address or the id.
        assert "198.51.100.30" not in plan_cancel._key(mine, PLAN)
        assert PLAN not in plan_cancel._key(mine, PLAN)


class TestSlots:
    def test_a_replacing_plan_takes_the_same_slots_with_a_short_wait(self) -> None:
        limit = ratelimit.replacing(ratelimit.ROUTING_IN_FLIGHT, plan_cancel.REPLACE_WAIT_S)
        assert limit.total_class == ratelimit.ROUTING_IN_FLIGHT.total_class
        assert limit.scope_id == ratelimit.ROUTING_IN_FLIGHT.scope_id
        assert limit.per_client == ratelimit.ROUTING_IN_FLIGHT.per_client
        assert limit.wait_s == plan_cancel.REPLACE_WAIT_S <= 1.0
        assert limit.max_waiters == ratelimit.REPLACE_WAITERS == 1

    def test_the_wait_is_asked_of_the_request(self, rf, monkeypatch) -> None:
        taken = []

        def acquire(request, limit, **kwargs):
            taken.append(limit)
            return [], None

        monkeypatch.setattr(ratelimit, "acquire", acquire)
        monkeypatch.setattr(ratelimit, "release", lambda held: None)
        view = ratelimit.in_flight_limited(
            ratelimit.ROUTING_IN_FLIGHT, wait_for=lambda r: getattr(r, "wait", 0)
        )(lambda request: "ran")
        plain = rf.post("/")
        waiting = rf.post("/")
        waiting.wait = 0.5
        assert view(plain) == "ran" and view(waiting) == "ran"
        assert taken[0] is ratelimit.ROUTING_IN_FLIGHT
        assert taken[1].wait_s == 0.5

    def test_the_cancel_takes_no_slot(self) -> None:
        decorators = []
        for _prefix, router_ in api.api._routers:
            for path, view in router_.path_operations.items():
                if path == "/route/cancel":
                    for op in view.operations:
                        decorators += getattr(op, "_run_decorators", [])
        limits = [getattr(d, "limits", None) for d in decorators]
        assert ratelimit.PLAN_CANCEL in limits
        assert not any(isinstance(limit, ratelimit.InFlight) for limit in limits)


def test_both_are_in_the_openapi_schema() -> None:
    schema = api.api.get_openapi_schema()
    answers = {str(k) for k in schema["paths"]["/api/route/cancel"]["post"]["responses"]}
    assert "204" in answers
    # A bad id is a 400, never a 422 (`api.invalid_input`): the schema says only what is answered.
    assert "400" in answers and "422" not in answers
    conflict = schema["paths"]["/api/route"]["post"]["responses"][409]
    assert "CancelledOut" in json.dumps(conflict)


def cancel(client, plan: str, **extra):
    return client.post(
        CANCEL_PATH, data=json.dumps({"plan_id": plan}), content_type="application/json", **extra
    )


@db
class TestOverHttp:
    def test_a_cancelled_plan_answers_409(self, client, segments, router) -> None:  # noqa: F811
        fake = router(standard_router())
        assert cancel(client, PLAN, REMOTE_ADDR="198.51.100.40").status_code == 204
        response = post(client, good_body(), REMOTE_ADDR="198.51.100.40", HTTP_X_PLAN_ID=PLAN)
        assert response.status_code == 409
        assert response.json()["code"] == "plan_cancelled"
        assert "Retry-After" not in response
        assert fake.calls == []
        assert our_advisory_locks() == 0

    def test_another_clients_cancel_does_not_stop_the_plan(self, client, segments, router) -> None:  # noqa: F811
        router(standard_router())
        assert cancel(client, PLAN, REMOTE_ADDR="198.51.100.41").status_code == 204
        response = post(client, good_body(), REMOTE_ADDR="198.51.100.42", HTTP_X_PLAN_ID=PLAN)
        assert response.status_code == 200

    def test_another_plans_cancel_does_not_stop_this_one(self, client, segments, router) -> None:  # noqa: F811
        router(standard_router())
        cancel(client, OTHER_PLAN, REMOTE_ADDR="198.51.100.43")
        response = post(client, good_body(), REMOTE_ADDR="198.51.100.43", HTTP_X_PLAN_ID=PLAN)
        assert response.status_code == 200

    def test_a_bad_id_is_refused(self, client) -> None:
        # Ninja's validation error is the contract's 400 (`api.invalid_input`), as declared.
        response = cancel(client, "no")
        assert response.status_code == 400
        assert "error" in response.json()

    def test_a_replacing_plan_cancels_the_plan_it_replaces(self, client, segments, router) -> None:  # noqa: F811
        router(standard_router())
        new = post(
            client,
            good_body(),
            REMOTE_ADDR="198.51.100.44",
            HTTP_X_PLAN_ID=OTHER_PLAN,
            HTTP_X_PLAN_REPLACES=PLAN,
        )
        assert new.status_code == 200
        old = post(client, good_body(), REMOTE_ADDR="198.51.100.44", HTTP_X_PLAN_ID=PLAN)
        assert old.status_code == 409

    @override_settings(ROUTING_CONCURRENCY=2)
    def test_a_replacing_plan_waits_for_the_slot_given_back(self, client, segments, router) -> None:  # noqa: F811
        # Beta's pool of two: the plan being replaced holds the client's slot, as another
        # worker would, and gives it back a moment later.
        router(standard_router())
        address = "198.51.100.45"
        key = ratelimit._client_lock_id(ratelimit.client_key(address))
        limit = ratelimit.ROUTING_IN_FLIGHT
        old = hold_slots(
            [
                (limit.total_class, 0),
                (ratelimit._LOCK_CLASS_CLIENT + limit.scope_id * 64, key),
            ]
        )
        refused = post(client, good_body(), REMOTE_ADDR=address)
        timer = threading.Timer(0.3, old.close)
        timer.start()
        try:
            waited = post(
                client,
                good_body(),
                REMOTE_ADDR=address,
                HTTP_X_PLAN_ID=OTHER_PLAN,
                HTTP_X_PLAN_REPLACES=PLAN,
            )
        finally:
            timer.join()
        assert refused.status_code == 429
        assert waited.status_code == 200
