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
    # Pinned exactly: a loosened share would pass the 49% / 72% build 408/409 refuse.
    assert real.REBUILD_SENTINEL_LTS4_MIN_SHARE == 0.6
    assert real.REBUILD_SENTINEL_LTS4_NORTH_MIN_SHARE == 0.95
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


@pytest.mark.parametrize(
    ("given", "words"),
    [
        # 2026-10-03: 49% overall, 72% north of R St.
        (tiers(lts4=490.0, north_lts4=432.0), ["only 49%", "72% of CONNECTICUT AVE NW north"]),
        (tiers(lts4=550.0, north_lts4=590.0), ["only 55%"]),
        (tiers(lts4=700.0, north_lts4=540.0), ["90% of CONNECTICUT AVE NW north"]),
    ],
)
def test_the_real_settings_refuse_the_build_of_2026_10_03(given, words) -> None:
    from config import settings as real

    found = lts_sentinels.problems(
        given, real.REBUILD_SENTINEL_LTS4_MIN_SHARE, real.REBUILD_SENTINEL_LTS4_NORTH_MIN_SHARE
    )
    assert len(found) == len(words), found
    for message, said in zip(found, words, strict=True):
        assert said in message, message


def test_the_real_settings_pass_the_street_as_rebuilt() -> None:
    from config import settings as real

    assert (
        lts_sentinels.problems(
            tiers(lts4=670.0, north_lts4=594.0),
            real.REBUILD_SENTINEL_LTS4_MIN_SHARE,
            real.REBUILD_SENTINEL_LTS4_NORTH_MIN_SHARE,
        )
        == []
    )


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


# --- The owner's rating rules over the whole table (review 2026-10-29) ---------------------

COUNTY_FIVE_RULE, COUNTY_ROW = lts_sentinels.county_five_prefixes()
BAN = json.dumps(
    {"agencies": [{"agency": "mdot-sha", "name": "MDOT SHA", "level": 5.0}], "used": "formula"}
)


@pytest.mark.django_db
def test_the_rating_rules_are_read_back_from_the_table() -> None:
    from pipeline.schema import create_segment_schema, drop_segment_schema

    name = "ltsrules"
    drop_segment_schema(name)
    create_segment_schema(name)
    rows = [
        # (way, tier, half, rule, adjustment, urban, trail, map_class, ratings, access)
        # A rural road at LTS 1 with no override; one an owner row set; an urban one; a trail.
        (1, 1, False, "mixed traffic, 20 mph or below", None, False, False, "road", None, None),
        (2, 1, False, "override: x", "owner-x", False, False, "road", None, None),
        (3, 1, False, "mixed traffic, 20 mph or below", None, True, False, "road", None, None),
        (4, 1, False, "path", None, False, True, "road", None, None),
        (5, 1, False, "mixed traffic", None, False, False, "hidden", None, None),
        # Montgomery's 5: at 4.5 (held), at 5 from the layer and from a row (refused).
        (6, 4, True, COUNTY_FIVE_RULE + ", our LTS 4.5", None, True, False, "road", None, None),
        (7, 5, False, COUNTY_FIVE_RULE, None, True, False, "road", None, None),
        (8, 5, False, "override: y", COUNTY_ROW + "ridge-road", True, False, "road", None, None),
        (9, 4, True, "override: y", COUNTY_ROW + "ridge-road", True, False, "road", None, None),
        # MDOT SHA's ban: closed (held), drawn with no reason (found), reopened by an override.
        (10, 4, False, "x", None, True, False, "barred", BAN, "mdot_prohibited"),
        (11, 4, False, "x", None, True, False, "road", BAN, None),
        (12, 4, False, "x", None, True, False, "road", BAN, "override_open"),
    ]
    try:
        with connection.cursor() as cursor:
            for way, tier, half, rule, adj, urban, trail, map_class, ratings, access in rows:
                cursor.execute(
                    f"INSERT INTO {name}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_half, stress_rule, stress_adjustment_id, road_urban, is_trail_class, "
                    "map_class, stress_ratings, bike_access_reason) VALUES (%s, 0, "
                    "ST_MakeLine(ST_SetSRID(ST_MakePoint(-77.2, 39.1), 4326), "
                    "ST_SetSRID(ST_MakePoint(-77.19, 39.1), 4326)), %s, %s, %s, %s, %s, %s, %s, "
                    "%s::jsonb, %s)",
                    [way, tier, half, rule, adj, urban, trail, map_class, ratings, access],
                )
        rural = lts_sentinels.rural_lts1_ways(name)
        county = lts_sentinels.county_five_ways(name)
        bans = lts_sentinels.open_ban_ways(name)
    finally:
        drop_segment_schema(name)
    assert rural == [1]
    assert county == [7, 8]
    assert bans == [11]


def test_the_rating_rules_say_what_is_wrong_in_words() -> None:
    assert lts_sentinels.rating_rule_problems([], [], []) == []
    found = lts_sentinels.rating_rule_problems(list(range(1, 13)), [7], [11])
    assert len(found) == 3
    assert found[0].startswith("12 ways (1, 2, 3") and "+2 more" in found[0]
    assert "rural floor" in found[0]
    assert found[1].startswith("1 way (7)") and "4.5" in found[1]
    assert "MDOT SHA" in found[2]


def test_validate_drops_exempt_rural_roads_and_listed_bans(monkeypatch) -> None:
    from pipeline import run

    ways = {
        1: SimpleNamespace(osm_id=1, tags={"highway": "residential"}),
        # Closed to cars: exempt from the rural floor.
        2: SimpleNamespace(osm_id=2, tags={"highway": "residential", "motor_vehicle": "no"}),
    }
    context = SimpleNamespace(
        staging_schema="x",
        ways_by_id=ways,
        ways=list(ways.values()),
        class_tags_by_way={},
        agency_prohibited_open={12},
    )
    monkeypatch.setattr(lts_sentinels, "rural_lts1_ways", lambda schema: [2])
    monkeypatch.setattr(lts_sentinels, "county_five_ways", lambda schema: [])
    monkeypatch.setattr(lts_sentinels, "open_ban_ways", lambda schema: [12])
    run.assert_rating_rules(context)
    monkeypatch.setattr(lts_sentinels, "rural_lts1_ways", lambda schema: [1, 2])
    with pytest.raises(run.ValidationFailed, match=r"^1 way \(1\) on a rural road"):
        run.assert_rating_rules(context)
    monkeypatch.setattr(lts_sentinels, "rural_lts1_ways", lambda schema: [])
    monkeypatch.setattr(lts_sentinels, "open_ban_ways", lambda schema: [11, 12])
    with pytest.raises(run.ValidationFailed, match="MDOT SHA"):
        run.assert_rating_rules(context)
