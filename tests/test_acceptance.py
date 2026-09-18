"""`scripts/acceptance.py` — the phase-1 checklist as a program.

Two things are held here. The script's *facts* about the stack (service names,
router URLs, the health path, the data-root directories) are derived from the
rendered configuration, the settings and the scripts they describe, so the
checklist cannot quietly disagree with the deployment it checks. And its pure
parts (the env-file reader, the `ps` parser, the report, the dry run) are
exercised without a daemon, because that is the one way this file can run.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from test_compose_render import render

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "acceptance.py"

STDLIB = set(sys.stdlib_module_names)


@pytest.fixture(scope="module")
def SERVICES() -> dict:
    """The rendered stack from the shipped example, the way the deploy tests read it."""
    return render(REPO / ".env.example")["services"]


@pytest.fixture(scope="module")
def acceptance():
    spec = importlib.util.spec_from_file_location("acceptance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: a dataclass under `from __future__ import
    # annotations` resolves its field types through `sys.modules`.
    sys.modules["acceptance"] = module
    spec.loader.exec_module(module)
    return module


def test_the_script_imports_the_standard_library_only():
    """It runs on the deploy host's Python, outside this repository's
    virtualenv and outside every container, so nothing here may import Django
    or anything installed by `pyproject.toml`."""
    tree = ast.parse(SCRIPT.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or "").split(".")[0])
    outside = sorted(name for name in imported if name and name not in STDLIB)
    assert outside == [], f"acceptance.py imports outside the standard library: {outside}"


# -- the facts the script encodes, held against what they describe ----------


def test_the_routers_are_the_valhalla_services_compose_runs(acceptance, SERVICES):
    valhalla = sorted(n for n, s in SERVICES.items() if "valhalla" in (s.get("image") or ""))
    assert sorted(acceptance.ROUTERS) == valhalla


def test_the_router_urls_are_the_upstreams_the_api_repoints(acceptance):
    assert acceptance.ROUTER_URL == settings.VALHALLA_UPSTREAMS


def test_the_health_and_login_paths_are_the_routed_ones(acceptance):
    assert acceptance.HEALTHZ == reverse("healthz")
    assert acceptance.LOGIN == reverse("login")


def test_the_django_services_are_the_ones_that_run_manage_py(acceptance, SERVICES):
    api_image = SERVICES["api"]["image"]
    django = sorted(
        n
        for n, s in SERVICES.items()
        if s.get("image") == api_image or "pipeline" in (s.get("image") or "")
    )
    # `migrate` is a one-shot and is watched, not exec'd into.
    assert sorted(acceptance.DJANGO_SERVICES) == sorted(set(django) - {"migrate"})


def test_the_restart_the_checklist_issues_is_the_one_the_commands_print(acceptance):
    from core.management.commands import rollback_rebuild, run_rebuild_now

    for hint in (run_rebuild_now.RESTART_HINT, rollback_rebuild.RESTART_HINT):
        assert "docker compose restart " + " ".join(acceptance.ROUTERS) in hint


def test_the_data_root_directories_are_read_from_the_prepare_script(acceptance, SERVICES):
    listed = acceptance.data_root_directories(REPO / "scripts" / "prepare_data_root.sh")
    assert "tiles" in listed and "backups" in listed and "postgres" in listed
    # Every host directory the rendered stack binds under DATA_ROOT is one the
    # script creates, so A1's "prepared" check covers the mounts.
    bound = set()
    for service in SERVICES.values():
        for volume in service.get("volumes", []):
            source = volume.get("source", "")
            marker = "/data/"
            if marker in source:
                bound.add(source.split(marker, 1)[1].split("/")[0])
    assert bound <= set(listed), bound - set(listed)


def test_the_free_space_floor_is_the_disk_gates(acceptance):
    assert acceptance.MIN_FREE_GIB * 1024**3 == settings.REBUILD_MIN_FREE_BYTES


def test_the_canary_is_two_points_inside_the_coverage_polygon(acceptance):
    (lon1, lat1), (lon2, lat2) = acceptance.CANARY
    west, south, east, north = -78.0, 38.2, -76.3, 39.5
    for lon, lat in ((lon1, lat1), (lon2, lat2)):
        assert west < lon < east and south < lat < north


# -- the pure parts --------------------------------------------------------


def test_the_env_reader_applies_composes_four_rules(acceptance, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nA=1\nA=2\r\nB='pa$w0rd'\nC=\"quoted\"\nD=un'balanced\n"
        "not a key=value\n  E = spaced \n"
    )
    values = acceptance.read_env_file(env)
    assert values["A"] == "2"  # the last assignment wins, the CR is gone
    assert values["B"] == "pa$w0rd"  # a matching pair of quotes is stripped
    assert values["C"] == "quoted"
    assert values["D"] == "un'balanced"  # an unbalanced quote is kept
    assert "not a key" not in values
    assert values["E"] == "spaced"


def test_the_ps_parser_reads_both_shapes_compose_prints(acceptance):
    row = {"Service": "postgis", "State": "running", "Health": "healthy"}
    assert acceptance.parse_ps(json.dumps([row])) == [row]
    assert acceptance.parse_ps(json.dumps(row) + "\n" + json.dumps(row)) == [row, row]
    assert acceptance.parse_ps("") == []


def test_the_report_names_the_outcome_and_every_item(acceptance):
    results = [
        acceptance.Result("A1", "Preflight", "PASS", ["ok"], 1.0),
        acceptance.Result("A2", "Build", "FAIL", ["migrate exited 1"], 2.0),
        acceptance.Result("A6", "Rollback", "SKIP", ["needs two builds"], 0.0),
    ]
    meta = {
        "started": "t",
        "commit": "abc",
        "host": "h",
        "compose_version": "v",
        "site": "s",
        "data_root": "/d",
    }
    text = acceptance.render_markdown(results, meta)
    assert "**Outcome:** FAIL — failed: A2 — skipped: A6" in text
    for item in ("A1", "A2", "A6"):
        assert f"| {item} " in text


def test_the_site_follows_the_caddy_posture(acceptance):
    args = type("A", (), {"dry_run": True})()
    assert acceptance.Context(args, {"CADDY_SITE_ADDRESS": ":80"}).site == "http://127.0.0.1"
    assert acceptance.Context(args, {"CADDY_SITE_ADDRESS": ":8080"}).site == "http://127.0.0.1:8080"
    assert acceptance.Context(args, {"CADDY_SITE_ADDRESS": "routes.example.org"}).site == (
        "https://routes.example.org"
    )


# -- the dry run -----------------------------------------------------------


def _git_only(real_run):
    def run(*args, **kwargs):
        if args[0][:2] == ["git", "rev-parse"]:
            return real_run(*args, **kwargs)
        raise AssertionError(f"a dry run ran a process: {args[0]}")

    return run


def test_a_dry_run_lists_every_item_and_runs_nothing(acceptance, monkeypatch, capsys):
    """The one mode that can run here. It must name all six items, touch no
    process and no network, and exit 0 — a dry run is a plan, not a verdict."""

    real_run = subprocess.run

    def refuse(*args, **kwargs):
        # The report's commit field is the one process a dry run may start.
        if args[0][:2] == ["git", "rev-parse"]:
            return real_run(*args, **kwargs)
        raise AssertionError(f"a dry run ran a process: {args[0]}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(acceptance.urllib.request, "build_opener", refuse)
    code = acceptance.main(["--dry-run", "--skip-manual"])
    out = capsys.readouterr().out
    assert code == 0
    for item, _title, _fn in acceptance.ITEMS:
        assert f"] {item} " in out
    assert "[FAIL]" not in out
    # The plan names the commands an operator would otherwise type.
    for needle in (
        "docker compose build",
        "docker compose up -d --no-build",
        "run_rebuild_now",
        "scripts/install_reference_data.py --data-root /data",
        "docker compose restart " + " ".join(acceptance.ROUTERS),
        "pg_restore --list",
        "rollback_rebuild",
    ):
        assert needle in out, needle


def test_a_resumed_report_skips_the_items_that_passed(acceptance, monkeypatch, tmp_path, capsys):
    earlier = tmp_path / "earlier.json"
    earlier.write_text(
        json.dumps(
            {"results": [{"item": "A1", "status": "PASS"}, {"item": "A2", "status": "FAIL"}]}
        )
    )
    monkeypatch.setattr(subprocess, "run", _git_only(subprocess.run))
    code = acceptance.main(["--dry-run", "--skip-manual", "--resume", str(earlier)])
    out = capsys.readouterr().out
    assert code == 0
    assert "[PASS] A1" in out and "passed in the resumed report" in out
    assert "docker compose build" in out  # A2 was not skipped: it had failed


def test_the_rollback_item_skips_without_a_second_build(acceptance, monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", _git_only(subprocess.run))
    acceptance.main(["--dry-run", "--skip-manual", "--only", "A6"])
    out = capsys.readouterr().out
    assert "[SKIP] A6" in out and "--second-rebuild" in out
    assert acceptance.main(["--dry-run", "--skip-manual", "--only", "A6", "--strict"]) == 1
