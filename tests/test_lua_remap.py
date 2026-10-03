"""Run the Lua suites as part of the Python suite.

The remap is Lua because Valhalla's tag transform is Lua, and it is tested in
Lua for the same reason: a Python reimplementation would be testing a
translation rather than the file the tile build actually loads. Shelling out
keeps one suite and one CI signal.

The interpreter matters as much as the files. Valhalla 3.5.1's CMakeLists has
`pkg_check_modules(LuaJIT REQUIRED IMPORTED_TARGET luajit)`, so the transform
runs under LuaJIT - Lua 5.1 semantics plus the `bit` library, which upstream's
`nodes_proc` calls for `access_mask` and which stock Lua 5.2+ does not have.
Running these suites under lua5.4 would be running them under an interpreter
Valhalla cannot use.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Ordered by fidelity to what Valhalla links against, not by what is newest.
LUAJIT = shutil.which("luajit")
ANY_LUA = LUAJIT or shutil.which("lua5.1") or shutil.which("lua5.4") or shutil.which("lua")


def _require(interpreter: str | None, what: str) -> str:
    """Skip locally, fail in CI.

    A skip is the right answer on a laptop without LuaJIT and the wrong one in
    CI, where an image that lost the interpreter would report green with the
    whole Lua suite unrun.
    """
    if interpreter is None:
        if os.environ.get("CI"):
            pytest.fail(f"CI image has no {what}; the Lua suites did not run")
        pytest.skip(f"no {what} available")
    return interpreter


def _run(interpreter: str, script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [interpreter, script],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ROUTEMAKER_LUA_DIR": "lua"},
    )


def test_remap_suite_passes() -> None:
    result = _run(_require(ANY_LUA, "Lua interpreter"), "tests/lua/test_remap.lua")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failures" in result.stdout


def test_entry_point_suite_passes_against_the_vendored_upstream() -> None:
    """The wrapper, the remap and Valhalla's own transform, end to end.

    Needs LuaJIT specifically: upstream's nodes_proc calls bit.bor.
    """
    result = _run(_require(LUAJIT, "LuaJIT"), "tests/lua/test_graph_entry.lua")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failures" in result.stdout


def test_the_lua_we_ship_stays_within_lua_51() -> None:
    """LuaJIT is Lua 5.1 with extensions. Syntax added in 5.2+ - integer division,
    the bitwise operators, goto - parses on a developer's lua5.4 and fails inside
    the container, where the failure surfaces as a silent fallback to Valhalla's
    compiled-in transform rather than as a crash.
    """
    for path in sorted((REPO / "lua").glob("*.lua")):
        source = path.read_text()
        for token in ("//", "goto ", "<<", ">>", "table.unpack", "math.type"):
            assert token not in source, f"{path.name} uses {token!r}, which LuaJIT does not accept"


def test_remap_declares_the_attributes_it_must_never_write() -> None:
    """highway and maxspeed set hierarchy, shortcuts, pruning and maneuver
    emission. A remap that wrote them could not serve use_roads 0 and use_roads 1
    from one graph."""
    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    assert "FORBIDDEN_KEYS" in source
    assert "highway = true" in source
    assert "maxspeed = true" in source


def test_the_vendored_upstream_is_pinned_and_present() -> None:
    """Checked in rather than fetched at build time, so the tags a tile build
    produces are a function of this repository and not of whichever image tag was
    pulled - and so the entry-point contract can be tested against the real file.
    """
    vendored = REPO / "lua" / "vendor" / "graph_upstream.lua"
    assert vendored.is_file()
    assert (REPO / "lua" / "vendor" / "VERSION").read_text().strip() == "3.5.1"
    source = vendored.read_text()
    # The contract the wrapper depends on: globals, and no module return. If a
    # future re-vendor changes this, the wrapper's global capture breaks and this
    # is where it should be noticed.
    assert "\nfunction ways_proc " in source
    assert "\nfunction nodes_proc " in source
    assert "\nfunction rels_proc " in source
    assert not source.rstrip().endswith("return M")


def test_every_key_the_remap_writes_is_one_valhalla_reads() -> None:
    """The quality bar's supported-key list, read from the pinned source.

    Valhalla's tile schema is fixed and a key it does not read is dropped in
    silence - no error, no effect - which is why believing the list is not good
    enough. `bicycle:forward` and `bicycle:backward` are in it;
    `bicycle:forward:conditional` is not, and upstream's graph.lua carries a bare
    `TODO access:conditional` where it would be.
    """
    supported = {
        line.strip()
        for line in (REPO / "lua" / "vendor" / "supported_keys.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert {"bicycle", "bicycle:forward", "bicycle:backward", "cycleway", "surface"} <= supported
    assert "bicycle:forward:conditional" not in supported
    assert "bicycle:conditional" not in supported

    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    written = set(re.findall(r'out\["([^"]+)"\]\s*=', source))
    written |= set(re.findall(r"\bout\.(\w+)\s*=", source))
    written |= set(re.findall(r'out_table\["([^"]+)"\]\s*=', source))
    # Keys built at runtime from a side, which the regexes above cannot see.
    written |= {"bicycle:forward", "bicycle:backward"}

    unsupported = {
        key
        for key in written
        # The rm: namespace is this project's own and is stripped by the entry
        # point before Valhalla sees it, which the entry-point suite asserts.
        if not key.startswith("rm:") and key not in supported
    }
    assert not unsupported, f"the remap writes keys Valhalla drops silently: {sorted(unsupported)}"


def test_the_supported_key_list_is_what_the_extractor_produces() -> None:
    """Regenerated and compared, so a re-vendor that changed the parser's key set
    fails here rather than leaving a stale list to be trusted."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "extract_valhalla_keys", REPO / "scripts" / "extract_valhalla_keys.py"
    )
    assert spec is not None and spec.loader is not None
    extractor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extractor)

    checked_in = [
        line
        for line in (REPO / "lua" / "vendor" / "supported_keys.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert checked_in == extractor.extract(
        (REPO / "lua" / "vendor" / "graph_upstream.lua").read_text()
    )


def _lua_driver(source: str) -> subprocess.CompletedProcess:
    """Run a snippet against the shipped entry point, as a separate process.

    Stderr is the point of these: the build-log check greps a real
    `valhalla_build_tiles` log, and what reaches that log is whatever the
    transform wrote to the process's stderr.
    """
    interpreter = _require(LUAJIT, "LuaJIT")
    return subprocess.run(
        [interpreter, "-e", source],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ROUTEMAKER_LUA_DIR": "lua"},
    )


def test_a_rule_violation_reaches_the_build_log_and_keeps_the_element() -> None:
    """`error()` inside an entry point does not stop a tile build.

    `LuaTagTransform::Transform` runs the entry point under lua_pcall and hands
    back an empty tag map when it fails, so the element is stripped of every tag
    and dropped while the build reports success - the opposite of what a guard
    written as `error()` claims. A violation has to be visible in the log and
    has to leave the element alone.
    """
    result = _lua_driver(
        'dofile("lua/graph.lua")\n'
        'local remap = require("routemaker_remap")\n'
        'remap.remap_way = function() return { highway = "motorway" } end\n'
        'local filter, out = ways_proc({ highway = "residential", name = "Ordinary" }, 2)\n'
        'io.stdout:write(tostring(filter), " ", tostring(out.highway), " ",\n'
        '  tostring(out.name), " ", tostring(out[remap.VIOLATION_TAG] ~= nil), "\\n")\n'
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0", "residential", "Ordinary", "true"]
    assert "ROUTEMAKER-VIOLATION" in result.stderr, "nothing a build log could be searched for"


# Tags on which upstream's `ways_proc` grants bicycle access over a plain
# `bicycle=no`, found through lua/graph.lua by the correctness review of
# 2026-09-26, and the barred roadway's own shapes as controls.
REOPENING_ROADWAYS = {
    "key-bridge-as-tagged": {"highway": "trunk", "bicycle": "no", "foot": "no", "bridge": "yes"},
    "memorial-as-tagged": {"highway": "primary", "bridge": "yes", "cycleway:both": "no"},
    "cycleway-both-lane": {"highway": "primary", "bridge": "yes", "cycleway:both": "lane"},
    "cycleway-both-shared-lane": {
        "highway": "primary",
        "bridge": "yes",
        "cycleway:both": "shared_lane",
    },
    "cycleway-left-right": {
        "highway": "primary",
        "bridge": "yes",
        "cycleway:left": "lane",
        "cycleway:right": "lane",
    },
    "cycleway-lane": {"highway": "primary", "bridge": "yes", "cycleway": "lane"},
    "cycleway-track": {"highway": "primary", "bridge": "yes", "cycleway": "track"},
    "vehicle-forward": {"highway": "primary", "bridge": "yes", "vehicle:forward": "yes"},
    "vehicle-backward": {"highway": "primary", "bridge": "yes", "vehicle:backward": "yes"},
    "oneway-opposite-lane": {
        "highway": "primary",
        "bridge": "yes",
        "oneway": "yes",
        "cycleway": "opposite_lane",
    },
    "oneway-bicycle-no": {"highway": "primary", "oneway": "yes", "oneway:bicycle": "no"},
    # One side alone: upstream's `bike_reverse` opens the contraflow from either
    # side's `opposite_lane`, so closing only the other side is not enough.
    "oneway-left-opposite-lane": {
        "highway": "primary",
        "bridge": "yes",
        "oneway": "yes",
        "cycleway:left": "opposite_lane",
    },
    "oneway-right-opposite-lane": {
        "highway": "primary",
        "bridge": "yes",
        "oneway": "yes",
        "cycleway:right": "opposite_lane",
    },
    "bicycle-designated": {"highway": "primary", "bicycle": "designated"},
}


def _bike_access(tags: dict[str, str]) -> tuple[str, str]:
    table = ", ".join(f'["{key}"] = "{value}"' for key, value in sorted(tags.items()))
    result = _lua_driver(
        'dofile("lua/graph.lua")\n'
        f"local _, out = ways_proc({{ {table} }}, 3)\n"
        'io.stdout:write(tostring(out and out.bike_forward), " ",\n'
        '  tostring(out and out.bike_backward), "\\n")\n'
    )
    assert result.returncode == 0, result.stderr
    forward, backward = result.stdout.split()
    return forward, backward


@pytest.mark.parametrize("name", sorted(REOPENING_ROADWAYS))
def test_a_mass_ride_only_bar_survives_the_real_transform(name) -> None:
    """The bar `variants.inject` writes on a mass-ride-only roadway, for the
    standard and e-bike variants, read back through the shipped entry point:
    no bicycle access in either direction, whatever else the way is tagged
    with. The no-trail variant, handed the same way, still grants it where
    OSM's tags do."""
    from pipeline.variants import Variant, inject

    tags = REOPENING_ROADWAYS[name]
    for variant in (Variant.STANDARD, Variant.EBIKE):
        barred = inject(variant, dict(tags), 7, frozenset(), frozenset({7}))
        assert _bike_access(barred) == ("false", "false"), (variant.value, barred)
        # Every key the source carried is still there: the extract writer lays
        # the pipeline's changes over the source's tags, so a key the bar
        # deleted would come back with OSM's value.
        assert set(tags) <= set(barred), (variant.value, set(tags) - set(barred))
    kept = inject(Variant.NO_TRAIL, dict(tags), 7, frozenset(), frozenset({7}))
    if tags.get("oneway") == "yes":
        # The contraflow closure (below) is the no-trail variant's own, and
        # the only thing it does to a one-way here; the bar is not it.
        assert {k: v for k, v in kept.items() if k not in CONTRAFLOW_WRITES} == {
            k: v for k, v in tags.items() if k not in CONTRAFLOW_WRITES
        }
    else:
        assert kept == tags, "the no-trail variant is untouched by the bar"
    if name == "cycleway-both-lane":
        assert _bike_access(kept) == ("true", "true"), "the control: this tag does open a way"


# Contraflow on a one-way (owner, 2026-10-02, items 192 and 193): the tag shapes
# on which upstream's `ways_proc` lets a bicycle ride against the traffic, read
# through lua/graph.lua, and what the no-trail variant makes of each. The keys
# `close_contraflow` writes or rewrites, for comparing what else it left alone.
CONTRAFLOW_WRITES = frozenset(
    {
        "oneway:bicycle",
        "bicycle:backward",
        "vehicle:backward",
        "bicycle:backward:conditional",
        "cycleway",
        "cycleway:left",
        "cycleway:right",
        "cycleway:both",
    }
)

CONTRAFLOW_FORMS = {
    "oneway-bicycle-no": {"oneway:bicycle": "no"},
    "oneway-bicycle-minus-one": {"oneway:bicycle": "-1"},
    "cycleway-opposite": {"cycleway": "opposite"},
    "cycleway-opposite-lane": {"cycleway": "opposite_lane"},
    "cycleway-opposite-track": {"cycleway": "opposite_track"},
    "left-opposite-lane": {"cycleway:left": "opposite_lane"},
    "right-opposite-lane": {"cycleway:right": "opposite_lane"},
    "left-opposite-track": {"cycleway:left": "opposite_track"},
    "both-opposite-lane": {"cycleway:both": "opposite_lane"},
    "opposite-lane-and-with-flow-lane": {
        "cycleway:left": "opposite_lane",
        "cycleway:right": "lane",
    },
    # Not an `opposite*` tag at all: upstream opens both directions of a one-way
    # that has a lane (or a track, or a sharrow) on each side.
    "lane-each-side": {"cycleway:left": "lane", "cycleway:right": "lane"},
    "lane-both": {"cycleway:both": "lane"},
    "track-both": {"cycleway:both": "track"},
    # The other two values of upstream's lane tables (`shared` and `dedicated`).
    "share-busway-each-side": {"cycleway:left": "share_busway", "cycleway:right": "share_busway"},
    # Destination-only access keeps the production remap's no-trail lane removal
    # (`lanes_may_move`) off the way, so only the closure stands between it and
    # a second direction.
    "buffered-lane-destination": {
        "access": "destination",
        "cycleway:left": "buffered_lane",
        "cycleway:right": "lane",
    },
    "bicycle-backward-yes": {"bicycle:backward": "yes"},
    "vehicle-backward-yes": {"vehicle:backward": "yes"},
    "bicycle-backward-designated": {"bicycle:backward": "designated"},
    # The conditionals the remap opens a direction from.
    "backward-conditional": {
        "bicycle:backward": "no",
        "bicycle:backward:conditional": "yes @ (Sa,Su)",
    },
    # On a one-way the undirected conditional opens the reverse only where the
    # way itself grants contraflow (`remap_conditional_access`), as here.
    "undirected-conditional-waived": {
        "bicycle": "no",
        "oneway:bicycle": "no",
        "bicycle:conditional": "yes @ (Sa,Su)",
    },
    # How DC maps a contraflow lane, and the form the Roadway Block overlay
    # writes (routemaker.agency_roads): into the tags classification reads
    # (`class_tags_by_way`), and into every variant's routing tags where the
    # District's record made the way one-way (OWNER-DECISIONS 216,
    # `variants.agency_routing_tags`).
    "dc-contraflow-lane": {
        "oneway:bicycle": "no",
        "cycleway:left": "opposite_lane",
        "bicycle": "yes",
    },
    # The District's shape for a contraflow lane in OSM: the lane on the left runs
    # against the traffic, a sharrow on the right, and the one-way is waived.
    "left-contraflow-lane-and-sharrow": {
        "oneway:bicycle": "no",
        "cycleway:left": "lane",
        "cycleway:left:oneway": "-1",
        "cycleway:right": "shared_lane",
    },
    "left-lane-and-sharrow-without-oneway-bicycle": {
        "cycleway:left": "lane",
        "cycleway:right": "shared_lane",
    },
    "everything-at-once": {
        "oneway:bicycle": "no",
        "cycleway": "opposite_lane",
        "cycleway:right": "opposite_track",
        "bicycle:backward": "yes",
        "vehicle:backward": "yes",
        "bicycle:backward:conditional": "designated @ (Sa)",
    },
}

# The directions of a one-way's geometry: `oneway=-1` runs against the way's
# nodes, so the traffic goes backward and a contraflow rider forward.
ONEWAYS = {"yes": ("bike_forward", "bike_backward"), "-1": ("bike_backward", "bike_forward")}


def _flow_access(tags: dict[str, str]) -> tuple[str, str]:
    """(with the one-way's traffic, against it), as upstream's transform reads
    the way, for a way carrying `oneway=yes` or `-1`."""
    forward, backward = _bike_access(tags)
    by_name = {"bike_forward": forward, "bike_backward": backward}
    with_flow, against = ONEWAYS[tags["oneway"]]
    return by_name[with_flow], by_name[against]


@pytest.mark.parametrize("oneway", sorted(ONEWAYS))
@pytest.mark.parametrize("form", sorted(CONTRAFLOW_FORMS))
def test_the_no_trail_variant_gives_a_one_way_no_contraflow(form, oneway) -> None:
    """The closure, read back through the shipped entry point: on the no-trail
    graph a bicycle rides a one-way with the traffic only, whichever tag shape
    gave it the other direction; and the standard graph, which a Group Ride with
    trails on uses, keeps whatever upstream reads from the same tags."""
    from pipeline.variants import Variant, inject

    tags = {"highway": "primary", "oneway": oneway, **CONTRAFLOW_FORMS[form]}
    closed = inject(Variant.NO_TRAIL, dict(tags), 7)
    assert _flow_access(closed) == ("true", "false"), closed
    for variant in (Variant.STANDARD, Variant.WEEKEND, Variant.EBIKE):
        assert inject(variant, dict(tags), 7) == tags, variant.value
    # The control: the standard graph does ride against the traffic on these
    # tags. Upstream's own reading of `oneway=-1` with `oneway:bicycle=no` is
    # the one exception (it grants nothing there), kept as a form because the
    # closure must not make it worse.
    standard = _flow_access(tags)
    if (form, oneway) != ("oneway-bicycle-no", "-1"):
        assert standard[1] == "true", (form, oneway, standard)


@pytest.mark.parametrize("oneway", ["true", "1"])
def test_every_spelling_of_one_way_is_closed(oneway) -> None:
    from pipeline.variants import Variant, inject

    tags = {"highway": "residential", "oneway": oneway, "cycleway:left": "opposite_lane"}
    assert _bike_access(tags) == ("true", "true"), "the control"
    assert _bike_access(inject(Variant.NO_TRAIL, dict(tags), 7)) == ("true", "false")


def test_a_roundabout_is_a_one_way_without_saying_so() -> None:
    """Upstream forces `junction=roundabout` one-way whatever `oneway` says."""
    from pipeline.variants import Variant, inject

    tags = {"highway": "secondary", "junction": "roundabout", "cycleway:left": "opposite_lane"}
    assert _bike_access(tags) == ("true", "true"), "the control"
    assert _bike_access(inject(Variant.NO_TRAIL, dict(tags), 7)) == ("true", "false")


@pytest.mark.parametrize(
    "tags",
    [
        {"oneway": "no", "oneway:bicycle": "no"},
        {"cycleway:left": "opposite_lane"},
        {"cycleway": "opposite_track", "oneway:bicycle": "no"},
        {"oneway": "reversible", "cycleway:left": "opposite_lane"},
        {"oneway": "alternating", "bicycle:backward": "yes"},
        {"oneway": "no", "cycleway:both": "lane"},
        {"bicycle:backward": "yes"},
    ],
)
def test_a_two_way_street_is_left_alone(tags) -> None:
    from pipeline.variants import Variant, inject

    way = {"highway": "residential", **tags}
    for variant in Variant:
        assert inject(variant, dict(way), 7) == way, variant.value
    assert _bike_access(way) == ("true", "true")


@pytest.mark.parametrize("oneway", sorted(ONEWAYS))
def test_the_closure_keeps_the_ride_with_the_traffic(oneway) -> None:
    """A one-way is not closed: the with-flow direction is open, and a bridge
    row's grant, or the legality written onto the way, does not reopen the other."""
    from pipeline.variants import Variant, inject

    for extra in (
        {},
        {"cycleway:right": "lane"},
        {"bicycle": "designated", "cycleway:left": "opposite_lane"},
    ):
        tags = {"highway": "tertiary", "oneway": oneway, **extra}
        assert _flow_access(inject(Variant.NO_TRAIL, dict(tags), 7)) == ("true", "false"), extra
    # The crossings fixture's legality, which the pipeline writes as a derived
    # tag on every variant, is a grant over `bicycle=no` and is not a contraflow.
    legal = {
        "highway": "primary",
        "bridge": "yes",
        "oneway": oneway,
        "bicycle": "no",
        "cycleway:left": "opposite_lane",
        "rm:bridge_bicycle": "yes",
    }
    assert _flow_access(inject(Variant.NO_TRAIL, dict(legal), 7)) == ("true", "false")
    assert _flow_access(legal)[1] == "true", "the control"


@pytest.mark.parametrize(
    "form",
    [
        "oneway-bicycle-no",
        "cycleway-opposite-lane",
        "left-opposite-track",
        "left-contraflow-lane-and-sharrow",
        "lane-both",
        "vehicle-backward-yes",
        "undirected-conditional-waived",
        # The closure rewrites these to `bicycle:backward=none`, which the remap
        # does not read as a restriction on a one-way (`access_is_unrestricted`).
        "bicycle-backward-yes",
        "bicycle-backward-designated",
        "everything-at-once",
    ],
)
@pytest.mark.parametrize("neutral", [False, True])
@pytest.mark.parametrize("oneway", sorted(ONEWAYS))
def test_the_closure_leaves_the_stress_penalty_on_a_one_way(form, oneway, neutral) -> None:
    """The closure must not make a one-way read as restricted to the remap
    (`access_is_unrestricted` reads `access`, `vehicle`, `bicycle` and its two
    directional keys): the stress penalty, `bicycle=use_sidepath` on a tier 3 or
    worse way, is what keeps a stressful one-way costly on the graph every ride
    with trails off is routed on. With the penalty written, the way still
    reads with the traffic only, with and without the no-trail graph's own
    `rm:facility_neutral`."""
    from pipeline.variants import Variant, inject

    tags = {
        "highway": "secondary",
        "oneway": oneway,
        "rm:stress_tier": "4",
        **({"rm:facility_neutral": "yes"} if neutral else {}),
        **{k: v for k, v in CONTRAFLOW_FORMS[form].items() if k != "bicycle"},
    }
    closed = inject(Variant.NO_TRAIL, dict(tags), 7)
    table = ", ".join(f'["{key}"] = "{value}"' for key, value in sorted(closed.items()))
    result = _lua_driver(
        'dofile("lua/graph.lua")\n'
        f"local _, out = ways_proc({{ {table} }}, 3)\n"
        'io.stdout:write(tostring(out.bicycle), " ", tostring(out.bike_forward), " ",\n'
        '  tostring(out.bike_backward), "\\n")\n'
    )
    assert result.returncode == 0, result.stderr
    bicycle, forward, backward = result.stdout.split()
    assert bicycle == "use_sidepath", closed
    by_name = {"bike_forward": forward, "bike_backward": backward}
    with_flow, against = ONEWAYS[oneway]
    assert (by_name[with_flow], by_name[against]) == ("true", "false"), closed


def test_the_with_flow_conditional_is_not_closed() -> None:
    """Only the conditional that can reach the reverse direction is overwritten;
    a with-flow `bicycle:forward:conditional` still opens its direction."""
    from pipeline.variants import Variant, inject

    tags = {
        "highway": "primary",
        "oneway": "yes",
        "bicycle:forward": "no",
        "bicycle:forward:conditional": "yes @ (Sa,Su)",
    }
    closed = inject(Variant.NO_TRAIL, dict(tags), 7)
    assert closed["bicycle:forward:conditional"] == "yes @ (Sa,Su)"
    assert _bike_access(closed) == ("true", "false")


# Pulaski Highway (ways 17625594 and 50276143 in the 2026-09-25 extract): a
# one-way trunk barred to bicycles except at weekends. The remap used to resolve
# its undirected conditional onto `bicycle:backward=yes` as well, which upstream
# reads as a second direction, so every graph but the no-trail one rode it
# against the traffic (contraflow review r1). Not a contraflow lane: the way
# grants no reverse direction of its own.
PULASKI = {
    "highway": "trunk",
    "name": "Pulaski Highway",
    "bicycle": "no",
    "bicycle:conditional": "yes @ (Sa-Su dawn-dusk; PH dawn-dusk)",
    "cycleway:both": "no",
}

# Every way upstream reads as one-way for motor traffic, and which of its
# geometry's directions the traffic takes.
ONEWAY_SHAPES = {
    "yes": {"oneway": "yes"},
    "true": {"oneway": "true"},
    "1": {"oneway": "1"},
    "-1": {"oneway": "-1"},
    "roundabout": {"junction": "roundabout"},
    "circular": {"junction": "circular"},
}


def _traffic_access(tags: dict[str, str]) -> tuple[str, str]:
    """(with the traffic, against it) for any one-way shape."""
    forward, backward = _bike_access(tags)
    return (backward, forward) if tags.get("oneway") == "-1" else (forward, backward)


@pytest.mark.parametrize("shape", sorted(ONEWAY_SHAPES))
@pytest.mark.parametrize("variant_name", ["STANDARD", "WEEKEND", "EBIKE", "NO_TRAIL"])
def test_a_conditional_never_opens_a_one_way_against_its_traffic(variant_name, shape) -> None:
    """Through the shipped entry point on every variant's tags: the weekend
    grant opens the way with the traffic and never against it."""
    from pipeline.variants import Variant, inject

    tags = {**PULASKI, **ONEWAY_SHAPES[shape]}
    built = inject(Variant[variant_name], dict(tags), 7)
    assert _traffic_access(built) == ("true", "false"), (variant_name, built)


@pytest.mark.parametrize("variant_name", ["STANDARD", "WEEKEND", "EBIKE", "NO_TRAIL"])
def test_the_same_conditional_on_a_two_way_road_opens_both_directions(variant_name) -> None:
    """The control: the conditional resolution is unchanged on a two-way way,
    and is what opens the road at all (the base is `bicycle=no`)."""
    from pipeline.variants import Variant, inject

    built = inject(Variant[variant_name], dict(PULASKI), 7)
    assert _bike_access(built) == ("true", "true"), variant_name
    bare = {k: v for k, v in PULASKI.items() if k != "bicycle:conditional"}
    assert _bike_access(bare) == ("false", "false"), "the control's control"


@pytest.mark.parametrize("oneway", sorted(ONEWAYS))
@pytest.mark.parametrize(
    "grant",
    [
        {"oneway:bicycle": "no"},
        {"oneway:bicycle": "-1"},
        {"cycleway:left": "opposite_lane"},
        {"cycleway": "opposite"},
        {"bicycle:backward:conditional": "yes @ (Sa,Su)"},
    ],
    ids=[
        "oneway-bicycle-no",
        "oneway-bicycle-minus-one",
        "left-opposite-lane",
        "opposite",
        "backward-conditional",
    ],
)
def test_a_one_way_that_grants_contraflow_keeps_its_conditional_reverse(grant, oneway) -> None:
    """Where the way itself grants the reverse direction, the conditional still
    opens it on the standard, weekend and e-bike graphs (the way is barred
    without it), and the no-trail graph still closes it."""
    from pipeline.variants import Variant, inject

    tags = {**PULASKI, "oneway": oneway, **grant}
    for variant in (Variant.STANDARD, Variant.WEEKEND, Variant.EBIKE):
        built = inject(variant, dict(tags), 7)
        assert _traffic_access(built)[1] == "true", (variant.value, built)
    assert _traffic_access(inject(Variant.NO_TRAIL, dict(tags), 7)) == ("true", "false")


# Ways upstream's highway table closes to a bicycle by class alone, found open
# under the retired ordinary-ride penalty by the round-3 correctness and
# mutation reviews (their probes, through lua/graph.lua), and one open class as
# control. The stress penalty and the tier-5 mark are the same writes now.
CLASS_BARRED_WAYS = {
    "motorway": {"highway": "motorway"},
    "motorway_link": {"highway": "motorway_link"},
    "footway": {"highway": "footway"},
    "sidewalk": {"highway": "footway", "footway": "sidewalk"},
    "footway-foot-designated": {"highway": "footway", "foot": "designated"},
    "footway-access-yes": {"highway": "footway", "access": "yes"},
    "pedestrian": {"highway": "pedestrian"},
    "bridleway": {"highway": "bridleway"},
    "busway": {"highway": "busway"},
    "bus_guideway": {"highway": "bus_guideway"},
    "corridor": {"highway": "corridor"},
    "elevator": {"highway": "elevator"},
    "platform": {"highway": "platform"},
}


@pytest.mark.parametrize("tier", ["3", "4", "5"])
@pytest.mark.parametrize("name", sorted(CLASS_BARRED_WAYS))
def test_the_stress_penalty_never_opens_a_class_upstream_bars(name, tier) -> None:
    tags = CLASS_BARRED_WAYS[name]
    assert _bike_access(tags) == ("false", "false"), "the control: the class bars it"
    marked = {**tags, "rm:stress_tier": tier}
    assert _bike_access(marked) == ("false", "false")


@pytest.mark.parametrize("tier", ["3", "4", "5"])
def test_the_stress_penalty_keeps_an_open_untagged_road_open(tier) -> None:
    marked = {"highway": "residential", "rm:stress_tier": tier}
    assert _bike_access(marked) == ("true", "true")


def test_the_border_guard_does_not_delete_the_border_node() -> None:
    """The guard exists so a state crossing stays passable. Written as `error()`
    it deleted the crossing node instead, which is the one outcome its comment
    ruled out."""
    result = _lua_driver(
        'dofile("lua/graph.lua")\n'
        'local remap = require("routemaker_remap")\n'
        'remap.remap_node = function() return { bicycle = "no" } end\n'
        'local _, out = nodes_proc({ barrier = "border_control", name = "StateLine" }, 2)\n'
        'io.stdout:write(tostring(out.name), " ", tostring(out.border_control), " ",\n'
        '  tostring(out.bicycle), " ", tostring(out.access_mask), "\\n")\n'
    )
    assert result.returncode == 0, result.stderr
    name, border, bicycle, mask = result.stdout.split()
    assert name == "StateLine", "the node was blanked"
    assert border == "true", "upstream no longer sees a border control node"
    assert bicycle == "nil", "the denying change was applied rather than refused"
    assert int(mask) // 4 % 2 == 1, "bicycle access at the border was removed"
    assert "ROUTEMAKER-VIOLATION" in result.stderr


def test_the_violation_sentinel_is_not_a_key_valhalla_reads() -> None:
    """Deliberate: the sentinel marks an element for whoever is watching the
    transform and must not be able to become a fact about the graph."""
    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    match = re.search(r'M\.VIOLATION_TAG = "([^"]+)"', source)
    assert match, "the sentinel is no longer declared where the entry point and the tests read it"
    sentinel = match.group(1)
    supported = {
        line.strip()
        for line in (REPO / "lua" / "vendor" / "supported_keys.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert sentinel not in supported
    assert not sentinel.startswith("rm:"), "it would be stripped before anything could see it"


def test_neither_entry_point_guards_with_error() -> None:
    """A transform-time `error()` is a silent delete. The two load-time ones are
    a different thing: they run in LuaTagTransform's constructor, which does
    throw, and are the loud case."""
    source = (REPO / "lua" / "graph.lua").read_text()
    entry_points = source[source.index("function ways_proc") :]
    assert "error(" not in entry_points, "a guard inside an entry point deletes the element"
    assert "record_violation" in entry_points


def lua_table(source: str, name: str) -> dict[str, str]:
    """One `name = { ... }` table out of a Lua file, as a dict of strings."""
    body = re.search(rf"^{name}\s*=\s*\{{(.*?)\}}", source, re.MULTILINE | re.DOTALL)
    assert body, f"no {name} table in the vendored file"
    return dict(re.findall(r'\["([^"]+)"\]\s*=\s*"([^"]*)"', body.group(1)))


def test_the_lit_mapping_is_upstreams_own_table() -> None:
    """The pipeline decides `rm:lit` from OSM's `lit` value, and what that value
    means is upstream's table, not "yes against everything else".

    `24/7`, `automatic`, `dusk-dawn` and `sunset-sunrise` all name a lit street.
    The derivation was `tags["lit"] == "yes"`, which called every one of them
    unlit and then wrote `lit=no` over the way's own tag - so the graph and the
    segment column both disagreed with OSM, in the direction the "Prefer lit
    streets" preference reads. Regenerated and compared rather than copied, so a
    re-vendor that changes the table fails here instead of diverging quietly.
    """
    from pipeline.run import LIT_BY_OSM_VALUE, lit_value

    upstream = lua_table((REPO / "lua" / "vendor" / "graph_upstream.lua").read_text(), "lit")
    assert upstream, "the vendored transform has no lit table any more"
    assert LIT_BY_OSM_VALUE == {key: value == "true" for key, value in upstream.items()}

    # The two mutations a `== "yes"` derivation survives.
    assert lit_value({"lit": "24/7"}) is True
    assert lit_value({"lit": "disused"}) is False, '`!= "no"` would call this lit'
    # A value upstream does not carry maps to nil there, which drops the tag
    # rather than asserting either way, so nothing is asserted here either.
    assert lit_value({"lit": "maybe"}) is None
    assert lit_value({}) is None


def test_the_violation_prefix_the_pipeline_greps_for_is_the_one_the_lua_writes() -> None:
    """Two files that cannot share a constant, and the whole guard is the string
    matching. `lua/routemaker_remap.lua` writes it and `pipeline.run` searches
    the parse log for it."""
    from pipeline.run import VIOLATION_LOG_PREFIX

    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    declared = re.search(r'M\.VIOLATION_LOG_PREFIX\s*=\s*"([^"]+)"', source)
    assert declared, "the remap no longer declares a violation prefix"
    assert declared.group(1) == VIOLATION_LOG_PREFIX


def test_the_remap_reads_each_side_as_the_classifier_does() -> None:
    """`declares_cycleway` and the classifier's side record, over every
    combination of the four key forms.

    The two files cannot share the precedence table, and the guard exists to
    keep the remap's `cycleway=track` write off a way whose sides somebody has
    already spoken for - the same sides `tags.cycleway_sides` resolves before
    the classifier scores the way. So the Lua is driven over the whole grid and
    has to give the answer Python gives, side by side.
    """
    import itertools

    from routemaker.tags import CYCLEWAY_KEYS, cycleway_sides

    values = (None, "", "no", "lane", "track")
    cases = [
        {key: value for key, value in zip(CYCLEWAY_KEYS, combo, strict=True) if value is not None}
        for combo in itertools.product(values, repeat=len(CYCLEWAY_KEYS))
    ]
    lua_cases = ",\n".join(
        "{" + ", ".join(f'["{k}"] = "{v}"' for k, v in case.items()) + "}" for case in cases
    )
    result = _lua_driver(
        'package.path = "lua/?.lua;" .. package.path\n'
        'local M = require("routemaker_remap")\n'
        f"local cases = {{\n{lua_cases}\n}}\n"
        "for _, tags in ipairs(cases) do\n"
        '  io.stdout:write(tostring(M.cycleway_on_side(tags, "left")), " ",\n'
        '    tostring(M.cycleway_on_side(tags, "right")), " ",\n'
        '    tostring(M.declares_cycleway(tags)), "\\n")\n'
        "end\n"
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == len(cases)
    for case, line in zip(cases, lines, strict=True):
        sides = cycleway_sides(case)
        left, right = (str(sides[s].value) if sides[s].value else "nil" for s in ("left", "right"))
        declared = "true" if sides["left"].value or sides["right"].value else "false"
        assert line.split() == [left, right, declared], case


# --- The intersection model's one dependence on the transform ---------------
#
# `routemaker.intersections` reads a junction's signal from the router's tiles
# (`/locate`'s `traffic_signal`), and the transform decides what a signal is.
# Upstream's `nodes_proc` reads `highway=traffic_signals` and
# `traffic_signals:direction`; a mapped crossing way tagged
# `crossing=traffic_signals` (a signal or a HAWK on a trail crossing) is not one,
# which is why the model counts a marked crossing with no signal flag at
# `MARKED_CROSSING_FACTOR` (docs/DEVELOPMENT.md, "Known gaps"). These two tests
# are the tripwire for that gap: when either side changes, the factor should too.


def test_upstream_reads_signals_from_traffic_signals_nodes_only() -> None:
    upstream = (REPO / "lua" / "vendor" / "graph_upstream.lua").read_text()
    reads = {m.group(0) for m in re.finditer(r"traffic_signals[:\w]*", upstream)}
    assert reads == {"traffic_signals", "traffic_signals:direction"}, (
        "upstream now reads another signal tag: a signalised trail crossing may reach the "
        "router's signal flag, and routemaker.intersections.MARKED_CROSSING_FACTOR is stale"
    )
    assert not re.search(r"crossing\W+\]?\s*==\s*[\"']traffic_signals", upstream)


def test_the_remap_derives_no_signal() -> None:
    """Nothing here writes `forward_signal` or `backward_signal`, so a node's
    signal flag is upstream's. Deriving one from `crossing=traffic_signals` is a
    recorded follow-up that needs a rebuild to verify (OPERATIONS.md, "Intersection
    costs and the calm search")."""
    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    assert "forward_signal" not in source and "backward_signal" not in source
    assert "traffic_signals" not in source


# OWNER-DECISIONS 216 ("Enforce on all maps"): the District's one-way record is
# every routing graph's direction. The overlay's routing decision
# (`agency_roads.Overlay.routing`), laid over the way's OSM tags
# (`variants.agency_routing_tags`) and handed to each variant, read back through
# the shipped entry point.
DISTRICT_DIRECTIONS = {
    # Row B: OSM's explicit two-way, the record one-way; OSM's lane each side,
    # which upstream would open both ways on a one-way, is not a contraflow lane.
    "row-b": (
        {"highway": "secondary", "oneway": "no", "cycleway:both": "lane"},
        {"oneway": "yes"},
        ("true", "false"),
        ("true", "false"),
    ),
    "row-b-against-the-line": (
        {"highway": "secondary", "oneway": "no"},
        {"oneway": "-1"},
        ("false", "true"),
        ("false", "true"),
    ),
    # A one-way OSM does not tag, the record's.
    "filled": ({"highway": "residential"}, {"oneway": "yes"}, ("true", "false"), ("true", "false")),
    # Row C4: OSM's one-way, the record two-way.
    "row-c4": (
        {"highway": "residential", "oneway": "yes", "cycleway:right": "lane"},
        {"oneway": "no"},
        ("true", "true"),
        ("true", "true"),
    ),
    # The record's one-way with its flagged contraflow lane: ridden against the
    # traffic on the standard graph, closed on the no-trail graph (items 192, 219).
    "contraflow": (
        {"highway": "residential", "oneway": "no"},
        {"oneway": "yes", "oneway:bicycle": "no", "cycleway:left": "opposite_lane"},
        ("true", "true"),
        ("true", "false"),
    ),
    "contraflow-against-the-line": (
        {"highway": "residential", "oneway": "no"},
        {"oneway": "-1", "oneway:bicycle": "no", "cycleway:left": "opposite_lane"},
        ("true", "true"),
        ("false", "true"),
    ),
}


@pytest.mark.parametrize("case", sorted(DISTRICT_DIRECTIONS))
def test_routing_direction_follows_the_district_s_record(case) -> None:
    """(forward, backward) along the way's geometry on the standard, weekend and
    e-bike graphs, and on the no-trail graph; and OSM's own reading differs, so
    the test can tell."""
    from pipeline.variants import Variant, agency_routing_tags, inject

    osm, routing, others, no_trail = DISTRICT_DIRECTIONS[case]
    changes = agency_routing_tags(dict(osm), routing)
    graph = {**osm, **changes}
    # Rewritten, never removed: every OSM key is still there.
    assert set(osm) <= set(graph)
    for variant in (Variant.STANDARD, Variant.WEEKEND, Variant.EBIKE):
        assert _bike_access(inject(variant, dict(graph), 7)) == others, (case, variant.value)
    assert _bike_access(inject(Variant.NO_TRAIL, dict(graph), 7)) == no_trail, case
    assert _bike_access(osm) != others or _bike_access(osm) != no_trail, "the control"
