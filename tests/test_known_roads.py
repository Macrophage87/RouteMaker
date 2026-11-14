"""Roads the owner has called, read back at VALIDATE_SEGMENTS (`pipeline.known_roads`)."""

from __future__ import annotations

import pytest
from django.db import connection

from pipeline import known_roads
from pipeline.known_roads import KnownRoad, KnownRoadTiers


def road(level=4.0, at_least=False, line="-77.0,38.90 -77.0,38.91") -> KnownRoad:
    return KnownRoad.of(
        {
            "road": "Test Road",
            "where": "here",
            "level": level,
            "at_least": at_least,
            "min_share": 0.9,
            "decision": "OWNER-DECISIONS 999",
            "line": line,
        }
    )


def test_the_fixture_loads_and_every_entry_names_its_decision() -> None:
    from config import settings as real

    roads = known_roads.load(real.REBUILD_KNOWN_ROADS)
    assert len(roads) >= 15
    for entry in roads:
        assert entry.decision and entry.line and 0 < entry.min_share <= 1
        assert 1 <= entry.level <= 5
    names = {entry.road for entry in roads}
    assert {"New York Avenue NE", "Darnestown Road", "Peach Tree Road"} <= names


def test_the_test_suite_turns_the_check_off() -> None:
    from django.conf import settings

    from pipeline import run

    assert settings.REBUILD_KNOWN_ROADS == ""
    assert known_roads.load("") == []
    assert run.assert_known_roads("x", "") == []


def test_a_level_must_be_a_half_step_and_a_line_two_points() -> None:
    with pytest.raises(ValueError, match="half steps"):
        road(level=3.2)
    with pytest.raises(ValueError, match="two points"):
        KnownRoad.of(
            {"road": "R", "level": 2, "min_share": 0.9, "decision": "d", "line": "-77,38.9"}
        )


def test_a_line_in_pieces_is_a_multilinestring() -> None:
    entry = KnownRoad.of(
        {
            "road": "R",
            "level": 5,
            "min_share": 0.9,
            "decision": "d",
            "line": "-77.0,38.9 -77.0,38.91 | -77.1,38.9 -77.1,38.91",
        }
    )
    assert entry.wkt == "MULTILINESTRING ((-77.0 38.9, -77.0 38.91), (-77.1 38.9, -77.1 38.91))"
    assert entry.wanted == "Avoid"


def test_held_found_and_lost_in_words() -> None:
    held = KnownRoadTiers(road(), 1000.0, 950.0, 1000.0)
    assert known_roads.problems(held) == []
    (calmer,) = known_roads.problems(KnownRoadTiers(road(), 1000.0, 0.0, 1000.0))
    assert "only 0%" in calmer and "OWNER-DECISIONS 999" in calmer and "LTS 4" in calmer
    assert " mi (" in calmer, "US units first"
    (lost,) = known_roads.problems(KnownRoadTiers(road(), 100.0, 100.0, 1000.0))
    assert "could not be checked" in lost and "redraw" in lost
    assert road(at_least=True).wanted == "LTS 4 or higher"


@pytest.mark.django_db
@pytest.mark.parametrize(("at_least", "share"), [(False, 0.5), (True, 1.0)])
def test_rows_are_read_back_by_where_they_are(at_least, share) -> None:
    from pipeline.schema import create_segment_schema, drop_segment_schema

    # One schema per case, so the two cases never share one however the suite is spread.
    name = f"knownroads_{int(at_least)}"
    drop_segment_schema(name)
    create_segment_schema(name)
    lon = -77.0
    # (way, tier, half, lon offset, map_class, trail, from lat, to lat)
    rows = [
        (1, 4, False, 0.0, "road", False, 38.900, 38.905),  # on the line, at 4
        (2, 4, True, 0.00005, "road", False, 38.905, 38.910),  # 4 m off, at 4.5
        (3, 1, False, 0.00012, "road", True, 38.900, 38.910),  # side path: never counts
        (4, 2, False, 0.003, "road", False, 38.900, 38.910),  # parallel street 260 m away
        (5, 2, False, 0.0, "road", False, 38.905, 38.9052),  # cross street: mostly outside
    ]
    try:
        with connection.cursor() as cursor:
            for way, tier, half, dx, map_class, trail, south, north in rows:
                if way == 5:
                    geom = (
                        f"ST_MakeLine(ST_SetSRID(ST_MakePoint({lon}, {south}), 4326), "
                        f"ST_SetSRID(ST_MakePoint({lon + 0.002}, {south}), 4326))"
                    )
                else:
                    geom = (
                        f"ST_MakeLine(ST_SetSRID(ST_MakePoint({lon + dx}, {south}), 4326), "
                        f"ST_SetSRID(ST_MakePoint({lon + dx}, {north}), 4326))"
                    )
                cursor.execute(
                    f"INSERT INTO {name}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    f"stress_half, stress_rule, map_class, is_trail_class) VALUES "
                    f"(%s, 0, {geom}, %s, %s, 'x', %s, %s)",
                    [way, tier, half, map_class, trail],
                )
        got = known_roads.read(name, road(level=4.0, at_least=at_least))
    finally:
        drop_segment_schema(name)
    one = 0.005 * 111_000
    assert got.total_m == pytest.approx(2 * one, rel=0.02), got
    assert got.share == pytest.approx(share, abs=0.01)
    assert got.line_m == pytest.approx(2 * one, rel=0.02)
