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
def test_the_command_fails_when_a_stress_averse_ride_takes_a_parkway(
    segment_schemas, monkeypatch
) -> None:
    live, _ = segment_schemas
    monkeypatch.setattr(check, "parkways", lambda schema: {101})

    def plan(points, preset, dials=None):
        on_road = preset in ("fast", "cargo")
        pieces = [routing.Piece(101 if on_road else 202, -77.0, 38.98, 500.0)]
        routing.breakdown(pieces, dials.when)
        return {}

    monkeypatch.setattr(check.routing, "plan", plan)
    out = io.StringIO()
    with pytest.raises(SystemExit) as failed:
        call_command("check_weekday_trails", stdout=out)
    assert failed.value.code == 1
    verdict = json.loads(out.getvalue().strip().splitlines()[-1])
    assert any(f.startswith("cargo ") for f in verdict["failures"])
    assert not any("fast no longer" in f for f in verdict["failures"])


@db
def test_it_fails_when_fast_stops_taking_the_parkway(segment_schemas, monkeypatch) -> None:
    monkeypatch.setattr(check, "parkways", lambda schema: {101})

    def plan(points, preset, dials=None):
        routing.breakdown([routing.Piece(202, -77.0, 38.98, 500.0)], dials.when)
        return {}

    monkeypatch.setattr(check.routing, "plan", plan)
    out = io.StringIO()
    with pytest.raises(SystemExit):
        call_command("check_weekday_trails", stdout=out)
    verdict = json.loads(out.getvalue().strip().splitlines()[-1])
    assert verdict["failures"] == ["fast no longer takes lower Sligo Creek Parkway on sligo-lower"]
