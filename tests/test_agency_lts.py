"""Agency stress ratings in the owner's order: county over state over formula."""

from __future__ import annotations

import pytest

from routemaker import agency_lts
from routemaker.agency_lts import AgencyRating
from routemaker.stress import Stress, StressResult, rural_floor

FORMULA = StressResult(Stress.LTS4, "mixed traffic, 35 mph or above", ("maxspeed",))


def test_the_county_wins_over_the_state():
    ratings = [AgencyRating("mdot-sha", 3), AgencyRating("moco", 1)]
    result = agency_lts.apply(FORMULA, ratings)
    assert result.tier is Stress.LTS1
    assert "Montgomery County Planning" in result.rule
    # Both kept for the road panel, most local first, with the formula's tier.
    assert [r.agency for r in result.agency_ratings] == ["moco", "mdot-sha"]
    assert result.formula_tier is Stress.LTS4
    assert result.formula_rule == FORMULA.rule


def test_a_half_level_is_kept():
    result = agency_lts.apply(FORMULA, [AgencyRating("moco", 2.5)])
    assert (result.tier, result.half) == (Stress.LTS2, True)


def test_an_agency_lts5_is_avoid():
    result = agency_lts.apply(FORMULA, [AgencyRating("moco", 5)])
    assert result.tier is Stress.AVOID


def test_no_rating_leaves_the_formula():
    assert agency_lts.apply(FORMULA, []) is FORMULA


def test_two_agencies_at_one_rank_take_the_higher():
    pick = agency_lts.chosen([AgencyRating("moco", 2), AgencyRating("moco", 3)])
    assert pick.level == 3


@pytest.mark.parametrize("level", [0.5, 5.5, 2.25, 0])
def test_unusable_levels_are_refused(level):
    with pytest.raises(ValueError):
        agency_lts.tier_of(level)


def test_the_rural_floor_ranks_above_an_agency():
    tags = {"highway": "unclassified", "name": "Davis Mill Road"}
    rated = agency_lts.apply(FORMULA, [AgencyRating("moco", 1)])
    floored = rural_floor(rated, tags, urban=False)
    assert floored.tier is Stress.LTS2
    assert floored.agency_ratings == rated.agency_ratings


def test_the_rural_floor_leaves_a_county_half_step_alone():
    tags = {"highway": "unclassified"}
    rated = agency_lts.apply(FORMULA, [AgencyRating("moco", 2.5)])
    assert rural_floor(rated, tags, urban=False) is rated


def test_internal_only_and_unrated_agencies_are_not_listed():
    """Arlington's layer is internal only; Alexandria's are cleared (CC0, 2026-10-16) but
    rate nothing, so the city's speeds reach the classifier as street facts instead."""
    assert not {"arlington", "alexandria"} & set(agency_lts.AGENCIES)


def test_the_rural_floor_raises_a_county_one_and_a_half_to_two():
    rated = agency_lts.apply(FORMULA, [AgencyRating("moco", 1.5)])
    floored = rural_floor(rated, {"highway": "unclassified"}, urban=False)
    assert (floored.tier, floored.half) == (Stress.LTS2, False)


def test_the_writer_records_every_rating_and_the_one_used():
    import json

    from pipeline import writers

    rated = agency_lts.apply(FORMULA, [AgencyRating("mdot-sha", 3), AgencyRating("moco", 2.5)])
    held = json.loads(writers._ratings_json(rated))
    assert held["used"] == "moco" and held["formula"] == 4
    assert [a["level"] for a in held["agencies"]] == [2.5, 3]
    assert writers._half(rated) is True
    floored = rural_floor(
        agency_lts.apply(FORMULA, [AgencyRating("moco", 1)]), {"highway": "track"}, urban=False
    )
    assert json.loads(writers._ratings_json(floored))["used"] == "rural floor"
    assert writers._ratings_json(FORMULA) is None


