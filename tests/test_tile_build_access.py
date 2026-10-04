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
may use, direction by direction. Each way stands alone and is mapped with
pedestrian access, so the pedestrian locate always finds it. A missing
pedestrian edge means the fixture is wrong, not that the closure worked. It
then reads the same tiles through the rebuild's own closure gate
(`pipeline.tiles.read_closures`, one-shot `valhalla_service locate`), so the
gate VALIDATE runs is checked against a real graph too.

It needs `valhalla_build_tiles`, `valhalla_service` and `osmium` on PATH, which
the pipeline image has. It skips without them, as it does in CI.
ROUTEMAKER_REQUIRE_TILE_BUILD=1 is the way to force it: a missing binary then
fails the run instead of skipping it, so a job that runs this inside the
pipeline image cannot pass by skipping. The image has no pytest, so the module
also runs as a script, and scripts/check_tile_build_access.sh does that inside
the pipeline image with the variable set.

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
RATED = {"mtb:scale": "2"}
OPEN, CLOSED = True, False

# (name, tags, bicycle access): True or False for both directions, or a
# (forward, backward) pair where the two differ.
CASES: list[tuple[str, dict[str, str], bool | tuple[bool, bool]]] = [
    ("singletrack, as the extract carries it", {**CCT, **SINGLETRACK}, CLOSED),
    (
        "singletrack rated every way upstream's parser reads",
        {
            **CCT,
            **SINGLETRACK,
            "mtb:scale:imba": "2",
            "mtb:scale:uphill": "2",
            "mtb:description": "roots",
        },
        CLOSED,
    ),
    (
        "singletrack rated by IMBA only",
        {
            **{k: v for k, v in CCT.items() if k != "mtb:scale"},
            "mtb:scale:imba": "1",
            **SINGLETRACK,
        },
        CLOSED,
    ),
    # rm:no_bicycle against the grants upstream reads ahead of plain `bicycle`
    # (SINGLETRACK-review-r0, finding 8).
    (
        "singletrack with bicycle:forward=yes",
        {**CCT, **SINGLETRACK, "bicycle:forward": "yes"},
        CLOSED,
    ),
    (
        "singletrack, one-way with oneway:bicycle=no",
        {**CCT, **SINGLETRACK, "oneway": "yes", "oneway:bicycle": "no"},
        CLOSED,
    ),
    (
        "singletrack, one-way with cycleway=opposite_lane",
        {**CCT, **SINGLETRACK, "oneway": "yes", "cycleway": "opposite_lane"},
        CLOSED,
    ),
    (
        "a CBD sidewalk",
        {
            "highway": "footway",
            "footway": "sidewalk",
            "bicycle": "yes",
            "rm:trail_class": "yes",
            "rm:no_bicycle": "cbd_sidewalk",
        },
        CLOSED,
    ),
    ("OSM bicycle=no on a path", {"highway": "path", "bicycle": "no", "foot": "yes"}, CLOSED),
    (
        "OSM bicycle=no on a rated path",
        {"highway": "path", "bicycle": "no", "foot": "yes", "mtb:scale": "0"},
        CLOSED,
    ),
    (
        "OSM bicycle=none on a rated path",
        {"highway": "path", "bicycle": "none", "foot": "yes", **RATED},
        CLOSED,
    ),
    (
        "OSM access=no on a rated path",
        {"highway": "path", "access": "no", "foot": "yes", **RATED},
        CLOSED,
    ),
    (
        "OSM vehicle=no on a rated path",
        {"highway": "path", "vehicle": "no", "foot": "yes", **RATED},
        CLOSED,
    ),
    (
        "OSM vehicle:forward=no and vehicle:backward=no on a rated path",
        {
            "highway": "path",
            "vehicle:forward": "no",
            "vehicle:backward": "no",
            "foot": "yes",
            **RATED,
        },
        CLOSED,
    ),
    (
        "OSM bicycle:forward=no and bicycle:backward=no on a rated path",
        {
            "highway": "path",
            "bicycle:forward": "no",
            "bicycle:backward": "no",
            "foot": "yes",
            **RATED,
        },
        CLOSED,
    ),
    (
        "bicycle:forward and :backward values upstream does not know, rated",
        {
            "highway": "path",
            "bicycle:forward": "maybe",
            "bicycle:backward": "maybe",
            "foot": "yes",
            **RATED,
        },
        CLOSED,
    ),
    (
        "OSM bicycle=no on a rated track",
        {"highway": "track", "bicycle": "no", "foot": "yes", "mtb:scale": "1"},
        CLOSED,
    ),
    (
        "OSM access=no and cycleway=no on a rated service road",
        {"highway": "service", "access": "no", "cycleway": "no", "foot": "yes", **RATED},
        CLOSED,
    ),
    (
        "a rated footway that says nothing about bicycles",
        {"highway": "footway", "mtb:scale": "0"},
        CLOSED,
    ),
    # One direction closed: the tile holds upstream's reading of each
    # direction, as it does for the same way unrated.
    (
        "OSM bicycle:forward=no alone on a rated path",
        {"highway": "path", "bicycle:forward": "no", "foot": "yes", **RATED},
        (CLOSED, OPEN),
    ),
    (
        "OSM bicycle:backward=no alone on a rated path",
        {"highway": "path", "bicycle:backward": "no", "foot": "yes", **RATED},
        (OPEN, CLOSED),
    ),
    (
        "a rated one-way trail",
        {"highway": "path", "oneway": "yes", "bicycle": "yes", "foot": "yes", **RATED},
        (OPEN, CLOSED),
    ),
    # The Green Loop Trail (ways 1324891525, 1324891526): a one-way keeps its
    # rating, and with it its surface class, since the parser keeps its
    # reverse closed anyway (SINGLETRACK-review-r1).
    (
        "a rated one-way asphalt trail (the Green Loop Trail)",
        {
            "highway": "path",
            "oneway": "yes",
            "bicycle": "yes",
            "foot": "yes",
            "surface": "asphalt",
            "mtb:scale": "3",
        },
        (OPEN, CLOSED),
    ),
    (
        "the same, mapped oneway=-1",
        {
            "highway": "path",
            "oneway": "-1",
            "bicycle": "yes",
            "foot": "yes",
            "surface": "asphalt",
            "mtb:scale": "3",
        },
        (CLOSED, OPEN),
    ),
    # Grants hold, rated or not.
    (
        "OSM access=no with a cycle lane on a rated service road",
        {"highway": "service", "access": "no", "cycleway": "lane", "foot": "yes", **RATED},
        OPEN,
    ),
    (
        "OSM access=no with bicycle=designated on a rated path",
        {"highway": "path", "access": "no", "bicycle": "designated", "foot": "yes", **RATED},
        OPEN,
    ),
    ("an open path", {"highway": "path", "bicycle": "yes", "foot": "yes"}, OPEN),
    (
        "an open rated trail (not singletrack)",
        {**CCT, "rm:trail_class": "yes", "rm:facility": "path"},
        OPEN,
    ),
    (
        "the same trail unrated",
        {
            **{k: v for k, v in CCT.items() if k != "mtb:scale"},
            "rm:trail_class": "yes",
            "rm:facility": "path",
        },
        OPEN,
    ),
    (
        "the C&O towpath above lock 21",
        {
            "highway": "path",
            "bicycle": "designated",
            "foot": "designated",
            "surface": "dirt",
            "mtb:scale:imba": "0",
            "rm:trail_class": "yes",
            "rm:facility": "path",
        },
        OPEN,
    ),
    # NO-BIKE-PATHS (OWNER-DECISIONS 291): each reason reaches the tiles closed,
    # on a plain path and on one that carries a rating the parser would
    # reopen it from.
    *[
        (
            f"NO-BIKE-PATHS: {reason} on a path",
            {"highway": "path", "foot": "yes", "rm:trail_class": "yes", "rm:no_bicycle": reason},
            CLOSED,
        )
        for reason in (
            "natural_surface",
            "private",
            "sac_scale",
            "informal",
            "foot_designated",
            "trail_visibility",
            "hiking_route",
            "park_path",
            "dismount",
            "zoo",
        )
    ],
    (
        "NO-BIKE-PATHS: mtb on a bikeable-tagged dirt trail",
        {
            "highway": "path",
            "bicycle": "yes",
            "surface": "dirt",
            "rm:trail_class": "yes",
            "rm:no_bicycle": "mtb",
        },
        CLOSED,
    ),
    (
        "NO-BIKE-PATHS: mtb on a trail rated by IMBA",
        {
            "highway": "path",
            "bicycle": "designated",
            "surface": "dirt",
            "mtb:scale:imba": "0",
            "rm:trail_class": "yes",
            "rm:no_bicycle": "mtb",
        },
        CLOSED,
    ),
    (
        "NO-BIKE-PATHS: the Zoo spur, a footway tagged bicycle=no",
        {
            "highway": "footway",
            "footway": "sidewalk",
            "bicycle": "no",
            "rm:trail_class": "yes",
            "rm:destination_only": "zoo",
        },
        OPEN,
    ),
    (
        "NO-BIKE-PATHS: the same footway unmarked (the Zoo control)",
        {"highway": "footway", "footway": "sidewalk", "bicycle": "no", "rm:trail_class": "yes"},
        CLOSED,
    ),
]

