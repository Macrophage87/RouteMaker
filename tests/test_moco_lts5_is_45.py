"""Montgomery County Planning's LTS 5 is our LTS 4.5, urban and rural alike (the owner,
2026-10-19: "5 in our case means technically legal, but not a real option. MoCo's mean very
high stress, what our 4.5 means."; and of Darnestown Road at Dawsonville: "While it can be
very high stress, it's not a complete No, as there's no real alternatives"). Its LTS 5 rows of
2026-10-01 (`moco-lts5-*`) read the same way; the owner's own rows, MDOT SHA's ban and DDOT's
5 are untouched."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import agency_ratings, overrides, writers
from pipeline.extract import Way
from pipeline.overrides import Override
from routemaker import agency_lts
from routemaker.agency_lts import PROHIBITED_NO_BICYCLE, AgencyRating
from routemaker.stress import Stress, StressResult, classify, rural_floor

FORMULA = StressResult(Stress.LTS4, "mixed traffic, 35 mph or above", ("maxspeed",))
OVERRIDES = Path(__file__).resolve().parents[1] / "fixtures" / "overrides"


def _row(way: int, tier: int, adjustment_id: str) -> Override:
    value = {
        "tier": tier,
        "adjustment_id": adjustment_id,
        "category": "other",
        "visibility": "hidden",
        "annotation_status": "approved",
        "display": "route_only",
    }
    return Override(kind="stress", osm_way_id=way, value=value, reason="r")


def _step(result) -> float:
    adjustment = getattr(result, "adjustment", None)
    half = adjustment.half if adjustment is not None else result.half
    return int(result.tier) + (0.5 if half else 0.0)


@pytest.mark.parametrize("urban", [False, True])
def test_a_county_5_is_45_on_rural_and_urban_ways(urban):
    rated = agency_lts.apply(FORMULA, [AgencyRating("moco", 5)])
    result = rural_floor(rated, {"highway": "primary"}, urban=urban)
    assert _step(result) == 4.5
    # The county's own number is kept for the road panel.
    assert [r.level for r in result.agency_ratings] == [5]


def test_the_county_5_beats_the_states_lower_level_and_reads_as_45():
    result = agency_lts.apply(FORMULA, [AgencyRating("mdot-sha", 3), AgencyRating("moco", 5)])
    assert _step(result) == 4.5
    assert result.rule.endswith(f", {agency_lts.READ_AS_REASON}")


def test_ddot_5_stays_avoid_and_wins_a_tie_with_the_county_5():
    assert _step(agency_lts.apply(FORMULA, [AgencyRating("ddot", 5)])) == 5
    # Two local agencies at one line: the higher level as the map uses it, DDOT's Avoid.
    pick = agency_lts.chosen([AgencyRating("moco", 5), AgencyRating("ddot", 5)])
    assert pick.agency == "ddot"


def test_mdot_5_still_closes_the_way():
    line = [(-77.37 + i * 0.001, 39.12) for i in range(3)]
    way = Way(1, {"highway": "primary"}, [0, 1, 2], line)
    rated = {1: (AgencyRating("moco", 5), AgencyRating("mdot-sha", 5))}
    prohibited = agency_ratings.prohibited_ways(rated)
    added, _rows = agency_ratings.prohibited_closures([way], prohibited, {}, set())
    assert added == {1: PROHIBITED_NO_BICYCLE}
    assert agency_lts.map_level("mdot-sha", 5) == 5


def test_a_county_row_loaded_as_an_override_is_45():
    by_way = {9: agency_lts.apply(FORMULA, [AgencyRating("moco", 5)])}
    applied, _ = overrides.apply_stress(by_way, [_row(9, 5, "moco-lts5-ridge-road")])
    assert applied == 1
    result = by_way[9]
    assert (result.tier, result.adjustment.half, _step(result)) == (Stress.LTS4, True, 4.5)
    held = json.loads(writers._ratings_json(result))
    assert held["used"] == "moco"
    assert held["override"]["level"] == 4.5


@pytest.mark.parametrize("adjustment_id", ["darnestown-road-lts4", "edit-12", "community-x"])
def test_owner_and_community_rows_keep_their_own_level(adjustment_id):
    by_way = {9: FORMULA}
    overrides.apply_stress(by_way, [_row(9, 5, adjustment_id)])
    assert _step(by_way[9]) == 5


def test_every_county_row_in_the_fixture_loads_as_45():
    rows = json.loads((OVERRIDES / "2026-10-01-owner-moco-lts5-avoid.json").read_text())["rows"]
    county = [r for r in rows if r["value"]["adjustment_id"].startswith("moco-lts5-")]
    assert county
    for row in county:
        override = Override(kind="stress", osm_way_id=row["osm_way_id"], value=row["value"])
        adjustment = overrides.stress_adjustment(override, Stress.LTS3)
        assert adjustment.step == 4.5, row["value"]["adjustment_id"]


def test_the_owners_darnestown_rows_stay_lts4():
    """Ways 5970658, 697630700, 222928109, 92183771 and 92183773 (the owner, 2026-10-14)."""
    rows = json.loads((OVERRIDES / "2026-10-14-owner-darnestown-road.json").read_text())["rows"]
    assert {r["osm_way_id"] for r in rows} == {5970658, 697630700, 222928109, 92183771, 92183773}
    for row in rows:
        by_way = {row["osm_way_id"]: agency_lts.apply(FORMULA, [AgencyRating("moco", 5)])}
        override = Override(kind="stress", osm_way_id=row["osm_way_id"], value=row["value"])
        overrides.apply_stress(by_way, [override])
        assert _step(by_way[row["osm_way_id"]]) == 4


def test_the_panel_says_the_county_rates_it_5_and_the_map_uses_45():
    from core import segment_info

    rule = agency_lts.apply(FORMULA, [AgencyRating("moco", 5)]).rule
    assert segment_info.rule_words(rule) == (
        "Rated LTS 5 by Montgomery County Planning, which means very high stress: LTS 4.5 here"
    )


@pytest.mark.parametrize(
    "tags,side_path",
    [
        ({"highway": "primary", "expressway": "yes", "maxspeed": "55 mph"}, False),
        ({"highway": "primary", "bicycle": "use_sidepath", "maxspeed": "40 mph"}, True),
    ],
)
def test_a_county_5_never_lowers_the_formulas_own_avoid(tags, side_path):
    # An urban expressway posted 50 mph or more, and a side path's road, are Avoid by our own
    # rule; the county's 5 agrees with that, so it does not lower them to 4.5.
    formula = classify(tags, urban=True, side_path=side_path)
    assert formula.tier is Stress.AVOID
    result = agency_lts.apply(formula, [AgencyRating("moco", 5)])
    assert result.tier is Stress.AVOID and not result.half
    assert result.rule == formula.rule
    assert result.agency_ratings == (AgencyRating("moco", 5),)


@pytest.mark.parametrize("with_rating", [False, True])
def test_a_county_row_never_lowers_the_formulas_own_avoid(with_rating):
    # As `agency_lts.apply`: a `moco-lts5-*` row read as 4.5 keeps our own Avoid, with or
    # without the county's rating on the way; the row is still the one that set it.
    formula = classify(
        {"highway": "primary", "expressway": "yes", "maxspeed": "55 mph"}, urban=True
    )
    assert formula.tier is Stress.AVOID
    way = agency_lts.apply(formula, [AgencyRating("moco", 5)]) if with_rating else formula
    by_way = {9: way}
    applied, _ = overrides.apply_stress(by_way, [_row(9, 5, "moco-lts5-ridge-road")])
    assert applied == 1
    result = by_way[9]
    assert result.tier is Stress.AVOID and _step(result) == 5
    assert result.adjustment.adjustment_id == "moco-lts5-ridge-road"


def test_a_county_row_on_a_formula_avoid_set_lower_by_an_agency_keeps_avoid():
    # The county's own 4 replaced the formula's Avoid; its LTS 5 row still agrees with our rule.
    formula = classify(
        {"highway": "primary", "expressway": "yes", "maxspeed": "55 mph"}, urban=True
    )
    by_way = {9: agency_lts.apply(formula, [AgencyRating("moco", 4)])}
    assert by_way[9].tier is Stress.LTS4
    overrides.apply_stress(by_way, [_row(9, 5, "moco-lts5-ridge-road")])
    assert _step(by_way[9]) == 5


def test_a_county_4_still_sets_the_level_on_an_avoid_road():
    # Only a level read as a lower one keeps the formula's Avoid; the county's own 4 decides.
    formula = classify({"highway": "primary", "expressway": "yes", "maxspeed": "55 mph"})
    assert agency_lts.apply(formula, [AgencyRating("moco", 4)]).tier is Stress.LTS4


def test_the_painted_lane_report_uses_45():
    result = agency_lts.apply(FORMULA, [AgencyRating("moco", 5)])
    row = agency_lts.painted_lane_row(1, "Darnestown Rd", "MD", result)
    assert row["agency_level"] == "4.5" and row["differs"] == "yes"