def _way(osm_id, coords, **tags):
    from pipeline.extract import Way

    return Way(osm_id, {"highway": "unclassified", **tags}, list(range(len(coords))), coords)


def test_the_rebuild_matches_each_agency_on_its_own(tmp_path):
    import json

    from pipeline import agency_ratings

    line = [(-77.30 + i * 0.001, 39.20) for i in range(11)]
    rows = [
        {
            "id": "moco-1-0",
            "agency": "moco",
            "level": 1,
            "name": "Davis Mill Road",
            "coordinates": line,
        },
        {
            "id": "sha-9-0",
            "agency": "mdot-sha",
            "level": 3,
            "name": "Davis Mill Road",
            "coordinates": line,
        },
    ]
    path = tmp_path / agency_ratings.FILE_NAME
    path.write_text(json.dumps(rows))
    features, ratings = agency_ratings.load(path)
    way = _way(42, line, name="Davis Mill Road")
    found = agency_ratings.ratings_by_way([way], [(42, line, False)], features, ratings)
    assert sorted(r.agency for r in found[42]) == ["mdot-sha", "moco"]
    assert agency_lts.chosen(found[42]).agency == "moco"


def test_an_internal_only_agency_is_refused(tmp_path):
    import json

    from pipeline import agency_ratings

    path = tmp_path / agency_ratings.FILE_NAME
    path.write_text(
        json.dumps(
            [{"id": "a", "agency": "arlington", "level": 2, "coordinates": [[0, 0], [0, 1]]}]
        )
    )
    with pytest.raises(agency_ratings.AgencyRatingsInvalid):
        agency_ratings.load(path)


def test_no_file_means_no_ratings(tmp_path):
    from pipeline import agency_ratings

    assert agency_ratings.load(tmp_path / "absent.json") == ((), {})


# --- The owner's order end to end: owner and community rows over every agency -----


def _stress_row(way, tier, adjustment_id, **extra):
    from pipeline.overrides import Override

    value = {
        "tier": tier,
        "adjustment_id": adjustment_id,
        "category": "other",
        "visibility": "hidden",
        "annotation_status": "approved",
        "display": "route_only",
        **extra,
    }
    return Override(kind="stress", osm_way_id=way, value=value, reason="r")


def test_an_owner_row_outranks_a_county_avoid_and_keeps_every_rating():
    """Darnestown Rd (the owner, 2026-10-14: "LTS 4" over Montgomery's LTS 5)."""
    import json

    from pipeline import overrides, writers

    rated = agency_lts.apply(FORMULA, [AgencyRating("moco", 5), AgencyRating("mdot-sha", 4)])
    assert rated.tier is Stress.AVOID
    by_way = {5970658: rated}
    applied, _ = overrides.apply_stress(by_way, [_stress_row(5970658, 4, "darnestown-road-lts4")])
    assert applied == 1
    result = by_way[5970658]
    assert result.tier is Stress.LTS4
    held = json.loads(writers._ratings_json(result))
    assert held["used"] == "owner"
    assert held["override"] == {"source": "owner", "name": "Owner", "level": 4}
    assert [a["level"] for a in held["agencies"]] == [5, 4]
    assert held["formula"] == 4


def test_a_community_row_outranks_an_agency_and_says_so():
    import json

    from pipeline import overrides, writers

    by_way = {7: agency_lts.apply(FORMULA, [AgencyRating("moco", 3)])}
    overrides.apply_stress(by_way, [_stress_row(7, 2, "community-quiet-lane", half=True)])
    held = json.loads(writers._ratings_json(by_way[7]))
    assert held["used"] == "community"
    assert held["override"]["level"] == 2.5


def test_a_county_row_loaded_as_an_override_is_the_countys():
    """Montgomery's LTS 5 rows of 2026-10-01 are the county's rating, not the owner's."""
    import json

    from pipeline import overrides, writers

    by_way = {9: agency_lts.apply(FORMULA, [AgencyRating("moco", 5)])}
    overrides.apply_stress(by_way, [_stress_row(9, 5, "moco-lts5-airpark-road")])
    assert json.loads(writers._ratings_json(by_way[9]))["used"] == "moco"


