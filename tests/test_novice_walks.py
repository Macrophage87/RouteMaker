"""Novice and Nervous walk the bike past a short busy stretch on the sidewalk beside it
(v0.11.0; the owner, 2026-10-21: "For the Novice or Nervous mode, walk a bike on sidewalk
mode should definitely be a consideration", choosing "Walk the bad stretch")."""

from __future__ import annotations

import math
import subprocess
import time
from xml.sax.saxutils import quoteattr

import pytest
import test_tile_build_access as tiles_test

from core import novice_walks, routing
from core.dedodge import encode_polyline6


def piece(name: str | None, metres: float) -> routing.Piece:
    return routing.Piece(1, -77.0, 38.9, metres, names=(name,) if name else ())


def deadline() -> routing.Deadline:
    return routing.Deadline(routing.clock() + 30, 10)


# A straight line about 1,000 m long, west to east.
LINE = [[-77.0, 38.95], [-77.0 + 1000 / (111_320 * math.cos(math.radians(38.95))), 38.95]]


def leg(a, b, metres: float) -> dict:
    return {
        "geometry": {"type": "LineString", "coordinates": [a, b]},
        "distance_m": metres,
        "duration_s": round(metres / (4.8 / 3.6), 1),
    }


class TestStretches:
    def test_runs_of_lts_4_or_worse_with_their_road(self) -> None:
        pieces = [piece("Quiet St", 300), piece("Redland Rd", 150), piece("Redland Rd", 100)]
        pieces += [piece("Calm Ave", 200), piece(None, 120)]
        classes = [("1", "path"), ("4", "none"), ("5", "none"), ("2", "none"), ("4", "none")]
        found = routing_free(novice_walks.stretches([(0, 5)], pieces, classes))
        assert found == [
            {"from_m": 300.0, "to_m": 550.0, "road": "Redland Rd", "pieces": [1, 2]},
            {"from_m": 750.0, "to_m": 870.0, "road": None, "pieces": [4]},
        ]

    def test_lts_3_is_ridden(self) -> None:
        classes = [("3", "none")]
        assert novice_walks.stretches([(0, 1)], [piece("Georgia Ave", 400)], classes) == []

    def test_a_side_street_mouth_does_not_end_the_stretch(self) -> None:
        pieces = [piece("Big Rd", 200), piece("Big Rd", 10), piece("Big Rd", 200)]
        classes = [("4", "none"), ("3", "none"), ("4", "none")]
        found = novice_walks.stretches([(0, 3)], pieces, classes)
        assert [(f["from_m"], f["to_m"], f["pieces"]) for f in found] == [(0.0, 410.0, [0, 2])]

    def test_a_stop_ends_the_stretch(self) -> None:
        pieces = [piece("Big Rd", 200), piece("Big Rd", 200)]
        classes = [("4", "none"), ("4", "none")]
        found = novice_walks.stretches([(0, 1), (1, 2)], pieces, classes)
        assert [(f["from_m"], f["to_m"]) for f in found] == [(0.0, 200.0), (200.0, 400.0)]


def routing_free(found: list[dict]) -> list[dict]:
    return [{**f, "from_m": round(f["from_m"], 1), "to_m": round(f["to_m"], 1)} for f in found]


