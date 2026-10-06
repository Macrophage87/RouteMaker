"""Ways inside a military area are closed to bicycles (owner report 2026-10-05).

The owner planned a route through Joint Base Anacostia-Bolling, down the base's
riverside walkways and parking aisles, which carry no access tag of their own. Under
the standing rule "err closed on bike access" (OWNER-DECISIONS 330) every road and
path inside a military area is closed, on every graph. OWNER-DECISIONS 437 narrowed
what stays open to a numbered public road, a way signed for bicycles
(`bicycle=designated`), the Pentagon's listed streets and walkways (437.5) and a way an
approved override reopens (437.6, 437a-c); `access=yes`/`permissive` and `bicycle=yes`
no longer open a way inside a base (437.1-437.3), and "inside" is the share of a way's
length, not of its vertices.

tests/data/military_through.json is Fort Belvoir and Fort Detrick: their outlines,
every way inside that its own tags opened or numbered (and Jeff Todd Way), and the
ways outside that meet them. tests/data/military_edges.json is four ways along a fence
(Telegraph Rd and Russell Rd at Quantico, South Fern St at the Pentagon, Saint
Elizabeths Rd SE) with their base's outline clipped around them. Both are from the
merged source extract of 2026-10-03 (OpenStreetMap contributors, ODbL).

tests/data/jbab_military.json is the real base: the Joint Base Anacostia Bolling and
Bolling Air Force Base polygons and every highway way of a box over the base's north
end and the streets east of it (I-295, South Capitol St, Malcolm X Ave), from the
Geofabrik District of Columbia extract of 2026-10-03.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import restricted_areas as ra
from pipeline import run
from pipeline import trail_closures as tc
from pipeline.extract import Way
from routemaker import trailaccess

JBAB = Path(__file__).parent / "data" / "jbab_military.json"
THROUGH = Path(__file__).parent / "data" / "military_through.json"
EDGES = Path(__file__).parent / "data" / "military_edges.json"
DESIGNATED = Path(__file__).parent / "data" / "military_designated.json"
REOPENINGS = (
    Path(__file__).parent.parent
    / "fixtures"
    / "overrides"
    / "2026-10-06-owner-military-reopenings.json"
)

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
            # Just over half its length in: inside by the INSIDE_FRACTION rule.
            (7, {"highway": "path"}, [(-77.0112, 38.845), (-77.009, 38.845)]),
            # Most vertices inside but most of the length outside (437: by length).
            (
                8,
                {"highway": "path"},
                [(-77.0101, 38.845), (-77.0102, 38.845), (-77.0103, 38.845), (-77.005, 38.845)],
            ),
            # Along the fence itself, both vertices on the boundary: not inside.
            (9, {"highway": "secondary"}, [(-77.02, 38.842), (-77.02, 38.848)]),
        ]
    )
    assert {w for w, m in found.items() if m.closed} == {1, 2, 3, 4, 7}
    assert 5 not in found and 6 not in found and 8 not in found and 9 not in found
    assert found[7].share == pytest.approx(0.545, abs=0.01)
    assert found[3].why == ra.WHY_NAMED_ROAD, "a named road with no access tag is listed"
    assert found[4].why == ra.WHY_CLOSED
    assert found[1].installation == "Fort Example"


@pytest.mark.parametrize(
    "tags, why",
    [
        ({"highway": "cycleway", "bicycle": "designated"}, ra.WHY_SIGNED),
        # B1: motor_vehicle=no keeps cars off a shared-use path, not bicycles (the Jeff
        # Todd Way side path, the Fairfax County Parkway Trail at the North Area).
        (
            {
                "highway": "cycleway",
                "bicycle": "designated",
                "foot": "designated",
                "motor_vehicle": "no",
            },
            ra.WHY_SIGNED,
        ),
        ({"highway": "trunk", "ref": "US 1", "name": "Richmond Highway"}, ra.WHY_PUBLIC_ROUTE),
        ({"highway": "primary", "ref": "SR 611;SR 999"}, ra.WHY_PUBLIC_ROUTE),
        ({"highway": "primary", "ref": "MD 198"}, ra.WHY_PUBLIC_ROUTE),
        # Montezuma Ave at Quantico: the state's number beside the base's own.
        ({"highway": "tertiary", "ref": "SR 641;MCB 3"}, ra.WHY_PUBLIC_ROUTE),
    ],
)
def test_a_signed_way_or_a_public_route_number_stays_open_and_is_listed(tags, why):
    (m,) = ra.military_closures([(9, tags, line(-77.018, 38.845))], [BASE])
    assert not m.closed and m.why == why


@pytest.mark.parametrize(
    "tags",
    [
        # 437.1: access=yes or permissive alone (Fort Belvoir's main post, Fort Detrick).
        {"highway": "service", "access": "permissive"},
        {"highway": "residential", "access": "yes", "name": "Porter Street"},
        # 437.2, 437.3: bicycle=yes (JBAB's sidewalks, Quantico's mountain-bike trails,
        # APG's access=private bicycle=yes roads), and permissive.
        {"highway": "footway", "bicycle": "yes"},
        {"highway": "path", "bicycle": "yes", "mtb:scale": "1"},
        {"highway": "residential", "access": "private", "bicycle": "yes"},
        {"highway": "path", "bicycle": "permissive"},
        # Signed, but an access key keeps everyone out.
        {"highway": "cycleway", "bicycle": "designated", "access": "private"},
        {"highway": "cycleway", "bicycle": "designated", "vehicle": "no"},
        {"highway": "cycleway", "bicycle": "designated", "access": "military"},
    ],
)
def test_a_ways_own_open_tags_no_longer_open_it_inside_a_base(tags):
    (m,) = ra.military_closures([(9, tags, line(-77.018, 38.845))], [BASE])
    assert m.closed
    if ra.public_permission(tags):
        assert m.why == ra.WHY_TAGGED_OPEN


def test_only_an_override_rows_bicycle_permission_reopens_a_way():
    ways = [
        (
            1,
            {"highway": "secondary", "name": "Russell Road", "bicycle": "yes"},
            line(-77.018, 38.845),
        ),
        (
            2,
            {"highway": "secondary", "name": "Jeff Todd Way", "bicycle": "no"},
            line(-77.018, 38.846),
        ),
        # The same tag from OSM, not from an override row: closed.
        (3, {"highway": "secondary", "bicycle": "yes"}, line(-77.018, 38.847)),
        (4, {"highway": "secondary", "bicycle:forward": "yes"}, line(-77.018, 38.848)),
    ]
    found = {m.way_id: m for m in ra.military_closures(ways, [BASE], reopened={1, 2, 4})}
    assert found[1].why == found[4].why == ra.WHY_OVERRIDE
    assert not found[1].closed and not found[4].closed
    assert found[2].closed and found[3].closed


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


def test_the_pentagon_keeps_open_only_its_listed_streets_and_walkways():
    """437.5: South Fern St and S Eads St open, North Rotary Rd closed, only the
    walkways around the memorial, the transit centre and the trail links open."""
    fern, eads, trail, memorial, transit = 44486932, 8797265, 548580375, 433350216, 438981666
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
            (fern, {"highway": "tertiary", "name": "South Fern Street"}, line(-77.056, 38.861)),
            (eads, {"highway": "tertiary", "name": "South Eads Street"}, line(-77.056, 38.862)),
            (trail, {"highway": "cycleway", "bicycle": "yes"}, line(-77.056, 38.864)),
            (memorial, {"highway": "footway", "bicycle": "yes"}, line(-77.056, 38.865)),
            (transit, {"highway": "footway"}, line(-77.056, 38.866)),
            (6, {"highway": "trunk", "ref": "VA 110"}, line(-77.056, 38.867)),
        ]
    )
    assert {w for w, m in found.items() if not m.closed} == {
        fern,
        eads,
        trail,
        memorial,
        transit,
        6,
    }
    assert {found[w].why for w in (fern, eads, trail, memorial, transit)} == {ra.WHY_EDGE_PATH}
    assert found[2].closed and found[3].closed and found[4].closed and found[5].closed
    # A listed id inside an ordinary base is not the Pentagon's: closed.
    (m,) = ra.military_closures([(fern, {"highway": "tertiary"}, line(-77.018, 38.845))], [BASE])
    assert m.closed
    # The ids not seen open are named for the log.
    missing = ra.pentagon_open_missing(list(found.values()))
    assert fern not in missing and 1022785577 in missing
    assert set(ra.PENTAGON_OPEN_WAYS) == set(ra.PENTAGON_STREETS) | set(ra.PENTAGON_WALKWAYS)
    assert len(ra.PENTAGON_OPEN_WAYS) == 26


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
    # Closed too, since 437.2 ("Same."): the sidewalks OSM tags bicycle=yes.
    opened = {w for w, m in found.items() if not m.closed}
    assert opened == set()
    assert found[97677535].why == ra.WHY_TAGGED_OPEN
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


def _context(no_bicycle, ids=(193043941, 97677540, 99419868), through=()):
    return SimpleNamespace(
        military_through=list(through),
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


def test_validate_refuses_an_installation_below_its_floor_or_a_through_network():
    ids = (193043941, 97677540, 99419868)
    held = _context({i: ra.MILITARY_NO_BICYCLE for i in ids})
    floors = {"Joint Base Anacostia Bolling": 3}
    assert run.assert_military_closures(held, ids, floors) == 3
    with pytest.raises(run.ValidationFailed, match="fewer ways than their floor"):
        run.assert_military_closures(held, ids, {"Joint Base Anacostia Bolling": 4})
    with pytest.raises(run.ValidationFailed, match="Fort Belvoir"):
        run.assert_military_closures(held, ids, {"Fort Belvoir": 1})
    through = _context({i: ra.MILITARY_NO_BICYCLE for i in ids}, through=[([1, 2], [7, 8])])
    with pytest.raises(run.ValidationFailed, match="pass through a base"):
        run.assert_military_closures(through, ids, floors)


def test_settings_floor_every_large_installation():
    from config import settings as real

    floors = real.REBUILD_SENTINEL_MILITARY_MIN_CLOSED
    assert {"Fort Belvoir", "Fort Detrick", "Marine Corps Base Quantico"} <= set(floors)
    assert {"Aberdeen Proving Ground", "The Pentagon"} <= set(floors)
    # Bolling's old outline and JBAB overlap: one floor for the two (O1).
    assert floors[("Bolling Air Force Base", "Joint Base Anacostia Bolling")] >= 800
    assert "Bolling Air Force Base" not in floors and "Joint Base Anacostia Bolling" not in floors
    assert all(floor >= 470 for floor in floors.values())


def test_overlapping_installations_share_one_floor_whichever_name_wins_the_tie():
    """O1: the old Bolling outline lies inside JBAB, so a way's name is a tie-break
    an OSM edit can move. The combined floor holds either way the ways fall."""
    pair = ("Bolling Air Force Base", "Joint Base Anacostia Bolling")

    def ctx(bolling, jbab):
        names = ["Bolling Air Force Base"] * bolling + ["Joint Base Anacostia Bolling"] * jbab
        found = [
            ra.MilitaryWay(i, name, "service", "", 10.0, ra.CLOSED, ra.WHY_CLOSED)
            for i, name in enumerate(names)
        ]
        return SimpleNamespace(military_ways=found, military_through=[], ways=[], no_bicycle={})

    for split in ((8, 2), (1, 9), (0, 10), (10, 0)):
        assert run.assert_military_closures(ctx(*split), (), {pair: 10}) == 10
    with pytest.raises(run.ValidationFailed, match="Bolling"):
        run.assert_military_closures(ctx(5, 4), (), {pair: 10})


# --- Inside by length (437; S2) ---------------------------------------------------


def _areas(raw):
    areas = []
    for a in raw:
        outers = [[tuple(p) for p in r] for r in a["outers"]]
        inners = [[tuple(p) for p in r] for r in a["inners"]]
        xs = [p[0] for r in outers for p in r]
        ys = [p[1] for r in outers for p in r]
        areas.append(
            ra.named_area(
                ((min(xs), min(ys), max(xs), max(ys)), outers, inners), a["name"], a["osm"]
            )
        )
    return areas


@pytest.mark.parametrize(
    "way_id, low, high, inside",
    [
        # Telegraph Rd at Quantico: both vertices are boundary nodes, the road the fence.
        (51806786, 0.0, 0.05, False),
        # Russell Rd at Quantico, the piece between two open pieces: 34% inside.
        (20448834, 0.30, 0.40, False),
        # South Fern St at the Pentagon, 87% outside the reservation.
        (346101190, 0.08, 0.16, False),
        # Saint Elizabeths Rd SE, inside the St. Elizabeths campus.
        (316866053, 0.95, 1.0, True),
    ],
)
def test_inside_is_the_share_of_a_ways_length(way_id, low, high, inside):
    case = next(c for c in json.loads(EDGES.read_text())["cases"] if c["id"] == way_id)
    areas = _areas(case["areas"])
    coords = [tuple(p) for p in case["coords"]]
    shapes = ra._Shapes(areas)
    share, _ = shapes.share(coords)
    assert low <= share <= high
    # And by the old vertex count, each of the first three was inside.
    if not inside:
        assert ra._inside(coords, ra._Index(areas))
    found = ra.military_closures([(way_id, case["tags"], coords)], areas)
    assert bool(found) is inside


def test_overlapping_areas_count_a_stretch_once_and_holes_are_outside():
    hole = ra.named_area(
        (
            (-77.02, 38.84, -77.01, 38.85),
            [[(-77.02, 38.84), (-77.01, 38.84), (-77.01, 38.85), (-77.02, 38.85)]],
            [[(-77.018, 38.841), (-77.012, 38.841), (-77.012, 38.849), (-77.018, 38.849)]],
        ),
        "Holed",
        "w2",
    )
    shapes = ra._Shapes([hole])
    assert shapes.share(line(-77.017, 38.845))[0] == 0.0
    twice = ra._Shapes([BASE, BASE])
    assert twice.share([(-77.015, 38.845), (-77.005, 38.845)])[0] == pytest.approx(0.5, abs=0.01)
    assert twice.share([(-77.015, 38.845)]) == (1.0, BASE)


# --- No open network passes through a base (437) ----------------------------------


def through_data():
    data = json.loads(THROUGH.read_text())
    areas = _areas(data["areas"])
    inside = [(w["id"], w["tags"], [tuple(p) for p in w["coords"]]) for w in data["inside"]]
    nodes = {w["id"]: w["nodes"] for w in data["inside"] + data["outside"]}
    outside = {w["id"] for w in data["outside"] if ra.open_to_bicycles(w["tags"])}
    return areas, inside, nodes, outside


def _as_before_437(found):
    """The rule before 437: a way's own access=yes/permissive or bicycle=yes opened it."""
    return [
        replace(m, status=ra.OPEN, why="open: the way's own tags (before 437)")
        if m.closed and m.why == ra.WHY_TAGGED_OPEN
        else m
        for m in found
    ]


