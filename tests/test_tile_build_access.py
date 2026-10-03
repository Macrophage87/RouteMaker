"""Bicycle closures, checked in real Valhalla tiles rather than in the Lua.

The Lua suites (tests/lua) prove what the transform hands back to Valhalla. They
cannot prove what the tile says, because Valhalla's C++ parser reads tags off
that table after the transform has run. The parser opens a way to bicycles
from any `mtb:scale`, `mtb:scale:imba`, `mtb:scale:uphill` or `mtb:description`
key, whatever `bicycle` says. That is how `rm:no_bicycle=singletrack`
(OWNER-DECISIONS 90, 91, 111) passed every Lua check and still left 753
singletrack ways routable in the 2026-10-03 build (reports/SINGLETRACK-DIAG-r0).

So this builds a tiny extract with `valhalla_build_tiles`, using the repo's own
graph.lua and the serving config's mjolnir settings. It serves the result with
`valhalla_service` on a loopback port and asks `/locate` which edges a bicycle
may use. Each way stands alone and is mapped with pedestrian access, so the
pedestrian locate always finds it. A missing pedestrian edge means the fixture
is wrong, not that the closure worked.

It needs `valhalla_build_tiles`, `valhalla_service` and `osmium` on PATH, which
the pipeline image has. It skips without them. Set
ROUTEMAKER_REQUIRE_TILE_BUILD=1 to make a missing binary a failure. The image
has no pytest, so the module also runs as a script:
scripts/check_tile_build_access.sh does that inside the pipeline image.

Every child process runs under an address-space limit and a timeout. The
extract is a few kilometres of path, and the build takes seconds.
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

try:
    import pytest
except ImportError:  # the pipeline image runs this as a script
    pytest = None

REPO = Path(__file__).resolve().parents[1]
BINARIES = ("valhalla_build_tiles", "valhalla_service", "osmium")
ADDRESS_SPACE_BYTES = 4 * 1024**3
BUILD_TIMEOUT_S = 240

# The tags of way 810382238 (Cross County Trail) as the 2026-10-03 standard
# extract carries them, derived tags included.
CCT = {
    "highway": "path",
    "bicycle": "yes",
    "foot": "yes",
    "motor_vehicle": "no",
    "mtb:scale": "2",
    "surface": "dirt",
}
SINGLETRACK = {
    "rm:trail_class": "yes",
    "rm:stress_tier": "1",
    "rm:facility": "path",
    "rm:no_bicycle": "singletrack",
}

# (name, tags, bicycle may use it)
CASES: list[tuple[str, dict[str, str], bool]] = [
    ("singletrack, as the extract carries it", {**CCT, **SINGLETRACK}, False),
    (
        "singletrack rated every way upstream's parser reads",
        {
            **CCT,
            **SINGLETRACK,
            "mtb:scale:imba": "2",
            "mtb:scale:uphill": "2",
            "mtb:description": "roots",
        },
        False,
    ),
    (
        "singletrack rated by IMBA only",
        {**{k: v for k, v in CCT.items() if k != "mtb:scale"}, "mtb:scale:imba": "1", **SINGLETRACK},
        False,
    ),
    ("a CBD sidewalk", {"highway": "footway", "footway": "sidewalk", "bicycle": "yes",
                        "rm:trail_class": "yes", "rm:no_bicycle": "cbd_sidewalk"}, False),
    ("OSM bicycle=no on a path", {"highway": "path", "bicycle": "no", "foot": "yes"}, False),
    ("OSM bicycle=no on a rated path", {"highway": "path", "bicycle": "no", "foot": "yes",
                                        "mtb:scale": "0"}, False),
    ("OSM access=no on a rated path", {"highway": "path", "access": "no", "foot": "yes",
                                       "mtb:scale": "2"}, False),
    ("OSM bicycle=no on a rated track", {"highway": "track", "bicycle": "no", "foot": "yes",
                                         "mtb:scale": "1"}, False),
    ("an open path", {"highway": "path", "bicycle": "yes", "foot": "yes"}, True),
    ("an open rated trail (not singletrack)", {**CCT, "rm:trail_class": "yes",
                                               "rm:facility": "path"}, True),
    (
        "the C&O towpath above lock 21",
        {"highway": "path", "bicycle": "designated", "foot": "designated", "surface": "dirt",
         "mtb:scale:imba": "0", "rm:trail_class": "yes", "rm:facility": "path"},
        True,
    ),
]


def missing_binaries() -> list[str]:
    return [name for name in BINARIES if shutil.which(name) is None]


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES))


def _osm_xml(cases) -> tuple[str, dict[str, tuple[int, float, float]]]:
    """One three-node way per case, 220 m apart, all in one level-2 tile."""
    from xml.sax.saxutils import quoteattr

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="routemaker-test">']
    where: dict[str, tuple[int, float, float]] = {}
    node = 1
    for index, (name, tags, _) in enumerate(cases):
        lat = 38.900 + index * 0.002
        refs = []
        for lon in (-77.000, -76.998, -76.996):
            lines.append(f'<node id="{node}" version="1" lat="{lat:.6f}" lon="{lon:.6f}"/>')
            refs.append(node)
            node += 1
        way_id = 1001 + index
        lines.append(f'<way id="{way_id}" version="1">')
        lines.extend(f'<nd ref="{ref}"/>' for ref in refs)
        lines.extend(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())
        lines.append("</way>")
        where[name] = (way_id, -76.999, lat)
    lines.append("</osm>")
    return "\n".join(lines) + "\n", where


def _config(work: Path, lua_dir: Path, port: int) -> Path:
    config = json.loads((REPO / "valhalla" / "valhalla-standard.json").read_text())
    mjolnir = config["mjolnir"]
    for key in ("tile_extract", "traffic_extract", "admin", "timezone", "landmarks"):
        mjolnir[key] = str(work / f"absent-{key}")
    mjolnir["transit_dir"] = str(work / "absent-transit")
    mjolnir["transit_feeds_dir"] = str(work / "absent-transit-feeds")
    mjolnir["tile_dir"] = str(work / "tiles")
    mjolnir["graph_lua_name"] = str(lua_dir / "graph.lua")
    mjolnir["concurrency"] = 1
    mjolnir["id_table_size"] = 10_000_000
    mjolnir["data_processing"]["use_admin_db"] = False
    config["additional_data"]["elevation"] = str(work / "absent-elevation")
    config["httpd"]["service"]["listen"] = f"tcp://127.0.0.1:{port}"
    path = work / "valhalla.json"
    path.write_text(json.dumps(config, indent=1))
    return path


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _post(port: int, action: str, body: dict) -> object:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/{action}",
        json.dumps(body).encode(),
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def build_and_locate(work: Path, lua_dir: Path = REPO / "lua", cases=CASES) -> dict[str, dict]:
    """Build the cases into tiles and report, per case, what /locate sees."""
    xml, where = _osm_xml(cases)
    (work / "tiles").mkdir(parents=True, exist_ok=True)
    (work / "fixture.osm").write_text(xml)
    port = _free_port()
    config = _config(work, lua_dir, port)
    env = {**os.environ, "ROUTEMAKER_LUA_DIR": str(lua_dir)}
    subprocess.run(
        ["osmium", "cat", "-O", str(work / "fixture.osm"), "-o", str(work / "fixture.osm.pbf")],
        check=True, capture_output=True, timeout=60, preexec_fn=_limits,
    )
    build = subprocess.run(
        ["valhalla_build_tiles", "-c", str(config), str(work / "fixture.osm.pbf")],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT_S, env=env, preexec_fn=_limits,
    )
    log = build.stdout + build.stderr
    if build.returncode != 0:
        raise RuntimeError(f"valhalla_build_tiles failed:\n{log[-3000:]}")
    if "Using LUA script" not in log:
        raise RuntimeError("the build never loaded graph.lua; the result would test nothing")
    if "ROUTEMAKER-VIOLATION" in log:
        raise RuntimeError(f"the transform reported a violation:\n{log[-3000:]}")

    service = subprocess.Popen(
        ["valhalla_service", str(config), "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, preexec_fn=_limits,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                _post(port, "status", {})
                break
            except OSError:
                if time.monotonic() > deadline or service.poll() is not None:
                    raise RuntimeError("valhalla_service did not come up")
                time.sleep(0.2)
        seen: dict[str, dict] = {}
        for name, (way_id, lon, lat) in where.items():
            answer = _post(port, "locate", {
                "locations": [{"lon": lon, "lat": lat, "radius": 30}],
                "verbose": True,
                "costing": "pedestrian",
            })
            edges = [
                edge for edge in (answer[0].get("edges") or [])
                if edge["edge_info"]["way_id"] == way_id
            ]
            seen[name] = {
                "edges": len(edges),
                "bicycle": any(edge["edge"]["access"]["bicycle"] for edge in edges),
            }
        return seen
    finally:
        service.terminate()
        try:
            service.wait(timeout=10)
        except subprocess.TimeoutExpired:
            service.kill()


def failures(seen: dict[str, dict], cases=CASES) -> list[str]:
    problems = []
    for name, _, open_to_bicycles in cases:
        result = seen[name]
        if result["edges"] == 0:
            problems.append(f"{name}: no pedestrian edge, so the fixture tests nothing")
        elif result["bicycle"] != open_to_bicycles:
            state = "open" if result["bicycle"] else "closed"
            problems.append(f"{name}: {state} to bicycles in the tile, expected the opposite")
    return problems


def _skip_or_fail(missing: list[str]) -> None:
    message = f"no {', '.join(missing)} on PATH; run scripts/check_tile_build_access.sh"
    if os.environ.get("ROUTEMAKER_REQUIRE_TILE_BUILD"):
        pytest.fail(message)
    pytest.skip(message)


def test_closures_reach_the_tiles(tmp_path) -> None:
    missing = missing_binaries()
    if missing:
        _skip_or_fail(missing)
    seen = build_and_locate(tmp_path)
    assert not failures(seen), "\n".join(failures(seen))


def main() -> int:
    missing = missing_binaries()
    if missing:
        print(f"missing: {', '.join(missing)}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="tile-build-access-") as tmp:
        seen = build_and_locate(Path(tmp))
    problems = failures(seen)
    for name, _, expected in CASES:
        print(f"{'ok  ' if not any(p.startswith(name + ':') for p in problems) else 'FAIL'} "
              f"{name}: bicycle {'open' if seen[name]['bicycle'] else 'closed'}"
              f" (expected {'open' if expected else 'closed'})")
    print(f"{len(CASES)} cases, {len(problems)} failures")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
