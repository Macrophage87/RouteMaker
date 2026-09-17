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


def parse_memory_gb(value: str) -> float:
    text = str(value).strip().upper()
    if text.endswith("G"):
        return float(text[:-1])
    if text.endswith("M"):
        return float(text[:-1]) / 1024
    raise ValueError(f"unrecognised memory limit: {value!r}")


def main(path: str = "compose.yaml") -> int:
    compose = yaml.safe_load(Path(path).read_text())
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
