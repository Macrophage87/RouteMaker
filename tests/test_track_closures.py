"""A farm or forest track with nothing that says the public may use it closes to bicycles
(owner report 2026-10-21, rural Montgomery County around Dickerson and Barnesville: "there's
some track roads on the rural part that are likely private roads that we can't legally use").

OSM's `highway=track` is a farm or forest road. With no access tag, upstream opens it to
bicycles by class and the stress map drew it as a calm road. `restricted_areas.track_closures`
closes it under "err closed on bike access" (OWNER-DECISIONS 330) but where its own tags open
it, it lies mostly in a park or protected area, it is named or numbered, or it is on a bicycle
or hiking route.
"""

from __future__ import annotations

import pytest

from pipeline import restricted_areas as ra
from pipeline import trail_closures as tc
from pipeline.extract import Way


def square(west, south, side=0.01):
    ring = [(west, south), (west + side, south), (west + side, south + side), (west, south + side)]
    return ((west, south, west + side, south + side), [ring], [])


LITTLE_BENNETT = ra.named_area(square(-77.28, 39.25), "Little Bennett Regional Park", "w2", "")
PARKS = [LITTLE_BENNETT]
(_W, _S, _E, _N), _O, _I = LITTLE_BENNETT
IN_PARK = [(_W + 0.003, _S + 0.005), (_W + 0.007, _S + 0.005)]
FARM = [(-77.42, 39.20), (-77.41, 39.20)]


def judged(tags, osm_id=1, coords=None, **kwargs):
    found = ra.track_closures([(osm_id, tags, coords or FARM)], PARKS, **kwargs)
    return found[0] if found else None


@pytest.mark.parametrize(
    "tags",
    [
        # Dickerson's farm lanes: a track, nothing else, or a surface and a grade.
        {"highway": "track"},
        {"highway": "track", "tracktype": "grade3", "surface": "gravel"},
        {"highway": "track", "surface": "asphalt"},
        # Cars kept off says nothing about the public on foot or on a bicycle.
        {"highway": "track", "motor_vehicle": "no"},
        {"highway": "track", "motor_vehicle": "private"},
        {"highway": "track", "access": "destination"},
        # A trail only for walkers is not a bicycle's.
        {"highway": "track", "foot": "yes"},
    ],
)
def test_a_farm_track_closes(tags):
    m = judged(tags)
    assert m.closed and m.why == ra.WHY_TRACK
    assert m.installation == "track"


@pytest.mark.parametrize(
    "tags, why",
    [
        ({"highway": "track", "bicycle": "yes"}, ra.WHY_TRACK_TAGGED_OPEN),
        ({"highway": "track", "bicycle": "designated"}, ra.WHY_TRACK_TAGGED_OPEN),
        ({"highway": "track", "access": "permissive"}, ra.WHY_TRACK_TAGGED_OPEN),
        ({"highway": "track", "access": "yes"}, ra.WHY_TRACK_TAGGED_OPEN),
        ({"highway": "track", "motor_vehicle": "yes"}, ra.WHY_TRACK_TAGGED_OPEN),
        ({"highway": "track", "foot": "designated"}, ra.WHY_TRACK_TAGGED_OPEN),
        ({"highway": "track", "name": "Old Hundred Road"}, ra.WHY_TRACK_NAMED),
        ({"highway": "track", "ref": "CR 12"}, ra.WHY_PUBLIC_ROUTE),
    ],
)
def test_a_track_its_tags_or_name_call_public_stays_open(tags, why):
    m = judged(tags)
    assert not m.closed and m.why == why


def test_a_track_in_a_park_stays_open():
    m = judged({"highway": "track"}, coords=IN_PARK)
    assert not m.closed and m.why == ra.WHY_TRACK_PARK
    assert m.installation == "Little Bennett Regional Park"
    # Mostly outside: a farm lane that only reaches the park's edge.
    mostly_out = [(_W - 0.008, _S + 0.005), (_W + 0.002, _S + 0.005)]
    assert judged({"highway": "track"}, coords=mostly_out).closed


def test_a_route_relation_and_an_override_reopen_one():
    m = judged({"highway": "track"}, trail_routes={1})
    assert not m.closed and m.why == ra.WHY_TRACK_ROUTE
    m = judged({"highway": "track", "bicycle": "yes"}, reopened={1})
    assert not m.closed and m.why == ra.WHY_OVERRIDE


@pytest.mark.parametrize(
    "tags",
    [
        # The tag rules have these already: hidden as private, or closed by upstream.
        {"highway": "track", "access": "private"},
        {"highway": "track", "access": "no"},
        {"highway": "track", "access": "agricultural"},
        {"highway": "track", "access": "forestry"},
        {"highway": "track", "vehicle": "private"},
        {"highway": "track", "bicycle": "no"},
        {"highway": "track", "bicycle": "private"},
        # Not a track.
        {"highway": "service"},
        {"highway": "path"},
        {"highway": "unclassified"},
    ],
)
def test_ways_the_rule_does_not_judge(tags):
    assert judged(tags) is None


def test_a_way_an_area_rule_judged_is_skipped():
    assert ra.track_closures([(1, {"highway": "track"}, FARM)], PARKS, skip={1}) == []
    assert ra.track_closures([(1, {"highway": "track"}, FARM)], [])[0].closed


def test_the_track_reason_comes_after_the_area_rules():
    assert tc.ORDER[:5] == (
        ra.MILITARY_NO_BICYCLE,
        ra.SECURED_NO_BICYCLE,
        ra.WORKS_NO_BICYCLE,
        ra.GOLF_NO_BICYCLE,
        ra.TRACK_NO_BICYCLE,
    )
    assert ra.TRACK_NO_BICYCLE not in tc.OFFROAD_KEEPS
    ways = [
        Way(osm_id=i, tags={"highway": "track"}, node_ids=[1, 2], coordinates=FARM)
        for i in (1, 2, 3)
    ]
    nobike = tc.closures(ways, {}, [], golf={1}, tracks={1, 2})
    assert nobike.reasons[1] == ra.GOLF_NO_BICYCLE
    assert nobike.reasons[2] == ra.TRACK_NO_BICYCLE
    assert 3 not in nobike.reasons


def test_the_map_panel_words_the_reason():
    from core import segment_info
    from routemaker import facility

    assert facility.bike_access_reason({"highway": "track"}, no_bicycle="track") == "track"
    is_open, words = segment_info.ACCESS_WORDS["track"]
    assert not is_open and "track" in words
    assert segment_info.ACCESS_SHORT["track"] == "private farm track"


def test_a_closed_track_is_not_listed_twice_in_review():
    from routemaker import bike_bans

    assert bike_bans.reason({"highway": "track"}, "track", False) is None


def test_the_report_lists_the_place():
    found = ra.track_closures(
        [(7, {"highway": "track"}, FARM), (8, {"highway": "track"}, IN_PARK)], PARKS
    )
    csv = ra.military_report_csv(found, "place")
    assert csv.splitlines()[0].startswith("way_id,place,")
    assert "Little Bennett Regional Park" in csv and ",closed," in csv and ",open," in csv
