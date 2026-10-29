# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""A stop or the end on a road not open to the public says so (the owner, 2026-10-29: "It would
only be routed to if there's a destination that would use those roads. Basically when you set a
destination: This end point is not typically open to the public, make sure you're authorized to
go here."). A road the route only passes along says nothing.

The router is the fake of tests/test_route_api.py: one leg over VERTICES, ways 101, 202 and 303,
the last one ending at the route's end."""

from __future__ import annotations

import sys

import pytest
from django.db import connection
from test_route_api import (  # noqa: F401 (fixtures)
    STANDARD_EDGES,
    VERTICES,
    FakeRouter,
    good_body,
    post,
    route_answer,
    router,
    segments,
    standard_router,
    trace_answer,
)

from core import routing

pytestmark = pytest.mark.usefixtures("weekday_clock")

db = pytest.mark.django_db(transaction=True)

NOTE = "This end point is not typically open to the public, make sure you're authorized to go here."


def mark(live: str, way: int, line, reason: str) -> None:
    wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, bike_access_reason) "
            "VALUES (%s, 9, ST_GeomFromText(%s, 4326), 1, 'test', %s)",
            [way, wkt, reason],
        )


def test_the_note_is_the_owners_words() -> None:
    assert routing.NOT_PUBLIC_NOTE == NOTE


@db
class TestThroughTheApi:
    @pytest.mark.parametrize("reason", routing.NOT_PUBLIC_REASONS)
    def test_an_end_on_a_road_not_open_to_the_public_says_so(
        self, client, segments, router, reason
    ) -> None:
        mark(segments, 303, VERTICES[3:], reason)
        router(standard_router())
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["point_notes"] == [
            {"index": 1, "reason": "not_public", "note": NOTE}
        ]

    def test_a_failed_read_still_answers_the_route_without_the_note(
        self, client, segments, router, monkeypatch
    ) -> None:
        # The end note is read after the route is traced: a timed-out or failed read must not
        # cost the rider the finished route (the v0.15.0 end review).
        mark(segments, 303, VERTICES[3:], "private")
        router(standard_router())

        real = routing.segment_info.has_columns

        def fail_for_the_end_note(schema, *columns):
            # Only the end note's own read fails: the caller is not_public_ends.
            if sys._getframe(1).f_code.co_name == "not_public_ends":
                raise routing.DeadlineExceeded("the plan's time ran out")
            return real(schema, *columns)

        monkeypatch.setattr(routing.segment_info, "has_columns", fail_for_the_end_note)
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["point_notes"] == []

    def test_a_road_only_passed_along_says_nothing(self, client, segments, router) -> None:
        mark(segments, 202, VERTICES[1:4], "private")
        router(standard_router())
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["point_notes"] == []

    def test_an_open_or_other_closed_end_says_nothing(self, client, segments, router) -> None:
        mark(segments, 303, VERTICES[3:], "bicycle_no")
        router(standard_router())
        assert post(client, good_body()).json()["point_notes"] == []

    def test_a_stop_says_so_and_names_its_point(self, client, segments, router) -> None:
        # Two legs: the first ends on way 202 at VERTICES[2], the stop; the second on 303.
        mark(segments, 202, VERTICES[1:3], "military")
        first, second = VERTICES[:3], VERTICES[2:]
        router(
            FakeRouter(
                {
                    "route": route_answer(
                        [(first, 1.2, [10.0, 20.0]), (second, 1.0, [15.0, 30.0])]
                    ),
                    "trace_attributes": lambda payload: (
                        trace_answer(first, [(101, 0, 1, 0.9), (202, 1, 2, 0.4)])
                        if payload["encoded_polyline"]
                        == route_answer([(first, 1, [])])["trip"]["legs"][0]["shape"]
                        else trace_answer(second, [(202, 0, 1, 0.4), (303, 1, 2, 0.5)])
                    ),
                }
            )
        )
        body = {**good_body(), "points": [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])]}
        response = post(client, body)
        assert response.status_code == 200, response.content
        assert response.json()["point_notes"] == [
            {"index": 1, "reason": "not_public", "note": NOTE}
        ]

    def test_in_spanish(self, client, segments, router) -> None:
        mark(segments, 303, VERTICES[3:], "private")
        router(standard_router())
        response = post(client, {**good_body(), "lang": "es"})
        assert response.status_code == 200, response.content
        assert response.json()["point_notes"][0]["note"].startswith("Este punto final")
