#!/usr/bin/env python3
"""Assert the compose stack's resource and exposure rules.

Run in CI. These are the two rules that are cheap to break by adding a service
and expensive to discover in production: a service with no memory limit can take
PostGIS down with it, a service with no CPU limit can saturate the host during a
rebuild and destroy the latency target, and a published port on anything but
Caddy puts an internal service on the open internet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

# Caddy terminates TLS, so it is the one service that may publish.
MAY_PUBLISH_PORTS = {"caddy"}

# The sum of memory limits, including the duplicate Valhalla containers that
# exist during a swap, must stay under host RAM.
HOST_RAM_GB = 32
SWAP_DUPLICATE_SERVICES = ("valhalla-standard", "valhalla-no-trail", "valhalla-ebike")

# PLAN.md, Operations/"Rebuild and swap": "raising the [worker] count
# multiplies the resident tile working set against the container's memory
# limit," and "the CI compose check asserts the worker count against the
# limit rather than merely asserting that a limit exists."
#
# This is a documented policy assumption, not a profiled measurement - nothing
# in this repository has run a real valhalla_service against these tile
# extracts to measure a worker's resident set (see handoff.md 2a: the image
# cannot even be pulled here). It is calibrated against the one configuration
# that is actually deployed: two workers inside a 2 GB limit. Charging 700 MB
# per worker leaves that configuration a bit under 600 MB of headroom for the
# base process and the resident tile working set outside any one worker's
# stack, which is not nothing but is not generous either - so a change to this
# number should come with a real measurement, not a bigger guess.
VALHALLA_PER_WORKER_MEMORY_MB = 700


def parse_memory_gb(value: str) -> float:
    text = str(value).strip().upper()
    if text.endswith("G"):
        return float(text[:-1])
    if text.endswith("M"):
        return float(text[:-1]) / 1024
    raise ValueError(f"unrecognised memory limit: {value!r}")


def valhalla_worker_count(service: dict) -> int:
    """The count each variant states on its own command line - not a config
    key, since valhalla_service reads none there and falls back to
    hardware_concurrency() if argv carries nothing."""
    command = service.get("command") or []
    if len(command) < 3 or command[0] != "valhalla_service":
        raise ValueError(f"not a valhalla_service command: {command!r}")
    return int(command[2])


def check_valhalla_worker_counts(services: dict) -> list[str]:
    """Each variant's worker count against its own memory and CPU limits,
    rather than merely asserting that a limit exists - the rule PLAN singles
    out by name. A worker count raised from 2 to 64 at the same 2 GB, 2-cpu
    limit must be refused here."""
    problems: list[str] = []
    for name, service in services.items():
        if not name.startswith("valhalla-"):
            continue
        try:
            workers = valhalla_worker_count(service)
        except ValueError as error:
            problems.append(f"{name}: {error}")
            continue

        limits = service.get("deploy", {}).get("resources", {}).get("limits", {})
        if "memory" not in limits or "cpus" not in limits:
            continue  # reported by the caller's own missing-limit check

        memory_mb = parse_memory_gb(limits["memory"]) * 1024
        needed_mb = workers * VALHALLA_PER_WORKER_MEMORY_MB
        if needed_mb > memory_mb:
            problems.append(
                f"{name}: {workers} workers at {VALHALLA_PER_WORKER_MEMORY_MB} MB each "
                f"need {needed_mb:.0f} MB, over its {memory_mb:.0f} MB limit"
            )

        cpus = float(limits["cpus"])
        if workers > cpus:
            problems.append(
                f"{name}: {workers} workers exceeds its {cpus:g}-cpu limit, "
                "serialising rather than parallelising the candidate set"
            )
    return problems


# NIT 7: this used to default to the bare string "compose.yaml", which resolves
# against the *caller's* current directory rather than the repository's. A
# test that imported this module and called main() with no argument from a
# different working directory silently read a different file from the one it
# thought it was checking - or none at all. The default now names the file
# next to this script instead of trusting the caller's cwd; passing an
# explicit path, which the CI invocation and the test both do, still works
# exactly as before.
DEFAULT_COMPOSE_PATH = Path(__file__).resolve().parent.parent / "compose.yaml"


def main(path: str | None = None) -> int:
    compose_path = Path(path) if path is not None else DEFAULT_COMPOSE_PATH
    compose = yaml.safe_load(compose_path.read_text())
    services = compose.get("services", {})
    problems: list[str] = []
    total_gb = 0.0

    for name, service in services.items():
        limits = service.get("deploy", {}).get("resources", {}).get("limits", {})

        if "memory" not in limits:
            problems.append(f"{name}: no memory limit")
        else:
            total_gb += parse_memory_gb(limits["memory"])

        if "cpus" not in limits:
            problems.append(f"{name}: no CPU limit")

        if service.get("ports") and name not in MAY_PUBLISH_PORTS:
            problems.append(f"{name}: publishes a port but is not the edge proxy")

    problems.extend(check_valhalla_worker_counts(services))

    # Two peaks, both asserted, because they describe two arrangements.
    #
    # Today: every service is resident, the rebuild worker included, and the
    # build validates itself by reading the tiles back inside its own
    # container - no duplicate serving containers exist. The peak is the plain
    # sum of the limits.
    if total_gb > HOST_RAM_GB:
        problems.append(f"resident total {total_gb:.1f}G exceeds host RAM {HOST_RAM_GB}G")

    # The plan's blue/green swap: a duplicate Valhalla per variant against the
    # new extracts, with the rebuild container out of the way before they
    # start. That arithmetic holds only while the rebuild is not resident, so
    # whoever introduces the duplicates inherits the constraint that the
    # rebuild worker is stopped for the swap window.
    duplicate_gb = sum(
        parse_memory_gb(services[s]["deploy"]["resources"]["limits"]["memory"])
        for s in SWAP_DUPLICATE_SERVICES
        if s in services
    )
    rebuild_gb = parse_memory_gb(
        services.get("rebuild", {})
        .get("deploy", {})
        .get("resources", {})
        .get("limits", {})
        .get("memory", "0M")
    )
    peak_gb = total_gb - rebuild_gb + duplicate_gb
    if peak_gb > HOST_RAM_GB:
        problems.append(f"swap-time peak {peak_gb:.1f}G exceeds host RAM {HOST_RAM_GB}G")

    for problem in problems:
        print(f"compose: {problem}", file=sys.stderr)
    if not problems:
        print(
            f"compose: {len(services)} services, resident {total_gb:.1f}G, "
            f"blue/green swap-time peak {peak_gb:.1f}G"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
