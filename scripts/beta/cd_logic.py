#!/usr/bin/env python3
"""The decisions behind scripts/beta/auto-release.sh, the beta's pull-based release agent
(OWNER-DECISIONS 431; docs/BETA-RUNBOOK.md, "Continuous deployment").

The shell script does the work; every judgement it acts on is made here, in small pure
functions the tests call directly (tests/test_beta_cd.py):

  pick        which release tag to deploy: the highest strict vX.Y.Z newer than the deployed one
  ci-verdict  whether GitHub's `test` check run is green for the tag's commit
  gate        whether the change between two commits is a code release the server may deploy
              by itself, or needs the owner (data from home, sudo, nginx); and which optional
              steps the deploy needs (front end, router restart, services to recreate)
  rollback    which undo steps a failed deploy needs, from the steps it got through

Standard library only, Python 3.8 or newer: it runs on the server with whatever python3 is
there. It reads git through `git -C <repo>`, never the network. It prints no secret: the
inputs are commit ids, file paths, compose and Valhalla config text, and GitHub's public
check-run JSON.

  cd_logic.py pick --deployed v0.1.0 < tags.txt          # prints the tag, or nothing
  cd_logic.py semver v0.2.0                               # exit 0 if strict vX.Y.Z
  cd_logic.py ci-verdict --sha <40 hex> < check-runs.json # green | pending | red
  cd_logic.py gate --repo DIR --old SHA --new SHA         # KEY=VALUE lines
  cd_logic.py rollback --done stopped,snapshot,...        # one undo action per line
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Callable, Iterable, Optional, Sequence

# --- the release tag -------------------------------------------------------------------------

# Strict: a v, three numbers without leading zeros, nothing before or after. No pre-release or
# build suffix (v1.2.3-rc1 is never deployed by the agent), no "1.2.3", no "v1.2".
SEMVER = re.compile(r"v(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")


def parse_semver(tag: str) -> Optional[tuple]:
    """(major, minor, patch) for a strict vX.Y.Z tag, else None."""
    m = SEMVER.fullmatch(tag)
    if m is None:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def pick_release(tags: Iterable[str], deployed: str) -> Optional[str]:
    """The highest strict vX.Y.Z tag newer than `deployed`, or None.

    Only the highest is ever offered: if it cannot be deployed (CI red, not on main, a
    lightweight tag) the agent waits for the owner rather than falling back to an older one."""
    base = parse_semver(deployed)
    if base is None:
        raise ValueError(f"the deployed tag {deployed!r} is not a strict vX.Y.Z")
    best: Optional[tuple] = None
    best_tag: Optional[str] = None
    for raw in tags:
        tag = raw.strip()
        version = parse_semver(tag)
        if version is None or version <= base:
            continue
        if best is None or version > best:
            best, best_tag = version, tag
    return best_tag


# --- GitHub's check run ----------------------------------------------------------------------

CHECK_NAME = "test"  # .github/workflows/ci.yml, jobs.test: the check main's ruleset requires
CHECK_APP = "github-actions"


def ci_verdict(payload: dict, sha: str, name: str = CHECK_NAME, app: str = CHECK_APP) -> str:
    """green, pending or red for the latest `name` check run on `sha`, from the JSON of
    GET /repos/{owner}/{repo}/commits/{sha}/check-runs.

    Only runs by GitHub Actions on exactly this commit count. The newest such run (highest
    id: a re-run supersedes) decides. No run yet, or one still queued or running, is
    pending: try again next time. Anything that finished other than success is red."""
    runs = [
        run
        for run in payload.get("check_runs") or []
        if isinstance(run, dict)
        and run.get("name") == name
        and run.get("head_sha") == sha
        and (run.get("app") or {}).get("slug") == app
    ]
    if not runs:
        return "pending"
    latest = max(runs, key=lambda run: int(run.get("id") or 0))
    if latest.get("status") != "completed":
        return "pending"
    return "green" if latest.get("conclusion") == "success" else "red"


# --- the gate --------------------------------------------------------------------------------

# Paths whose change means the release needs the owner. Each says why, in the report's words.
STOP_PREFIXES: Sequence[tuple] = (
    (
        "deploy/",
        "the nginx site, its 401 page or the env template changed (owner steps, with sudo)",
    ),
    (
        "scripts/prepare_data_root.sh",
        "the data directory layout changed (prepare_data_root.sh runs with sudo)",
    ),
    ("lua/", "the graph tag transform changed: rebuild the routing graphs at home and ship them"),
    (
        "valhalla/vendor/",
        "the vendored Valhalla config builder changed: rebuild the graphs at home",
    ),
    (
        "src/pipeline/schema.py",
        "the live table layout changed: rebuild the data at home and ship it",
    ),
    ("src/pipeline/variants.py", "the routing graph variants changed: rebuild the data at home"),
    ("src/pipeline/tiles.py", "how the routing graphs are built changed: rebuild the data at home"),
    ("docker/valhalla", "a router image changed"),
    ("docker/photon", "the Photon image changed"),
    ("docker/postgis", "the database image changed"),
)
# A path git would have to quote (a byte outside printable ASCII, a quote, a backslash) or one
# with a character no file in the repository uses: the gate cannot be sure what it is, so it
# stops (it errs closed). The repository's own paths use only these characters.
PLAIN_PATH = re.compile(r"[A-Za-z0-9._/+@=,~-]+")
# Paths that never affect the server (documentation, reports, CI): ignored entirely.
INERT_PREFIXES = ("docs/", "reports/", ".github/", "fixtures/")
INERT_SUFFIXES = (".md",)
OFFROAD_CONFIG = "valhalla/valhalla-offroad.json"
COMPOSE_FILES = ("compose.yaml", "compose.beta.yaml")
# A FORMAT_VERSION change in either tile module needs no data from home: the tile cache is
# keyed on the version, so the release deploys and the agent runs the pre-draw (OWNER-DECISIONS
# 436). The one pre-draw command (predraw_stress_tiles) draws both the stress and the Mass Ride tiles.
TILE_FORMAT_FILES = ("src/core/stress_tiles.py", "src/core/mass_tiles.py")
FORMAT_VERSION = re.compile(r"(?m)^FORMAT_VERSION\s*=\s*(\S+)")
AGENT_FILES = (
    "scripts/beta/auto-release.sh",
    "scripts/beta/cd_logic.py",
    "scripts/beta/receive-data.sh",
)
MIGRATION = re.compile(r"^src/[^/]+/migrations/[^/]+\.py$")
# A migration that names the live schema reads or reshapes data that comes from home. A
# comment that merely mentions it stops the release too: that errs closed.
MIGRATION_NEEDS_DATA = re.compile(r"(?i)\blive\b|LIVE_SCHEMA")

# Valhalla config keys a router reads at start and that need no new graph: a change to only
# these is handled with the four-router restart (docs/BETA-RUNBOOK.md, release step 8).
# Everything else under mjolnir (and all of additional_data) shapes the graph build, and an
# unknown section errs closed: a stop.
VALHALLA_RUNTIME_SECTIONS = frozenset(
    {"httpd", "loki", "meili", "odin", "service_limits", "statsd", "thor"}
)
VALHALLA_RUNTIME_MJOLNIR = frozenset(
    {
        "global_synchronized_cache",
        "logging",
        "lru_mem_cache_hard_control",
        "max_cache_size",
        "max_concurrent_reader_users",
        "use_lru_mem_cache",
        "use_simple_mem_cache",
    }
)


def _flatten(value, prefix: str = "") -> dict:
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return {prefix: value}


def valhalla_change(old_text: Optional[str], new_text: Optional[str]) -> tuple:
    """("none" | "runtime" | "build", [changed keys]) for one valhalla/*.json file.

    A file added or removed, or one that does not parse, is "build" (a stop)."""
    if old_text is None or new_text is None:
        return "build", ["(file added or removed)"]
    try:
        old, new = _flatten(json.loads(old_text)), _flatten(json.loads(new_text))
    except ValueError:
        return "build", ["(not valid JSON)"]
    missing = object()
    changed = sorted(
        key for key in set(old) | set(new) if old.get(key, missing) != new.get(key, missing)
    )
    if not changed:
        return "none", []
    for key in changed:
        section, _, rest = key.partition(".")
        if section in VALHALLA_RUNTIME_SECTIONS:
            continue
        if section == "mjolnir" and rest.split(".")[0] in VALHALLA_RUNTIME_MJOLNIR:
            continue
        return "build", changed
    return "runtime", changed


def compose_change(diff_text: str) -> list:
    """Reasons to stop in a unified diff (-U0) of the compose files, or [] if none.

    A changed image line is a stop (a third-party image to pull, possibly a database or router
    version the shipped data does not match). An added line naming DATA_ROOT may be a new bind
    mount, whose source has to be created under DATA_ROOT with sudo first."""
    reasons = []
    for line in diff_text.splitlines():
        if line.startswith(("+++", "---")) or line[:1] not in ("+", "-"):
            continue
        body = line[1:]
        if re.match(r"\s*image\s*:", body):
            reasons.append(f"a compose image line changed: {body.strip()[:120]}")
        elif line.startswith("+") and "DATA_ROOT" in body:
            reasons.append(
                "compose adds a line under DATA_ROOT (a new data path may need sudo): "
                f"{body.strip()[:120]}"
            )
    return sorted(set(reasons))


def gate(
    changes: Sequence[tuple],
    show: Callable[[str, str], Optional[str]],
    compose_diff: str = "",
) -> dict:
    """The verdict on a release.

    `changes` is git's --name-status as (status, path[, new path]) tuples; `show(side, path)`
    returns a file's text at "old" or "new" (None if absent there); `compose_diff` is the -U0
    diff of the compose files. Returns verdict ("deploy" or "stop"), reasons, and the flags the
    deploy acts on."""
    reasons: list = []
    result: dict = {
        "frontend": False,
        "lockfile_changed": False,
        "migrations": False,
        "compose_changed": False,
        "routers_restart": False,
        "predraw": False,
        "agent_changed": False,
        "changed_files": 0,
        "notes": [],
    }
    paths: list = []
    for change in changes:
        paths.extend(change[1:])
    for path in sorted(set(paths)):
        if not PLAIN_PATH.fullmatch(path):
            # Before the inert test: an odd name under docs/ stops too.
            result["changed_files"] += 1
            reasons.append(
                f"{_clean(path)}: a file name with a character the gate does not accept (a "
                "space, a quote, a backslash, a control or non-ASCII character): check it by hand"
            )
            continue
        if path.startswith(INERT_PREFIXES) or path.endswith(INERT_SUFFIXES):
            continue
        result["changed_files"] += 1
        for prefix, why in STOP_PREFIXES:
            if path == prefix or path.startswith(prefix):
                reasons.append(f"{path}: {why}")
                break
        if path.startswith("frontend/"):
            result["frontend"] = True
            if path in ("frontend/package-lock.json", "frontend/package.json"):
                result["lockfile_changed"] = True
        if path in COMPOSE_FILES:
            result["compose_changed"] = True
        if path in AGENT_FILES:
            result["agent_changed"] = True
        if (
            path.startswith("valhalla/")
            and path.endswith(".json")
            and not path.startswith("valhalla/vendor/")
        ):
            kind, keys = valhalla_change(show("old", path), show("new", path))
            if kind == "build":
                reasons.append(
                    f"{path}: a graph-build setting changed ({', '.join(keys[:5])}): "
                    "rebuild the graphs at home"
                )
            elif kind == "runtime" and path == OFFROAD_CONFIG:
                # valhalla-offroad is never started on the beta (compose profile `offroad`).
                result["notes"].append(
                    f"{path}: runtime settings only ({', '.join(keys[:5])}); "
                    "the offroad router does not run on the beta, so no restart"
                )
            elif kind == "runtime":
                result["routers_restart"] = True
                result["notes"].append(
                    f"{path}: runtime settings only ({', '.join(keys[:5])}); the routers restart"
                )
        if path in TILE_FORMAT_FILES:
            old_v = FORMAT_VERSION.search(show("old", path) or "")
            new_v = FORMAT_VERSION.search(show("new", path) or "")
            old_n = old_v.group(1) if old_v else None
            new_n = new_v.group(1) if new_v else None
            if old_n != new_n:
                result["predraw"] = True
                result["notes"].append(
                    f"{path}: FORMAT_VERSION changed ({old_n} to {new_n}); the tiles are "
                    "pre-drawn after the deploy"
                )
        if MIGRATION.match(path):
            text = show("new", path)
            if text is None:
                reasons.append(f"{path}: a migration was removed")
            else:
                result["migrations"] = True
                if MIGRATION_NEEDS_DATA.search(text):
                    reasons.append(f"{path}: a migration names the live schema (data from home)")
    if compose_diff:
        reasons.extend(compose_change(compose_diff))
    result["reasons"] = sorted(set(reasons))
    result["verdict"] = "stop" if result["reasons"] else "deploy"
    return result


# --- rollback --------------------------------------------------------------------------------

# Deploy steps, in the order the agent runs them; it records each one as it starts it.
STEPS = (
    "stopped",  # api and worker stopped
    "image",  # the api image built or tagged (nothing to undo: the old one keeps its own tag)
    "snapshot",  # pre-release database dump written
    "index_saved",  # the front end's top-level files (index.html, beta-build.txt) copied aside
    "checkout",  # the checkout moved to the new tag
    "tag_set",  # TAG= in .env set to the new release
    "migrate",  # migrate started (the database may have moved forward)
    "frontend",  # front end install started (the index may be the new one)
    "started",  # api and worker started on the new image
    "services",  # photon and the routers recreated for a compose change
    "routers",  # the four routers restarted for a valhalla/*.json change
)


def rollback_plan(done: Iterable[str]) -> list:
    """The undo actions for a deploy that got through `done`, in the order to run them
    (rollback A/C of docs/BETA-RUNBOOK.md, without sudo).

    The database is restored only if a migration ran (the snapshot is what it was before);
    index.html only if the new front end was installed; the routers are restarted again if
    they were restarted or recreated on the new config; the pre-draw follows a database
    restore (the restored stress-tile cache is keyed on the old table's oid)."""
    did = set(done)
    unknown = did - set(STEPS)
    if unknown:
        raise ValueError(f"unknown steps: {sorted(unknown)}")
    if "migrate" in did and "snapshot" not in did:
        raise ValueError("a migration ran without a snapshot: this must never happen")
    plan = []
    if "stopped" in did:
        plan.append("stop-app")
    if "checkout" in did:
        plan.append("checkout-old")
    if "tag_set" in did:
        plan.append("tag-old")
    if "checkout" in did or "tag_set" in did:
        plan.append("gate")
    if "migrate" in did:
        plan.append("restore-db")
    if "frontend" in did:
        plan.append("restore-index")
    if "stopped" in did:
        plan.append("start-app")
    if "services" in did:
        plan.append("recreate-services")
    if "routers" in did or "services" in did:
        plan.append("restart-routers")
    if "migrate" in did:
        plan.append("predraw")
    if "stopped" in did:
        plan.append("smoke")
    return plan


# --- the command line ------------------------------------------------------------------------


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    # surrogateescape: a path that is not UTF-8 still reads (and then fails PLAIN_PATH: a stop).
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        errors="surrogateescape",
        check=False,
    )


def parse_name_status_z(text: str) -> list:
    """(status, path) tuples from `git diff -z --name-status --no-renames`: the fields are
    NUL-terminated, a status then its path. Anything else is refused."""
    fields = text.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2:
        raise SystemExit("cd_logic: git diff -z gave an odd number of fields")
    changes = []
    for i in range(0, len(fields), 2):  # (zip's strict= needs Python 3.10; this runs on 3.8)
        status, path = fields[i], fields[i + 1]
        if not re.fullmatch(r"[ACDMTUX][0-9]{0,3}", status) or not path:
            raise SystemExit(f"cd_logic: unexpected git diff entry {_clean(status)!r}")
        changes.append((status, path))
    return changes


def git_gate(repo: str, old: str, new: str) -> dict:
    """gate() over the git history of `repo` between two full commit ids."""
    for sha in (old, new):
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise SystemExit(f"cd_logic: not a full commit id: {sha!r}")
    # -z: every path exactly as stored, NUL-terminated, never quoted or escaped by git (a quoted
    # path would slip past every prefix test). --no-renames: one path per entry.
    names = _git(repo, "diff", "-z", "--name-status", "--no-renames", old, new)
    if names.returncode != 0:
        raise SystemExit(f"cd_logic: git diff failed: {names.stderr.strip()}")
    changes = parse_name_status_z(names.stdout)
    compose = _git(repo, "diff", "-U0", old, new, "--", *COMPOSE_FILES)
    if compose.returncode != 0:
        # Without the compose diff the image and DATA_ROOT stops cannot be checked: err closed.
        raise SystemExit(
            f"cd_logic: git diff of the compose files failed: {compose.stderr.strip()}"
        )

    def show(side: str, path: str) -> Optional[str]:
        done = _git(repo, "show", f"{old if side == 'old' else new}:{path}")
        return done.stdout if done.returncode == 0 else None

    return gate(changes, show, compose.stdout)


def _clean(text: str) -> str:
    """One printable line, for the KEY=VALUE output the shell reads with sed."""
    return re.sub(r"[^\x20-\x7e]", "?", str(text))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="cd_logic.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("pick").add_argument("--deployed", required=True)
    sub.add_parser("semver").add_argument("tag")
    sub.add_parser("ci-verdict").add_argument("--sha", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--repo", required=True)
    g.add_argument("--old", required=True)
    g.add_argument("--new", required=True)
    sub.add_parser("rollback").add_argument("--done", default="")
    args = parser.parse_args(argv)

    if args.command == "pick":
        tag = pick_release(sys.stdin.read().split(), args.deployed)
        if tag:
            print(tag)
        return 0
    if args.command == "semver":
        return 0 if parse_semver(args.tag) else 1
    if args.command == "ci-verdict":
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            payload = {}
        print(ci_verdict(payload if isinstance(payload, dict) else {}, args.sha))
        return 0
    if args.command == "gate":
        result = git_gate(args.repo, args.old, args.new)
        print(f"verdict={result['verdict']}")
        for key in (
            "frontend",
            "lockfile_changed",
            "migrations",
            "compose_changed",
            "routers_restart",
            "predraw",
            "agent_changed",
        ):
            print(f"{key}={int(result[key])}")
        print(f"changed_files={result['changed_files']}")
        for reason in result["reasons"]:
            print(f"reason={_clean(reason)}")
        for note in result["notes"]:
            print(f"note={_clean(note)}")
        return 0
    if args.command == "rollback":
        for action in rollback_plan(step for step in args.done.split(",") if step):
            print(action)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
