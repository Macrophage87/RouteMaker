"""The named-corridor fixture and its matcher (OWNER-DECISIONS 286, 294, 295, 296).

The geometry under test is the real North Capitol Street of the 2026-10-03 extract
(tests/data/north_capitol_ways.json: 159 ways, tags and nodes), so what is checked is
the owner's own acceptance table and not a synthetic road.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from routemaker import corridors
from routemaker.stress import Stress, StressResult

DATA = Path(__file__).parent / "data" / "north_capitol_ways.json"
# Connecticut Avenue NW from just south of R St to just north of Calvert St, the same
# extract (OWNER-DECISIONS 408, 409).
CONNECTICUT = Path(__file__).parent / "data" / "connecticut_ways.json"
NORTH_CAPITOL_FILE = corridors.CORRIDORS_DIR / "2026-10-04-owner-north-capitol-underpasses.json"

# The owner's targets (see scripts/analysis/arterial_verify.py for how they were derived
# from ARTERIAL-CAL-r0 section 5.4 and its two fixes).
FIRST_THROUGH_AVOID = {
    130772891, 920784194, 296374855, 50753931, 296374852, 516193840,
    516193841, 516193839, 130772888, 695842754,
}  # fmt: skip
TRIMMED_AT_GRADE = {
    1306065346, 1355134125, 516193842, 1306065345, 1355134128, 1320069049, 397300798,
}  # fmt: skip
FIRST_SIDES_LTS4 = {
    397303406, 50228155, 918453671, 1280512687, 918340140, 468472150, 503077369,
    1112231796, 468472149, 362659445, 50228568, 930215092,
}  # fmt: skip
SECOND_THROUGH_LTS4 = {
    507273044, 130772889, 122080103, 122080102, 122080106, 122080105, 122080104,
    122079298, 122080107, 122079297, 122079299, 130772880, 122079300,
}  # fmt: skip
SECOND_SIDES_LTS3 = {1501632583, 50753962, 1501632581, 50753965, 422355425}


@dataclass
class W:
    osm_id: int
    tags: dict
    coordinates: list = field(default_factory=list)


def north_capitol() -> list[W]:
    return [W(w["id"], w["tags"], w["coords"]) for w in json.loads(DATA.read_text())]


def nc() -> corridors.Corridor:
    """North Capitol Street's corridor, the one these tests' geometry is."""
    return next(c for c in corridors.load() if c.id == "north-capitol-st")


def classify_all(ways, tier=3):
    return {w.osm_id: StressResult(Stress(tier), "mixed traffic, 25 mph") for w in ways}


def apply(ways, **kwargs):
    stress = classify_all(ways)
    report = corridors.apply([nc()], ways, stress, **kwargs)
    return stress, report


def tiers(stress, ids):
    return {i: int(stress[i].tier) for i in ids}


# --- The fixture ------------------------------------------------------------


def test_the_fixture_loads_and_every_entry_carries_the_owners_reason() -> None:
    loaded = corridors.load()
    assert [c.id for c in loaded] == ["north-capitol-st", "connecticut-ave-nw-r-to-calvert"]
    corridor = nc()
    assert corridor.streets == {"north capitol street"}
    assert {e.id for e in corridor.entries} == {
        "first-underpass-through",
        "first-underpass-sides",
        "second-underpass-through",
        "second-underpass-sides",
    }
    for entry in corridor.entries:
        assert "owner" in entry.reason.lower(), entry.id
        assert entry.evidence.strip(), entry.id
    assert "OWNER-DECISIONS 284" in corridor.reason and "294" in corridor.reason


def test_the_tiers_the_fixture_sets() -> None:
    by_id = {e.id: e.tier for e in nc().entries}
    assert by_id == {
        "first-underpass-through": 5,
        "first-underpass-sides": 4,
        "second-underpass-through": 4,
        "second-underpass-sides": 3,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(version=2),
        lambda d: d.update(corridors=[]),
        lambda d: d["corridors"][0].update(streets=[]),
        lambda d: d["corridors"][0].update(axis=[[0, 0]]),
        lambda d: d["corridors"][0].update(axis=[[1, 1], [1, 1]]),
        lambda d: d["corridors"][0].update(reason=""),
        lambda d: d["corridors"][0]["entries"][0].update(reason=" "),
        lambda d: d["corridors"][0]["entries"][0].update(evidence=""),
        lambda d: d["corridors"][0]["entries"][0].update(tier=6),
        lambda d: d["corridors"][0]["entries"][0].update(tier=True),
        lambda d: d["corridors"][0]["entries"][0].update(role="middle"),
        lambda d: d["corridors"][0]["entries"][0].update(along_m=[10, 5]),
        lambda d: d["corridors"][0]["entries"][0].update(id=d["corridors"][0]["entries"][1]["id"]),
        # Two through entries that overlap along the axis would both claim a way.
        lambda d: d["corridors"][0]["entries"][2].update(along_m=[500, 2000]),
        lambda d: d["corridors"][0].update(through_max_offset_m=30),
    ],
)
def test_a_malformed_file_is_refused(mutate) -> None:
    path = NORTH_CAPITOL_FILE
    document = copy.deepcopy(json.loads(path.read_text()))
    mutate(document)
    with pytest.raises(corridors.CorridorRefused):
        corridors.parse(document)


# --- The owner's acceptance table -------------------------------------------


def test_north_capitol_matches_the_owners_targets() -> None:
    stress, report = apply(north_capitol())
    assert tiers(stress, FIRST_THROUGH_AVOID) == dict.fromkeys(FIRST_THROUGH_AVOID, 5)
    assert tiers(stress, FIRST_SIDES_LTS4) == dict.fromkeys(FIRST_SIDES_LTS4, 4)
    assert tiers(stress, SECOND_THROUGH_LTS4) == dict.fromkeys(SECOND_THROUGH_LTS4, 4)
    assert tiers(stress, SECOND_SIDES_LTS3) == dict.fromkeys(SECOND_SIDES_LTS3, 3)
    assert not report.unmatched_entries


def test_the_side_lane_tagged_two_lanes_is_a_side_lane_not_avoid() -> None:
    """Way 468472149 (decision 295's miss) is tagged lanes=2 and is the western outer
    side lane: by where it lies, it is LTS 4. Way 930215092, the same on the east side,
    is the same case the study had left as Avoid."""
    ways = {w.osm_id: w for w in north_capitol()}
    assert ways[468472149].tags["lanes"] == "2" and ways[930215092].tags["lanes"] == "2"
    stress, _ = apply(list(ways.values()))
    assert int(stress[468472149].tier) == 4
    assert int(stress[930215092].tier) == 4


def test_the_first_clusters_avoid_stops_about_100_m_short_of_the_old_north_end() -> None:
    """The seven through ways of the study's northern tail keep their rating."""
    ways = north_capitol()
    stress, _ = apply(ways)
    assert tiers(stress, TRIMMED_AT_GRADE) == dict.fromkeys(TRIMMED_AT_GRADE, 3)
    by_id = {w.osm_id: w for w in ways}
    lengths = corridors_lengths(by_id, TRIMMED_AT_GRADE)
    # Both carriageways: 93 m each, "about 100 m".
    assert 170 < lengths < 200, lengths


def corridors_lengths(by_id, ids) -> float:
    from pipeline import conflation

    return sum(conflation._length_m(by_id[i].coordinates) for i in ids)


def test_the_at_grade_parts_keep_their_current_rating() -> None:
    """Decision 296: only the named underpasses change; every other way of the street is
    left exactly as the classifier rated it."""
    ways = north_capitol()
    covered = FIRST_THROUGH_AVOID | FIRST_SIDES_LTS4 | SECOND_THROUGH_LTS4 | SECOND_SIDES_LTS3
    stress, _ = apply(ways)
    others = [w.osm_id for w in ways if w.osm_id not in covered | TRIMMED_AT_GRADE]
    assert others
    assert all(int(stress[i].tier) == 3 for i in others)
    # And a tier that is not 3 is left alone too: the rating is the classifier's.
    mixed = {
        w.osm_id: StressResult(Stress.LTS4 if i % 2 else Stress.LTS2, "x")
        for i, w in enumerate(ways)
    }
    before = {i: int(r.tier) for i, r in mixed.items()}
    corridors.apply([nc()], ways, mixed)
    assert all(int(mixed[i].tier) == before[i] for i in others)


def test_the_rule_names_itself_and_says_nothing_else_changed() -> None:
    ways = north_capitol()
    stress, report = apply(ways)
    assert stress[130772891].rule == "named corridor: north-capitol-st, first-underpass-through"
    # Sides at LTS 3 were already 3: matched, and left with the classifier's own rule.
    assert stress[1501632583].rule == "mixed traffic, 25 mph"
    assert stress[1501632583].tier is Stress.LTS3
    assert len(report.applied) > len(report.changed)
    assert "re-tiered" in report.summary()


# --- Robust to OSM's changes ------------------------------------------------


def test_it_survives_every_way_id_being_replaced() -> None:
    """The point of matching by geometry: a rebuild after OSM renumbers the ways."""
    ways = north_capitol()
    renumbered = [W(w.osm_id + 9_000_000_000, w.tags, w.coordinates) for w in ways]
    stress, _ = apply(renumbered)
    for ids, tier in (
        (FIRST_THROUGH_AVOID, 5),
        (FIRST_SIDES_LTS4, 4),
        (SECOND_THROUGH_LTS4, 4),
        (SECOND_SIDES_LTS3, 3),
    ):
        assert all(int(stress[i + 9_000_000_000].tier) == tier for i in ids)


def test_it_survives_a_way_being_split() -> None:
    """Way 130772888 (146 m, a first-underpass through lane) split in two at a new node
    gives two ways that are both Avoid."""
    ways = north_capitol()
    target = next(w for w in ways if w.osm_id == 130772888)
    (lon0, lat0), (lon1, lat1) = target.coordinates[0], target.coordinates[-1]
    middle = [(lon0 + lon1) / 2, (lat0 + lat1) / 2]
    halves = [
        W(7_000_000_001, target.tags, [target.coordinates[0], middle]),
        W(7_000_000_002, target.tags, [middle, target.coordinates[-1]]),
    ]
    rest = [w for w in ways if w.osm_id != 130772888]
    stress, _ = apply([*rest, *halves])
    assert int(stress[7_000_000_001].tier) == 5 and int(stress[7_000_000_002].tier) == 5


def test_a_way_merged_across_a_boundary_goes_with_most_of_its_length() -> None:
    """Each way takes the entry holding at least half of it: 130772888 (146 m, Avoid)
    merged with the 40 m of 1355134125 beyond the entry's north end is still Avoid, and
    merged the other way round, with the tail dominant, it is not."""
    ways = north_capitol()
    avoid = next(w for w in ways if w.osm_id == 130772888)
    tail = next(w for w in ways if w.osm_id == 1355134125)

    def south_bound(w):
        return sorted(w.coordinates, key=lambda c: -c[1])

    merged = W(7_100_000_000, avoid.tags, [*south_bound(tail), *south_bound(avoid)])
    rest = [w for w in ways if w.osm_id not in (130772888, 1355134125)]
    stress, _ = apply([*rest, merged])
    assert int(stress[7_100_000_000].tier) == 5

    long_tail = W(
        7_100_000_001,
        tail.tags,
        [
            [tail.coordinates[0][0], tail.coordinates[0][1] + 0.0020],
            *south_bound(tail),
            south_bound(avoid)[0],
        ],
    )
    stress, _ = apply([*rest, long_tail])
    assert int(stress[7_100_000_001].tier) == 3


def test_the_quadrant_suffix_is_ignored_and_other_streets_are_untouched() -> None:
    ways = north_capitol()
    names = {w.tags["name"] for w in ways}
    assert {"North Capitol Street Northwest", "North Capitol Street Northeast"} <= names
    # The same geometry under another street's name is not the corridor.
    other = [W(w.osm_id, {**w.tags, "name": "K Street Northwest"}, w.coordinates) for w in ways]
    stress, report = apply(other)
    assert all(int(r.tier) == 3 for r in stress.values())
    assert not report.applied and len(report.unmatched_entries) == 4
    unnamed = [
        W(w.osm_id, {k: v for k, v in w.tags.items() if k != "name"}, w.coordinates) for w in ways
    ]
    assert not apply(unnamed)[1].applied


def test_a_way_across_the_road_or_far_from_the_axis_is_not_matched() -> None:
    ways = north_capitol()
    shifted = [
        W(w.osm_id, w.tags, [[lon + 0.002, lat] for lon, lat in w.coordinates]) for w in ways
    ]
    assert not apply(shifted)[1].applied
    across = W(
        1,
        {"highway": "primary", "name": "North Capitol Street Northwest"},
        [[-77.00910, 38.9070], [-77.00900, 38.9070]],
    )
    assert not apply([across])[1].applied


# Metres to degrees on North Capitol Street (38.907 N).
LAT_M = 111_195.0
LON_M = LAT_M * 0.7783


def first_underpass_way(osm_id, degrees_off, length_m=20.0, north_m=0.0):
    """A way of the street centred on the first underpass's through lanes (about
    773 m along the axis, 4 m off it), `degrees_off` from the axis's direction."""
    lon, lat = -77.009096, 38.906953 + north_m / LAT_M
    dx = length_m / 2 * math.sin(math.radians(degrees_off)) / LON_M
    dy = length_m / 2 * math.cos(math.radians(degrees_off)) / LAT_M
    return W(
        osm_id,
        {"highway": "primary", "name": "North Capitol Street Northwest"},
        [[lon - dx, lat - dy], [lon + dx, lat + dy]],
    )


def test_a_way_60_degrees_off_the_axis_is_not_a_lane_of_it() -> None:
    """The bearing must be within 40 degrees (`DEFAULT_MAX_BEARING_DEG`; the fixture
    does not set it). A way at 60 degrees across the through lanes lies within their
    offset but is a crossing, not a lane; one at 20 degrees is a lane."""
    corridor = nc()
    assert corridor.max_bearing_deg == 40.0
    crossing = first_underpass_way(1, 60)
    placement = corridors.place(corridor, crossing.coordinates)
    assert placement.mean_offset <= corridor.through_max_offset_m, "only the bearing refuses it"
    assert corridors.role_of(corridor, placement) is None
    stress, report = apply([crossing])
    assert int(stress[1].tier) == 3 and not report.applied
    stress, _ = apply([first_underpass_way(1, 20)])
    assert int(stress[1].tier) == 5


def test_a_way_with_less_than_half_its_length_in_the_range_is_not_taken() -> None:
    """At least half (`MIN_SHARE_IN_RANGE`): a through way from 830 m to about 1,197 m
    along the axis has 147 m, 40%, in the first underpass's range (569-977 m) and is
    not Avoid; from 830 m to 1,100 m (54%) it is."""
    corridor = nc()

    def through_way(osm_id, north_end_m):
        south, lat0 = 830.0, 38.907466
        return W(
            osm_id,
            {"highway": "primary", "name": "North Capitol Street Northwest"},
            [[-77.009096, lat0 + (north_end_m - south) / LAT_M], [-77.009096, lat0]],
        )

    long = through_way(1, 1197)
    samples = corridors.place(corridor, long.coordinates).samples
    share = sum(1 for along, _ in samples if 569 <= along <= 977) / len(samples)
    assert 0.35 < share < 0.45
    stress, _ = apply([long])
    assert int(stress[1].tier) == 3
    stress, _ = apply([through_way(2, 1100)])
    assert int(stress[2].tier) == 5


# --- Exemptions ---------------------------------------------------------------


@pytest.mark.parametrize(
    "tags",
    [
        {"cycleway:both": "track"},
        {"cycleway:right": "track", "cycleway:left": "track"},
        {"cycleway:both": "lane", "cycleway:both:separation": "flex_post"},
        {"cycleway:both": "separate"},
        {"cycleway": "separate"},
        # Closed to motor traffic: a path-class facility (`facility.Facility.PATH`).
        {"motor_vehicle": "no"},
    ],
)
def test_a_way_with_a_protected_lane_or_a_separate_bikeway_is_exempt(tags) -> None:
    """Decision 294: "Virginia Ave goes under the road but is fine due to a protected
    bike lane"."""
    ways = north_capitol()
    ways = [
        W(w.osm_id, {**w.tags, **tags} if w.osm_id == 130772891 else w.tags, w.coordinates)
        for w in ways
    ]
    stress, report = apply(ways)
    assert int(stress[130772891].tier) == 3, "left as the classifier rated it"
    hit = next(a for a in report.applied if a.way_id == 130772891)
    assert hit.exempt and hit.before == hit.after == 3
    assert int(stress[920784194].tier) == 5, "its neighbour is not"


def test_a_painted_lane_is_not_an_exemption() -> None:
    """The owner named protected lanes and separate bikeways; paint is neither."""
    ways = [
        W(
            w.osm_id,
            {**w.tags, "cycleway:both": "lane"} if w.osm_id == 130772891 else w.tags,
            w.coordinates,
        )
        for w in north_capitol()
    ]
    stress, _ = apply(ways)
    assert int(stress[130772891].tier) == 5


def test_a_lane_the_agency_recorded_exempts_through_the_tags_the_classifier_read() -> None:
    ways = north_capitol()
    overlay = {
        130772891: {**next(w for w in ways if w.osm_id == 130772891).tags, "cycleway:both": "track"}
    }
    stress, report = apply(ways, tags_of=overlay)
    assert int(stress[130772891].tier) == 3
    assert next(a for a in report.applied if a.way_id == 130772891).exempt


def test_a_bikeway_mapped_beside_the_road_exempts_it() -> None:
    stress, report = apply(north_capitol(), separate_roads={130772891})
    assert int(stress[130772891].tier) == 3
    assert next(a for a in report.applied if a.way_id == 130772891).exempt == (
        "bikeway mapped beside it"
    )


def test_a_trail_class_way_is_never_lifted() -> None:
    ways = north_capitol()
    ways = [
        W(
            w.osm_id,
            {**w.tags, "highway": "cycleway"} if w.osm_id == 130772891 else w.tags,
            w.coordinates,
        )
        for w in ways
    ]
    stress, report = apply(ways)
    assert int(stress[130772891].tier) == 3
    assert next(a for a in report.applied if a.way_id == 130772891).exempt == "trail-class way"


# --- Reporting --------------------------------------------------------------


def test_an_entry_that_matches_no_way_is_reported_not_dropped() -> None:
    ways = [w for w in north_capitol() if w.osm_id not in SECOND_SIDES_LTS3]
    _, report = apply(ways)
    assert report.unmatched_entries == ["north-capitol-st/second-underpass-sides"]
    assert "matched no way" in report.summary()


def test_a_way_the_classifier_never_rated_is_counted_not_invented() -> None:
    ways = north_capitol()
    stress = classify_all(ways)
    del stress[130772891]
    report = corridors.apply([nc()], ways, stress)
    assert report.skipped_unclassified == [130772891]
    assert 130772891 not in stress


def test_a_missing_corridor_folder_is_refused_not_read_as_none(tmp_path, caplog) -> None:
    """ARTERIAL review r0, SF4: the image copies fixtures/, so a missing folder is a
    broken image, and the owner's ratings must not vanish without a word."""
    with pytest.raises(corridors.CorridorRefused, match="does not exist"):
        corridors.load(tmp_path / "nowhere")
    with caplog.at_level("WARNING", logger="routemaker.corridors"):
        assert corridors.load(tmp_path) == []
    assert any("no corridor file" in r.getMessage() for r in caplog.records)


def test_the_report_lists_every_way_and_the_unmatched_entries() -> None:
    ways = [w for w in north_capitol() if w.osm_id not in SECOND_SIDES_LTS3]
    _, report = apply(ways)
    text = report.to_markdown()
    assert "| 130772891 | north-capitol-st | first-underpass-through | through | 3 | 5 |  |" in text
    assert "north-capitol-st/second-underpass-sides" in text


# --- Connecticut Avenue NW, R St to Calvert St (OWNER-DECISIONS 408, 409) -----------


def connecticut() -> list[W]:
    return [W(w["id"], w["tags"], w["coords"]) for w in json.loads(CONNECTICUT.read_text())]


# Both carriageways of the divided part north of R St, and the two-way part over the Taft
# Bridge to Calvert St: the 2026-10-03 build rated every one LTS 3 (posted 25 mph).
CONNECTICUT_R_TO_CALVERT = {
    344730214, 923262510, 321451470, 421801604, 468283860, 130285110, 1047809091,
    520472517, 1330635170, 130285107, 123816447, 1330635168, 123816448, 130285102,
    321452334, 321452335, 321452333, 1525664979, 24792770, 1212403787, 468487076,
    24792772,
}  # fmt: skip
# Just south of R St (Dupont Circle's north side) and north of Calvert St.
CONNECTICUT_OUTSIDE = {123819563, 130285091, 130285106, 1120314163, 130285117, 434982618}


def test_connecticut_is_lts4_from_r_st_to_calvert_st_and_nowhere_else() -> None:
    """409: "I'd say it's LTS4 north of R." The corridor lifts the through lanes from R St
    NW to Calvert St NW, where the classifier's own LTS 4 (30 mph) begins; not the ways
    south of R St and not the side streets that share the name."""
    (corridor,) = [c for c in corridors.load() if c.id == "connecticut-ave-nw-r-to-calvert"]
    assert corridor.streets == {"connecticut avenue"}
    assert "OWNER-DECISIONS 408" in corridor.reason and "409" in corridor.reason
    for entry in corridor.entries:
        assert "owner" in entry.reason.lower() and entry.evidence.strip()
    ways = connecticut()
    ids = {w.osm_id for w in ways}
    assert CONNECTICUT_R_TO_CALVERT <= ids and CONNECTICUT_OUTSIDE <= ids
    stress = classify_all(ways)
    report = corridors.apply([corridor], ways, stress)
    lifted = {a.way_id for a in report.applied if a.after == 4}
    assert lifted == CONNECTICUT_R_TO_CALVERT
    assert all(int(stress[i].tier) == 3 for i in ids - CONNECTICUT_R_TO_CALVERT)
    assert not report.unmatched_entries
    # A way already at LTS 4 stays there.
    stress = classify_all(ways, tier=4)
    corridors.apply([corridor], ways, stress)
    assert {int(stress[i].tier) for i in CONNECTICUT_R_TO_CALVERT} == {4}
