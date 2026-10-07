"""Ways inside a secured federal compound are closed to bicycles (owner report 2026-10-06).

The owner: "a secure secret service compound is also showing trails" (the James J.
Rowley Training Center, Beltsville/Laurel) and "As is the CIA headquarters" (Langley).
CIA headquarters is `landuse=military` in OSM and the military rule already closes it
(its floor is in REBUILD_SENTINEL_MILITARY_MIN_CLOSED). Rowley is `office=government`
with a name and nothing else, so it is closed as a secured compound
(`restricted_areas.SECURED_AREAS`), by the military rule's own tests: at least half a
way's length inside, and only an owner's override, a numbered public road or a way
signed for bicycles stays open. Under the standing rule "err closed on bike access"
(OWNER-DECISIONS 330).

tests/data/secured_areas.json is the real thing: the Rowley outline (way 437408534) and
the CIA outline (way 186034091) with every highway way of a box over each, Powder Mill
Rd, Colonial Farm Rd and the George Washington Memorial Parkway among them, from the
merged source extract of 2026-10-03 (OpenStreetMap contributors, ODbL).
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

REAL = Path(__file__).parent / "data" / "secured_areas.json"

ROWLEY = "w437408534"
COMPOUND = ra.named_area(
    (
        (-76.85, 39.03, -76.84, 39.04),
        [[(-76.85, 39.03), (-76.84, 39.03), (-76.84, 39.04), (-76.85, 39.04)]],
        [],
    ),
    "James J. Rowley Training Center",
    ROWLEY,
)


def line(lon, lat, d=0.002):
    return [(lon, lat), (lon + d / 2, lat), (lon + d, lat)]


@pytest.mark.parametrize(
    "tags, osm, secured",
    [
        # Rowley: `office=government` and a name only; curated by its id.
        ({"office": "government", "name": "James J. Rowley Training Center"}, ROWLEY, True),
        ({"office": "government", "name": "James J. Rowley Training Center"}, "w1", False),
        # Goddard: a government area with its own access tag keeping the public out.
        (
            {"amenity": "research_institute", "government": "aerospace", "access": "private"},
            "r4237285",
            True,
        ),
        ({"landuse": "government", "access": "no"}, "w2", True),
        ({"office": "government", "access": "restricted"}, "w3", True),
        # Not caught: an access=private subdivision or office park, a government area
        # open to visitors, a building, `government=no`.
        ({"landuse": "residential", "access": "private"}, "w4", False),
        (
            {"landuse": "commercial", "access": "private", "name": "New Dominion Technology"},
            "r5",
            False,
        ),
        ({"landuse": "industrial", "access": "private"}, "w6", False),
        ({"office": "government", "access": "customers"}, "w7", False),
        ({"office": "government", "access": "permissive"}, "w8", False),
        ({"building": "government", "office": "government", "access": "private"}, "w9", False),
        ({"government": "no", "access": "private"}, "w10", False),
        (
            {"amenity": "research_institute", "name": "Beltsville Agricultural Research Center"},
            "r4237277",
            False,
        ),
    ],
)
def test_which_areas_are_secured_compounds(tags, osm, secured):
    assert ra.is_secured_area(tags, osm) is secured
    assert (ra.area_kind(tags, osm) == ra.SECURED) is secured


def test_a_military_area_stays_military_even_where_it_is_listed_or_governmental():
    cia = {"landuse": "military", "operator": "Central Intelligence Agency"}
    assert ra.area_kind(cia, "w186034091") == ra.MILITARY
    weather = {"landuse": "military", "office": "government", "government": "yes"}
    assert ra.area_kind(weather, "w502765475") == ra.MILITARY
    assert ra.area_kind({"office": "government"}, ROWLEY) == ra.SECURED
    assert ra.area_kind({"office": "government"}) is None
    # A base that is also a government area keeping the public out, or that the curated
    # list names, is still filed as a base: closed under the military rule, its floors
    # and its exceptions, not the secured rule's.
    both = {"landuse": "military", "government": "yes", "access": "private"}
    assert ra.is_secured_area(both)
    assert ra.area_kind(both, "w5") == ra.MILITARY
    assert ra.area_kind({"military": "base", "office": "government", "access": "no"}) == (
        ra.MILITARY
    )
    assert ra.area_kind({"landuse": "military"}, ROWLEY) == ra.MILITARY


def test_every_curated_compound_is_a_way_or_relation_id_with_a_name():
    assert ROWLEY in ra.SECURED_AREAS
    assert ra.SECURED_AREAS[ROWLEY] == "James J. Rowley Training Center"
    for osm, name in ra.SECURED_AREAS.items():
        assert osm[0] in "wr" and osm[1:].isdigit() and name


def closures(ways, areas=(COMPOUND,), **kw):
    return {m.way_id: m for m in ra.secured_closures(ways, list(areas), **kw)}


def test_untagged_ways_inside_are_closed_and_public_ways_outside_are_not():
    found = closures(
        [
            (1, {"highway": "service"}, line(-76.848, 39.035)),
            (2, {"highway": "footway"}, line(-76.846, 39.036)),
            (3, {"highway": "path"}, line(-76.848, 39.038)),
            (4, {"highway": "tertiary", "name": "Range Road"}, line(-76.847, 39.033)),
            (5, {"highway": "service", "access": "yes"}, line(-76.848, 39.032)),
            (6, {"highway": "footway", "bicycle": "yes"}, line(-76.848, 39.031)),
            # Outside: a road past the fence, and one along it.
            (7, {"highway": "secondary", "name": "Powder Mill Road"}, line(-76.85, 39.0295)),
            (8, {"highway": "residential"}, [(-76.85, 39.032), (-76.85, 39.038)]),
        ]
    )
    assert {w for w, m in found.items() if m.closed} == {1, 2, 3, 4, 5, 6}
    assert 7 not in found and 8 not in found
    assert found[1].why == ra.WHY_SECURED
    assert found[4].why == ra.WHY_NAMED_ROAD
    assert found[5].why == found[6].why == ra.WHY_SECURED_TAGGED_OPEN
    assert found[1].installation == "James J. Rowley Training Center"


@pytest.mark.parametrize(
    "tags, why",
    [
        ({"highway": "primary", "ref": "MD 212", "name": "Powder Mill Road"}, ra.WHY_PUBLIC_ROUTE),
        ({"highway": "cycleway", "bicycle": "designated"}, ra.WHY_SIGNED),
    ],
)
def test_a_numbered_public_road_or_a_signed_way_stays_open(tags, why):
    (m,) = ra.secured_closures([(9, tags, line(-76.848, 39.035))], [COMPOUND])
    assert not m.closed and m.why == why


def test_an_override_reopens_and_the_military_rules_ways_are_skipped():
    ways = [
        (1, {"highway": "service", "bicycle": "yes"}, line(-76.848, 39.035)),
        (2, {"highway": "service"}, line(-76.848, 39.036)),
    ]
    found = closures(ways, reopened={1}, skip={2})
    assert found[1].why == ra.WHY_OVERRIDE and not found[1].closed
    assert 2 not in found
    assert ra.secured_closures(ways, []) == []


def test_the_curated_name_files_a_compound_whatever_osm_calls_it():
    renamed = ra.named_area(tuple(COMPOUND), "USSS JJRTC", ROWLEY)
    (m,) = ra.secured_closures([(1, {"highway": "service"}, line(-76.848, 39.035))], [renamed])
    assert m.installation == "James J. Rowley Training Center"
    other = ra.named_area(tuple(COMPOUND), "", "w77")
    (m,) = ra.secured_closures([(1, {"highway": "service"}, line(-76.848, 39.035))], [other])
    assert m.installation == "w77"


def test_a_curated_compound_missing_from_the_extract_is_named():
    assert ROWLEY not in ra.secured_missing([COMPOUND])
    assert ROWLEY in ra.secured_missing([])


def test_the_report_has_a_facility_column():
    found = ra.secured_closures([(1, {"highway": "service"}, line(-76.848, 39.035))], [COMPOUND])
    text = ra.military_report_csv(found, "facility")
    assert text.splitlines()[0] == "way_id,facility,highway,name,length_m,status,why,tags"
    assert text.splitlines()[1].startswith("1,James J. Rowley Training Center,service,")
    assert ra.military_report_csv([]).startswith("way_id,installation,")
    assert ra.military_summary(found, "secured federal compounds").startswith(
        "secured federal compounds: 1 ways closed"
    )


def _way(osm_id, tags):
    return Way(osm_id=osm_id, tags=tags, node_ids=[1, 2], coordinates=line(-76.848, 39.035))


def test_the_secured_reason_follows_the_military_one_and_beats_every_other():
    assert tc.ORDER[:2] == (ra.MILITARY_NO_BICYCLE, ra.SECURED_NO_BICYCLE)
    ways = [
        _way(1, {"highway": "path"}),
        _way(2, {"highway": "path"}),
        _way(3, {"highway": "cycleway"}),
    ]
    nobike = tc.closures(ways, {}, [], military={1}, secured={1, 2})
    assert nobike.reasons[1] == ra.MILITARY_NO_BICYCLE
    assert nobike.reasons[2] == ra.SECURED_NO_BICYCLE
    assert 3 not in nobike.reasons
    # And no graph reopens it: the off-road graph keeps only the mtb reason.
    assert ra.SECURED_NO_BICYCLE not in tc.OFFROAD_KEEPS


def _context(no_bicycle, present=None, found=None, through=()):
    ids = list(present if present is not None else no_bicycle)
    if found is None:
        found = [
            ra.MilitaryWay(
                i, "James J. Rowley Training Center", "service", "", 10.0, ra.CLOSED, ra.WHY_SECURED
            )
            for i in ids
        ]
    return SimpleNamespace(
        secured_ways=found,
        secured_through=list(through),
        secured_missing=[],
        ways=[SimpleNamespace(osm_id=i) for i in ids],
        no_bicycle=no_bicycle,
    )


def test_validate_holds_the_sentinels_floors_and_through_networks():
    ids = (11, 12)
    held = _context({i: ra.SECURED_NO_BICYCLE for i in ids})
    assert run.assert_secured_closures(held, ids, {"James J. Rowley Training Center": 2}) == 2
    with pytest.raises(run.ValidationFailed, match="Rowley"):
        run.assert_secured_closures(_context({11: ra.SECURED_NO_BICYCLE}, ids), ids)
    # Closed as a base's is not closed as a compound's: the rule did not run.
    with pytest.raises(run.ValidationFailed, match="Rowley"):
        run.assert_secured_closures(_context({i: ra.MILITARY_NO_BICYCLE for i in ids}), ids)
    # A sentinel the extract no longer has is warned about, not refused.
    assert run.assert_secured_closures(_context({11: ra.SECURED_NO_BICYCLE}), ids) == 1
    with pytest.raises(run.ValidationFailed, match="fewer ways than their floor"):
        run.assert_secured_closures(held, ids, {"James J. Rowley Training Center": 3})
    with pytest.raises(run.ValidationFailed, match="fewer ways than their floor"):
        run.assert_secured_closures(held, ids, {"FDA White Oak Campus": 1})
    # Only closed ways count toward a floor: a compound reopened way by way would
    # otherwise keep its count.
    reopened = ra.MilitaryWay(
        13, "James J. Rowley Training Center", "service", "", 10.0, ra.OPEN, ra.WHY_OVERRIDE
    )
    partly = _context(
        {i: ra.SECURED_NO_BICYCLE for i in ids},
        found=[*held.secured_ways, reopened],
    )
    assert run.assert_secured_closures(partly, ids, {"James J. Rowley Training Center": 2}) == 2
    with pytest.raises(run.ValidationFailed, match="fewer ways than their floor"):
        run.assert_secured_closures(partly, ids, {"James J. Rowley Training Center": 3})
    through = _context({i: ra.SECURED_NO_BICYCLE for i in ids}, through=[([1, 2], [7, 8])])
    with pytest.raises(run.ValidationFailed, match="pass through"):
        run.assert_secured_closures(through, ids)


def test_settings_hold_every_curated_compound_and_the_cia():
    from config import settings as real

    floors = real.REBUILD_SENTINEL_SECURED_MIN_CLOSED
    assert set(ra.SECURED_AREAS.values()) <= set(floors)
    # Goddard is found by its tags (`government=aerospace access=private`), not listed.
    assert "Goddard Space Flight Center" in floors
    assert all(floor >= 1 for floor in floors.values())
    # Rowley's footway, track and service road (2026-10-03 extract), pinned: a dropped id
    # would silently weaken VALIDATE's check that the rule ran.
    assert real.REBUILD_SENTINEL_SECURED_CLOSED_WAYS == (902479602, 1276271654, 6084740)
    # CIA headquarters is a military area in OSM; its floor is the military rule's.
    assert real.REBUILD_SENTINEL_MILITARY_MIN_CLOSED["Central Intelligence Agency"] >= 1


def test_goddards_public_roads_stay_open_and_count_as_a_listed_way_through():
    ways = [
        (521217842, {"highway": "tertiary", "name": "Good Luck Road"}, line(-76.848, 39.035)),
        (
            50935645,
            {"highway": "secondary", "name": "Soil Conservation Road"},
            line(-76.848, 39.036),
        ),
        # Listed, but tagged against the public: closed.
        (1413238483, {"highway": "secondary", "access": "private"}, line(-76.848, 39.037)),
    ]
    found = closures(ways)
    assert found[521217842].why == found[50935645].why == ra.WHY_SECURED_PUBLIC_ROAD
    assert not found[521217842].closed and found[1413238483].closed
    assert ra.WHY_SECURED_PUBLIC_ROAD in ra.THROUGH_EXCEPTIONS


def _real():
    data = json.loads(REAL.read_text())
    areas = {
        a["osm"]: ra.named_area(
            (
                tuple(a["bbox"]),
                [[tuple(p) for p in r] for r in a["outers"]],
                [[tuple(p) for p in r] for r in a["inners"]],
            ),
            a["name"],
            a["osm"],
        )
        for a in data["areas"]
    }
    ways = [(w["id"], w["tags"], [tuple(p) for p in w["coords"]]) for w in data["ways"]]
    return areas, ways, data


def test_rowley_is_closed_and_powder_mill_road_is_not_on_real_data():
    from config import settings as real

    areas, ways, data = _real()
    assert ra.area_kind(data["tags"][ROWLEY], ROWLEY) == ra.SECURED
    found = {m.way_id: m for m in ra.secured_closures(ways, [areas[ROWLEY]])}
    closed = {w for w, m in found.items() if m.closed}
    for way_id in real.REBUILD_SENTINEL_SECURED_CLOSED_WAYS:
        assert way_id in closed
    assert (
        len(closed) >= real.REBUILD_SENTINEL_SECURED_MIN_CLOSED["James J. Rowley Training Center"]
    )
    by_name = {}
    for way_id, tags, _ in ways:
        by_name.setdefault(tags.get("name", ""), set()).add(way_id)
    for public in data["public_names"]["rowley"]:
        assert by_name[public], public
        assert not (by_name[public] & closed), f"{public} closed"


def test_the_cia_is_a_military_area_and_its_public_roads_stay_open_on_real_data():
    areas, ways, data = _real()
    cia = "w186034091"
    assert ra.area_kind(data["tags"][cia], cia) == ra.MILITARY
    found = {m.way_id: m for m in ra.military_closures(ways, [areas[cia]])}
    closed = {w for w, m in found.items() if m.closed}
    assert len(closed) >= 100
    by_name = {}
    for way_id, tags, _ in ways:
        by_name.setdefault(tags.get("name", ""), set()).add(way_id)
    for internal in ("HUMINT Drive", "OSINT Drive"):
        if internal in by_name:
            assert by_name[internal] <= closed, internal
    for public in data["public_names"]["cia"]:
        assert by_name[public], public
        assert not (by_name[public] & closed), f"{public} closed"


# --- Goddard's Visitor Center (446) and the Jessup prison complex (446b) -----------------

# tests/data/secured_goddard_jessup.json is the real thing too: Goddard's outline
# (r4237285) and the Jessup complex's (w1000668306), every highway way within about
# 450 m of the Visitor Center, Goddard Center Bikeway, Good Luck Rd and Soil Conservation
# Rd, and every highway way over the Jessup outline's box, with their node ids, from the
# merged source extract of 2026-10-03 (OpenStreetMap contributors, ODbL).
REAL_446 = Path(__file__).parent / "data" / "secured_goddard_jessup.json"
GODDARD = "r4237285"
JESSUP = "w1000668306"
GODDARD_BIKEWAY = (1527307168, 1527307170, 1527307171)


def _real_446():
    data = json.loads(REAL_446.read_text())
    areas = {
        a["osm"]: ra.named_area(
            (
                tuple(a["bbox"]),
                [[tuple(p) for p in r] for r in a["outers"]],
                [[tuple(p) for p in r] for r in a["inners"]],
            ),
            a["name"],
            a["osm"],
        )
        for a in data["areas"]
    }
    ways = [(w["id"], w["tags"], [tuple(p) for p in w["coords"]]) for w in data["ways"]]
    nodes = {w["id"]: w["nodes"] for w in data["ways"]}
    return areas, ways, nodes, data


def test_the_visitor_centres_way_in_is_listed_open_and_tagged_against_the_public_closes():
    ways = [
        (6095432, {"highway": "service", "access": "yes"}, line(-76.848, 39.035)),
        (165477134, {"highway": "unclassified", "name": "WMAP Road"}, line(-76.848, 39.036)),
        # Listed, but tagged against the public: closed (err closed, 330).
        (521457474, {"highway": "unclassified", "access": "private"}, line(-76.848, 39.037)),
        # Not listed: closed.
        (GODDARD_BIKEWAY[0], {"highway": "cycleway"}, line(-76.848, 39.038)),
    ]
    found = closures(ways)
    assert found[6095432].why == found[165477134].why == ra.WHY_SECURED_VISITOR
    assert not found[6095432].closed and not found[165477134].closed
    assert found[521457474].closed and found[GODDARD_BIKEWAY[0]].closed
    assert "446" in ra.WHY_SECURED_VISITOR
    assert ra.WHY_SECURED_VISITOR in ra.THROUGH_EXCEPTIONS
    assert not set(GODDARD_BIKEWAY) & set(ra.SECURED_VISITOR_WAYS)
    assert not set(ra.SECURED_VISITOR_WAYS) & set(ra.SECURED_PUBLIC_WAYS)


def test_goddard_opens_only_the_visitor_centre_and_its_county_roads_on_real_data():
    areas, ways, nodes, data = _real_446()
    assert ra.area_kind(data["tags"][GODDARD], GODDARD) == ra.SECURED
    found = {m.way_id: m for m in ra.secured_closures(ways, [areas[GODDARD]])}
    opened = {w for w, m in found.items() if not m.closed}
    # Every listed way is in the extract, inside the outline and open.
    assert set(ra.SECURED_VISITOR_WAYS) <= opened
    assert {found[w].why for w in ra.SECURED_VISITOR_WAYS} == {ra.WHY_SECURED_VISITOR}
    goddard_public = {
        w
        for w, name in ra.SECURED_PUBLIC_WAYS.items()
        if name in ("Good Luck Road", "Soil Conservation Road")
    }
    assert len(goddard_public) == 6
    assert goddard_public <= opened
    # Nothing else near the centre is open: the bikeway, ICESat Rd past the gate
    # (`access=private`), Explorer Rd and the centre's plaza stay closed.
    assert opened == set(ra.SECURED_VISITOR_WAYS) | goddard_public
    for closed in (*GODDARD_BIKEWAY, 1427214072, 1426248713, 1058157663, 165477010, 1171520444):
        assert found[closed].closed, closed
    # The way in meets Greenbelt Rd at three points, and is an exception, so VALIDATE's
    # through-network check passes.
    outside = {w for w, tags, _ in ways if w not in found and ra.open_to_bicycles(tags)}
    assert ra.through_networks(list(found.values()), nodes, outside) == []
    loose = ra.through_networks(list(found.values()), nodes, outside, exceptions=frozenset())
    assert any(set(ids) >= set(ra.SECURED_VISITOR_WAYS) for ids, _ in loose)


def test_the_jessup_prison_complex_is_closed_and_brock_bridge_road_is_not_on_real_data():
    from config import settings as real

    areas, ways, nodes, data = _real_446()
    assert ra.SECURED_AREAS[JESSUP] == "Jessup correctional complex"
    assert ra.area_kind(data["tags"][JESSUP], JESSUP) == ra.SECURED
    found = {m.way_id: m for m in ra.secured_closures(ways, [areas[JESSUP]])}
    closed = {w for w, m in found.items() if m.closed}
    assert len(closed) >= real.REBUILD_SENTINEL_SECURED_MIN_CLOSED["Jessup correctional complex"]
    by_name: dict[str, set[int]] = {}
    for way_id, tags, _ in ways:
        by_name.setdefault(tags.get("name", ""), set()).add(way_id)
    # House of Correction Rd inside the outline (`access=private`) is closed; its
    # approach from the north (11514305, no access tag) is outside it.
    assert {119619494, 119619495, 119619496} <= closed
    assert 11514305 in by_name["House of Correction Road"] and 11514305 not in found
    # Brock Bridge Rd's bridge is inside the outline and stays open; the rest of it and
    # Jessup Rd (MD 175) are outside it.
    assert not found[78343985].closed and found[78343985].why == ra.WHY_SECURED_PUBLIC_ROAD
    for public in ("Brock Bridge Road", "Jessup Road"):
        assert by_name[public], public
        assert not (by_name[public] & closed), f"{public} closed"
    outside = {w for w, tags, _ in ways if w not in found and ra.open_to_bicycles(tags)}
    assert ra.through_networks(list(found.values()), nodes, outside) == []


def test_what_446b_leaves_open_is_not_a_secured_area():
    # The owner (446b): "the others aren't much more different than many other buildings
    # in the area". The SSA's Woodlawn campus and the wider White Oak Federal Research
    # Center stay open; Saint Elizabeths waits for a DHS West Campus outline.
    _, _, _, data = _real_446()
    for osm in ("w315105784", "r13305997", "w1001721340"):
        assert osm not in ra.SECURED_AREAS, osm
        assert ra.area_kind(data["tags"][osm], osm) != ra.SECURED, osm


# --- The correctional department's land at Sykesville (447) ------------------------------

# tests/data/secured_sykesville.json is the real thing: the department's Sykesville outline
# (w736540664, `landuse=government` and a name only) and every highway way within about
# 450 m of it, with their node ids (`tiger:*` tags dropped), from the merged source
# extract of 2026-10-03 (OpenStreetMap contributors, ODbL).
REAL_447 = Path(__file__).parent / "data" / "secured_sykesville.json"
SYKESVILLE = "w736540664"
SLACKS_ROAD = (11537133, 1021005795, 1021005796, 110346455)


def test_the_sykesville_land_is_closed_and_slacks_road_is_not_on_real_data():
    """447: the orchestrator's err-closed pick while the owner's answer is pending. Its
    farm, service and track roads close; Slacks Rd, the county road through it, stays
    open as Brock Bridge Rd does at Jessup."""
    from config import settings as real

    data = json.loads(REAL_447.read_text())
    (a,) = data["areas"]
    area = ra.named_area(
        (tuple(a["bbox"]), [[tuple(p) for p in r] for r in a["outers"]], []), a["name"], a["osm"]
    )
    ways = [(w["id"], w["tags"], [tuple(p) for p in w["coords"]]) for w in data["ways"]]
    nodes = {w["id"]: w["nodes"] for w in data["ways"]}
    assert ra.SECURED_AREAS[SYKESVILLE] == "Sykesville correctional land"
    assert ra.area_kind(data["tags"][SYKESVILLE], SYKESVILLE) == ra.SECURED
    # Only the curated id catches it: the tag rule alone would not.
    assert ra.area_kind(data["tags"][SYKESVILLE]) is None
    found = {m.way_id: m for m in ra.secured_closures(ways, [area])}
    closed = {w for w, m in found.items() if m.closed}
    assert len(found) == 64 and len(closed) == 60
    floor = real.REBUILD_SENTINEL_SECURED_MIN_CLOSED["Sykesville correctional land"]
    assert 1 <= floor <= len(closed)
    assert {found[w].installation for w in closed} == {"Sykesville correctional land"}
    # Ways with no access tag of their own close: Beef Farm Rd, a track, a service road.
    for way_id in (436808063, 1021005797, 1126815407):
        assert way_id in closed and found[way_id].why == ra.WHY_SECURED, way_id
    for way_id in SLACKS_ROAD:
        assert not found[way_id].closed and found[way_id].why == ra.WHY_SECURED_PUBLIC_ROAD
        assert "Slacks Road" in ra.SECURED_PUBLIC_WAYS[way_id]
    # The rest of Slacks Rd is outside the outline and open.
    rest = {w for w, tags, _ in ways if tags.get("name") == "Slacks Road"} - set(SLACKS_ROAD)
    assert rest and not rest & set(found)
    outside = {w for w, tags, _ in ways if w not in found and ra.open_to_bicycles(tags)}
    assert ra.through_networks(list(found.values()), nodes, outside) == []