def test_no_open_network_inside_fort_belvoir_or_fort_detrick_meets_the_outside_twice():
    areas, inside, nodes, outside = through_data()
    found = ra.military_closures(inside, areas)
    assert ra.through_networks(found, nodes, outside) == []
    # With the owner's Jeff Todd Way rows (437.6) applied, still none: an override and a
    # numbered road are listed exceptions.
    jeff = json.loads(REOPENINGS.read_text())
    jeff_ids = {r["osm_way_id"] for r in jeff["rows"] if "Jeff Todd" in r["evidence"]}
    reopened = [(w, {**t, "bicycle": "yes"} if w in jeff_ids else t, c) for w, t, c in inside]
    found = ra.military_closures(reopened, areas, reopened=jeff_ids)
    assert {m.way_id for m in found if m.why == ra.WHY_OVERRIDE} == jeff_ids
    assert ra.through_networks(found, nodes, outside) == []
    # The failure 437 answers, held by the same check: before it, the access=permissive
    # main post at Fort Belvoir and Fort Detrick's access=yes streets were open networks
    # joined to the public streets at many points.
    before = ra.through_networks(_as_before_437(found), nodes, outside)
    by_size = sorted(before, key=lambda n: -len(n[0]))
    assert len(by_size[0][0]) > 200 and len(by_size[0][1]) >= 21  # Fort Belvoir, 33.8 mi
    names = {m.way_id: m.installation for m in found}
    assert {names[ways[0]] for ways, _ in before} >= {"Fort Belvoir", "Fort Detrick"}


