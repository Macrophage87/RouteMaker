"""Roads whose motor traffic is barred or limited are low stress
(`routemaker.stress.motor_restriction`).

The owner, 2026-10-06: "The WB&A trail has a section that parallels a very quiet
road, but is marked LTS4 here" (OWNER-DECISIONS, "Record of owner words used in
444/445"; approved as 444). Bragers Road (way 11507607) carries the WB&A Trail
near Patuxent Rd / Conway Rd and is closed to the public's cars, but it read
LTS 4 from the 35 mph default speed of an unclassified road with nothing posted.
Stress only: whether a bicycle may ride a way is the access rules' alone.
"""

from __future__ import annotations

import pytest

from routemaker.stress import Stress, classify, motor_restriction

# Way 11507607 as the 2026-10-03 extract tags it.
BRAGERS_ROAD = {
    "highway": "unclassified",
    "access": "private",
    "motor_vehicle": "private",
    "bicycle": "designated",
    "foot": "designated",
    "railway": "abandoned",
    "surface": "asphalt",
    "name": "Bragers Road",
}


@pytest.mark.parametrize("urban", [True, False])
def test_bragers_road_is_low_stress(urban) -> None:
    result = classify(BRAGERS_ROAD, urban=urban, jurisdiction="MD")
    assert result.tier is Stress.LTS2
    assert "35 mph" not in result.rule
    assert "motor_vehicle=private" in result.rule
    assert result.speed_mph is None, "the default speed is not stated as fact"


def test_without_the_restriction_it_read_lts_4() -> None:
    open_road = {k: v for k, v in BRAGERS_ROAD.items() if k not in ("access", "motor_vehicle")}
    assert classify(open_road, urban=False, jurisdiction="MD").tier is Stress.LTS4


@pytest.mark.parametrize(
    ("tags", "tier"),
    [
        ({"motor_vehicle": "no"}, Stress.LTS1),
        ({"motor_vehicle": "agricultural"}, Stress.LTS1),
        ({"motor_vehicle": "forestry"}, Stress.LTS1),
        ({"vehicle": "no", "bicycle": "yes"}, Stress.LTS1),
        ({"motorcar": "no"}, Stress.LTS1),
        ({"motor_vehicle": "private"}, Stress.LTS2),
        ({"motor_vehicle": "destination"}, Stress.LTS2),
        ({"motor_vehicle": "permit"}, Stress.LTS2),
        ({"motor_vehicle": "delivery"}, Stress.LTS2),
        ({"access": "private", "bicycle": "yes"}, Stress.LTS2),
        ({"access": "no", "bicycle": "designated"}, Stress.LTS1),
    ],
)
def test_restricted_motor_traffic_caps_the_tier(tags, tier) -> None:
    result = classify({"highway": "unclassified", **tags}, urban=False, jurisdiction="VA")
    assert result.tier is tier, result.rule


def test_the_most_specific_key_decides() -> None:
    tags = {"highway": "unclassified", "motor_vehicle": "private", "motorcar": "yes"}
    assert motor_restriction(tags) is None
    assert classify(tags, urban=False, jurisdiction="VA").tier is Stress.LTS4


@pytest.mark.parametrize(
    "tags",
    [
        # Closed to bicycles as well: there is no ride to state a stress for.
        {"motor_vehicle": "no", "bicycle": "no"},
        {"motor_vehicle": "private", "access": "private"},
        {"access": "private"},
        {"motor_vehicle": "private", "bicycle": "use_sidepath"},
        # bicycle=private (Red Brook Blvd, review of wip/pre-rebuild), and the
        # other values bicycles cannot use (routemaker.facility.BICYCLE_ALLOWED).
        {"motor_vehicle": "private", "bicycle": "private"},
        {"motor_vehicle": "no", "bicycle": "private"},
        {"motor_vehicle": "private", "bicycle": "dismount"},
        {"motor_vehicle": "no", "bicycle": "destination"},
        # vehicle covers bicycles: with no bicycle tag, vehicle=no/private closes
        # the road to them (Broad Creek Church Rd, vehicle=no).
        {"vehicle": "no"},
        {"vehicle": "private"},
        {"motor_vehicle": "no", "vehicle": "private"},
        {"vehicle": "agricultural"},
        # Open to motor traffic.
        {"motor_vehicle": "yes"},
        {"access": "yes"},
        {},
    ],
)
def test_no_cap_where_bicycles_are_barred_or_traffic_is_open(tags) -> None:
    assert motor_restriction({"highway": "unclassified", **tags}) is None


