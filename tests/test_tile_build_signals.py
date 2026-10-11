"""Signalised trail crossings reach the router's signal flag, in real tiles.

FOLLOWUP-SIGNAL-DERIVE. Valhalla's parser reads a node's signal from
`highway=traffic_signals` alone, so a crossing mapped `highway=crossing` +
`crossing=traffic_signals` on its node, or `crossing=traffic_signals` on the
crossing way alone, read "no signal mapped" in the junction model
(`core.junctions` reads `/locate`'s node `traffic_signal`). This builds a small
extract of a road crossed by trails, through the rebuild's own node marking
(`pipeline.signals`, `pipeline.extract.write_extract`) and the repo's graph.lua,
and asks `/locate` which crossing nodes carry the flag.

Like tests/test_tile_build_access.py, whose helpers it uses, it needs
`valhalla_build_tiles`, `valhalla_service` and `osmium` on PATH and skips without
them (ROUTEMAKER_REQUIRE_TILE_BUILD=1 makes a missing binary a failure).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest
import test_tile_build_access as tiles_test

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

ROAD = {"highway": "secondary", "name": "Test Road", "lanes": "2"}
TRAIL = {"highway": "path", "bicycle": "designated", "foot": "designated"}
SIGNALISED_WAY = {
    "highway": "footway",
    "footway": "crossing",
    "crossing": "traffic_signals",
    "bicycle": "yes",
}

# (name, crossing-node tags, crossing-way tags, whether the router should see a signal)
CASES = [
    ("a node mapped highway=traffic_signals (the control)",
     {"highway": "traffic_signals", "crossing": "traffic_signals"},
     {**SIGNALISED_WAY}, True),
    ("a node mapped highway=crossing + crossing=traffic_signals",
     {"highway": "crossing", "crossing": "traffic_signals"},
     {**SIGNALISED_WAY}, True),
    ("a node mapped highway=crossing + crossing:signals=yes",
     {"highway": "crossing", "crossing": "marked", "crossing:signals": "yes"},
     {**SIGNALISED_WAY, "crossing": "marked", "crossing:signals": "yes"}, True),
    ("a signal mapped on the crossing way alone",
     {},
     {**SIGNALISED_WAY}, True),
    ("an unsignalised marked crossing",
     {"highway": "crossing", "crossing": "uncontrolled"},
     {**SIGNALISED_WAY, "crossing": "uncontrolled"}, False),
    ("a flashing beacon (RRFB)",
     {"highway": "crossing", "crossing": "uncontrolled", "flashing_lights": "button"},
     {**SIGNALISED_WAY, "crossing": "uncontrolled", "flashing_lights": "button"}, False),
    ("a node that says uncontrolled under a way that says signals",
     {"highway": "crossing", "crossing": "uncontrolled"},
     {**SIGNALISED_WAY}, False),
    ("a node with no tags under an unsignalised way",
     {},
     {**SIGNALISED_WAY, "crossing": "unmarked"}, False),
]  # fmt: skip


def _osm_xml(cases):
    """Per case: a north-south road of three nodes and an east-west trail of
    crossing way plus path, sharing the road's middle node, 220 m from the next."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="t">']
    nodes, ways, where = [], [], {}
    node_id, way_id = 1, 1001
    for index, (name, node_tags, way_tags, _) in enumerate(cases):
        lon = -77.000 + index * 0.003
        lat = 38.900
        south, middle, north, west, east = range(node_id, node_id + 5)
        node_id += 5
        points = {
            south: (lon, lat - 0.001, {}),
            middle: (lon, lat, node_tags),
            north: (lon, lat + 0.001, {}),
            west: (lon - 0.0008, lat, {}),
            east: (lon + 0.0008, lat, {}),
        }
        for nid, (x, y, tags) in sorted(points.items()):
            body = "".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())
            nodes.append(f'<node id="{nid}" version="1" lat="{y:.6f}" lon="{x:.6f}">{body}</node>')
        for refs, tags in (((south, middle, north), ROAD), ((west, middle), way_tags),
                           ((middle, east), way_tags)):  # fmt: skip
            body = "".join(f'<nd ref="{r}"/>' for r in refs)
            body += "".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())
            ways.append(f'<way id="{way_id}" version="1">{body}</way>')
            way_id += 1
        where[name] = (middle, lon, lat)
    lines += nodes + ways + ["</osm>"]
    return "\n".join(lines) + "\n", where


def build_and_read(work: Path, cases=CASES) -> dict[str, bool]:
    from pipeline import extract, signals

    work.mkdir(parents=True, exist_ok=True)
    xml, where = _osm_xml(cases)
    (work / "raw.osm").write_text(xml)
    subprocess.run(
        ["osmium", "cat", "-O", str(work / "raw.osm"), "-o", str(work / "raw.osm.pbf")],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    ways = extract.read_ways(work / "raw.osm.pbf")
    marked = signals.node_tags(signals.signal_nodes(ways))
    extract.write_extract(work / "raw.osm.pbf", work / "fixture.osm.pbf", {}, [], {},
                          node_tags=marked)  # fmt: skip
    (work / "tiles").mkdir(exist_ok=True)
    port = tiles_test._free_port()
    config = tiles_test._config(work, REPO / "lua", port)
    env = {**tiles_test.os.environ, "ROUTEMAKER_LUA_DIR": str(REPO / "lua")}
    built = subprocess.run(
        ["valhalla_build_tiles", "-c", str(config), str(work / "fixture.osm.pbf")],
        capture_output=True, text=True, timeout=tiles_test.BUILD_TIMEOUT_S, env=env,
        preexec_fn=tiles_test._limits,
    )  # fmt: skip
    log = built.stdout + built.stderr
    assert built.returncode == 0, log[-3000:]
    assert "Using LUA script" in log
    assert "ROUTEMAKER-VIOLATION" not in log, log[-3000:]
    service = subprocess.Popen(
        ["valhalla_service", str(config), "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        preexec_fn=tiles_test._limits,
    )  # fmt: skip
    try:
        deadline = tiles_test.time.monotonic() + 30
        while True:
            try:
                tiles_test._post(port, "status", {})
                break
            except OSError:
                if tiles_test.time.monotonic() > deadline or service.poll() is not None:
                    raise RuntimeError("valhalla_service did not come up") from None
                tiles_test.time.sleep(0.2)
        seen = {}
        for name, (_, lon, lat) in where.items():
            answer = tiles_test._post(
                port,
                "locate",
                {"locations": [{"lon": lon, "lat": lat, "radius": 5}], "verbose": True,
                 "costing": "bicycle"},
            )  # fmt: skip
            located = answer[0].get("nodes") or []
            assert located, f"{name}: /locate found no node at the crossing"
            seen[name] = any(node.get("traffic_signal") for node in located)
        return seen
    finally:
        service.kill()
        service.wait(timeout=10)


def test_signalised_crossings_reach_the_router(tmp_path) -> None:
    missing = tiles_test.missing_binaries()
    if missing:
        tiles_test._skip_or_fail(missing)
    seen = build_and_read(tmp_path)
    wrong = [
        f"{name}: {'a signal' if seen[name] else 'no signal'} in the tile"
        for name, _, _, expected in CASES
        if seen[name] != expected
    ]
    assert not wrong, "\n".join(wrong)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