def test_through_networks_ignores_islands_one_entry_and_listed_exceptions():
    def way(i, why, status=ra.OPEN):
        return ra.MilitaryWay(i, "Fort Example", "service", "", 10.0, status, why)

    found = [
        way(1, "open: by hand"),  # meets the outside at nodes 10 and 11: a through network
        way(2, "open: by hand"),  # one entry only (node 20)
        way(3, "open: by hand"),  # an island
        way(4, ra.WHY_PUBLIC_ROUTE),  # a numbered road, entries 40 and 41: an exception
        way(5, ra.WHY_CLOSED, ra.CLOSED),  # closed: never a member
    ]
    nodes = {
        1: [10, 12, 11],
        2: [20, 21],
        3: [30, 31],
        4: [40, 41],
        5: [11, 50],
        9: [10, 11, 20, 40, 41],
    }
    networks = ra.through_networks(found, nodes, {9})
    assert networks == [([1], [10, 11])]
    assert ra.through_networks(found, nodes, {9}, exceptions=()) == [
        ([1], [10, 11]),
        ([4], [40, 41]),
    ]
    # A way outside the base that is not open to bicycles gives no entry.
    assert ra.through_networks(found, nodes, set()) == []
    assert not ra.open_to_bicycles({"highway": "motorway"})
    assert not ra.open_to_bicycles({"highway": "service", "access": "private"})
    assert ra.open_to_bicycles({"highway": "residential"})