# What the tile says the surface is, where a rating decides it. The parser
# reads a rating as the surface too (SINGLETRACK-review-r0, finding 4), so an
# open rated trail must keep its rating - the towpath above all - and its
# unrated twin shows what the surface would be without one.
SURFACES = {
    "a rated one-way asphalt trail (the Green Loop Trail)": "path",
    "the same, mapped oneway=-1": "path",
    "an open rated trail (not singletrack)": "path",
    "the same trail unrated": "dirt",
    "the C&O towpath above lock 21": "dirt",
}


def expected_directions(expected: bool | tuple[bool, bool]) -> tuple[bool, bool]:
    return expected if isinstance(expected, tuple) else (expected, expected)


def missing_binaries() -> list[str]:
    return [name for name in BINARIES if shutil.which(name) is None]


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES))


def _osm_xml(cases) -> tuple[str, dict[str, tuple[int, float, float]]]:
    """One three-node way per case, 220 m apart, all in one level-2 tile."""
    from xml.sax.saxutils import quoteattr

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<osm version="0.6" generator="routemaker-test">',
    ]
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


def build(work: Path, lua_dir: Path = REPO / "lua", cases=CASES):
    """Build the cases into tiles: (config path, where each case lies, env)."""
    xml, where = _osm_xml(cases)
    (work / "tiles").mkdir(parents=True, exist_ok=True)
    (work / "fixture.osm").write_text(xml)
    port = _free_port()
    config = _config(work, lua_dir, port)
    env = {**os.environ, "ROUTEMAKER_LUA_DIR": str(lua_dir)}
    subprocess.run(
        ["osmium", "cat", "-O", str(work / "fixture.osm"), "-o", str(work / "fixture.osm.pbf")],
        check=True,
        capture_output=True,
        timeout=60,
        preexec_fn=_limits,
    )
    built = subprocess.run(
        ["valhalla_build_tiles", "-c", str(config), str(work / "fixture.osm.pbf")],
        capture_output=True,
        text=True,
        timeout=BUILD_TIMEOUT_S,
        env=env,
        preexec_fn=_limits,
    )
    log = built.stdout + built.stderr
    if built.returncode != 0:
        raise RuntimeError(f"valhalla_build_tiles failed:\n{log[-3000:]}")
    if "Using LUA script" not in log:
        raise RuntimeError("the build never loaded graph.lua; the result would test nothing")
    if "ROUTEMAKER-VIOLATION" in log:
        raise RuntimeError(f"the transform reported a violation:\n{log[-3000:]}")
    return config, port, where, env


