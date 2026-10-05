"""The owner's reference LTS 4 road at VALIDATE (OWNER-DECISIONS 408, 409)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from django.db import connection

from pipeline import lts_sentinels
from pipeline.lts_sentinels import StreetTiers

R_ST = 38.9126


def tiers(total=1000.0, lts4=700.0, north=600.0, north_lts4=590.0) -> StreetTiers:
    return StreetTiers("CONNECTICUT AVE NW", R_ST, total, lts4, north, north_lts4)


def test_the_settings_are_the_owners_street_and_r_st() -> None:
    from django.conf import settings

    # conftest turns the street off for the toy extracts; the module's own value is the
    # real one.
    from config import settings as real

    assert real.REBUILD_SENTINEL_LTS4_STREET == "CONNECTICUT AVE NW"
    assert real.REBUILD_SENTINEL_LTS4_NORTH_OF_LAT == R_ST
    assert 0.5 < real.REBUILD_SENTINEL_LTS4_MIN_SHARE <= real.REBUILD_SENTINEL_LTS4_NORTH_MIN_SHARE
    assert settings.REBUILD_SENTINEL_LTS4_STREET == ""


def test_a_street_mostly_lts4_and_lts4_north_of_r_holds() -> None:
    assert lts_sentinels.problems(tiers(), 0.6, 0.95) == []
    assert tiers().share == pytest.approx(0.7) and tiers().north_share == pytest.approx(590 / 600)


@pytest.mark.parametrize(
    ("given", "said"),
    [
        # The 2026-10-03 build: 49% overall, and R St to Calvert St at LTS 3.
        (tiers(lts4=490.0, north_lts4=430.0), ["only 49%", "72% of CONNECTICUT AVE NW north"]),
        (tiers(lts4=590.0), ["only 59%"]),
        (tiers(north_lts4=560.0), ["93% of CONNECTICUT AVE NW north of 38.9126 N"]),
        (tiers(north=0.0, north_lts4=0.0), ["0% of CONNECTICUT AVE NW north"]),
    ],
)
def test_a_calmer_street_is_refused_in_words(given, said) -> None:
    found = lts_sentinels.problems(given, 0.6, 0.95)
    assert len(found) == len(said)
    for message, words in zip(found, said, strict=True):
        assert words in message, message
        assert "OWNER-DECISIONS 40" in message
    assert " mi (" in found[0], "US units first"


def test_a_street_with_no_rows_is_refused() -> None:
    (message,) = lts_sentinels.problems(tiers(0.0, 0.0, 0.0, 0.0), 0.6, 0.95)
    assert "not rated at all" in message


def test_the_blocks_are_found_by_the_agencys_name() -> None:
    def block(feature_id, name):
        return SimpleNamespace(feature_id=feature_id, facts=SimpleNamespace(name=name))

    blocks = [
        block("dc-2", "CONNECTICUT AVE NW"),
        block("dc-1", "Connecticut Ave NW "),
        block("dc-3", "K ST NW"),
        block("b-1", None),
    ]
    assert lts_sentinels.block_ids(blocks, "CONNECTICUT AVE NW") == ["dc-1", "dc-2"]


@pytest.mark.django_db
def test_the_rows_are_read_back_by_their_blocks_and_their_middles() -> None:
    from pipeline.schema import create_segment_schema, drop_segment_schema

    name = "ltscheck"
    drop_segment_schema(name)
    create_segment_schema(name)
    try:
        rows = [
            # (way, tier, latitude, blocks): south of R St LTS 3, north of it LTS 4 and Avoid,
            # another street's LTS 4, and a hidden way of the street.
            (1, 3, 38.9100, ["dc-a"], "road"),
            (2, 4, 38.9200, ["dc-a", "dc-b"], "road"),
            (3, 5, 38.9300, ["dc-b"], "road"),
            (4, 4, 38.9400, ["dc-k"], "road"),
            (5, 1, 38.9500, ["dc-b"], "hidden"),
        ]
        with connection.cursor() as cursor:
            for way, tier, lat, blocks, map_class in rows:
                cursor.execute(
                    f"INSERT INTO {name}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_rule, map_class, attr_sources) VALUES (%s, 0, ST_MakeLine("
                    "ST_SetSRID(ST_MakePoint(-77.05, %s), 4326), "
                    "ST_SetSRID(ST_MakePoint(-77.05, %s), 4326)), %s, 'x', %s, %s::jsonb)",
                    [
                        way,
                        lat - 0.0009,
                        lat + 0.0009,
                        tier,
                        map_class,
                        json.dumps({"blocks": blocks}),
                    ],
                )
        got = lts_sentinels.street_tiers(name, "CONNECTICUT AVE NW", ["dc-a", "dc-b"], R_ST)
    finally:
        drop_segment_schema(name)
    one = 0.0018 * 111_195  # metres in 0.0018 degrees of latitude, about 200 m
    assert got.total_m == pytest.approx(3 * one, rel=0.01)
    assert got.lts4_m == pytest.approx(2 * one, rel=0.01)
    assert got.north_m == pytest.approx(2 * one, rel=0.01)
    assert got.north_lts4_m == pytest.approx(2 * one, rel=0.01)