# --- The owner's reopenings (437.6, 437a, 437b, 437c) -------------------------------


def test_the_reopenings_file_carries_each_decision():
    data = json.loads(REOPENINGS.read_text())
    access = {r["osm_way_id"]: r for r in data["rows"] if r["kind"] == "access"}
    stress = {r["osm_way_id"]: r for r in data["rows"] if r["kind"] == "stress"}
    assert all(r["value"] == {"bicycle": "yes"} for r in access.values())
    by_decision = {
        "437.6": {
            131756393,
            131756713,
            131756714,
            131756715,
            232308619,
            232308625,
            232308636,
            306059636,
            1098724285,
            1098724286,
        },
        "437a": {
            20535693,
            130229063,
            130229064,
            239145265,
            239145266,
            267730802,
            267730806,
            532701662,
            532701663,
            532701664,
            532701667,
            827080188,
            827080200,
            827080201,
            827080202,
            827080203,
            828914761,
            828941252,
            828941253,
            828941255,
            828941256,
            1078047788,
            1078047792,
            1078047793,
            1198494292,
            1198494293,
            1198494296,
            1198494298,
            1198494299,
            1198494300,
            1198494302,
            1198494303,
        },
        "437c": {316866053, 1181165198},
        # Pentagon Connector Road, by id (not Fort Meade's Connector Road, access=no).
        "438.2": {
            32866298,
            50557521,
            50557526,
            50557527,
            50557528,
            296172078,
            296172079,
            296172080,
            296172081,
            296173435,
            296173436,
            345398624,
            345398633,
            514215556,
            514215557,
            514215558,
            758995471,
            1022788239,
            1311964674,
            1311964675,
            1311964676,
            1311964678,
            1311964679,
            1365254349,
            1365254351,
        },
        "437b": {
            1184926339,
            1469856110,
            1469856109,
            1469856111,
            1469856112,
            1001796646,
            1001796647,
            1181165194,
            1001796648,
            1181165195,
            1001796649,
        },
    }
    for decision, ids in by_decision.items():
        assert {w for w, r in access.items() if f"decision {decision}," in r["reason"]} == ids
    assert len(access) == sum(len(ids) for ids in by_decision.values()) == 80
    assert {r["fingerprint"]["name"] for w, r in access.items() if w in by_decision["438.2"]} == {
        "Connector Road"
    }
    # 439: the Pentagon transit-centre link runs over sidewalk 345398651 (OSM
    # access=private); the owner left it closed pending community review. So no row
    # opens it or the link's other ways.
    assert not {345398651, 38355363, 345398802, 904642304, 345398771, 1022785583} & set(access)
    # Saint Elizabeths Rd SE is LTS 4 (437c), and the Avoid rows the east-of-the-Anacostia
    # file loaded are retired here; that file no longer carries them.
    # Jeff Todd Way's roadway is LTS 4 (439b: "I meant Jeff Todd. It's LTS4"): the 10
    # ways above and its 5 SR 619 carriageways inside the base. Connector Road keeps
    # the classifier's rating; the side path keeps its own.
    jeff_sr619 = {232308648, 232393907, 1076054099, 1076054100, 1411382767}
    assert set(stress) == by_decision["437c"] | by_decision["437.6"] | jeff_sr619
    assert all(r["value"]["tier"] == 4 for r in stress.values())
    assert all("decision 439b," in stress[w]["reason"] for w in by_decision["437.6"] | jeff_sr619)
    assert not set(stress) & set(JEFF_TODD_SIDE_PATH)
    assert not set(stress) & by_decision["438.2"]
    assert {r["osm_way_id"] for r in data["retire"]} == by_decision["437c"]
    assert all(r["value"]["tier"] == 5 for r in data["retire"])
    east = json.loads(
        (REOPENINGS.parent / "2026-09-30-owner-arterials-east-of-anacostia.json").read_text()
    )
    assert not {r["osm_way_id"] for r in east["rows"]} & by_decision["437c"]
    # Russell Rd's access=private MCB 1 ways further west stay closed by their own tags.
    assert not {1026975878, 1527935777} & set(access)
    # Jeff Todd Way's SR 619 ways are numbered, so the rule leaves them open already.
    assert not {232308648, 232393907, 1076054099, 1076054100, 1411382767} & set(access)


