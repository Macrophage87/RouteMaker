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


# --- Owner-rated stretches (OWNER-DECISIONS 432) ------------------------------------


def test_the_south_capitol_stretch_is_the_owners() -> None:
    from django.conf import settings

    from config import settings as real

    (row,) = real.REBUILD_SENTINEL_STRETCHES
    stretch = lts_sentinels.Stretch.of(row)
    assert stretch.street == "SOUTH CAPITOL ST BN"
    assert (stretch.south_lat, stretch.north_lat) == (38.8309, 38.8357)
    assert stretch.tier == 4 and stretch.min_share >= 0.95
    assert "432" in stretch.decision
    assert settings.REBUILD_SENTINEL_STRETCHES == ()


def _stretch() -> lts_sentinels.Stretch:
    return lts_sentinels.Stretch(
        "SOUTH CAPITOL ST BN", 38.8309, 38.8357, 4, 0.95, "OWNER-DECISIONS 432"
    )


def test_a_stretch_at_the_owners_tier_holds_and_one_left_at_avoid_is_refused() -> None:
    held = lts_sentinels.StretchTiers(_stretch(), 550.0, 550.0)
    assert lts_sentinels.stretch_problems(held) == []
    (message,) = lts_sentinels.stretch_problems(lts_sentinels.StretchTiers(_stretch(), 550.0, 0.0))
    assert "0%" in message and "OWNER-DECISIONS 432" in message and "retires" in message
    (empty,) = lts_sentinels.stretch_problems(lts_sentinels.StretchTiers(_stretch(), 0.0, 0.0))
    assert "no segment row" in empty


@pytest.mark.django_db
def test_a_stretch_is_read_back_by_its_blocks_and_latitudes_at_exactly_its_tier() -> None:
    from pipeline.schema import create_segment_schema, drop_segment_schema

    name = "ltsstretch"
    drop_segment_schema(name)
    create_segment_schema(name)
    try:
        rows = [
            # (way, tier, latitude of the middle, blocks): inside at 4, inside at Avoid,
            # south of Mississippi Ave at 5, north of MLK at 5, another street at 4.
            (1, 4, 38.8340, ["dc-s"]),
            (2, 5, 38.8320, ["dc-s"]),
            (3, 5, 38.8300, ["dc-s"]),
            (4, 5, 38.8370, ["dc-s"]),
            (5, 4, 38.8330, ["dc-x"]),
        ]
        with connection.cursor() as cursor:
            for way, tier, lat, blocks in rows:
                cursor.execute(
                    f"INSERT INTO {name}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_rule, map_class, attr_sources) VALUES (%s, 0, ST_MakeLine("
                    "ST_SetSRID(ST_MakePoint(-77.008, %s), 4326), "
                    "ST_SetSRID(ST_MakePoint(-77.008, %s), 4326)), %s, 'x', 'road', %s::jsonb)",
                    [way, lat - 0.0002, lat + 0.0002, tier, json.dumps({"blocks": blocks})],
                )
        got = lts_sentinels.stretch_tiers(name, _stretch(), ["dc-s"])
    finally:
        drop_segment_schema(name)
    one = 0.0004 * 111_195
    assert got.total_m == pytest.approx(2 * one, rel=0.01)
    assert got.at_tier_m == pytest.approx(one, rel=0.01)
    assert lts_sentinels.stretch_problems(got)


def test_validate_refuses_a_stretch_left_at_avoid(monkeypatch) -> None:
    from pipeline import run

    blocks = [SimpleNamespace(feature_id="dc-s", facts=SimpleNamespace(name="SOUTH CAPITOL ST BN"))]
    context = SimpleNamespace(
        require_reference=lambda: SimpleNamespace(road_blocks=blocks), staging_schema="x"
    )
    seen = {}

    def read(schema, stretch, ids):
        seen["ids"] = ids
        return lts_sentinels.StretchTiers(stretch, 550.0, 0.0)

    monkeypatch.setattr(lts_sentinels, "stretch_tiers", read)
    row = ("SOUTH CAPITOL ST BN", 38.8309, 38.8357, 4, 0.95, "OWNER-DECISIONS 432")
    with pytest.raises(run.ValidationFailed, match="432"):
        run.assert_owner_stretches(context, [row])
    assert seen["ids"] == ["dc-s"]
    assert run.assert_owner_stretches(context, []) == []
