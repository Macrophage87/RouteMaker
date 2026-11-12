"""A trip point inside a closed site goes to the site's gate (routemaker.restricted_sites;
the owner, 2026-11-12: "route them to the gate and they can figure it out themselves")."""

from __future__ import annotations

from unittest import mock

from routemaker import restricted_sites as rs

W, S, E, N = -76.85, 39.0, -76.84, 39.01
GATE = [-76.845, 38.999]
FAR_GATE = [-76.839, 39.009]
DATA = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"site": "w1", "kind": "secured", "name": "Test Space Center"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[W, S], [E, S], [E, N], [W, N], [W, S]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"site": "w1", "name": "Test Space Center"},
            "geometry": {"type": "Point", "coordinates": [-76.845, 39.005]},
        },
        {
            "type": "Feature",
            "properties": {"gate": "w1"},
            "geometry": {"type": "Point", "coordinates": GATE},
        },
        {
            "type": "Feature",
            "properties": {"gate": "w1"},
            "geometry": {"type": "Point", "coordinates": FAR_GATE},
        },
        {
            "type": "Feature",
            "properties": {"open": "w1"},
            "geometry": {
                "type": "MultiLineString",
                "coordinates": [[[-76.849, 39.009], [-76.841, 39.009]]],
            },
        },
    ],
}
SITES = rs.parse(DATA)


def test_parse_reads_the_site_its_gates_and_open_ways():
    (site,) = SITES
    assert site.site == "w1" and site.name == "Test Space Center"
    assert site.gates == (tuple(GATE), tuple(FAR_GATE))
    assert len(site.open_lines) == 1


def test_a_point_inside_goes_to_the_nearest_gate():
    found = rs.redirect(-76.846, 39.002, SITES)
    assert found is not None and found[1] == tuple(GATE)


def test_a_point_outside_or_near_an_open_way_is_not_moved():
    assert rs.redirect(-76.86, 39.002, SITES) is None
    # About 55 m from the open road through the site: routed as it is.
    assert rs.redirect(-76.845, 39.0085, SITES) is None


def test_a_site_without_gates_is_routed_as_before():
    data = {**DATA, "features": [f for f in DATA["features"] if "gate" not in f["properties"]]}
    assert rs.redirect(-76.846, 39.002, rs.parse(data)) is None


def test_no_file_means_no_sites(tmp_path):
    rs.sites.cache_clear()
    try:
        with mock.patch.object(rs, "SITES_FILE", tmp_path / "missing.json"):
            assert rs.sites() == ()
    finally:
        rs.sites.cache_clear()


def test_the_router_moves_the_point_and_says_so():
    from core import routing

    with mock.patch.object(rs, "sites", return_value=SITES):
        points, moved = routing.move_restricted_points(
            [[-76.9, 38.98], [-76.846, 39.002], [-76.846, 39.003]], skip=set()
        )
        assert points[0] == [-76.9, 38.98]
        # Two points with one nearest gate: the second is routed as asked, not a trip of nothing.
        assert points[1] == GATE and points[2] == [-76.846, 39.003]
        assert [m["index"] for m in moved] == [1]
        assert moved[0]["reason"] == "restricted_gate"
        assert moved[0]["note"] == "Restricted site. Route goes to the gate."
        # The end, on its own: "ends at"; on a loop the last point asked is a turnaround.
        _points, end = routing.move_restricted_points([[-76.9, 38.98], [-76.846, 39.003]])
        assert end[0]["note"] == "Restricted site. Route ends at the gate."
        assert end[0]["asked"] == [-76.846, 39.003]
        _points, turn = routing.move_restricted_points(
            [[-76.9, 38.98], [-76.846, 39.003]], loop=True
        )
        assert turn[0]["note"] == "Restricted site. Route goes to the gate."
        # A ride's re-plan's start is the rider: never moved.
        _points, kept = routing.move_restricted_points(
            [[-76.846, 39.002], [-76.9, 38.98]], skip={0}
        )
        assert kept == []


def test_the_file_the_map_and_router_read_parses():
    found = rs.parse(__import__("json").loads(rs.SITES_FILE.read_text(encoding="utf-8")))
    assert all(site.polygons for site in found)