def test_the_rebuild_finds_a_through_network_from_its_own_ways():
    """`run.military_through_networks` over the rebuild's ways: an open in-base road
    whose ends meet two open streets outside is found; a motorway gives no entry."""
    found = [ra.MilitaryWay(1, "Fort Example", "service", "", 10.0, ra.OPEN, "open: by hand")]
    ways = [
        Way(1, {"highway": "service"}, [10, 11, 12], line(-77.018, 38.845), [0, 1, 2]),
        Way(2, {"highway": "residential"}, [10, 20], line(-77.03, 38.845, 0.001), [0, 1]),
        Way(3, {"highway": "residential"}, [12, 30], line(-77.03, 38.846, 0.001), [0, 1]),
        Way(4, {"highway": "motorway"}, [11, 40], line(-77.03, 38.847, 0.001), [0, 1]),
    ]
    context = SimpleNamespace(military_ways=found, ways=ways, ways_by_id={})
    assert run.military_through_networks(context) == [([1], [10, 12])]
    context.ways = [ways[0], ways[1], ways[3]]
    assert run.military_through_networks(context) == []


# --- Ways signed for bicycles (B1, 438.1) -------------------------------------------

JEFF_TODD_SIDE_PATH = (
    1147219723, 299021475, 232393905, 299021476, 232393906, 679383213,
    679385745, 679385747, 679385748,
)  # fmt: skip
NORTH_AREA_TRAIL = (
    158976668, 158976667, 600029658, 1452551410, 1452551411, 1452551424, 1452551425,
    1452551426, 1452551429, 1452551430, 1452551431, 1452551432, 1452551434, 1452551435,
)  # fmt: skip
RIVERWALK = (148773141, 148773142, 546106273)


