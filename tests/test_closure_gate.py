"""The rebuild's bicycle-closure gate (VALIDATE), without Valhalla.

Valhalla's C++ parser reopened 753 singletrack ways after the transform had
closed them, and nothing between the build and the swap looked
(SINGLETRACK-review-r0, finding 2a). The gate reads a bounded sample of
singletrack and rated OSM closures back from every staged graph and refuses
the swap if any is open. These tests hold its selection, its reading of a
`/locate` answer, its verdict and its bounds; tests/test_tile_build_access.py
runs `read_closures` against a real graph, and tests/test_pipeline_end_to_end.py
runs the gate inside a rebuild.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import tiles
from pipeline.extract import Way
from pipeline.run import (
    CLOSURE_GATE_OSM_CLOSURES,
    CLOSURE_GATE_SINGLETRACKS,
    CLOSURE_PROBES_REPORT,
    SINGLETRACK_REPORT,
    ValidationFailed,
    _run_command,
    _spread,
    assert_bicycle_closures_reached_the_tiles,
    closure_probes,
    is_rated_osm_closure,
    probe_point,
    write_closure_reports,
)
from pipeline.variants import Variant

LOG = "2026/10/03 [INFO] Tile extract successfully loaded with tile count: 12\n"


# --- Which ways the gate holds the graph to --------------------------------------


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "path", "bicycle": "no", "mtb:scale": "1"},
        {"highway": "path", "bicycle": "no", "foot": "yes", "mtb:scale:imba": "0"},
        {"highway": "track", "bicycle": "no", "mtb:description": "roots"},
        {"highway": "footway", "bicycle": "no", "mtb:scale:uphill": "2"},
    ],
)
def test_a_rated_way_osm_closes_to_bicycles_is_held_closed(tags) -> None:
    assert is_rated_osm_closure(tags)


@pytest.mark.parametrize(
    "tags",
    [
        # Not closed, or not by `bicycle=no`.
        {"highway": "path", "mtb:scale": "1"},
        {"highway": "path", "bicycle": "yes", "mtb:scale": "1"},
        {"highway": "path", "access": "no", "mtb:scale": "1"},
        # Not rated: nothing for the parser to reopen it from. Bare `mtb` is
        # not a rating.
        {"highway": "path", "bicycle": "no"},
        {"highway": "path", "bicycle": "no", "mtb": "yes"},
        # Dropped outright, so there is no edge to read.
        {"highway": "path", "bicycle": "no", "foot": "no", "mtb:scale": "1"},
        # Open by upstream's own reading in at least one direction.
        {"highway": "path", "bicycle": "no", "bicycle:forward": "yes", "mtb:scale": "1"},
        {"highway": "path", "bicycle": "no", "vehicle:backward": "yes", "mtb:scale": "1"},
        {
            "highway": "path",
            "bicycle": "no",
            "oneway": "yes",
            "oneway:bicycle": "no",
            "mtb:scale": "1",
        },
        {"highway": "path", "bicycle": "no", "cycleway": "opposite", "mtb:scale": "1"},
        {"highway": "service", "bicycle": "no", "cycleway:both": "lane", "mtb:scale": "1"},
        {"highway": "service", "bicycle": "no", "service": "driveway", "mtb:scale": "1"},
        {"highway": "residential", "bicycle": "no", "bicycle_road": "yes", "mtb:scale": "1"},
        # The remap resolves a conditional grant onto the directional keys.
        {
            "highway": "path",
            "bicycle": "no",
            "bicycle:conditional": "yes @ (Sa-Su 00:00-24:00)",
            "mtb:scale": "1",
        },
        {
            "highway": "path",
            "bicycle": "no",
            "bicycle:forward:conditional": "yes @ (Sa-Su)",
            "mtb:scale": "1",
        },
        {
            "highway": "path",
            "bicycle": "no",
            "bicycle:backward:conditional": "yes @ (Sa-Su)",
            "mtb:scale": "1",
        },
    ],
)
def test_a_way_upstream_may_open_is_not(tags) -> None:
    assert not is_rated_osm_closure(tags)


def test_the_probe_is_the_midpoint_of_the_longest_segment() -> None:
    assert probe_point([(0.0, 0.0), (0.0, 0.0), (1.0, 0.0), (1.0, 3.0)]) == (1.0, 1.5)
    assert probe_point([(0.0, 0.0)]) is None
    assert probe_point([(1.0, 1.0), (1.0, 1.0)]) is None, "no segment of any length"


def test_the_sample_is_bounded_and_the_same_every_time() -> None:
    ids = list(range(1000, 0, -1))
    picked = _spread(ids, 40)
    assert len(picked) == 40
    assert picked == sorted(picked) and picked[0] == 1, "in id order, from the first"
    assert picked[-1] >= 950, "and reaching across the whole range"
    assert picked == _spread(list(reversed(ids)), 40), "whatever order it was handed"
    assert _spread([3, 1, 2], 40) == [1, 2, 3]


def _way(osm_id: int, tags: dict[str, str]) -> Way:
    lon = -77.0 + osm_id * 1e-4
    return Way(osm_id, tags, [1, 2], [(lon, 38.9), (lon + 1e-4, 38.9)], [0, 1])


def _context(ways: list[Way], singletracks: set[int], legal: dict[int, bool] | None = None):
    reference = SimpleNamespace(bridge_bicycle_legal=legal or {})
    return SimpleNamespace(
        ways=ways,
        ways_by_id={way.osm_id: way for way in ways},
        singletracks=singletracks,
        require_reference=lambda: reference,
    )


def test_the_gate_samples_singletrack_and_rated_osm_closures_within_its_bounds() -> None:
    rated_no = {"highway": "path", "bicycle": "no", "mtb:scale": "1"}
    singles = [_way(i, {"highway": "path", "mtb:scale": "2"}) for i in range(1, 101)]
    walled = [_way(i, {"highway": "path", "mtb:scale": "2", "foot": "no"}) for i in range(101, 111)]
    osm = [_way(i, rated_no) for i in range(200, 260)]
    bridge = _way(300, rated_no)
    plain = _way(400, {"highway": "path"})
    context = _context(
        singles + walled + osm + [bridge, plain],
        {w.osm_id for w in singles + walled},
        legal={300: True},
    )

    probes = closure_probes(context)
    ids = [probe.way_id for probe in probes]

    assert len(ids) == CLOSURE_GATE_SINGLETRACKS + CLOSURE_GATE_OSM_CLOSURES
    assert set(ids[:CLOSURE_GATE_SINGLETRACKS]) <= {w.osm_id for w in singles}
    assert not set(ids) & {w.osm_id for w in walled}, "a foot=no way has no edge to read"
    assert set(ids[CLOSURE_GATE_SINGLETRACKS:]) <= {w.osm_id for w in osm}
    assert 300 not in ids, "the crossings fixture may open a bridge OSM closes"
    assert 400 not in ids
    first = context.ways_by_id[ids[0]]
    assert (probes[0].lon, probes[0].lat) == probe_point(first.coordinates)


def test_the_probes_are_left_for_the_post_swap_check(tmp_path: Path) -> None:
    probes = [tiles.ClosureProbe(900, -77.1175, 38.93), tiles.ClosureProbe(17, -77.0, 38.9)]
    write_closure_reports(tmp_path / "reports", probes, {900, 5})
    assert (tmp_path / "reports" / CLOSURE_PROBES_REPORT).read_text() == (
        "way_id,lon,lat,reason\n900,-77.1175000,38.9300000,\n17,-77.0000000,38.9000000,\n"
    )
    assert (tmp_path / "reports" / SINGLETRACK_REPORT).read_text() == "5\n900\n"


# --- Reading a graph's answer -----------------------------------------------------


def _edge(way_id: int, bicycle: bool, forward: bool = True) -> dict:
    return {
        "edge_info": {"way_id": way_id},
        "edge": {"forward": forward, "access": {"bicycle": bicycle}},
    }


class Locate:
    """A one-shot `valhalla_service locate`, answering with given edges."""

    def __init__(self, answers, stdout_prefix: str = "") -> None:
        self.answers = answers
        self.prefix = stdout_prefix
        self.calls: list[list[str]] = []

    def __call__(self, command):
        self.calls.append(list(command))
        return tiles.CommandOutput(self.prefix + json.dumps(self.answers), LOG)


PROBES = [
    tiles.ClosureProbe(1, -77.0, 38.9),
    tiles.ClosureProbe(2, -77.0, 38.91),
    tiles.ClosureProbe(3, -77.0, 38.92),
]


def test_one_read_per_graph_with_pedestrian_costing() -> None:
    run = Locate([{"edges": [_edge(1, False)]}, {"edges": None}, {"edges": []}])
    readback = tiles.read_closures(run, Path("/c/standard.json"), PROBES)

    assert readback == tiles.ClosureReadback(probed=3, found=1, open_to_bicycles=())
    assert len(run.calls) == 1
    command = run.calls[0]
    assert command[:3] == ["valhalla_service", "/c/standard.json", "locate"]
    request = json.loads(command[3])
    assert request["costing"] == "pedestrian", "a bicycle locate cannot tell closed from missed"
    assert request["verbose"] is True, "access.bicycle is only in the verbose answer"
    assert [(loc["lon"], loc["lat"]) for loc in request["locations"]] == [
        (p.lon, p.lat) for p in PROBES
    ]
    assert {loc["radius"] for loc in request["locations"]} == {tiles.CLOSURE_LOCATE_RADIUS_M}


def test_an_open_edge_in_either_direction_is_open() -> None:
    run = Locate(
        [
            {"edges": [_edge(1, False, True), _edge(1, True, False)]},
            {"edges": [_edge(2, False), _edge(2, False, False)]},
            {"edges": [_edge(3, True)]},
        ]
    )
    readback = tiles.read_closures(run, Path("c.json"), PROBES)
    assert readback.open_to_bicycles == (1, 3)
    assert readback.found == 3


def test_only_the_probed_way_answers_for_itself() -> None:
    """A neighbour inside the radius, open or closed, says nothing about the
    probed way: an open cycle track beside a closed singletrack is not the
    singletrack reopened, and a closed footway beside it is not it closed."""
    run = Locate(
        [
            {"edges": [_edge(99, True), _edge(1, False)]},
            {"edges": [_edge(98, False)]},
            {"edges": [_edge(97, True)]},
        ]
    )
    readback = tiles.read_closures(run, Path("c.json"), PROBES)
    assert readback.open_to_bicycles == ()
    assert readback.found == 1


def test_the_answer_is_read_off_stdout_past_anything_ahead_of_it() -> None:
    run = Locate([{"edges": [_edge(1, True)]}, {}, {}], stdout_prefix="a stray line {x}\n")
    assert tiles.read_closures(run, Path("c.json"), PROBES).open_to_bicycles == (1,)


def test_an_answer_that_does_not_match_the_request_is_refused() -> None:
    with pytest.raises(ValueError, match="answered 3 locations with 2"):
        tiles.read_closures(Locate([{}, {}]), Path("c.json"), PROBES)
    with pytest.raises(ValueError, match="no locate answer"):
        tiles.read_closures(lambda command: tiles.CommandOutput("", LOG), Path("c.json"), PROBES)


def test_no_probes_is_no_read() -> None:
    run = Locate([])
    assert tiles.read_closures(run, Path("c.json"), []) == tiles.ClosureReadback(0, 0, ())
    assert run.calls == []


# --- The verdict ------------------------------------------------------------------


def _all(**overrides):
    held = tiles.ClosureReadback(probed=3, found=3, open_to_bicycles=())
    return {variant: overrides.get(variant.name, held) for variant in Variant}


def test_every_graph_holding_every_closure_passes() -> None:
    assert_bicycle_closures_reached_the_tiles(_all())


def test_a_graph_that_reopened_a_closure_is_not_swapped_in() -> None:
    reopened = tiles.ClosureReadback(probed=3, found=3, open_to_bicycles=(810382238,))
    with pytest.raises(ValidationFailed) as caught:
        assert_bicycle_closures_reached_the_tiles(_all(WEEKEND=reopened))
    message = str(caught.value)
    assert "weekend graph" in message and "810382238" in message
    assert "1 of 3" in message


def test_a_read_that_found_nothing_tested_nothing() -> None:
    nothing = tiles.ClosureReadback(probed=3, found=0, open_to_bicycles=())
    with pytest.raises(ValidationFailed, match="tested nothing"):
        assert_bicycle_closures_reached_the_tiles(_all(STANDARD=nothing))
    # The no-trail graph drops every trail, singletrack with them.
    assert_bicycle_closures_reached_the_tiles(_all(NO_TRAIL=nothing))
    # And with nothing to probe there is nothing to find.
    empty = tiles.ClosureReadback(probed=0, found=0, open_to_bicycles=())
    assert_bicycle_closures_reached_the_tiles({variant: empty for variant in Variant})


def test_every_graph_is_read() -> None:
    readbacks = _all()
    del readbacks[Variant.EBIKE]
    with pytest.raises(ValidationFailed, match="ebike"):
        assert_bicycle_closures_reached_the_tiles(readbacks)


# --- The bound on a read ------------------------------------------------------------


def test_a_read_has_its_own_timeout_inside_the_rebuild_budget() -> None:
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_command(["sleep", "5"], deadline=time.monotonic() + 3600, timeout=0.3)
    assert time.monotonic() - started < 3
    # And the budget still wins when less of it is left than the timeout.
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_command(["sleep", "5"], deadline=time.monotonic() + 0.3, timeout=60)
    assert time.monotonic() - started < 3


# --- The post-swap probe (scripts/probe_bicycle_closures.py) ----------------------


@pytest.fixture
def probe_script(monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import probe_bicycle_closures

    return probe_bicycle_closures


def _probes_file(tmp_path: Path) -> Path:
    path = tmp_path / "probes.csv"
    write_closure_reports(tmp_path, PROBES, set())
    (tmp_path / CLOSURE_PROBES_REPORT).replace(path)
    return path


def test_the_post_swap_probe_asks_every_router_and_fails_on_an_open_way(
    probe_script, monkeypatch, tmp_path, capsys
) -> None:
    asked = []

    def post(url, body, headers=None):
        asked.append((url, body))
        open_here = "weekend" in url
        return [{"edges": [_edge(p.way_id, open_here and p.way_id == 2)]} for p in PROBES]

    monkeypatch.setattr(probe_script, "_post", post)
    assert probe_script.main(["locate", "--probes", str(_probes_file(tmp_path))]) == 1
    assert sorted(url for url, _ in asked) == sorted(
        f"{url}/locate" for url in probe_script.ROUTERS.values()
    )
    assert {body["costing"] for _, body in asked} == {"pedestrian"}
    assert "weekend: 3 probed, 3 found, OPEN: 2" in capsys.readouterr().out


def test_the_post_swap_probe_passes_when_every_router_holds(
    probe_script, monkeypatch, tmp_path, capsys
) -> None:
    def post(url, body, headers=None):
        found = "no-trail" not in url  # the no-trail graph has no trails to find
        return [{"edges": [_edge(p.way_id, False)] if found else None} for p in PROBES]

    monkeypatch.setattr(probe_script, "_post", post)
    assert probe_script.main(["locate", "--probes", str(_probes_file(tmp_path))]) == 0
    assert "no-trail: 3 probed, 0 found, ok" in capsys.readouterr().out


def test_the_post_swap_probe_skips_an_off_road_router_that_is_not_running(
    probe_script, monkeypatch, tmp_path, capsys
) -> None:
    """Operations review S6: with the profile-gated off-road router off (the
    default), the probe printed four "ok" lines and then a URLError traceback."""
    import urllib.error

    def post(url, body, headers=None):
        if "offroad" in url:
            raise urllib.error.URLError("Name or service not known")
        found = "no-trail" not in url
        return [{"edges": [_edge(p.way_id, False)] if found else None} for p in PROBES]

    monkeypatch.setattr(probe_script, "_post", post)
    assert probe_script.main(["locate", "--probes", str(_probes_file(tmp_path))]) == 0
    assert "offroad: not running, skipped" in capsys.readouterr().out

    def down(url, body, headers=None):
        if "weekend" in url:
            raise urllib.error.URLError("Connection refused")
        return post(url, body, headers)

    monkeypatch.setattr(probe_script, "_post", down)
    with pytest.raises(urllib.error.URLError):
        probe_script.main(["locate", "--probes", str(_probes_file(tmp_path))])


def test_the_post_swap_probe_fails_a_router_that_found_nothing(
    probe_script, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(probe_script, "_post", lambda url, body, headers=None: [{}, {}, {}])
    assert probe_script.main(["locate", "--probes", str(_probes_file(tmp_path))]) == 1


def test_the_post_swap_trip_reports_the_distance_on_avoided_ways(
    probe_script, monkeypatch, tmp_path, capsys
) -> None:
    calls = []

    def post(url, body, headers=None):
        calls.append((url, body, headers))
        if url.endswith("/api/route"):
            return {
                "variant": "standard",
                "distance_m": 4667.0,
                "geometry": {"coordinates": [[-77.3168, 38.8984], [-77.3318, 38.8798]]},
            }
        return {"edges": [{"way_id": 810382238, "length": 1.9}, {"way_id": 5, "length": 0.4}]}

    monkeypatch.setattr(probe_script, "_post", post)
    argv = ["trip", "--preset", "mountain-goat", "--from=-77.3168,38.8984"]
    argv += ["--to=-77.3318,38.8798", "--avoid-way", "810382238", "--host", "example.test"]
    assert probe_script.main(argv) == 1
    route_call, match_call = calls
    assert route_call[1]["preset"] == "mountain-goat"
    assert route_call[2]["Host"] == "example.test"
    assert match_call[0] == f"{probe_script.ROUTERS['standard']}/trace_attributes"
    assert "810382238 1900 m" in capsys.readouterr().out

    monkeypatch.setattr(
        probe_script,
        "_post",
        lambda url, body, headers=None: (
            post(url, body, headers)
            if url.endswith("/api/route")
            else {"edges": [{"way_id": 5, "length": 0.4}]}
        ),
    )
    assert probe_script.main(argv) == 0


def test_a_bridge_the_crossings_fixture_rules_on_is_not_held_to_osm() -> None:
    """A legality row may open a roadway OSM tags bicycle=no; the gate must not
    refuse the graph for following it."""
    rated_no = {"highway": "secondary", "bicycle": "no", "mtb:scale": "0"}
    context = _context([_way(300, rated_no), _way(301, rated_no)], set(), legal={300: True})
    assert [probe.way_id for probe in closure_probes(context)] == [301]


def test_the_gate_also_samples_each_no_bike_paths_reason() -> None:
    """Every NO-BIKE-PATHS rule must reach the tiles, so the sample takes up to
    CLOSURE_GATE_PER_REASON ways of each reason; the Zoo spur is open on
    purpose and not sampled."""
    from pipeline.run import CLOSURE_GATE_PER_REASON

    ways = [_way(i, {"highway": "path", "surface": "dirt"}) for i in range(1, 31)]
    ways += [_way(i, {"highway": "path", "access": "private"}) for i in range(31, 61)]
    ways += [_way(i, {"highway": "footway", "bicycle": "no", "foot": "no"}) for i in range(61, 66)]
    spur = _way(70, {"highway": "footway"})
    context = _context(ways + [spur], set())
    context.no_bicycle = {
        **dict.fromkeys(range(1, 31), "natural_surface"),
        **dict.fromkeys(range(31, 61), "private"),
        **dict.fromkeys(range(61, 66), "zoo"),
    }
    context.destination_only = {70}
    probes = closure_probes(context)
    by_reason = {}
    for probe in probes:
        by_reason.setdefault(probe.reason, []).append(probe.way_id)
    assert len(by_reason["natural_surface"]) == CLOSURE_GATE_PER_REASON
    assert len(by_reason["private"]) == CLOSURE_GATE_PER_REASON
    assert "zoo" not in by_reason, "a foot=no way has no edge to read"
    assert 70 not in [p.way_id for p in probes]


def test_the_offroad_graph_is_not_held_to_the_mtb_class(tmp_path: Path) -> None:
    from pipeline.run import write_closure_reports

    probes = [
        tiles.ClosureProbe(1, -77.0, 38.9, "mtb"),
        tiles.ClosureProbe(2, -77.0, 38.91, "private"),
    ]
    write_closure_reports(tmp_path, probes, set())
    text = (tmp_path / "bicycle-closure-probes.csv").read_text().splitlines()
    assert text[0] == "way_id,lon,lat,reason"
    assert text[1].endswith(",mtb") and text[2].endswith(",private")


def test_only_the_offroad_readback_leaves_out_the_mtb_probes(monkeypatch, tmp_path: Path) -> None:
    from pipeline import run as run_module

    probes = [
        tiles.ClosureProbe(1, -77.0, 38.9, "mtb"),
        tiles.ClosureProbe(2, -77.0, 38.91, "private"),
    ]
    monkeypatch.setattr(run_module, "closure_probes", lambda context: probes)
    monkeypatch.setattr(run_module, "write_closure_reports", lambda *args: None)
    monkeypatch.setattr(
        tiles, "read_closures", lambda run, config_path, held: [probe.way_id for probe in held]
    )
    context = SimpleNamespace(
        work_dir=tmp_path,
        singletracks=set(),
        build_configs={variant: tmp_path / f"{variant.value}.json" for variant in Variant},
    )
    readbacks = run_module._closures_across_variants(context, run=None)
    assert set(readbacks) == set(Variant)
    for variant in Variant:
        expected = [2] if variant is Variant.OFFROAD else [1, 2]
        assert readbacks[variant] == expected, variant
