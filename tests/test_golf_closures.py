"""A golf course's cart paths, walks and drives close to bicycles (owner report 2026-10-21,
Woodmont Country Club, Rockville: "Still showing some bike paths on private property. These
are golf courses.").

The course's cart paths were plain `highway=path` ways with no access tag inside
`leisure=golf_course`, so the tag rule for a private golf-cart path (OWNER-DECISIONS 278,
290) missed them and the map drew them as bike paths. `restricted_areas.golf_closures`
closes every way inside a course under "err closed on bike access" (330) but a public street
and its sidewalks, a way its own tags open, a bicycle route and a named trail.
"""

from __future__ import annotations

import pytest

from pipeline import restricted_areas as ra
from pipeline import trail_closures as tc
from pipeline.extract import Way


def square(west, south, side=0.01):
    ring = [(west, south), (west + side, south), (west + side, south + side), (west, south + side)]
    return ((west, south, west + side, south + side), [ring], [])


WOODMONT = ra.named_area(square(-77.14, 39.06), "Woodmont Country Club", "w1", "")
AREAS = [WOODMONT]


def inside(area=WOODMONT, d=0.004):
    (west, south, _e, _n), _o, _i = area
    lon, lat = west + 0.003, south + 0.005
    return [(lon, lat), (lon + d / 2, lat), (lon + d, lat)]


OUTSIDE = [(-77.30, 39.0), (-77.29, 39.0)]


def judged(tags, osm_id=1, coords=None, **kwargs):
    found = ra.golf_closures([(osm_id, tags, coords or inside())], AREAS, **kwargs)
    return found[0] if found else None


@pytest.mark.parametrize(
    "tags, kind",
    [
        ({"leisure": "golf_course"}, ra.GOLF),
        ({"leisure": "golf_course", "access": "private"}, ra.GOLF),
        # A public course a park agency runs is a golf course, not a park.
        ({"leisure": "golf_course", "operator": "National Park Service"}, ra.GOLF),
        ({"leisure": "park"}, ra.PARK),
        ({"leisure": "miniature_golf"}, None),
    ],
)
def test_area_kind(tags, kind):
    assert ra.area_kind(tags) == kind


@pytest.mark.parametrize(
    "tags",
    [
        # Woodmont's cart paths: a plain path, nothing else.
        {"highway": "path"},
        {"highway": "path", "surface": "asphalt"},
        {"highway": "cycleway"},
        {"highway": "footway"},
        {"highway": "service"},
        {"highway": "service", "name": "Clubhouse Drive"},
        {"highway": "track"},
        {"highway": "unclassified"},
        {"highway": "path", "golf": "cartpath", "name": "Cart Path"},
        {"highway": "path", "foot": "yes"},
        {"highway": "path", "bicycle": "no"},
        {"highway": "path", "access": "private", "bicycle": "private"},
        {"highway": "residential", "access": "private"},
    ],
)
def test_a_courses_own_ways_close(tags):
    m = judged(tags)
    assert m.closed
    assert m.installation == "Woodmont Country Club"


@pytest.mark.parametrize(
    "tags, why",
    [
        ({"highway": "path", "bicycle": "designated"}, ra.WHY_GOLF_TAGGED_OPEN),
        ({"highway": "path", "bicycle": "yes", "golf": "cartpath"}, ra.WHY_GOLF_TAGGED_OPEN),
        ({"highway": "service", "access": "yes"}, ra.WHY_GOLF_TAGGED_OPEN),
        ({"highway": "path", "name": "Sligo Creek Trail"}, ra.WHY_GOLF_TRAIL),
        ({"highway": "cycleway", "name": "Rock Creek Trail"}, ra.WHY_GOLF_TRAIL),
        ({"highway": "residential", "name": "Fairway Road"}, ra.WHY_GOLF_STREET),
        ({"highway": "residential"}, ra.WHY_GOLF_STREET),
        ({"highway": "tertiary", "name": "Montrose Road"}, ra.WHY_GOLF_STREET),
        ({"highway": "footway", "footway": "sidewalk"}, ra.WHY_GOLF_STREET),
        ({"highway": "secondary", "ref": "MD 187"}, ra.WHY_PUBLIC_ROUTE),
    ],
)
def test_a_public_way_through_a_course_stays_open(tags, why):
    m = judged(tags)
    assert not m.closed and m.why == why