def designated_found():
    data = json.loads(DESIGNATED.read_text())
    ways = [(w["id"], w["tags"], [tuple(p) for p in w["coords"]]) for w in data["ways"]]
    return {m.way_id: m for m in ra.military_closures(ways, _areas(data["areas"]))}


def test_motor_vehicle_no_does_not_close_a_signed_path():
    tags = {"highway": "cycleway", "bicycle": "designated", "motor_vehicle": "no"}
    assert ra.signed_for_bicycles(tags)
    assert not ra.signed_for_bicycles({**tags, "access": "no"})
    assert not ra.signed_for_bicycles({**tags, "vehicle": "private"})
    # A numbered road still closes on motor_vehicle (unchanged).
    assert not ra.public_route({"highway": "primary", "ref": "SR 610", "motor_vehicle": "no"})


def test_the_jeff_todd_way_side_path_and_the_parkway_trail_stay_open_on_real_data():
    """B1, on the 2026-10-03 ways: the mapped Jeff Todd Way side path (437.6) and the
    Fairfax County Parkway Trail through Fort Belvoir North Area are all
    `bicycle=designated motor_vehicle=no`, and stay open; so does the Riverwalk."""
    found = designated_found()
    for way_id in (*JEFF_TODD_SIDE_PATH, *NORTH_AREA_TRAIL, *RIVERWALK):
        assert found[way_id].why == ra.WHY_SIGNED, way_id
    assert found[299021476].installation == "Fort Belvoir"
    assert found[158976668].installation == "Fort Belvoir North Area"
    assert "motor_vehicle=no" in found[299021476].tags
    assert "motor_vehicle=no" in found[158976668].tags


