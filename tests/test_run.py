"""How the rebuild reads a built graph back, and what it does when it cannot.

The two validation reads are the last thing standing between a build and the
swap, so how they fail matters as much as what they say: a read the service
refuses is a sentinel that has moved, and a rebuild is not the way to answer it.
"""

from __future__ import annotations

import json

import pytest

from pipeline import run as run_module
from pipeline import tiles
from pipeline.run import CommandFailed, RebuildContext, ValidationFailed
from pipeline.variants import Variant

# The `valhalla_exception_t` body one-shot mode writes to stdout before exiting
# 1 when map matching finds no edge near the shape it was given
# (src/valhalla_service.cc; the code is baldr::valhalla_exception_t 171).
NO_EDGE_REFUSAL = json.dumps(
    {
        "error_code": 171,
        "error": "No suitable edges near location",
        "status_code": 400,
        "status": "Bad Request",
    }
)


def context_with_build_configs(tmp_path) -> RebuildContext:
    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
        tiles_dir=tmp_path / "tiles",
    )
    context.build_configs = {
        variant: tmp_path / f"{variant.value}-build-config.json" for variant in Variant
    }
    return context


def command_that_exits(stdout: str, stderr: str = ""):
    """The runner's own behaviour on a non-zero exit, which is where both
    validation reads meet a failure: `CommandFailed` carrying both streams."""

    def run(command):
        raise CommandFailed(list(command), 1, tiles.CommandOutput(stdout, stderr))

    return run


def test_a_refused_validation_read_is_terminal_rather_than_retried(tmp_path) -> None:
    """valhalla_service in one-shot mode answers a request it cannot satisfy by
    writing the exception to stdout and exiting 1, and the exit status is all
    the command runner sees. So "no edge near the sentinel" - the failure both
    sentinel coordinates will produce if they have moved, and neither has ever
    been confirmed against a real extract - arrived as `CommandFailed`, which is
    deliberately retryable. The weekly job answered it by rebuilding every tile
    five times over, then alerting with a message about a command exiting 1.
    """
    from config.procrastinate import terminal_causes

    context = context_with_build_configs(tmp_path)
    run = command_that_exits(NO_EDGE_REFUSAL)

    for read in (run_module._standard_cycle_lane, run_module._least_grade_across_variants):
        with pytest.raises(ValidationFailed) as raised:
            read(context, run)
        message = str(raised.value)
        assert "171" in message, f"the code is named: {message}"
        assert "No suitable edges near location" in message, message
        assert isinstance(raised.value, terminal_causes()), "and a rebuild is not the answer"


def test_a_command_that_failed_for_any_other_reason_stays_retryable(tmp_path) -> None:
    """The other door has to keep the class it had. A binary that was killed, a
    config it could not read, a volume that went away: those are the failures a
    second attempt does fix, and turning them terminal would strand a rebuild
    that a retry would have completed."""
    context = context_with_build_configs(tmp_path)

    for stdout, stderr in (
        ("", "2026/09/17 [ERROR] could not load config\n"),
        # A JSON body that is not an exception is not a refusal either.
        (json.dumps({"edges": []}), ""),
    ):
        run = command_that_exits(stdout, stderr)
        with pytest.raises(CommandFailed):
            run_module._standard_cycle_lane(context, run)
        with pytest.raises(CommandFailed):
            run_module._least_grade_across_variants(context, run)


def test_the_sentinels_own_way_is_what_the_cycle_lane_read_is_narrowed_to(
    tmp_path, monkeypatch
) -> None:
    """The way id is threaded from the caller, which is the only place that
    knows which way the sentinel edge lies on. With it, a neighbouring way in
    the same trace cannot answer; without it - the state this repository ships,
    because the sentinel coordinates have never been confirmed against a real
    extract and no id can honestly be written beside them - a trace spanning
    more than one way answers nothing at all rather than answering from
    whichever edge came back first."""
    context = context_with_build_configs(tmp_path)

    def run(command):
        return tiles.CommandOutput(
            json.dumps(
                {
                    "edges": [
                        {"way_id": 111, "cycle_lane": "shared"},
                        {"way_id": 222, "cycle_lane": "separated"},
                    ]
                }
            ),
            "",
        )

    assert run_module.DERIVED_SENTINEL_WAY_ID is None
    assert run_module._standard_cycle_lane(context, run) is None

    monkeypatch.setattr(run_module, "DERIVED_SENTINEL_WAY_ID", 222)
    assert run_module._standard_cycle_lane(context, run) == "separated"
    monkeypatch.setattr(run_module, "DERIVED_SENTINEL_WAY_ID", 111)
    assert run_module._standard_cycle_lane(context, run) == "shared"


def test_the_read_uses_the_standard_variants_own_build_config(tmp_path) -> None:
    """The derived-tag sentinel is read out of the standard variant's graph, and
    the config is what names the tiles to open."""
    context = context_with_build_configs(tmp_path)
    seen: list[list[str]] = []

    def run(command):
        seen.append(list(command))
        return tiles.CommandOutput(
            json.dumps({"edges": [{"way_id": 7, "cycle_lane": "separated"}]}), ""
        )

    assert run_module._standard_cycle_lane(context, run) == "separated"
    assert seen[0][1] == str(context.build_configs[Variant.STANDARD])