@pytest.mark.parametrize(
    ("adjustment_id", "source"),
    [
        ("moco-lts5-darnestown-road", "moco"),
        ("mdot-sha-us-29", "mdot-sha"),
        ("ddot-k-st", "ddot"),
        ("community-quiet-lane", "community"),
        ("darnestown-road-lts4", "owner"),
        ("edit-12", "owner"),
        (None, "owner"),
    ],
)
def test_whose_rating_an_override_row_is(adjustment_id, source):
    assert agency_lts.adjustment_source(adjustment_id) == source


def test_every_source_has_a_name_the_panel_shows():
    names = {agency_lts.source_name(s) for s in ("moco", "mdot-sha", "ddot", "owner", "community")}
    assert names == {"Montgomery County Planning", "MDOT SHA", "DDOT", "Owner", "Community"}


def test_with_no_agency_rating_the_formula_stands_and_nothing_is_recorded():
    from pipeline import writers

    assert agency_lts.apply(FORMULA, ()) is FORMULA
    assert writers._ratings_json(FORMULA) is None


@pytest.mark.parametrize("level", [1.5, 2.5, 3.5, 4.5])
def test_every_half_step_maps_one_to_one(level):
    result = agency_lts.apply(FORMULA, [AgencyRating("moco", level)])
    assert int(result.tier) + (0.5 if result.half else 0) == level


def test_the_state_rates_where_the_county_does_not():
    result = agency_lts.apply(FORMULA, [AgencyRating("mdot-sha", 2)])
    assert result.tier is Stress.LTS2 and "MDOT SHA" in result.rule


def test_a_state_avoid_under_a_county_rating_takes_the_county():
    """County over state holds at LTS 5 as well: the county's own level is used."""
    result = agency_lts.apply(FORMULA, [AgencyRating("mdot-sha", 5), AgencyRating("moco", 3)])
    assert result.tier is Stress.LTS3


def test_the_rural_floor_never_lowers_an_agency_avoid():
    rated = agency_lts.apply(FORMULA, [AgencyRating("moco", 5)])
    assert rural_floor(rated, {"highway": "unclassified"}, urban=False).tier is Stress.AVOID


# --- The installer: Montgomery's 0.5 is no rating -----------------------------------


def _moco_feature(objectid, level, **props):
    return {
        "type": "Feature",
        "properties": {
            "OBJECTID": objectid,
            "STATUS": "Existing",
            "LTS_EXIST": level,
            "STREET_NAME": "Davis Mill",
            "STREET_TYPE": "Rd",
            **props,
        },
        "geometry": {"type": "LineString", "coordinates": [[-77.2, 39.2], [-77.19, 39.2]]},
    }


def test_the_installer_drops_moco_none_and_keeps_half_steps_and_avoid(tmp_path):
    import importlib.util
    import json
    from collections import Counter

    from rebuild_fixtures import REPO

    spec = importlib.util.spec_from_file_location(
        "install_agency_lts", REPO / "scripts" / "install_agency_lts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    layer = tmp_path / "moco-bicycle-lts"
    layer.mkdir()
    features = [
        _moco_feature(1, 0.5),
        _moco_feature(2, 2.5),
        _moco_feature(3, 5),
        _moco_feature(4, 1, BIKEWAY="Sidepath"),
        _moco_feature(5, 3, STATUS="Proposed"),
    ]
    (layer / "moco-bicycle-lts.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features})
    )
    dropped = Counter()
    rows = list(module.moco(tmp_path, dropped))
    assert {row["id"]: row["level"] for row in rows} == {"moco-2-0": 2.5, "moco-3-0": 5.0}
    assert rows[0]["name"] == "Davis Mill Rd"
    assert dropped["moco: no rating (0.5 'None')"] == 1
