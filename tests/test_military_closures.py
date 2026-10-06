"""Ways inside a military area are closed to bicycles (owner report 2026-10-05).

The owner planned a route through Joint Base Anacostia-Bolling, down the base's
riverside walkways and parking aisles, which carry no access tag of their own. Under
the standing rule "err closed on bike access" (OWNER-DECISIONS 330) every road and
path inside a military area is closed, on every graph, but for a way whose own tags
give the public a bicycle and a numbered public road; those stay open and are listed
for the owner. The Pentagon reservation, where "There are parts of the pentagon
reservation you can bike to" (the owner, 2026-10-05), closes only its roads.

tests/data/jbab_military.json is the real base: the Joint Base Anacostia Bolling and
Bolling Air Force Base polygons and every highway way of a box over the base's north
end and the streets east of it (I-295, South Capitol St, Malcolm X Ave), from the
Geofabrik District of Columbia extract of 2026-10-03.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import restricted_areas as ra
from pipeline import run
from pipeline import trail_closures as tc
from pipeline.extract import Way
from routemaker import trailaccess

JBAB = Path(__file__).parent / "data" / "jbab_military.json"

# A square base, 0.01 degrees a side, with the Pentagon-like public-edge area beside it.
BASE = ra.named_area(
    (
        (-77.02, 38.84, -77.01, 38.85),
        [[(-77.02, 38.84), (-77.01, 38.84), (-77.01, 38.85), (-77.02, 38.85)]],
        [],
    ),
    "Fort Example",
    "w1",
)
EDGE = ra.named_area(
    (
        (-77.06, 38.86, -77.05, 38.87),
        [[(-77.06, 38.86), (-77.05, 38.86), (-77.05, 38.87), (-77.06, 38.87)]],
        [],
    ),
    "The Pentagon",
    "w916068128",
)


def line(lon, lat, d=0.002):
    return [(lon, lat), (lon + d / 2, lat), (lon + d, lat)]


def closures(ways, areas=(BASE, EDGE)):
    return {m.way_id: m for m in ra.military_closures(ways, list(areas))}


def test_untagged_roads_and_paths_inside_a_base_are_closed_and_perimeter_ways_are_not():
    found = closures(
        [
            (1, {"highway": "service"}, line(-77.018, 38.845)),
            (2, {"highway": "footway", "footway": "sidewalk"}, line(-77.016, 38.846)),
            (3, {"highway": "tertiary", "name": "Defense Boulevard"}, line(-77.018, 38.847)),
            (4, {"highway": "residential", "access": "private"}, line(-77.015, 38.844)),
            # Outside the fence: along the base's edge, and a street just past it.
            (5, {"highway": "primary", "name": "South Capitol Street"}, line(-77.009, 38.845)),
            (6, {"highway": "cycleway"}, [(-77.025, 38.839), (-77.015, 38.839)]),
            # Half in, half out: inside by the INSIDE_FRACTION rule.
            (7, {"highway": "path"}, [(-77.011, 38.845), (-77.009, 38.845)]),
        ]
    )
    assert {w for w, m in found.items() if m.closed} == {1, 2, 3, 4, 7}
    assert 5 not in found and 6 not in found
    assert found[3].why == ra.WHY_NAMED_ROAD, "a named road with no access tag is listed"
    assert found[4].why == ra.WHY_CLOSED
    assert found[1].installation == "Fort Example"


@pytest.mark.parametrize(
    "tags, why",
    [
        ({"highway": "cycleway", "bicycle": "designated"}, ra.WHY_PERMITTED),
        ({"highway": "footway", "bicycle": "yes"}, ra.WHY_PERMITTED),
        ({"highway": "path", "bicycle": "permissive"}, ra.WHY_PERMITTED),
        ({"highway": "service", "access": "permissive"}, ra.WHY_PERMITTED),
        ({"highway": "trunk", "ref": "US 1", "name": "Richmond Highway"}, ra.WHY_PUBLIC_ROUTE),
        ({"highway": "primary", "ref": "SR 611;SR 999"}, ra.WHY_PUBLIC_ROUTE),
        ({"highway": "primary", "ref": "MD 198"}, ra.WHY_PUBLIC_ROUTE),
    ],
)
def test_a_public_permission_or_a_public_route_number_stays_open_and_is_listed(tags, why):
    (m,) = ra.military_closures([(9, tags, line(-77.018, 38.845))], [BASE])
    assert not m.closed and m.why == why


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "service", "access": "permissive", "bicycle": "no"},
        {"highway": "secondary", "ref": "MCB 1", "name": "Russell Road"},
        {"highway": "residential", "ref": "SR 639", "access": "private"},
        {"highway": "primary", "ref": "SR 610", "motor_vehicle": "military"},
        {"highway": "footway", "foot": "yes"},
        {"highway": "service", "access": "destination"},
    ],
)
def test_anything_else_is_closed_err_closed(tags):
    (m,) = ra.military_closures([(9, tags, line(-77.018, 38.845))], [BASE])
    assert m.closed


def test_the_pentagon_reservation_closes_its_roads_and_keeps_its_paths():
    found = closures(
        [
            (1, {"highway": "service"}, line(-77.058, 38.865)),
            (2, {"highway": "tertiary", "name": "North Rotary Road"}, line(-77.058, 38.866)),
            (3, {"highway": "footway"}, line(-77.058, 38.867)),
            (4, {"highway": "pedestrian"}, line(-77.058, 38.868)),
            (
                5,
                {"highway": "tertiary", "name": "Connector Road", "bicycle": "yes"},
                line(-77.058, 38.864),
            ),
            (
                6,
                {"highway": "cycleway", "name": "27 Trail", "bicycle": "yes"},
                line(-77.056, 38.864),
            ),
        ]
    )
    assert {w for w, m in found.items() if m.closed} == {1, 2}
    assert found[3].why == found[4].why == ra.WHY_EDGE_PATH
    assert found[5].why == found[6].why == ra.WHY_PERMITTED


def test_an_ordinary_area_inside_the_reservation_is_closed_whole():
    """The Pentagon building is `military=office` inside the reservation: closed."""
    building = ra.named_area(
        (
            (-77.059, 38.865, -77.054, 38.869),
            [[(-77.059, 38.865), (-77.054, 38.865), (-77.054, 38.869), (-77.059, 38.869)]],
            [],
        ),
        "The Pentagon",
        "r89605",
    )
    (m,) = ra.military_closures(
        [(3, {"highway": "corridor"}, line(-77.058, 38.867))], [EDGE, building]
    )
    assert m.closed


def test_no_military_area_closes_nothing():
    assert ra.military_closures([(1, {"highway": "service"}, line(-77.018, 38.845))], []) == []


def test_the_report_lists_every_way_with_its_reason():
    found = ra.military_closures(
        [
            (1, {"highway": "service"}, line(-77.018, 38.845)),
            (
                2,
                {"highway": "cycleway", "bicycle": "designated", "name": 'The "River" Walk, north'},
                line(-77.016, 38.846),
            ),
        ],
        [BASE],
    )
    text = ra.military_report_csv(found)
    lines = text.splitlines()
    assert lines[0] == "way_id,installation,highway,name,length_m,status,why,tags"
    assert lines[1].startswith("1,Fort Example,service,,") and ",closed," in lines[1]
    assert '"The ""River"" Walk, north"' in lines[2] and ",open," in lines[2]
    summary = ra.military_summary(found)
    assert "1 ways closed" in summary and "1 left open" in summary and "Fort Example" in summary


# --- The real base -------------------------------------------------------------


def jbab():
    data = json.loads(JBAB.read_text())
    areas = []
    for a in data["areas"]:
        outers = [[tuple(p) for p in r] for r in a["outers"]]
        inners = [[tuple(p) for p in r] for r in a["inners"]]
        xs = [p[0] for r in outers for p in r]
        ys = [p[1] for r in outers for p in r]
        areas.append(
            ra.named_area(
                ((min(xs), min(ys), max(xs), max(ys)), outers, inners), a["name"], a["osm"]
            )
        )
    ways = [(w["id"], w["tags"], [tuple(p) for p in w["coords"]]) for w in data["ways"]]
    return areas, ways


def test_joint_base_anacostia_bolling_is_closed_and_its_neighbours_are_not():
    areas, ways = jbab()
    found = closures(ways, areas)
    tags = {w: t for w, t, _ in ways}
    closed = {w for w, m in found.items() if m.closed}
    # The settings' sentinels: two sidewalks and a service road, no access tag.
    assert {193043941, 97677540, 99419868} <= closed
    assert all("access" not in tags[w] for w in (193043941, 97677540, 99419868))
    # The base's own access=private streets are closed under this reason too.
    assert 6055584 in closed or 6055584 not in tags
    # The streets outside the fence: I-295, South Capitol St, Malcolm X Ave.
    for way_id in (50477467, 130772913, 37867118, 105673914):
        assert way_id in tags and way_id not in found
    # Left open, and listed: the sidewalks OSM tags bicycle=yes.
    opened = {w for w, m in found.items() if not m.closed}
    assert opened == {w for w in found if tags[w].get("bicycle") in ra.PUBLIC_BICYCLE}
    assert 97677535 in opened
    assert len(closed) > 500


def test_settings_sentinels_are_the_jbab_ways():
    from config import settings as real

    assert real.REBUILD_SENTINEL_MILITARY_CLOSED_WAYS == (193043941, 97677540, 99419868)


# --- Closed on every graph -----------------------------------------------------


def test_the_military_reason_comes_first_and_no_graph_reopens_it():
    coords = line(-77.018, 38.845)
    ways = [
        # A trail the mountain-bike class would leave open on the off-road graph.
        Way(
            1,
            {"highway": "path", "bicycle": "yes", "surface": "dirt"},
            [10, 11, 12],
            coords,
            [0, 1, 2],
        ),
        Way(2, {"highway": "service"}, [20, 21, 22], coords, [0, 1, 2]),
    ]
    result = tc.closures(ways, {}, [], military={1, 2})
    assert result.reasons == {1: ra.MILITARY_NO_BICYCLE, 2: ra.MILITARY_NO_BICYCLE}
    assert ra.MILITARY_NO_BICYCLE not in tc.OFFROAD_KEEPS
    assert tc.ORDER[0] == ra.MILITARY_NO_BICYCLE
    assert not result.mtb_only()
    # Without the military set, the same trail is the mountain-bike class.
    assert tc.closures(ways, {}, []).reasons == {1: trailaccess.MTB}


def _context(no_bicycle, ids=(193043941, 97677540, 99419868)):
    return SimpleNamespace(
        military_ways=[
            ra.MilitaryWay(
                i, "Joint Base Anacostia Bolling", "service", "", 10.0, ra.CLOSED, ra.WHY_CLOSED
            )
            for i in ids
        ],
        ways=[SimpleNamespace(osm_id=i) for i in ids],
        no_bicycle=no_bicycle,
    )


def test_validate_holds_the_jbab_sentinels_closed():
    ids = (193043941, 97677540, 99419868)
    held = _context({i: ra.MILITARY_NO_BICYCLE for i in ids})
    assert run.assert_military_closures(held, ids) == 3
    with pytest.raises(run.ValidationFailed, match="Anacostia-Bolling"):
        run.assert_military_closures(_context({193043941: ra.MILITARY_NO_BICYCLE}), ids)
    # A sentinel the extract no longer has is warned about, not refused.
    renumbered = _context({i: ra.MILITARY_NO_BICYCLE for i in ids[:2]}, ids[:2])
    assert run.assert_military_closures(renumbered, ids) == 2
