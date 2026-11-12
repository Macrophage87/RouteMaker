#!/usr/bin/env python3
"""A dozen testers at once: replay simulated riders against a stack and report what waits.

Backlog 2026-11-12, "Ready for a dozen testers" (areas 09 item 5, 08 item 2). Beta allows two
route plans at once site-wide (compose.beta.yaml), and every cap there was sized from idle
readings. This script measures the busy case on a copy, never on beta itself.

    python3 scripts/load_test.py --base http://127.0.0.1:8087 --host-header localhost \
        --riders 12 --ride-minutes 10 --docker-stats --out load-12.md

Each simulated rider, started within the first --spread seconds (a group's Saturday start):
  1. opens the app: /healthz, /api/closures/stamp
  2. searches for a place (/api/geocode)
  3. plans a ride (POST /api/route) between two of a fixed list of DC-area places
  4. pans the map: --tiles stress tiles around the start (/tiles/stress/z/x/y.pbf)
  5. rides for --ride-minutes: every 2 minutes (Ride's closure watch and trip check,
     frontend/src/lib/tripCheck.ts TRIP_CHECK_MS) a /api/closures/stamp, and once, half way, a
     re-route from a point on the way (POST /api/route), as a missed turn does.
--time-scale shrinks the ride's clock (0.1 = a 10-minute ride in 1 minute) for a quick pass.

Each rider sends its own X-Forwarded-For (10.77.0.N), so the per-client limits
(src/core/ratelimit.py) count riders apart, as they would on beta. That header is only believed
straight from the api (beta's BETA_API_PORT on 127.0.0.1, or inside the compose network); through
Caddy or nginx it is replaced and all riders share one budget, which the report says.

Where it may run: a loopback or private address only (the PC stack, a cloud box given beta's
compose.beta.yaml caps). On the beta host it refuses to run (~/routemaker-beta-state/vars.sh or
$RM_VARS exists); aimed at beta from elsewhere it cannot tell, so never point it there.
--allow-host NAME adds one more name, for a cloud box reached by name.

--docker-stats (on the host running the stack): samples `docker stats` every 5 s for each
container's memory peak, and compares each container's restart count and OOM flag before and
after. Nothing is written but the report. Standard library only, so it runs anywhere python3 does.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import random
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Public places a tester might ride between (lon, lat). No rider's own place.
PLACES = [
    ("Union Station", (-77.0063, 38.8973)),
    ("Lincoln Memorial", (-77.0502, 38.8893)),
    ("Dupont Circle", (-77.0434, 38.9096)),
    ("Silver Spring Metro", (-77.0311, 38.9939)),
    ("Bethesda Metro", (-77.0941, 38.9847)),
    ("Takoma Metro", (-77.0182, 38.9761)),
    ("Navy Yard", (-77.0050, 38.8764)),
    ("Arlington Courthouse", (-77.0847, 38.8913)),
    ("Georgetown Waterfront", (-77.0633, 38.9022)),
    ("Brookland Metro", (-76.9945, 38.9332)),
    ("College Park Metro", (-76.9283, 38.9786)),
    ("Hyattsville Arts District", (-76.9455, 38.9637)),
]
SEARCHES = ["union station", "tacos", "library", "coffee", "bike shop", "grocery", "park", "metro"]
RIDE_POLL_S = 120  # frontend/src/lib/tripCheck.ts TRIP_CHECK_MS


@dataclass
class Result:
    kind: str
    status: int  # 0 = no answer (timeout, refused)
    seconds: float


@dataclass
class Log:
    results: list[Result] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, kind: str, status: int, seconds: float) -> None:
        with self.lock:
            self.results.append(Result(kind, status, seconds))


class Target:
    def __init__(self, base: str, host_header: str | None, timeout: float) -> None:
        self.base = base.rstrip("/")
        self.host_header = host_header
        self.timeout = timeout

    def call(self, log: Log, kind: str, path: str, rider: int, body: dict | None = None) -> bytes:
        headers = {
            "Accept": "application/json",
            "X-Forwarded-For": f"10.77.0.{rider + 1}",
            "User-Agent": "routemaker-load-test",
        }
        if self.host_header:
            headers["Host"] = self.host_header
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method="POST" if data else "GET"
        )
        start = time.monotonic()
        status, payload = 0, b""
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as answer:
                status, payload = answer.status, answer.read()
        except urllib.error.HTTPError as error:
            status = error.code
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            status = 0
        log.add(kind, status, time.monotonic() - start)
        return payload


def tile_of(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def rider(target: Target, log: Log, n: int, args: argparse.Namespace, rng: random.Random) -> None:
    time.sleep(rng.uniform(0, args.spread))
    target.call(log, "open", "/healthz", n)
    target.call(log, "open", "/api/closures/stamp", n)
    q = urllib.parse.quote(rng.choice(SEARCHES))
    target.call(log, "search", f"/api/geocode?q={q}&limit=5&lat=38.9&lon=-77.03", n)
    (_, a), (_, b) = rng.sample(PLACES, 2)
    target.call(log, "plan", "/api/route", n, {"points": [list(a), list(b)], "preset": args.preset})
    z = 14
    x0, y0 = tile_of(*a, z)
    for i in range(args.tiles):
        target.call(log, "tile", f"/tiles/stress/{z}/{x0 + i % 4 - 2}/{y0 + i // 4 - 2}.pbf", n)
    ride_s = args.ride_minutes * 60 * args.time_scale
    poll_s = RIDE_POLL_S * args.time_scale
    end = time.monotonic() + ride_s
    rerouted = False
    half = time.monotonic() + ride_s / 2
    while time.monotonic() < end:
        time.sleep(min(poll_s, max(0.0, end - time.monotonic())))
        target.call(log, "ride poll", "/api/closures/stamp", n)
        if not rerouted and time.monotonic() >= half:
            mid = [
                (a[0] + b[0]) / 2 + rng.uniform(-0.003, 0.003),
                (a[1] + b[1]) / 2 + rng.uniform(-0.003, 0.003),
            ]
            target.call(
                log, "re-route", "/api/route", n, {"points": [mid, list(b)], "preset": args.preset}
            )
            rerouted = True


class DockerStats:
    """Each container's memory peak (docker stats every 5 s) and its restarts and OOM kills."""

    def __init__(self) -> None:
        self.peaks: dict[str, float] = defaultdict(float)
        self.limits: dict[str, str] = {}
        self.stop = threading.Event()
        self.before = self.inspect()
        self.thread = threading.Thread(target=self.sample, daemon=True)
        self.thread.start()

    @staticmethod
    def inspect() -> dict[str, tuple[int, bool]]:
        ids = subprocess.run(
            ["docker", "ps", "-q"], capture_output=True, text=True, check=False
        ).stdout.split()
        if not ids:
            return {}
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.Name}} {{.RestartCount}} {{.State.OOMKilled}}", *ids],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        found = {}
        for line in out.splitlines():
            name, count, oom = line.split()
            found[name.lstrip("/")] = (int(count), oom == "true")
        return found

    def sample(self) -> None:
        while not self.stop.is_set():
            out = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            for line in out.splitlines():
                name, _, usage = line.partition("\t")
                used, _, limit = usage.partition(" / ")
                self.peaks[name] = max(self.peaks[name], to_mib(used))
                self.limits[name] = limit.strip()
            self.stop.wait(5)

    def finish(self) -> list[str]:
        self.stop.set()
        self.thread.join(timeout=30)
        after = self.inspect()
        lines = [
            "",
            "## Memory and restarts",
            "",
            "| Container | Peak | Cap | Restarts during the test | OOM kill |",
            "|---|---|---|---|---|",
        ]
        for name in sorted(set(self.peaks) | set(after)):
            restarts = after.get(name, (0, False))[0] - self.before.get(name, (0, False))[0]
            oom = after.get(name, (0, False))[1]
            lines.append(
                f"| {name} | {self.peaks.get(name, 0):.0f} MiB | {self.limits.get(name, '?')} | "
                f"{max(restarts, 0)} | {'yes' if oom else 'no'} |"
            )
        return lines