class TestWalks:
    def stretch(self, from_m: float, to_m: float, road: str | None = "Redland Rd") -> dict:
        return {"from_m": from_m, "to_m": to_m, "road": road, "pieces": [0]}

    def test_a_short_stretch_with_a_sidewalk_is_walked(self) -> None:
        asked = []

        def walk(a, b):
            asked.append((a, b))
            return leg(a, b, 330.0)

        found = novice_walks.walks(
            [self.stretch(200, 500)], LINE, 1000.0, 1000.0, walk, lambda _line: 20.0
        )
        assert len(found) == 1
        walked = found[0]
        assert (walked["from_m"], walked["to_m"], walked["road"]) == (200, 500, "Redland Rd")
        assert walked["ride_m"] == 300.0
        assert walked["distance_m"] == 330.0
        # Asked from the stretch's start to its end on the route's line.
        (a, b) = asked[0]
        assert a[0] == pytest.approx(LINE[0][0] + (LINE[1][0] - LINE[0][0]) * 0.2, abs=1e-6)
        assert b[0] == pytest.approx(LINE[0][0] + (LINE[1][0] - LINE[0][0]) * 0.5, abs=1e-6)

    @pytest.mark.parametrize(("from_m", "to_m"), [(100, 150), (0, 900)])
    def test_a_crossing_or_a_long_stretch_is_not_walked(self, from_m, to_m) -> None:
        def walk(a, b):
            raise AssertionError("no walk is asked for")

        stretch = self.stretch(from_m, to_m)
        assert novice_walks.walks([stretch], LINE, 1000.0, 1000.0, walk, lambda _: 0.0) == []

    def test_a_walk_on_the_carriageway_is_not_offered(self) -> None:
        found = novice_walks.walks(
            [self.stretch(200, 500)],
            LINE,
            1000.0,
            1000.0,
            lambda a, b: leg(a, b, 300.0),
            lambda _line: 300.0,
        )
        assert found == []

    def test_a_walk_the_long_way_round_is_not_offered(self) -> None:
        found = novice_walks.walks(
            [self.stretch(200, 500)],
            LINE,
            1000.0,
            1000.0,
            lambda a, b: leg(a, b, 700.0),
            lambda _line: 0.0,
        )
        assert found == []

    def test_no_walk_on_foot_or_no_trace_offers_nothing(self) -> None:
        stretch = [self.stretch(200, 500)]
        assert novice_walks.walks(stretch, LINE, 1000.0, 1000.0, lambda a, b: None, None) == []
        found = novice_walks.walks(
            stretch, LINE, 1000.0, 1000.0, lambda a, b: leg(a, b, 300.0), lambda _line: None
        )
        assert found == []

    def test_at_most_a_few_walks_are_asked_for(self) -> None:
        asked = []

        def walk(a, b):
            asked.append(a)
            return None

        many = [self.stretch(i * 200, i * 200 + 100) for i in range(5)]
        novice_walks.walks(many, LINE, 1000.0, 1000.0, walk, lambda _: 0.0)
        assert len(asked) == novice_walks.MOST

    def test_the_directions_measure_is_the_routers(self) -> None:
        # Pieces measuring 900 m on a route the router says is 1,000 m.
        found = novice_walks.walks(
            [self.stretch(180, 450)],
            LINE,
            900.0,
            1000.0,
            lambda a, b: leg(a, b, 300.0),
            lambda _: 0.0,
        )
        assert (found[0]["from_m"], found[0]["to_m"], found[0]["ride_m"]) == (200, 500, 300.0)


def a_walk(from_m=1609, to_m=1909, road="Redland Road", distance_m=320.0, duration_s=240.0):
    return {
        "from_m": from_m,
        "to_m": to_m,
        "road": road,
        "ride_m": float(to_m - from_m),
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        "distance_m": distance_m,
        "duration_s": duration_s,
        "pieces": [3],
    }


class TestWords:
    def test_the_directions_line(self) -> None:
        assert novice_walks.line(a_walk()) == (
            "At 1.0 mi (1.6 km): walk your bike on the sidewalk along Redland Road for"
            " 0.2 mi (320 m), about 4 min. The road is too busy to ride."
        )

    def test_a_short_walk_in_feet_and_an_unnamed_road(self) -> None:
        text = novice_walks.line(a_walk(road=None, distance_m=120.0, duration_s=20))
        assert "along the busy road for 390 ft (120 m), about 1 min." in text

    def test_the_walk_is_a_walk_entry_in_route_order(self) -> None:
        description = [
            {"kind": "stretch", "from_m": 0, "text": "a"},
            {"kind": "stretch", "from_m": 1609, "text": "b"},
            {"kind": "stretch", "from_m": 2500, "text": "c"},
        ]
        out = novice_walks.with_entries(description, [a_walk()])
        assert [e["kind"] for e in out] == ["stretch", "walk", "stretch", "stretch"]
        walk = out[1]
        assert (walk["from_m"], walk["to_m"], walk["street"]) == (1609, 1909, "Redland Road")
        assert walk["text"].startswith("At 1.0 mi (1.6 km): walk your bike on the sidewalk")
        assert novice_walks.with_entries(None, [a_walk()]) is None
        assert novice_walks.with_entries(description, []) is description

    def test_the_walk_replaces_the_rides_time(self) -> None:
        # A 300 m stretch ridden at 5 m/s (60 s) walked in 240 s: 180 s more.
        change = novice_walks.time_change_s([a_walk()], 10_000.0, 2_000.0)
        assert change == pytest.approx(180.0)

    def test_the_answers_walk_has_no_piece_indices(self) -> None:
        (out,) = novice_walks.public([a_walk()])
        assert "pieces" not in out
        assert out["text"] == novice_walks.line(a_walk())


