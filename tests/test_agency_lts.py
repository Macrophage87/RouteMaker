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


def test_internal_only_agencies_are_not_listed():
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
