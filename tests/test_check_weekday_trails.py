"""The weekday-trails acceptance check (manage.py check_weekday_trails, A7)."""

from __future__ import annotations

import io
import json

import pytest
from django.core.management import call_command
from django.db import connection

from core import routing
from core.management.commands import check_weekday_trails as check

db = pytest.mark.django_db(transaction=True)


def insert(schema, way, line, *, facility="none", trail=False, car_free="{}"):
    wkt = "LINESTRING(" + ", ".join(f"{x} {y}" for x, y in line) + ")"
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier,"
            " stress_rule,"
            " is_trail_class, facility, car_free_when)"
            " VALUES (%s, 0, ST_GeomFromText(%s, 4326), 2, 'test', %s, %s, %s::text[])",
            [way, wkt, trail, facility, car_free],
        )


@db
def test_a_parkway_is_a_weekend_closure_with_a_path_beside_it(segment_schemas) -> None:
    live, _ = segment_schemas
    road = [(-77.000, 38.980), (-77.000, 38.990)]
    insert(live, 1, road, car_free="{weekend}")
    insert(live, 2, [(-77.0003, 38.980), (-77.0003, 38.990)], facility="path", trail=True)  # 26 m
    insert(live, 3, [(-77.010, 38.980), (-77.010, 38.990)], car_free="{weekend}")  # no path near
    insert(live, 4, [(-77.0103, 38.980), (-77.0103, 38.9815)], facility="path", trail=True)
    assert check.parkways(live) == {1}


@db
def test_a_stress_averse_ride_on_a_parkway_is_reported_not_failed(
    segment_schemas, monkeypatch
) -> None:
    """Report-only (review r1, S6): the owner has not approved it as a gate."""
    live, _ = segment_schemas
    monkeypatch.setattr(check, "parkways", lambda schema: {101})

    def plan(points, preset, dials=None):
        on_road = preset in ("fast", "cargo")
        pieces = [routing.Piece(101 if on_road else 202, -77.0, 38.98, 500.0)]
        routing.breakdown(pieces, dials.when)
        return {}

    monkeypatch.setattr(check.routing, "plan", plan)
    out = io.StringIO()
    call_command("check_weekday_trails", stdout=out)  # no SystemExit
    verdict = json.loads(out.getvalue().strip().splitlines()[-1])
    assert verdict["report_only"] is True
    cargo = [f for f in verdict["findings"] if f.startswith("cargo ")]
    assert cargo and "1,640 ft [500 m]" in cargo[0], "feet first, metres in brackets"
    assert not any("fast no longer" in f for f in verdict["findings"])
    assert "ft [" in out.getvalue().splitlines()[0]


@db
def test_fast_leaving_the_parkway_is_a_finding(segment_schemas, monkeypatch) -> None:
    monkeypatch.setattr(check, "parkways", lambda schema: {101})

    def plan(points, preset, dials=None):
        routing.breakdown([routing.Piece(202, -77.0, 38.98, 500.0)], dials.when)
        return {}

    monkeypatch.setattr(check.routing, "plan", plan)
    out = io.StringIO()
    call_command("check_weekday_trails", stdout=out)
    verdict = json.loads(out.getvalue().strip().splitlines()[-1])
    assert verdict["findings"] == ["fast no longer takes lower Sligo Creek Parkway on sligo-lower"]
