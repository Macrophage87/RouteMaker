"""The National Zoo closure and its destination-only spur (OWNER-DECISIONS 291(4))."""

from __future__ import annotations

from routemaker import zoo

INSIDE = (-77.0495, 38.9290)
OUTSIDE = (-77.0300, 38.9000)


def line(lon, lat):
    return [(lon, lat), (lon + 0.0001, lat + 0.0001)]


def test_a_footway_inside_is_closed_outside_is_not():
    tags = {"highway": "footway", "bicycle": "no"}
    assert zoo.closed_way(1, tags, line(*INSIDE))
    assert not zoo.closed_way(1, tags, line(*OUTSIDE))


def test_the_zoo_roads_are_closed():
    for highway in ("unclassified", "service", "pedestrian", "path"):
        assert zoo.closed_way(2, {"highway": highway}, line(*INSIDE)), highway


def test_public_streets_and_the_signed_cycleway_stay_open():
    for highway in ("primary", "secondary", "tertiary", "residential", "tertiary_link"):
        assert not zoo.closed_way(3, {"highway": highway}, line(*INSIDE)), highway
    trail = {"highway": "cycleway", "bicycle": "designated"}
    assert not zoo.closed_way(4, trail, line(*INSIDE))
    assert not zoo.closed_way(4, {"highway": "cycleway", "bicycle": "yes"}, line(*INSIDE))
    assert zoo.closed_way(4, {"highway": "cycleway"}, line(*INSIDE))


def test_a_retagged_rock_creek_trail_piece_stays_open():
    # Hunt A5 (2026-11-08): the rule kept only `highway=cycleway` + `bicycle=designated|yes`,
    # so an OSM retag of a Rock Creek Trail piece along the Zoo's edge to a designated path
    # or a bare named cycleway closed it (before: True) and cut the trail on every graph.
    for tags in (
        {"highway": "path", "bicycle": "designated", "foot": "designated", "segregated": "no"},
        {"highway": "path", "bicycle": "yes"},
        {"highway": "cycleway", "name": "Rock Creek Trail"},
        {"highway": "footway", "name": "Rock Creek Trail"},
        {"highway": "path", "name": "Zoo Loop Trail"},
    ):
        assert not zoo.closed_way(5, tags, line(*INSIDE)), tags
    # The Zoo's own named walks, and a through trail its own tags bar bicycles from, close.
    assert zoo.closed_way(5, {"highway": "footway", "name": "Asia Trail"}, line(*INSIDE))
    barred = {"highway": "footway", "name": "Rock Creek Trail", "bicycle": "no"}
    assert zoo.closed_way(5, barred, line(*INSIDE))


def _zoo_extract(trail_tags=None, drop_spur=()):
    """The spur ways, four open trail ways (the floor) and a closed walk, all inside the Zoo."""
    lon, lat = INSIDE
    ways = [
        (way_id, {"highway": "footway"}, line(lon, lat))
        for way_id in sorted(zoo.spur_ways() - set(drop_spur))
    ]
    signed = {"highway": "cycleway", "bicycle": "designated"}
    ways.append((1, trail_tags or {**signed, "name": "Rock Creek Trail"}, line(lon, lat)))
    for way_id in (2, 3, 4):
        ways.append((way_id, {**signed, "name": "Zoo Loop Trail"}, line(lon, lat)))
    ways.append((6, {"highway": "footway", "name": "Asia Trail"}, line(lon, lat)))
    no_bicycle = {
        way_id: zoo.NO_BICYCLE
        for way_id, tags, coords in ways
        if zoo.closed_way(way_id, tags, coords)
    }
    return ways, no_bicycle


def test_the_rebuild_checks_the_zoo_rule_still_fits_the_extract():
    # Hunt A5 (2026-11-08): seven hand-listed spur ids and a tag test had no rebuild check,
    # unlike the military and secured rules; now `pipeline.run.assert_zoo_rule` fails on these.
    assert zoo.check(*_zoo_extract()) == []
    # A renumbered spur way.
    problems = zoo.check(*_zoo_extract(drop_spur=(183192886,)))
    assert len(problems) == 1 and "183192886" in problems[0]
    # The Rock Creek Trail piece retagged past the rule (no name, no bicycle tag): closed,
    # so no piece of the trail is open and the open trail ways fall below the floor.
    problems = zoo.check(*_zoo_extract(trail_tags={"highway": "path", "foot": "designated"}))
    assert any("Rock Creek Trail" in p for p in problems)
    assert any("floor" in p for p in problems)
    # An extract with nothing inside the Zoo (a test's, or another region's) is not checked.
    assert zoo.check([(1, {"highway": "footway"}, line(*OUTSIDE))], {}) == []


def test_assert_zoo_rule_fails_the_rebuild():
    from types import SimpleNamespace

    import pytest

    from pipeline import run
    from pipeline.extract import Way

    ways, no_bicycle = _zoo_extract(drop_spur=(183192886,))
    context = SimpleNamespace(
        ways=[
            Way(osm_id=i, tags=t, node_ids=list(range(len(c))), coordinates=c) for i, t, c in ways
        ],
        no_bicycle=no_bicycle,
    )
    with pytest.raises(run.ValidationFailed, match="Zoo spur"):
        run.assert_zoo_rule(context)


def test_the_spur_is_not_closed_and_is_named_by_id():
    spur = zoo.spur_ways()
    assert {50524918, 183192886, 1244165507} <= spur
    assert len(spur) == 7
    for way_id in spur:
        assert not zoo.closed_way(way_id, {"highway": "footway", "bicycle": "no"}, line(*INSIDE))


def test_a_destination_inside_goes_to_the_racks():
    assert zoo.redirect(*INSIDE) == zoo.racks()
    assert zoo.redirect(*OUTSIDE) is None
    assert zoo.contains(zoo.racks())


def test_the_fixture_names_the_racks_node():
    spec = zoo.access()["spur"]["racks"]
    assert spec["node"] == 9827008403
    assert "bicycle_parking" in spec["tags"]


def test_a_way_is_inside_by_its_midpoint_not_its_first_node():
    footway = {"highway": "footway", "bicycle": "no"}
    # Starts and ends outside the outline, and runs through the middle of the Zoo.
    through = [(INSIDE[0] - 0.006, INSIDE[1]), (INSIDE[0] + 0.006, INSIDE[1])]
    assert not zoo.contains(through[0])
    assert zoo.closed_way(1, footway, through)
    # Starts inside it, and runs a mile and more away: its midpoint is outside.
    away = [INSIDE, (INSIDE[0] + 0.02, INSIDE[1])]
    assert zoo.contains(away[0])
    assert not zoo.closed_way(1, footway, away)