class TestNoviceNote:
    def test_walked_metres_are_not_ridden(self) -> None:
        note = routing.novice_note({"1": 3000.0, "4": 300.0}, {}, None, 300.0, [{"a": 1}])
        assert note["busy_m"] == 0.0
        assert note["walked_m"] == 300.0
        assert note["walks"] == [{"a": 1}]
        assert note["transit"] is False

    def test_a_route_with_nothing_walked_says_so(self) -> None:
        note = routing.novice_note({"1": 3000.0, "4": 300.0}, {}, None)
        assert (note["busy_m"], note["walked_m"], note["walks"]) == (300.0, 0.0, [])
        assert note["transit"] is True


class TestRouterCalls:
    def test_the_walk_prefers_sidewalks_only_when_asked(self, monkeypatch) -> None:
        payloads = []

        def fake_call(variant, action, payload, _deadline):
            payloads.append(payload)
            shape = [(p["lon"], p["lat"]) for p in payload["locations"]]
            summary = {"length": 0.3, "time": 225.0}
            return {"trip": {"legs": [{"shape": encode_polyline6(shape), "summary": summary}]}}

        monkeypatch.setattr(routing, "_call", fake_call)
        routing.walk_leg(LINE[0], LINE[1], deadline())
        routing.walk_leg(LINE[0], LINE[1], deadline(), prefer_walkways=True)
        plain, preferring = (p["costing_options"]["pedestrian"] for p in payloads)
        assert "sidewalk_factor" not in plain
        assert preferring["sidewalk_factor"] == routing.WALKWAY_PREFERENCE
        assert preferring["walkway_factor"] == routing.WALKWAY_PREFERENCE

    def test_the_roadside_metres_count_main_roads_without_a_sidewalk(self, monkeypatch) -> None:
        edges = [
            {"use": "road", "road_class": "secondary", "sidewalk": "none", "length": 0.02},
            {"use": "pedestrian_crossing", "road_class": "service_other", "length": 0.01},
            {"use": "footway", "road_class": "service_other", "length": 0.3},
            {"use": "road", "road_class": "primary", "sidewalk": "both", "length": 0.1},
            {"use": "road", "road_class": "residential", "length": 0.1},
            {"use": "road", "road_class": "tertiary", "length": 0.03},
        ]
        monkeypatch.setattr(routing, "_call", lambda *args: {"edges": edges})
        assert routing.walk_roadside_m(LINE, deadline()) == 50.0

    def test_a_refused_trace_is_none(self, monkeypatch) -> None:
        def refuse(*args):
            raise routing.RouterUnavailable("down")

        monkeypatch.setattr(routing, "_call", refuse)
        assert routing.walk_roadside_m(LINE, deadline()) is None


# On real tiles (as tests/test_tile_build_access.py builds them): an LTS 4 road with its
# sidewalk mapped as a way of its own, one with none, and one tagged sidewalk=both.
LAT0, LON0 = 38.95, -77.0
ROAD = {
    "highway": "secondary",
    "maxspeed": "45 mph",
    "lanes": "4",
    "rm:stress_tier": "4",
    "name": "Busy Road",
}
KINDS = ("separate", "none", "tagged")


