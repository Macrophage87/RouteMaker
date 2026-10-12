"""Ways inside a quarry, a landfill or an industrial area close to bicycles (owner report
2026-10-12: "A marked climb appears to be a quarry, which isn't likely open to the public.
Ensure only public roads open to bikes are marked.").

The Travilah quarry's haul roads were nine OSM ways tagged `highway=track` and nothing else,
inside `landuse=quarry`: open by their own tags, so routable, drawn and carrying a Cat 4
climb. `restricted_areas.works_closures` closes them under "err closed on bike access"
(OWNER-DECISIONS 330), as the military and secured rules close a base's ways.
"""

from __future__ import annotations

import pytest

from pipeline import restricted_areas as ra
from pipeline import trail_closures as tc
from pipeline.extract import Way


def square(west, south, side=0.01):
    ring = [(west, south), (west + side, south), (west + side, south + side), (west, south + side)]
    return ((west, south, west + side, south + side), [ring], [])


QUARRY = ra.named_area(square(-77.23, 39.07), "Travilah Quarry", "w1", "quarry")
LANDFILL = ra.named_area(square(-77.20, 39.07), "", "w2", "landfill")
INDUSTRIAL = ra.named_area(square(-77.17, 39.07), "Test Park", "w3", "industrial")
AREAS = [QUARRY, LANDFILL, INDUSTRIAL]


def inside(area, d=0.004):
    (west, south, _e, _n), _o, _i = area
    lon, lat = west + 0.003, south + 0.005
    return [(lon, lat), (lon + d / 2, lat), (lon + d, lat)]


def judged(tags, area=QUARRY, osm_id=1, **kwargs):
    found = ra.works_closures([(osm_id, tags, inside(area))], AREAS, **kwargs)
    return found[0] if found else None


@pytest.mark.parametrize(
    "tags, kind",
    [
        ({"landuse": "quarry"}, ra.WORKS),
        ({"landuse": "landfill"}, ra.WORKS),
        ({"landuse": "industrial"}, ra.WORKS),
        ({"landuse": "commercial"}, None),
        ({"landuse": "residential"}, None),
        # The kinds before it keep their areas: a military quarry is a base's.
        ({"landuse": "military"}, ra.MILITARY),
        ({"amenity": "parking", "landuse": "industrial"}, ra.PARKING),
    ],
)
def test_area_kind(tags, kind):
    assert ra.area_kind(tags) == kind


def test_nist_stays_a_secured_compound_not_a_works_area():
    # NIST, Gaithersburg is `landuse=industrial`, listed by id in SECURED_AREAS.
    assert ra.area_kind({"landuse": "industrial"}, "w47244898") == ra.SECURED


def test_a_quarry_haul_road_with_no_access_tag_closes():
    m = judged({"highway": "track"})
    assert m.closed and m.why == ra.WHY_WORKS
    assert m.installation == "Travilah Quarry (quarry)"


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "track"},
        {"highway": "service"},
        {"highway": "unclassified", "name": "Quarry Road"},
        {"highway": "path"},
        {"highway": "track", "access": "private", "bicycle": "no"},
        {"highway": "track", "access": "customers"},
        {"highway": "track", "access": "destination"},
        {"highway": "track", "motor_vehicle": "private"},
        # Access opened but vehicles kept out, and no bicycle tag: unclear, so closed.
        {"highway": "track", "access": "yes", "vehicle": "no"},
        {"highway": "cycleway", "access": "private"},
        {"highway": "track", "bicycle": "no", "access": "yes"},
    ],
)
def test_every_way_in_a_quarry_or_landfill_closes_unless_its_tags_open_it(tags):
    assert judged(tags).closed
    assert judged(tags, LANDFILL).closed


