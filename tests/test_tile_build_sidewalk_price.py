"""A ridden sidewalk's price, checked in real Valhalla tiles (routemaker.sidewalks).

The owner, 2026-10-20, chose "Also sidewalks as last resort": a sidewalk is ridden
where the road beside it is very stressful, and not otherwise. The transform prices it
(`rm:sidewalk`, lua/routemaker_remap.lua `SIDEWALK_SPEED`) and the claim is about what
Valhalla's bicycle costing then chooses, so this builds a road with a sidewalk beside it,
reached from side streets at both ends, once per road rating, and asks which way a
route between the side streets takes.

Like tests/test_tile_build_access.py, it needs `valhalla_build_tiles`,
`valhalla_service` and `osmium` on PATH and skips without them.
"""

from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest
import test_tile_build_access as tba

from core import presets

LAT0, LON0 = 38.95, -77.0
SIDEWALK = {
    "highway": "footway",
    "footway": "sidewalk",
    "rm:trail_class": "yes",
    "rm:sidewalk": "yes",
    "rm:stress_tier": "3",
}
SIDE_STREET = {"highway": "residential", "rm:stress_tier": "1"}


def road(tier: int, half: bool = False) -> dict[str, str]:
    tags = {"highway": "secondary", "maxspeed": "40 mph", "lanes": "4", "rm:stress_tier": str(tier)}
    if half:
        tags["rm:stress_half"] = "yes"
    return tags


# (name, road tags, slider position, whether the route rides the sidewalk)
CASES = [
    ("LTS 2 at Default", road(2), 70, False),
    ("LTS 3 at Default", road(3), 70, False),
    ("LTS 3 at the calm end", road(3), 80, False),
    ("LTS 3.5 at Default", road(3, half=True), 70, False),
    ("LTS 4 at Default", road(4), 70, True),
    ("LTS 4 at Balanced", road(4), 40, True),
    ("LTS 4 at the direct end", road(4), 0, False),
    ("LTS 4.5 at Default", road(4, half=True), 70, True),
    ("Avoid at Default", road(5), 70, True),
]


def _at(east: float, north: float) -> tuple[float, float]:
    lon = LON0 + east / (111_320 * math.cos(math.radians(LAT0)))
    return lon, LAT0 + north / 110_570


def _osm() -> tuple[str, dict[str, tuple[tuple[float, float], tuple[float, float], int]]]:
    """Per case: an 800 m road, a sidewalk 8 m beside it joined at both ends by a
    crosswalk, and a side street at each end."""
    nodes: dict[int, tuple[float, float]] = {}
    ways = []
    where = {}
    for index, (name, road_tags, _, _) in enumerate(CASES):
        north = index * 400.0
        base = 1000 * (index + 1)
        on_road, beside = [], []
        for step, east in enumerate(range(0, 801, 100)):
            nodes[base + step] = _at(east, north)
            on_road.append(base + step)
            nodes[base + 100 + step] = _at(east, north + 8)
            beside.append(base + 100 + step)
        for offset, east in ((200, 0), (201, 800)):
            nodes[base + offset] = _at(east, north - 150)
        way = 10 * (index + 1)
        crossing = {**SIDEWALK, "footway": "crossing"}
        ways += [
            (way, on_road, road_tags),
            (way + 1, beside, SIDEWALK),
            (way + 2, [on_road[0], beside[0]], crossing),
            (way + 3, [beside[-1], on_road[-1]], crossing),
            (way + 4, [base + 200, on_road[0]], SIDE_STREET),
            (way + 5, [on_road[-1], base + 201], SIDE_STREET),
        ]
        where[name] = (_at(0, north - 140), _at(800, north - 140), way + 1)
    # osmium and the tile builder want nodes, then ways, each in id order.
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="t">']
    for node, (lon, lat) in sorted(nodes.items()):
        lines.append(f'<node id="{node}" version="1" lat="{lat:.7f}" lon="{lon:.7f}"/>')
    for way, refs, tags in ways:
        lines.append(f'<way id="{way}" version="1">')
        lines += [f'<nd ref="{ref}"/>' for ref in refs]
        lines += [f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items()]
        lines.append("</way>")
    lines.append("</osm>")
    return "\n".join(lines) + "\n", where


def _ways_ridden(port: int, start, end, stress: int) -> set[int]:
    body = {
        "locations": [{"lon": start[0], "lat": start[1]}, {"lon": end[0], "lat": end[1]}],
        "costing": "bicycle",
        "costing_options": presets.costing("default", stress=stress),
    }
    shape = tba._post(port, "route", body)["trip"]["legs"][0]["shape"]
    traced = tba._post(
        port,
        "trace_attributes",
        {
            "encoded_polyline": shape,
            "shape_match": "edge_walk",
            "costing": "bicycle",
            "costing_options": body["costing_options"],
            "filters": {"attributes": ["edge.way_id"], "action": "include"},
        },
    )
    return {edge["way_id"] for edge in traced["edges"]}


def test_a_sidewalk_is_ridden_only_beside_a_very_stressful_road(tmp_path: Path) -> None:
    missing = tba.missing_binaries()
    if missing:
        tba._skip_or_fail(missing)
    xml, where = _osm()
    (tmp_path / "tiles").mkdir()
    (tmp_path / "fixture.osm").write_text(xml)
    port = tba._free_port()
    config = tba._config(tmp_path, tba.REPO / "lua", port)
    env = {**tba.os.environ, "ROUTEMAKER_LUA_DIR": str(tba.REPO / "lua")}
    subprocess.run(
        ["osmium", "cat", "-O", str(tmp_path / "fixture.osm"), "-o", str(tmp_path / "f.osm.pbf")],
        check=True,
        capture_output=True,
        timeout=60,
    )
    built = subprocess.run(
        ["valhalla_build_tiles", "-c", str(config), str(tmp_path / "f.osm.pbf")],
        capture_output=True,
        text=True,
        timeout=tba.BUILD_TIMEOUT_S,
        env=env,
        preexec_fn=tba._limits,
    )
    assert built.returncode == 0, built.stderr[-2000:]
    service = subprocess.Popen(
        ["valhalla_service", str(config), "1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        preexec_fn=tba._limits,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                tba._post(port, "status", {})
                break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail("valhalla_service did not come up")
                time.sleep(0.2)
        wrong = []
        for name, _, stress, rides in CASES:
            start, end, sidewalk = where[name]
            ridden = sidewalk in _ways_ridden(port, start, end, stress)
            if ridden != rides:
                wrong.append(f"{name}: {'rode' if ridden else 'did not ride'} the sidewalk")
        assert not wrong, "\n".join(wrong)
    finally:
        service.kill()
        service.wait(timeout=10)
