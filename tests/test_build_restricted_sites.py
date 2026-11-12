"""The closed sites' build step (scripts/build_restricted_sites.py): shading, labels, gates."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("osmium")
pytest.importorskip("shapely")

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_restricted_sites.py"

spec = importlib.util.spec_from_file_location("build_restricted_sites", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["build_restricted_sites"] = mod
spec.loader.exec_module(mod)
ra = mod.ra

W, S, E, N = -76.85, 39.0, -76.84, 39.01
SQUARE = [(W, S), (E, S), (E, N), (W, N), (W, S)]


def area(ring, osm, name):
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return ra.named_area(((min(xs), min(ys), max(xs), max(ys)), [ring], []), name, osm)


def areas(**extra):
    out = {kind: [] for kind in ra.KINDS}
    out[ra.SECURED] = [area(SQUARE, "w1", "Test Space Center")]
    for kind, found in extra.items():
        out[kind] = found
    return out


GATE = (-76.845, 38.999)
WAYS = [
    # The public road along the fence, with the gate's node on it.
    (
        10,
        {"highway": "secondary", "name": "Outer Rd"},
        [(-76.86, 38.999), (-76.848, 38.999), GATE, (-76.83, 38.999)],
    ),
    # The campus road the rule closes, from the gate in.
    (11, {"highway": "tertiary", "name": "Inner Rd"}, [GATE, (-76.845, 39.003), (-76.845, 39.008)]),
    # A numbered road through the campus: open.
    (12, {"highway": "primary", "ref": "MD 999"}, [(-76.849, 39.005), (-76.841, 39.005)]),
    # A campus footway meeting the public road: no gate while a road gate exists.
    (13, {"highway": "footway"}, [(-76.848, 38.999), (-76.848, 39.004), (-76.848, 39.008)]),
]


@pytest.fixture(autouse=True)
def no_hand_drawn_areas(tmp_path, monkeypatch):
    """The repo's own hand-drawn areas (`fixtures/restricted-sites/`, the Patuxent closed area)
    stay out of these synthetic sites; `drawn_features` has its own tests below."""
    monkeypatch.setattr(mod, "DRAWN", tmp_path / "no-drawn-areas")


def by(found, key):
    return [f for f in found["features"] if key in f["properties"]]


def test_a_site_is_shaded_labelled_and_gated():
    found = mod.collection(areas(), WAYS)
    (site,) = [f for f in by(found, "kind")]
    assert site["properties"] == {"site": "w1", "kind": "secured", "name": "Test Space Center"}
    assert site["geometry"]["type"] == "Polygon"
    (label,) = [f for f in by(found, "name") if "kind" not in f["properties"]]
    lon, lat = label["geometry"]["coordinates"]
    assert W < lon < E and S < lat < N
    assert [g["geometry"]["coordinates"] for g in by(found, "gate")] == [list(GATE)]
    (open_ways,) = by(found, "open")
    assert open_ways["properties"] == {"open": "w1"}
    assert open_ways["geometry"]["coordinates"][0][0] == [-76.849, 39.005]


def test_a_site_with_only_closed_paths_takes_their_gates():
    ways = [w for w in WAYS if w[0] != 11]
    gates = [g["geometry"]["coordinates"] for g in by(mod.collection(areas(), ways), "gate")]
    assert gates == [[-76.848, 38.999]]


def test_small_sites_and_the_pentagon_reservation_are_left_out():
    tiny = area([(W, S), (W + 0.0002, S), (W + 0.0002, S + 0.0002), (W, S)], "w2", "Armory")
    pentagon = area(SQUARE, "w916068128", "The Pentagon")
    sites = mod.sites_of(areas(military=[tiny, pentagon]))
    assert [mod.site_id(a) for _k, a in sites] == ["w1"]


def test_an_unnamed_or_small_site_is_shaded_without_a_label():
    small = [(W, S), (W + 0.003, S), (W + 0.003, S + 0.003), (W, S + 0.003), (W, S)]
    found = mod.collection(areas(secured=[area(small, "w3", "Small Lab")]), [])
    assert [f["properties"]["site"] for f in by(found, "kind")] == ["w3"]
    assert [f for f in by(found, "name") if "kind" not in f["properties"]] == []


def test_area_in_square_metres():
    assert mod.ring_m2(SQUARE) == pytest.approx(0.01 * 0.01 * 111_320**2 * 0.7771, rel=0.01)


def test_only_ways_near_a_site_are_read():
    cells = mod.site_cells([(W, S, E, N)])
    assert mod.near_sites([(-76.845, 39.005)], cells)
    assert not mod.near_sites([(-77.5, 38.5)], cells)


def test_hand_drawn_closed_areas_are_shaded_and_labelled(tmp_path):
    ring = [[W, S], [E, S], [E, N], [W, S]]
    (tmp_path / "x.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":'
        '{"site":"x-closed","name":"Refuge closed area","source":"https://example.org"},'
        '"geometry":{"type":"Polygon","coordinates":[' + str(ring) + "]}}]}"
    )
    found = mod.drawn_features(tmp_path)
    assert found[0]["properties"] == {
        "site": "x-closed",
        "kind": "closed",
        "name": "Refuge closed area",
    }
    assert found[1]["properties"] == {"site": "x-closed", "name": "Refuge closed area"}
    assert mod.drawn_features(tmp_path / "none") == []


def test_a_drawn_area_without_an_id_fails_the_build(tmp_path):
    (tmp_path / "x.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},'
        '"geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]}}]}'
    )
    with pytest.raises(ValueError):
        mod.drawn_features(tmp_path)


def test_a_cemetery_drive_or_an_untagged_footway_is_no_way_in():
    # The campus road meets only a cemetery's drive and an untagged footway: no gate.
    cemetery = area(
        [(-76.86, 38.99), (-76.83, 38.99), (-76.83, 38.9995), (-76.86, 38.9995), (-76.86, 38.99)],
        "w9",
        "A Cemetery",
    )
    ways = [
        (20, {"highway": "service"}, [(-76.86, 38.995), GATE, (-76.83, 38.995)]),
        (21, {"highway": "footway"}, [GATE, (-76.845, 38.99)]),
        WAYS[1],
    ]
    found = mod.collection(areas(cemetery=[cemetery]), ways)
    assert by(found, "gate") == []
    # The same drive outside any cemetery is a way in.
    assert len(by(mod.collection(areas(), ways), "gate")) == 1


def test_a_small_unshaded_sites_gate_is_not_its_neighbours():
    # An armory yard under the shading floor, beside the campus, with its own gate.
    yard = [
        (E + 0.0002, S),
        (E + 0.0006, S),
        (E + 0.0006, S + 0.0004),
        (E + 0.0002, S + 0.0004),
        (E + 0.0002, S),
    ]
    ways = [
        (30, {"highway": "secondary"}, [(E + 0.0004, S - 0.001), (E + 0.0004, S - 0.0001)]),
        (
            31,
            {"highway": "service"},
            [(E + 0.0004, S - 0.0001), (E + 0.0004, S + 0.0002), (E + 0.0004, S + 0.0003)],
        ),
    ]
    found = mod.collection(areas(military=[area(yard, "w8", "Armory")]), ways)
    assert by(found, "gate") == []