def test_a_designated_way_only_the_base_reaches_is_closed_with_its_own_reason():
    """438.1: the Belvoir Rd crossing on the main post (1322746319) is closed; 439:
    the borderline ways wait for the community; the listed ids close even with no
    other tag against them, and the rest stay open."""
    pending = {704730666, 1117514150, 1117514151, 1117514152, 1117514153, 1117514154}
    assert set(ra.DESIGNATED_BASE_ONLY) == {1322746319} | pending
    found = designated_found()
    m = found[1322746319]
    assert m.closed and m.why == ra.WHY_BASE_ONLY
    assert m.installation == "Fort Belvoir"
    # 439: the borderline ways (704730666 at Belvoir, the Russell Rd side path at
    # Quantico) are closed until the community confirms them.
    for way_id in pending:
        assert found[way_id].closed and found[way_id].why == ra.WHY_PENDING_REVIEW, way_id
    assert found[704730666].installation == "Fort Belvoir"
    assert found[1117514150].installation == "Marine Corps Base Quantico"
    assert ra.signed_for_bicycles({"bicycle": "designated", "foot": "designated"})
    # By id only: the same tags on another way stay open.
    tags = {"highway": "cycleway", "bicycle": "designated"}
    (other,) = ra.military_closures([(9, tags, line(-77.018, 38.845))], [BASE])
    assert not other.closed
    # An approved override row still reopens a listed way (the owner's evidence).
    (reopened,) = ra.military_closures(
        [(1322746319, {**tags, "bicycle": "yes"}, line(-77.018, 38.845))],
        [BASE],
        reopened={1322746319},
    )
    assert reopened.why == ra.WHY_OVERRIDE


def test_the_jeff_todd_way_side_path_keeps_its_low_rating_beside_the_lts_4_road():
    """439b: the roadway is LTS 4 by its own stress rows; the side path ("But that
    sidepath looks fine") has no row and the classifier rates it by its own tags."""
    from routemaker import stress

    data = json.loads(DESIGNATED.read_text())
    tags = {w["id"]: w["tags"] for w in data["ways"]}
    for way_id in JEFF_TODD_SIDE_PATH:
        result = stress.classify(dict(tags[way_id]), jurisdiction="VA")
        assert result.tier == stress.Stress.LTS1, (way_id, result)