@pytest.mark.parametrize(
    "tags",
    [
        {"bicycle": "private", "motor_vehicle": "private"},
        {"vehicle": "no"},
    ],
)
def test_a_road_closed_to_bicycles_keeps_the_tables_tier(tags) -> None:
    """OWNER-DECISIONS 444: the cap is skipped where the way is closed to bicycles."""
    road = {"highway": "unclassified", **tags}
    open_road = {"highway": "unclassified"}
    assert (
        classify(road, urban=False, jurisdiction="VA").tier
        is classify(open_road, urban=False, jurisdiction="VA").tier
    )


@pytest.mark.parametrize(
    ("tags", "tier"),
    [
        # A bicycle tag that keeps bicycles on the road reopens it under vehicle=no.
        ({"vehicle": "no", "bicycle": "designated"}, Stress.LTS1),
        ({"vehicle": "private", "bicycle": "permissive"}, Stress.LTS2),
        # A public vehicle value does not close it; the motor key decides.
        ({"vehicle": "yes", "motor_vehicle": "private"}, Stress.LTS2),
    ],
)
def test_a_bicycle_tag_that_keeps_bicycles_on_it_still_caps(tags, tier) -> None:
    result = classify({"highway": "unclassified", **tags}, urban=False, jurisdiction="VA")
    assert result.tier is tier, result.rule


def test_a_motorway_is_never_capped() -> None:
    assert motor_restriction({"highway": "motorway", "motor_vehicle": "private"}) is None


def test_it_only_ever_lowers() -> None:
    quiet = {"highway": "residential", "motor_vehicle": "private", "maxspeed": "15 mph"}
    assert classify(quiet, jurisdiction="DC").tier is Stress.LTS1


def test_a_posted_limit_above_30_raises_the_cap() -> None:
    tags = {"highway": "unclassified", "motor_vehicle": "private", "maxspeed": "40 mph"}
    result = classify(tags, urban=False, jurisdiction="VA")
    assert result.tier is Stress.LTS3
    assert "posted 40 mph" in result.rule


def test_a_posted_limit_of_exactly_30_does_not_raise_the_cap() -> None:
    tags = {"highway": "unclassified", "motor_vehicle": "private", "maxspeed": "30 mph"}
    open_road = {k: v for k, v in tags.items() if k != "motor_vehicle"}
    assert classify(open_road, urban=False, jurisdiction="VA").tier > Stress.LTS2
    result = classify(tags, urban=False, jurisdiction="VA")
    assert result.tier is Stress.LTS2, result.rule
    assert "posted 30 mph" in result.rule


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        # bicycle=official keeps bicycles on an access=private road, as designated does.
        ({"access": "private", "bicycle": "official"}, (Stress.LTS2, "access=private")),
        # access=public is a public value: with no bicycle tag the motor key decides.
        ({"access": "public", "motor_vehicle": "private"}, (Stress.LTS2, "motor_vehicle=private")),
        # access=destination is not: with no bicycle tag the road is closed to bicycles too.
        ({"access": "destination"}, None),
        ({"access": "destination", "motor_vehicle": "private"}, None),
    ],
)
def test_the_access_values_that_keep_bicycles_on(tags, expected) -> None:
    assert motor_restriction({"highway": "unclassified", **tags}) == expected


def test_a_traffic_count_keeps_the_tables() -> None:
    result = classify(
        BRAGERS_ROAD, aadt=12000, aadt_source="MDOT SHA", urban=False, jurisdiction="MD"
    )
    assert result.tier is Stress.LTS4


def test_rough_still_floors_a_closed_road() -> None:
    tags = {"highway": "track", "motor_vehicle": "no", "tracktype": "grade5"}
    assert classify(tags, urban=False, jurisdiction="VA").tier is Stress.LTS2


def test_the_tags_are_untouched() -> None:
    """Stress only: classify reads the tags and writes no access."""
    tags = dict(BRAGERS_ROAD)
    classify(tags, urban=False, jurisdiction="MD")
    assert tags == BRAGERS_ROAD