@pytest.mark.parametrize(
    "tags, why",
    [
        ({"highway": "track", "bicycle": "yes"}, ra.WHY_WORKS_TAGGED_OPEN),
        ({"highway": "track", "bicycle": "permissive"}, ra.WHY_WORKS_TAGGED_OPEN),
        ({"highway": "path", "bicycle": "designated"}, ra.WHY_WORKS_TAGGED_OPEN),
        # A bicycle tag outranks `access`, as OSM reads it.
        ({"highway": "track", "access": "private", "bicycle": "yes"}, ra.WHY_WORKS_TAGGED_OPEN),
        ({"highway": "track", "access": "permissive"}, ra.WHY_WORKS_TAGGED_OPEN),
        ({"highway": "service", "access": "yes"}, ra.WHY_WORKS_TAGGED_OPEN),
        # A cycleway is signed for bicycles by its class.
        ({"highway": "cycleway"}, ra.WHY_WORKS_TAGGED_OPEN),
        ({"highway": "secondary", "ref": "MD 28", "name": "Darnestown Road"}, ra.WHY_PUBLIC_ROUTE),
    ],
)
def test_a_way_its_own_tags_open_stays_open(tags, why):
    m = judged(tags)
    assert not m.closed and m.why == why


def test_an_override_reopens_one():
    tags = {"highway": "track", "bicycle": "yes"}
    assert judged(tags, osm_id=7, reopened={7}).why == ra.WHY_OVERRIDE
    # An override that wrote no bicycle permission does not.
    assert judged({"highway": "track"}, osm_id=7, reopened={7}).closed


@pytest.mark.parametrize(
    "tags, closed",
    [
        # An industrial park's named street is public unless its tags say otherwise.
        ({"highway": "residential", "name": "Industrial Court"}, False),
        ({"highway": "unclassified", "name": "Research Boulevard"}, False),
        ({"highway": "residential", "name": "Plant Road", "access": "private"}, True),
        # Its own drives close: a service road or track, named or not, and an unnamed way.
        ({"highway": "service"}, True),
        ({"highway": "service", "name": "Plant Drive"}, True),
        ({"highway": "track", "name": "Haul Road"}, True),
        ({"highway": "residential"}, True),
        ({"highway": "footway"}, True),
        ({"highway": "service", "bicycle": "yes"}, False),
    ],
)
def test_in_an_industrial_area_only_its_own_drives_close(tags, closed):
    assert judged(tags, INDUSTRIAL).closed is closed


def test_a_way_outside_or_only_touching_is_not_judged():
    outside = [(-77.30, 39.0), (-77.29, 39.0)]
    assert ra.works_closures([(1, {"highway": "track"}, outside)], AREAS) == []
    # Less than half its length inside.
    (west, south, _e, _n), _o, _i = QUARRY
    mostly_out = [(west - 0.008, south + 0.005), (west + 0.002, south + 0.005)]
    assert ra.works_closures([(1, {"highway": "track"}, mostly_out)], AREAS) == []
    # Not a highway, or a way another rule judged.
    assert ra.works_closures([(1, {"waterway": "ditch"}, inside(QUARRY))], AREAS) == []
    assert ra.works_closures([(1, {"highway": "track"}, inside(QUARRY))], AREAS, skip={1}) == []
    assert ra.works_closures([(1, {"highway": "track"}, inside(QUARRY))], []) == []


def test_the_works_reason_comes_after_the_military_and_secured_ones():
    assert tc.ORDER[:3] == (ra.MILITARY_NO_BICYCLE, ra.SECURED_NO_BICYCLE, ra.WORKS_NO_BICYCLE)
    assert ra.WORKS_NO_BICYCLE not in tc.OFFROAD_KEEPS
    coords = inside(QUARRY)
    ways = [
        Way(osm_id=i, tags={"highway": "track"}, node_ids=[1, 2], coordinates=coords)
        for i in (1, 2, 3)
    ]
    nobike = tc.closures(ways, {}, [], military={1}, works={1, 2})
    assert nobike.reasons[1] == ra.MILITARY_NO_BICYCLE
    assert nobike.reasons[2] == ra.WORKS_NO_BICYCLE
    assert nobike.reasons.get(3) != ra.WORKS_NO_BICYCLE


def test_the_map_panel_words_the_reason():
    from core import segment_info

    is_open, words = segment_info.ACCESS_WORDS["works"]
    assert not is_open and "quarry" in words
    assert segment_info.ACCESS_SHORT["works"]
