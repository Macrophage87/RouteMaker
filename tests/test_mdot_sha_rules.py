"""The owner's rules over MDOT SHA's statewide LTS (`routemaker.mdot_sha_rules`, 2026-10-30)."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from core import segment_info
from pipeline import agency_ratings, writers
from routemaker import agency_lts, mdot_sha_rules
from routemaker.agency_lts import AgencyRating
from routemaker.mdot_sha_rules import ENABLED, Stretch, read_as
from routemaker.stress import Stress, StressResult

FIRST = "16000MD00410--1-----"
SECOND = "16000MD00410--2-----"
CITY = "24000MU01234--1-----"


def _stretch(**overrides) -> Stretch:
    base = dict(
        route_id=FIRST,
        level=4.0,
        functional_class=5,
        speed_mph=35,
        speed_assumed=True,
        lanes=2,
        shoulder_ft=0,
        bike_facility=None,
        aadt=None,
        urban=True,
    )
    return Stretch(**(base | overrides))


@pytest.mark.parametrize(
    "overrides, expected",
    [
        # A two-lane collector where SHA assumed 35 mph: Montgomery's 3; 3.5 at 10-15k a day.
        ({}, (3.0, "collector-assumed-35")),
        ({"aadt": 12_000}, (3.5, "collector-assumed-35")),
        ({"aadt": 16_000}, None),
        ({"speed_assumed": False}, None),
        ({"route_id": CITY}, (3.0, "city-collector")),
        # A two-lane street at 30 mph or less: 2.5 under 7,500 a day, 3 to 15,000.
        ({"speed_mph": 30, "speed_assumed": False, "aadt": 5_900}, (2.5, "slow-street")),
        ({"speed_mph": 30, "speed_assumed": False, "aadt": 9_000}, (3.0, "slow-street")),
        # Four lanes at 30-45 mph, or two lanes posted 40-45, rated 3 or less: 4.
        ({"level": 2.0, "lanes": 4, "aadt": 32_000}, (4.0, "multilane-or-40")),
        ({"level": 2.0, "lanes": 4, "bike_facility": "Standard"}, (3.5, "multilane-or-40")),
        ({"level": 3.0, "speed_mph": 40, "speed_assumed": False}, (4.0, "multilane-or-40")),
        # A two-lane road with a painted lane at 40 mph keeps SHA's 3 (MD 450; 2026-10-31).
        (
            {"level": 3.0, "speed_mph": 40, "speed_assumed": False, "bike_facility": "Standard"},
            None,
        ),
        # Only that case: at 45 mph, or rated lower, the painted lane still lifts.
        (
            {"level": 3.0, "speed_mph": 45, "speed_assumed": False, "bike_facility": "Standard"},
            (3.5, "multilane-or-40"),
        ),
        (
            {"level": 2.0, "speed_mph": 40, "speed_assumed": False, "bike_facility": "Standard"},
            (3.5, "multilane-or-40"),
        ),
        ({"level": 3.0, "speed_mph": 40}, None),
        # A 35 mph road SHA rated 2 for its shoulder: no shoulder credit.
        ({"level": 2.0, "shoulder_ft": 8}, (3.0, "shoulder-credit")),
        ({"level": 2.0, "shoulder_ft": 8, "aadt": 20_000}, (4.0, "shoulder-credit")),
        ({"level": 2.0, "shoulder_ft": 8, "bike_facility": "Standard"}, None),
        # The owner's 1st Street rule: 25 mph at 5,000-15,000 a day is 2.5, not with paint.
        (
            {"level": 1.0, "speed_mph": 25, "aadt": 7_000, "functional_class": 7},
            (2.5, "busy-residential"),
        ),
        ({"level": 1.0, "speed_mph": 25, "aadt": 3_000, "functional_class": 7}, None),
        (
            {"level": 1.0, "speed_mph": 25, "aadt": 7_000, "bike_facility": "Standard"},
            None,
        ),
        # A rural minor collector at 1,500+ a day is 3.5; a quiet one keeps the rural floor.
        (
            {"urban": False, "level": 1.0, "functional_class": 6, "speed_mph": 30, "aadt": 1_800},
            (3.5, "rural-collector"),
        ),
        ({"urban": False, "level": 1.0, "functional_class": 6, "speed_mph": 30, "aadt": 600}, None),
        (
            {"urban": False, "level": 1.0, "functional_class": 7, "speed_mph": 30, "aadt": 1_800},
            None,
        ),
        # A four-lane divided highway posted 55: 4.5, urban or rural; a 2-lane 50 stays 4
        # (the owner's Darnestown call).
        (
            {"functional_class": 3, "lanes": 4, "speed_mph": 55, "speed_assumed": False},
            (4.5, "rural-expressway"),
        ),
        (
            {
                "functional_class": 3,
                "lanes": 4,
                "speed_mph": 55,
                "speed_assumed": False,
                "urban": False,
            },
            (4.5, "rural-expressway"),
        ),
        (
            {
                "functional_class": 3,
                "lanes": 2,
                "speed_mph": 50,
                "speed_assumed": False,
                "urban": False,
            },
            None,
        ),
        # SHA's 5 is a ban and is never read otherwise.
        ({"level": 5.0}, None),
    ],
)
def test_each_rule_reads_shas_level_as_montgomery_would(overrides, expected):
    assert read_as(_stretch(**overrides)) == expected


@pytest.mark.parametrize(
    "overrides, expected",
    [
        # 3.5 runs to 15,000 a day inclusive, as the table says.
        ({"aadt": 15_000}, (3.5, "collector-assumed-35")),
        ({"level": 2.0, "shoulder_ft": 8, "aadt": 15_000}, (3.5, "shoulder-credit")),
        ({"level": 2.0, "lanes": 4, "bike_facility": "PROTECTED"}, None),
    ],
)
def test_the_edges_follow_the_table(overrides, expected):
    assert read_as(_stretch(**overrides)) == expected


def test_a_reading_of_shas_level_sets_the_review_spread():
    from core import stress_review

    held = {
        "formula": 2,
        "agencies": [{"agency": "mdot-sha", "name": "MDOT SHA", "level": 4.0, "read_as": 2.5}],
        "used": "mdot-sha",
    }
    rows = stress_review.rating_sources({"ratings": held})
    sha = next(r for r in rows if r["key"] == "mdot-sha")
    assert sha["level"] == 2.5 and "rated LTS 4" in sha["name"]


def test_a_count_joins_a_record_inventoried_downward():
    module = _installer()
    by_route = {FIRST[:12]: [(0.0, 2.0, 9_000)]}
    assert module.count_for(by_route, FIRST, 1.5, 0.5) == 9_000


def test_a_struck_rule_leaves_shas_level():
    enabled = mdot_sha_rules.ENABLED - {"collector-assumed-35"}
    assert read_as(_stretch(), enabled) is None


def test_every_rule_has_panel_words_without_commas():
    assert all("," not in words for words in mdot_sha_rules.RULE_WORDS.values())
    assert mdot_sha_rules.words("slow-street", 2.5) == (
        "read as LTS 2.5: a two-lane street at 30 mph or less"
    )


def test_a_second_direction_record_pairs_with_its_own_route_beside_it():
    # About 57 ft (17 m) apart: the other carriageway of one road.
    records = {
        "a": (FIRST, [[-76.90, 39.00], [-76.89, 39.00]]),
        "b": (SECOND, [[-76.90, 39.00015], [-76.89, 39.00015]]),
        # A block away (about 330 ft, 100 m): a one-way pair, not one road.
        "c": (SECOND, [[-76.90, 39.0009], [-76.89, 39.0009]]),
        # Another route beside it: never paired.
        "d": ("16000MD00201--2-----", [[-76.90, 39.0001], [-76.89, 39.0001]]),
    }
    assert mdot_sha_rules.pair_second_records(records) == {"b": "a"}


def test_point_in_polygons_honours_holes():
    square = [(0, 0), (4, 0), (4, 4), (0, 4)]
    hole = [(1, 1), (3, 1), (3, 3), (1, 3)]
    polygons = [((0, 0, 4, 4), [square, hole])]
    assert mdot_sha_rules.point_in_polygons((0.5, 0.5), polygons)
    assert not mdot_sha_rules.point_in_polygons((2, 2), polygons)
    assert not mdot_sha_rules.point_in_polygons((5, 5), polygons)


def test_the_map_uses_the_reading_and_the_panel_shows_shas_level_and_why():
    formula = StressResult(Stress.LTS4, "mixed traffic, 35 mph or above", ("maxspeed",))
    note = mdot_sha_rules.words("collector-assumed-35", 3.0)
    rating = AgencyRating("mdot-sha", 4.0, read_as=3.0, note=note)
    result = agency_lts.apply(formula, [rating])
    assert (result.tier, result.half) == (Stress.LTS3, False)
    assert result.rule == f"agency rating: MDOT SHA LTS 4, {note}"
    assert segment_info.rule_words(result.rule).startswith(
        "Rated LTS 4 by MDOT SHA, read as LTS 3: a two-lane collector where SHA assumed 35 mph"
    )
    held = writers._ratings_json(result)
    rows = segment_info.rating_rows({"stress_ratings": held})
    assert rows[0]["value"].startswith("LTS 4, read as LTS 3")


def test_a_county_rating_still_wins_over_a_reading_of_the_states():
    formula = StressResult(Stress.LTS4, "mixed traffic, 35 mph or above", ())
    ratings = [AgencyRating("mdot-sha", 2.0, read_as=4.0, note="x"), AgencyRating("moco", 2.0)]
    result = agency_lts.apply(formula, ratings)
    assert result.tier is Stress.LTS2 and "Montgomery" in result.rule


def test_the_rebuild_reads_a_reading_from_the_installed_file(tmp_path):
    rows = [
        {
            "id": f"{agency}-1-0",
            "agency": agency,
            "level": 4,
            "name": None,
            "coordinates": [[-76.9, 39.0], [-76.901, 39.001]],
        }
        for agency in ("moco", "ddot", "mdot-sha")
    ]
    rows[2] |= {"read_as": 3.0, "note": "read as LTS 3: a test"}
    path = tmp_path / "agency-lts.json"
    path.write_text(json.dumps(rows))
    _features, ratings = agency_ratings.load(path, required=True)
    assert ratings["mdot-sha-1-0"] == AgencyRating(
        "mdot-sha", 4.0, read_as=3.0, note="read as LTS 3: a test"
    )
    rows[2]["read_as"] = 3.25
    path.write_text(json.dumps(rows))
    with pytest.raises(agency_ratings.AgencyRatingsInvalid, match="half step"):
        agency_ratings.load(path, required=True)


def _installer():
    import importlib.util

    from rebuild_fixtures import REPO

    spec = importlib.util.spec_from_file_location(
        "install_agency_lts", REPO / "scripts" / "install_agency_lts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path, features):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def test_the_installer_reads_shas_records_through_the_rules(tmp_path):
    line1 = [[-76.90, 39.00], [-76.89, 39.00]]
    line2 = [[-76.90, 39.00015], [-76.89, 39.00015]]
    common = {
        "FUNCTIONAL_CLASS": 3,
        "SPEED_LIMIT": 40,
        "SPEEDLIMIT_DERIVED": 0,
        "FROMMEASURE": 0.0,
        "TOMEASURE": 1.0,
        "SHOULDER_WD_LT": 0,
        "SHOULDER_WD_RT": 0,
        "BIKE_FACILITY_TYPE": None,
    }
    _write(
        tmp_path / "mdot-lts" / "mdot-lts.geojson",
        [
            {
                "type": "Feature",
                "properties": common
                | {"OBJECTID": 1, "ROUTEID": FIRST, "LTS_ADJUSTED": 3, "NUMBER_THRU_LANES": 4},
                "geometry": {"type": "LineString", "coordinates": line1},
            },
            {
                # The other direction: lanes one way only, no count, rated lower.
                "type": "Feature",
                "properties": common
                | {
                    "OBJECTID": 2,
                    "ROUTEID": SECOND,
                    "LTS_ADJUSTED": 2,
                    "NUMBER_THRU_LANES": 2,
                    "SPEEDLIMIT_DERIVED": 1,
                },
                "geometry": {"type": "LineString", "coordinates": line2},
            },
        ],
    )
    counts = tmp_path / "mdot-sha-aadt.geojson"
    _write(
        counts,
        [
            {
                "type": "Feature",
                "properties": {
                    "ROUTEID": FIRST[:12] + "  01NN",
                    "BEGIN_SECTION": 0.0,
                    "END_SECTION": 2.0,
                    "AADT": 30_000,
                    "LOC_ERROR": "NO ERROR",
                },
                "geometry": None,
            }
        ],
    )
    urban = tmp_path / "urban.geojson"
    ring = [[-77.0, 38.9], [-76.8, 38.9], [-76.8, 39.1], [-77.0, 39.1], [-77.0, 38.9]]
    _write(
        urban,
        [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    )
    module = _installer()
    read = Counter()
    rows = list(module.mdot_sha(tmp_path, Counter(), counts=counts, urban_areas=urban, read=read))
    by_id = {r["id"]: r for r in rows}
    assert by_id["mdot-sha-1-0"]["level"] == 3.0 and by_id["mdot-sha-1-0"]["read_as"] == 4.0
    # The second record takes the first's level, as read.
    assert by_id["mdot-sha-2-0"]["read_as"] == 4.0
    assert by_id["mdot-sha-2-0"]["note"].startswith("read as LTS 4: SHA's record")
    assert read == Counter({"multilane-or-40": 1, "second-record": 1})


def test_the_installer_refuses_the_rules_without_their_inputs(tmp_path):
    module = _installer()
    _write(
        tmp_path / "mdot-lts" / "mdot-lts.geojson",
        [
            {
                "type": "Feature",
                "properties": {"OBJECTID": 1, "LTS_ADJUSTED": 3},
                "geometry": {"type": "LineString", "coordinates": [[-76.9, 39.0], [-76.8, 39.0]]},
            }
        ],
    )
    with pytest.raises(SystemExit, match="--mdot-as-published"):
        list(module.mdot_sha(tmp_path, Counter()))


class TestBusyRuralTwoLane:
    """P7 on SHA-rated roads (the owner, 2026-10-31: "Yes, same rule in MD")."""

    US_15 = dict(
        level=4.0, functional_class=3, speed_mph=55, speed_assumed=False, lanes=2, urban=False
    )

    def test_us_15_reads_the_same_either_side_of_the_potomac(self) -> None:
        from routemaker.stress import classify

        virginia = classify(
            {"highway": "primary", "maxspeed": "55 mph", "lanes": "2"},
            aadt=20_000,
            urban=False,
            jurisdiction="VA",
        )
        maryland = read_as(_stretch(**self.US_15, aadt=20_000))
        assert (virginia.tier, virginia.half) == (Stress.LTS4, True)
        assert maryland == (4.5, "busy-rural-two-lane")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"aadt": 17_999},
            {"aadt": 25_000, "urban": True},
            {"aadt": 25_000, "lanes": 4, "speed_mph": 50},
            {"aadt": 25_000, "lanes": None},
            {"aadt": 25_000, "bike_facility": "Standard"},
            {"aadt": None},
            {"aadt": 25_000, "functional_class": 4},
            {"aadt": 25_000, "level": 3.0},
        ],
    )
    def test_not_below_the_gate_in_town_on_four_lanes_or_rated_lower(self, overrides) -> None:
        found = read_as(_stretch(**(self.US_15 | overrides)))
        assert found is None or found[1] != "busy-rural-two-lane"

    @pytest.mark.parametrize("overrides", [{"lanes": 3}, {"aadt": 18_000}, {"functional_class": 2}])
    def test_three_lanes_the_gate_itself_and_class_2_are_taken(self, overrides) -> None:
        found = read_as(_stretch(**(self.US_15 | {"aadt": 20_000} | overrides)))
        assert found == (4.5, "busy-rural-two-lane")

    def test_it_has_its_own_switch(self) -> None:
        enabled = ENABLED - {"busy-rural-two-lane"}
        assert read_as(_stretch(**self.US_15, aadt=20_000), enabled) is None


def test_the_panel_note_states_the_facts_the_rule_read():
    s = _stretch(**TestBusyRuralTwoLane.US_15, aadt=21_000)
    note = mdot_sha_rules.words("busy-rural-two-lane", 4.5, s)
    assert note == (
        "read as LTS 4.5: a rural two-lane highway carrying 18000 or more cars a day; "
        "SHA's record: rural; 2 lanes; posted 55 mph; 21000 cars a day by SHA's count"
    )
    assert "," not in note
    assumed = mdot_sha_rules.words("collector-assumed-35", 3.0, _stretch())
    assert assumed.endswith("SHA's record: urban; 2 lanes; assumed 35 mph; no count")
    assert "1 lane;" in mdot_sha_rules.facts(_stretch(lanes=1)) + ";"


@pytest.mark.parametrize(
    "overrides, expected",
    [
        # busy-residential: 5,000 to 15,000 a day, both ends taken.
        ({"level": 2.0, "speed_mph": 25, "speed_assumed": False, "aadt": 4_999}, None),
        (
            {"level": 2.0, "speed_mph": 25, "speed_assumed": False, "aadt": 5_000},
            (2.5, "busy-residential"),
        ),
        (
            {"level": 2.0, "speed_mph": 25, "speed_assumed": False, "aadt": 15_000},
            (2.5, "busy-residential"),
        ),
        ({"level": 2.0, "speed_mph": 25, "speed_assumed": False, "aadt": 15_001}, None),
        # slow-street: 3 from 7,500 a day.
        ({"speed_mph": 30, "speed_assumed": False, "aadt": 7_499}, (2.5, "slow-street")),
        ({"speed_mph": 30, "speed_assumed": False, "aadt": 7_500}, (3.0, "slow-street")),
        # rural-collector: from 1,500 a day.
        ({"level": 2.0, "functional_class": 6, "urban": False, "aadt": 1_499}, None),
        (
            {"level": 2.0, "functional_class": 6, "urban": False, "aadt": 1_500},
            (3.5, "rural-collector"),
        ),
    ],
)
def test_the_rules_thresholds_themselves(overrides, expected):
    assert read_as(_stretch(**overrides)) == expected