def _at(east: float, north: float) -> tuple[float, float]:
    return LON0 + east / (111_320 * math.cos(math.radians(LAT0))), LAT0 + north / 110_570


def _osm() -> str:
    nodes: dict[int, tuple[float, float]] = {}
    ways: list[tuple[int, list[int], dict]] = []

    def node(east, north):
        nodes[len(nodes) + 10] = _at(east, north)
        return len(nodes) + 9

    def way(refs, tags):
        ways.append((len(ways) + 10, refs, tags))

    for row, kind in enumerate(KINDS):
        north = row * 600.0
        xs = range(0, 501, 100)
        road = [node(x, north) for x in xs]
        way(road, {**ROAD, **({"sidewalk": "both"} if kind == "tagged" else {})})
        if kind == "separate":
            side = [node(x, north + 8) for x in xs]
            way(side, {"highway": "footway", "footway": "sidewalk"})
            way([road[0], side[0]], {"highway": "footway", "footway": "crossing"})
            way([side[-1], road[-1]], {"highway": "footway", "footway": "crossing"})
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="t">']
    for n, (lon, lat) in sorted(nodes.items()):
        lines.append(f'<node id="{n}" version="1" lat="{lat:.7f}" lon="{lon:.7f}"/>')
    for w, refs, tags in ways:
        lines.append(f'<way id="{w}" version="1">')
        lines += [f'<nd ref="{r}"/>' for r in refs]
        lines += [f"<tag k={quoteattr(k)} v={quoteattr(str(v))}/>" for k, v in tags.items()]
        lines.append("</way>")
    lines.append("</osm>")
    return "\n".join(lines) + "\n"


def test_on_real_tiles_only_a_road_with_a_sidewalk_is_walked(tmp_path, monkeypatch) -> None:
    missing = tiles_test.missing_binaries()
    if missing:
        tiles_test._skip_or_fail(missing)
    lua = tiles_test.REPO / "lua"
    (tmp_path / "tiles").mkdir()
    (tmp_path / "f.osm").write_text(_osm())
    port = tiles_test._free_port()
    config = tiles_test._config(tmp_path, lua, port)
    env = {**tiles_test.os.environ, "ROUTEMAKER_LUA_DIR": str(lua)}
    pbf = str(tmp_path / "f.osm.pbf")
    subprocess.run(["osmium", "cat", "-O", str(tmp_path / "f.osm"), "-o", pbf], check=True)
    built = subprocess.run(
        ["valhalla_build_tiles", "-c", str(config), pbf],
        capture_output=True,
        text=True,
        env=env,
        timeout=tiles_test.BUILD_TIMEOUT_S,
    )
    assert built.returncode == 0, built.stderr[-2000:]
    service = subprocess.Popen(
        ["valhalla_service", str(config), "1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        for _ in range(150):
            try:
                tiles_test._post(port, "status", {})
                break
            except OSError:
                time.sleep(0.2)
        monkeypatch.setattr(
            routing,
            "_call",
            lambda _v, action, payload, _d: tiles_test._post(port, action, payload),
        )
        walked = {}
        for row, kind in enumerate(KINDS):
            line = [list(_at(0, row * 600.0)), list(_at(500, row * 600.0))]
            stretch = {"from_m": 20.0, "to_m": 480.0, "road": "Busy Road", "pieces": [0]}
            found = novice_walks.walks(
                [stretch],
                line,
                500.0,
                500.0,
                lambda a, b: routing.walk_leg(a, b, deadline(), prefer_walkways=True),
                lambda shape: routing.walk_roadside_m(shape, deadline()),
            )
            walked[kind] = bool(found)
            if kind == "separate" and found:
                # On the sidewalk, 8 m north of the road, not on the road itself.
                north = max(lat for _lon, lat in found[0]["geometry"]["coordinates"])
                assert north > line[0][1] + 5 / 110_570
        assert walked == {"separate": True, "none": False, "tagged": True}
    finally:
        service.kill()
