"""No U-turn round a median's end, in real tiles.

The owner, 2026-10-24, Frederick Road (MD 144) at the Beltway in Catonsville:
"There were some left turns on my route across a median", "Which wasn't
possible". The two carriageways round the island meet the two-way road at a node
each end, and the router turned from one onto the other there as at any junction.
This builds the island as OSM maps it, through the rebuild's own reading
(`routemaker.divided.median_uturns`) and writer (`pipeline.extract.write_extract`)
and the repo's graph.lua, and routes a bicycle from the westbound carriageway to the
eastbound one: with the restrictions it must find another way than the U-turn.

Like tests/test_tile_build_signals.py it needs `valhalla_build_tiles`,
`valhalla_service` and `osmium` on PATH and skips without them
(ROUTEMAKER_REQUIRE_TILE_BUILD=1 makes a missing binary a failure).
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

FREDERICK = {"highway": "primary", "name": "Frederick Road", "lanes": "2", "oneway": "yes"}
TWO_WAY = {**FREDERICK, "oneway": "no"}
# Nodes (lon, lat): the island's west nose at the ramp signal (W), Woodlawn Avenue
# off the westbound carriageway (N), the east nose (E); the road runs on two-way
# 300 m west of W (to a dead end, here) and 300 m east of E.
POINTS = {
    1: (-76.72710, 39.27300),
    2: (-76.72374, 39.27373),  # W
    3: (-76.72365, 39.27380),
    4: (-76.72322, 39.27389),  # N
    5: (-76.72363, 39.27369),
    6: (-76.72349, 39.27373),
    7: (-76.72320, 39.27381),
    8: (-76.72303, 39.27387),
    9: (-76.72291, 39.27392),  # E
    10: (-76.71960, 39.27480),
    11: (-76.72392, 39.27582),
}
WAYS = [
    (425007805, [1, 2], TWO_WAY),
    (425007803, [4, 3, 2], FREDERICK),
    (425007808, [2, 5, 6, 7, 8, 9], FREDERICK),
    (425007797, [9, 4], FREDERICK),
    (202623983, [9, 10], TWO_WAY),
    (5318288, [4, 11], {"highway": "residential", "name": "Woodlawn Avenue"}),
]
# From the westbound carriageway just past Woodlawn Avenue to the eastbound one
# just past the west nose: 50 m by the U-turn, more than 600 m without it.
START = (-76.72345, 39.27385)
END = (-76.72356, 39.27371)
U_TURN_KM = 0.15


def _osm_xml() -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="t">']
    for node_id, (lon, lat) in sorted(POINTS.items()):
        lines.append(f'<node id="{node_id}" version="1" lat="{lat:.7f}" lon="{lon:.7f}"/>')
    for way_id, refs, tags in sorted(WAYS):
        body = "".join(f'<nd ref="{r}"/>' for r in refs)
        body += "".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())
        lines.append(f'<way id="{way_id}" version="1">{body}</way>')
    lines.append("</osm>")
    return "\n".join(lines) + "\n"


def route_km(work: Path, restrict: bool) -> tuple[float, list]:
    """Build the island into tiles, with the median ends' restrictions or without,
    and the bicycle route's length from START to END; with the restrictions found."""
    from pipeline import extract, variants
    from routemaker import divided

    work.mkdir(parents=True, exist_ok=True)
    (work / "raw.osm").write_text(_osm_xml())
    subprocess.run(
        ["osmium", "cat", "-O", str(work / "raw.osm"), "-o", str(work / "raw.osm.pbf")],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    uturns = divided.median_uturns(extract.read_ways(work / "raw.osm.pbf"),
                                   variants.has_contraflow_tag)  # fmt: skip
    relations = [
        (extract.SYNTHETIC_RELATION_ID_FLOOR + i,
         [("w", a, "from"), ("n", node, "via"), ("w", b, "to")], dict(divided.NO_UTURN_TAGS))
        for i, (a, node, b) in enumerate(uturns)
    ] if restrict else []  # fmt: skip
    extract.write_extract(work / "raw.osm.pbf", work / "fixture.osm.pbf", {}, [], {},
                          new_relations=relations)  # fmt: skip
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
        answer = tiles_test._post(
            port,
            "route",
            {"locations": [{"lon": START[0], "lat": START[1]}, {"lon": END[0], "lat": END[1]}],
             "costing": "bicycle", "units": "kilometers"},
        )  # fmt: skip
        return answer["trip"]["summary"]["length"], uturns
    finally:
        service.kill()
        service.wait(timeout=10)


def test_the_router_no_longer_u_turns_round_the_median(tmp_path) -> None:
    missing = tiles_test.missing_binaries()
    if missing:
        tiles_test._skip_or_fail(missing)
    # The control: without the restrictions the router takes the U-turn at W.
    without, _ = route_km(tmp_path / "without", restrict=False)
    assert without < U_TURN_KM, f"the control route is {without} km; it no longer U-turns"
    with_them, uturns = route_km(tmp_path / "with", restrict=True)
    assert uturns == [(425007803, 2, 425007808), (425007808, 9, 425007797)]
    assert with_them > U_TURN_KM, f"the route is {with_them} km: it still U-turns at W"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