def to_mib(text: str) -> float:
    text = text.strip()
    # docker stats prints binary units (1.2GiB / 1.4GiB); the decimal ones are here in case.
    units = (
        ("GiB", 1024.0),
        ("MiB", 1.0),
        ("KiB", 1 / 1024),
        ("GB", 1e9 / 2**20),
        ("MB", 1e6 / 2**20),
        ("kB", 1e3 / 2**20),
        ("B", 1 / 2**20),
    )
    for unit, factor in units:
        if text.endswith(unit):
            try:
                return float(text[: -len(unit)]) * factor
            except ValueError:
                return 0.0
    return 0.0


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def report(log: Log, args: argparse.Namespace, took: float, direct: bool) -> list[str]:
    lines = [
        f"# Load test: {args.riders} riders",
        "",
        f"{args.riders} riders started within {args.spread:.0f} s, "
        f"each riding {args.ride_minutes} min (time scale {args.time_scale}); "
        f"preset {args.preset}; run took {took:.0f} s.",
        "",
    ]
    if not direct:
        lines += [
            "**Every rider counted as one client** (the target is not the api itself), "
            "so the per-client limits are tighter here than on beta.",
            "",
        ]
    lines += [
        "| Request | Count | OK | Refused (429/503) | Other errors | No answer | p50 | p95 | Max |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    by_kind: dict[str, list[Result]] = defaultdict(list)
    for result in log.results:
        by_kind[result.kind].append(result)
    for kind in ["open", "search", "plan", "tile", "ride poll", "re-route"]:
        results = by_kind.get(kind, [])
        if not results:
            continue
        times = [r.seconds for r in results]
        ok = sum(200 <= r.status < 400 for r in results)
        refused = sum(r.status in (429, 503) for r in results)
        none = sum(r.status == 0 for r in results)
        other = len(results) - ok - refused - none
        lines.append(
            f"| {kind} | {len(results)} | {ok} | {refused} | {other} | {none} | "
            f"{statistics.median(times):.1f} s | {pct(times, 95):.1f} s | {max(times):.1f} s |"
        )
    statuses = sorted({r.status for r in log.results if not 200 <= r.status < 400})
    if statuses:
        lines += [
            "",
            "Statuses other than OK: "
            + ", ".join(
                f"{s or 'no answer'} x{sum(r.status == s for r in log.results)}" for s in statuses
            ),
        ]
    return lines


def allowed(base: str, extra: list[str]) -> str | None:
    """Why the target is refused, or None."""
    beta_vars = [Path.home().joinpath("routemaker-beta-state", "vars.sh")]
    if os.environ.get("RM_VARS"):
        beta_vars.append(Path(os.environ["RM_VARS"]))
    if any(path.exists() for path in beta_vars):
        return (
            "this machine is the beta host (~/routemaker-beta-state/vars.sh); "
            "the load test never runs on beta"
        )
    host = urllib.parse.urlsplit(base).hostname or ""
    if host in extra or host == "localhost":
        return None
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return f"cannot resolve {host}"
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not (ip.is_loopback or ip.is_private):
            return (
                f"{host} is a public address; give --allow-host {host} "
                "if it is your own test box (never beta)"
            )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", required=True, help="the api, e.g. http://127.0.0.1:8087")
    parser.add_argument(
        "--host-header", help="the Host header the api expects (RM_BETA_HOST's role)"
    )
    parser.add_argument("--riders", type=int, default=12)
    parser.add_argument(
        "--spread", type=float, default=60.0, help="seconds over which riders start (our default)"
    )
    parser.add_argument(
        "--ride-minutes", type=float, default=10.0, help="each rider's ride (our default)"
    )
    parser.add_argument("--time-scale", type=float, default=1.0)
    parser.add_argument(
        "--tiles", type=int, default=12, help="stress tiles per rider (one map pan; our default)"
    )
    parser.add_argument("--preset", default="default")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--seed", type=int, default=12)
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--docker-stats", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    why = allowed(args.base, args.allow_host)
    if why:
        print(f"load_test: refused: {why}", file=sys.stderr)
        return 2
    if args.docker_stats and not shutil.which("docker"):
        print("load_test: --docker-stats needs docker on this host", file=sys.stderr)
        return 2
    target = Target(args.base, args.host_header, args.timeout)
    log = Log()
    stats = DockerStats() if args.docker_stats else None
    rng = random.Random(args.seed)
    threads = [
        threading.Thread(target=rider, args=(target, log, n, args, random.Random(rng.random())))
        for n in range(args.riders)
    ]
    start = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    took = time.monotonic() - start
    port = urllib.parse.urlsplit(args.base).port
    direct = port not in (None, 80, 443)
    lines = report(log, args, took, direct)
    if stats:
        lines += stats.finish()
    text = "\n".join(lines) + "\n"
    if args.out:
        args.out.write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