def test_a_cart_path_never_opens_by_its_name_or_a_route():
    tags = {"highway": "path", "golf": "cartpath", "name": "Back Nine Path"}
    assert judged(tags).why == ra.WHY_GOLF_CARTPATH
    assert judged(tags, bicycle_routes={1}).closed


def test_a_bicycle_route_through_a_course_stays_open():
    m = judged({"highway": "path"}, bicycle_routes={1})
    assert not m.closed and m.why == ra.WHY_GOLF_BICYCLE_ROUTE


def test_an_override_and_ddot_records_reopen_one():
    m = judged({"highway": "path", "bicycle": "yes"}, reopened={1})
    assert not m.closed and m.why == ra.WHY_OVERRIDE
    m = judged({"highway": "service"}, osm_id=9, dc_streets={9})
    assert not m.closed and m.why == ra.WHY_GOLF_DC_STREET


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "path", "golf": "cartpath"},
        {"highway": "service", "golf": "path"},
        {"highway": "path", "golf_cart": "designated"},
    ],
)
def test_a_cart_path_outside_a_mapped_course_still_closes(tags):
    m = judged(tags, coords=OUTSIDE)
    assert m.closed and m.installation == "golf cart path"
    assert ra.golf_closures([(1, tags, OUTSIDE)], [])[0].closed


def test_a_street_carts_may_share_is_not_a_cart_path():
    assert judged({"highway": "residential", "golf_cart": "yes"}, coords=OUTSIDE) is None
    assert judged({"highway": "residential", "golf_cart": "designated"}, coords=OUTSIDE) is None


def test_a_way_outside_or_only_touching_is_not_judged():
    assert judged({"highway": "path"}, coords=OUTSIDE) is None
    (west, south, _e, _n), _o, _i = WOODMONT
    mostly_out = [(west - 0.008, south + 0.005), (west + 0.002, south + 0.005)]
    assert judged({"highway": "path"}, coords=mostly_out) is None
    assert ra.golf_closures([(1, {"waterway": "ditch"}, inside())], AREAS) == []
    assert ra.golf_closures([(1, {"highway": "path"}, inside())], AREAS, skip={1}) == []


def test_the_golf_reason_comes_after_the_site_rules():
    assert tc.ORDER[:4] == (
        ra.MILITARY_NO_BICYCLE,
        ra.SECURED_NO_BICYCLE,
        ra.WORKS_NO_BICYCLE,
        ra.GOLF_NO_BICYCLE,
    )
    assert ra.GOLF_NO_BICYCLE not in tc.OFFROAD_KEEPS
    ways = [
        Way(osm_id=i, tags={"highway": "path"}, node_ids=[1, 2], coordinates=inside())
        for i in (1, 2, 3)
    ]
    nobike = tc.closures(ways, {}, [], works={1}, golf={1, 2})
    assert nobike.reasons[1] == ra.WORKS_NO_BICYCLE
    assert nobike.reasons[2] == ra.GOLF_NO_BICYCLE
    assert nobike.reasons.get(3) != ra.GOLF_NO_BICYCLE


def test_a_closed_cart_path_is_not_drawn_as_a_bike_path():
    from routemaker import facility

    # The path's own tags draw it as a bike path; the closure is what leaves it to the
    # base map (`pipeline.run.map_class_of`: a trail-class way with a closure reason).
    assert facility.map_class({"highway": "path"}) is facility.MapClass.ROAD
    assert facility.bike_access_reason({"highway": "path"}, no_bicycle="golf") == "golf"


def test_the_map_panel_words_the_reason():
    from core import segment_info

    is_open, words = segment_info.ACCESS_WORDS["golf"]
    assert not is_open and "golf" in words
    assert segment_info.ACCESS_SHORT["golf"] == "golf course"


def test_the_report_lists_the_course():
    found = ra.golf_closures([(7, {"highway": "path"}, inside())], AREAS)
    csv = ra.military_report_csv(found, "course")
    assert csv.splitlines()[0].startswith("way_id,course,")
    assert "Woodmont Country Club" in csv and ",closed," in csv