def locate(config: Path, port: int, where, env) -> dict[str, dict]:
    """Serve the tiles and report, per case, what a pedestrian /locate sees."""
    service = subprocess.Popen(
        ["valhalla_service", str(config), "1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        preexec_fn=_limits,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                _post(port, "status", {})
                break
            except OSError:
                if time.monotonic() > deadline or service.poll() is not None:
                    raise RuntimeError("valhalla_service did not come up") from None
                time.sleep(0.2)
        seen: dict[str, dict] = {}
        for name, (way_id, lon, lat) in where.items():
            answer = _post(
                port,
                "locate",
                {
                    "locations": [{"lon": lon, "lat": lat, "radius": 30}],
                    "verbose": True,
                    "costing": "pedestrian",
                },
            )
            edges = [
                edge
                for edge in (answer[0].get("edges") or [])
                if edge["edge_info"]["way_id"] == way_id
            ]
            by_direction = {True: [], False: []}
            for edge in edges:
                by_direction[bool(edge["edge"].get("forward"))].append(
                    bool(edge["edge"]["access"]["bicycle"])
                )
            # A one-way's reverse edge has no pedestrian access either, so the
            # pedestrian locate does not return it. A bicycle locate returns
            # exactly the directions a bicycle may use, so where the
            # pedestrian one is silent it decides, and it can only add an
            # open direction, never hide one.
            biked = _post(
                port,
                "locate",
                {
                    "locations": [{"lon": lon, "lat": lat, "radius": 30}],
                    "verbose": True,
                    "costing": "bicycle",
                },
            )
            for edge in biked[0].get("edges") or []:
                if edge["edge_info"]["way_id"] == way_id:
                    by_direction[bool(edge["edge"].get("forward"))].append(True)
            if edges:
                for values in by_direction.values():
                    if not values:
                        values.append(False)
            seen[name] = {
                "edges": len(edges),
                "bicycle": any(any(v) for v in by_direction.values()),
                "forward": any(by_direction[True]) if by_direction[True] else None,
                "backward": any(by_direction[False]) if by_direction[False] else None,
                "surfaces": sorted(
                    {
                        str((edge["edge"].get("classification") or {}).get("surface"))
                        for edge in edges
                    }
                ),
            }
        return seen
    finally:
        # valhalla_service ignores SIGTERM for over ten seconds, so a terminate
        # and a wait only waited out the timeout (SINGLETRACK-review-r0,
        # finding 6). Nothing is left to flush: the tiles are a throwaway.
        service.kill()
        service.wait(timeout=10)


def build_and_locate(work: Path, lua_dir: Path = REPO / "lua", cases=CASES) -> dict[str, dict]:
    """Build the cases into tiles and report, per case, what /locate sees."""
    config, port, where, env = build(work, lua_dir, cases)
    return locate(config, port, where, env)


def failures(seen: dict[str, dict], cases=CASES) -> list[str]:
    problems = []
    for name, _, expected in cases:
        result = seen[name]
        if result["edges"] == 0:
            problems.append(f"{name}: no pedestrian edge, so the fixture tests nothing")
            continue
        for direction, want in zip(
            ("forward", "backward"), expected_directions(expected), strict=True
        ):
            got = result[direction]
            if got is not None and got != want:
                state = "open" if got else "closed"
                problems.append(f"{name}: {state} to bicycles {direction} in the tile")
        if result["forward"] is None and expected_directions(expected)[0]:
            problems.append(f"{name}: no forward edge, where bicycles may ride forward")
        surface = SURFACES.get(name)
        if surface is not None and result["surfaces"] != [surface]:
            problems.append(f"{name}: surface {result['surfaces']} in the tile, not {surface!r}")
    return problems


def gate_failures(config: Path, where, env, cases=CASES) -> list[str]:
    """Read the same tiles through the rebuild's closure gate, which uses
    one-shot `valhalla_service <config> locate` rather than the HTTP server."""
    sys.path.insert(0, str(REPO / "src"))
    from pipeline import tiles

    def run(command):
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            preexec_fn=_limits,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{command[0]} {command[2]} failed: {result.stdout[-500:]}")
        return tiles.CommandOutput(result.stdout, result.stderr)

    probes = [tiles.ClosureProbe(way_id, lon, lat) for way_id, lon, lat in where.values()]
    readback = tiles.read_closures(run, config, probes)
    want_open = {
        where[name][0] for name, _, expected in cases if any(expected_directions(expected))
    }
    problems = []
    if readback.found != len(probes):
        problems.append(f"gate: found {readback.found} of {len(probes)} ways")
    if set(readback.open_to_bicycles) != want_open:
        problems.append(
            f"gate: open {sorted(readback.open_to_bicycles)}, expected {sorted(want_open)}"
        )
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
    config, port, where, env = build(tmp_path)
    seen = locate(config, port, where, env)
    problems = failures(seen) + gate_failures(config, where, env)
    assert not problems, "\n".join(problems)


def main() -> int:
    missing = missing_binaries()
    if missing:
        print(f"missing: {', '.join(missing)}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="tile-build-access-") as tmp:
        config, port, where, env = build(Path(tmp))
        seen = locate(config, port, where, env)
        problems = failures(seen) + gate_failures(config, where, env)

    def shown(value):
        return "-" if value is None else ("open" if value else "closed")

    for name, _, expected in CASES:
        state = "FAIL" if any(p.startswith(name + ":") for p in problems) else "ok  "
        forward, backward = expected_directions(expected)
        print(
            f"{state} {name}: bicycle {shown(seen[name]['forward'])}/"
            f"{shown(seen[name]['backward'])} (expected {shown(forward)}/{shown(backward)}),"
            f" surface {','.join(seen[name]['surfaces'])}"
        )
    for problem in problems:
        if problem.startswith("gate:"):
            print(f"FAIL {problem}")
    print(f"{len(CASES)} cases, {len(problems)} failures")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
