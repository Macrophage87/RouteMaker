"""The analysis script that compares our tiers with other agencies' (scripts/analysis/
compare_agency_lts.py): its guards on the internal-only layers.

OWNER-DECISIONS 155: Arlington's Bike Comfort Index and Alexandria's Transport Streets are
for internal comparison only, never copied into anything published. Review r1 found the
script would write their reports wherever `--out` pointed, the repository included, and
nothing refused one of those layers as a published input.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest
from rebuild_fixtures import REPO

from routemaker.agency_roads import InternalOnlySource

SCRIPT = REPO / "scripts" / "analysis" / "compare_agency_lts.py"


@pytest.fixture(scope="module")
def compare():
    spec = importlib.util.spec_from_file_location("compare_agency_lts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "inside",
    ["", "reports", "reports/data-comparison", "reports/data-comparison/internal", "fixtures"],
)
def test_an_internal_report_is_refused_inside_the_repository(compare, inside) -> None:
    with pytest.raises(compare.RefusedOutput, match="inside the repository"):
        compare.internal_output_dir(REPO / inside if inside else REPO)


def test_an_internal_report_needs_somewhere_to_go(compare) -> None:
    with pytest.raises(compare.RefusedOutput, match="--internal-out"):
        compare.internal_output_dir(None)


def test_an_internal_report_may_go_outside_the_repository(compare, tmp_path) -> None:
    assert compare.internal_output_dir(tmp_path / "internal") == (tmp_path / "internal").resolve()


def test_a_published_report_never_reads_an_internal_only_layer(compare, tmp_path) -> None:
    with pytest.raises(InternalOnlySource):
        compare.published_layer(tmp_path / "internal-only" / "arlington" / "layer.geojson")
    assert compare.published_layer(tmp_path / "moco-bicycle-lts" / "layer.geojson")


def test_the_internal_subcommands_refuse_the_repository_before_reading_anything(tmp_path) -> None:
    """Refused at once, before the slow part, and nothing is written."""
    for dataset in ("arlington", "alexandria"):
        done = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                dataset,
                *("--datasets", str(tmp_path), "--ways-dir", str(tmp_path)),
                *("--state-polygons", "x", "--urban", "x", "--live-ways", "x"),
                *("--internal-out", str(REPO / "reports" / "data-comparison" / "internal")),
            ],
            capture_output=True,
            text=True,
        )
        assert done.returncode != 0, dataset
        assert "inside the repository" in done.stderr + done.stdout
    assert not (REPO / "reports" / "data-comparison" / "internal").exists()


def test_internal_reports_are_ignored_by_git_wherever_they_land() -> None:
    done = subprocess.run(
        ["git", "check-ignore", "-q", "reports/data-comparison/internal/x.md"], cwd=REPO
    )
    assert done.returncode == 0
