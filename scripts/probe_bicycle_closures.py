#!/usr/bin/env python3
"""After a swap: do the serving routers keep singletrack closed to bicycles?

The rebuild's VALIDATE stage checks the staged tiles before the swap
(`pipeline.run.assert_bicycle_closures_reached_the_tiles`). This asks the same
question of what is actually being served, which also catches a router that was
never restarted onto the new build (docs/OPERATIONS.md, "After a rebuild:
restart the routers"). Run it in the `rebuild` container, which has this
script, the rebuild's reports and the routers' addresses:

    docker compose exec -T rebuild python3 scripts/probe_bicycle_closures.py locate
    docker compose exec -T rebuild python3 scripts/probe_bicycle_closures.py trip \\
        --preset default --from=-77.0063,38.8973 --to=-76.6158,39.3074 \\
        --avoid-ways /data/rebuild/reports/singletrack-ways.txt --host <allowed host>

`locate` reads the probes VALIDATE wrote (`bicycle-closure-probes.csv`) and asks
every router, with one pedestrian `/locate` each, whether any probed way has an
edge a bicycle may use. Pedestrian, because a bicycle locate finds no edge on a
closed way, which a missed snap also produces; the way's own edges then say
`access.bicycle` (SINGLETRACK-review-r0, finding 7). Exit 1 if any is open, or
if a router that keeps trails found none of the probed ways at all.

`trip` plans a route through the api, as the planner would, map-matches its
geometry on the router that served it and reports the distance it rides on the
ways it must avoid. Exit 1 if that is more than nothing.

Bounded: at most MAX_PROBES probes, and every request has a timeout. It reads
and writes nothing else.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pipeline import tiles  # noqa: E402

REPORTS = Path(os.environ.get("DATA_ROOT", "/data")) / "rebuild" / "reports"
ROUTERS = {
    "standard": os.environ.get("VALHALLA_STANDARD_URL", "http://valhalla-standard:8002"),
    "no-trail": os.environ.get("VALHALLA_NO_TRAIL_URL", "http://valhalla-no-trail:8002"),
    "ebike": os.environ.get("VALHALLA_EBIKE_URL", "http://valhalla-ebike:8002"),
    "weekend": os.environ.get("VALHALLA_WEEKEND_URL", "http://valhalla-weekend:8002"),
}
MAX_PROBES = 200
TIMEOUT_S = 60
MILE_M = 1609.344


def _post(url: str, body: dict, headers: dict[str, str] | None = None) -> object:
    request = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)


def read_probes(path: Path) -> list[tiles.ClosureProbe]:
    with path.open(newline="") as handle:
        probes = [
            tiles.ClosureProbe(int(row["way_id"]), float(row["lon"]), float(row["lat"]))
            for row in csv.DictReader(handle)
        ]
    if len(probes) > MAX_PROBES:
        raise SystemExit(f"{len(probes)} probes in {path}; at most {MAX_PROBES}")
    return probes


def locate(args: argparse.Namespace) -> int:
    probes = read_probes(args.probes)
    if not probes:
        print(f"no probes in {args.probes}: the last rebuild had no closure to check")
        return 0
    failed = False
    for name, url in ROUTERS.items():
        answer = _post(f"{url}/locate", tiles.closure_locate_request(probes))
        readback = tiles.closure_readback(probes, answer)
        verdict = "ok"
        if readback.open_to_bicycles:
            verdict = "OPEN: " + " ".join(str(w) for w in readback.open_to_bicycles)
            failed = True
        elif name != "no-trail" and not readback.found:
            verdict = "FOUND NONE: is this router serving the new build?"
            failed = True
        print(f"{name}: {readback.probed} probed, {readback.found} found, {verdict}")
    return 1 if failed else 0


def _lonlat(text: str) -> list[float]:
    lon, lat = (float(part) for part in text.split(","))
    return [lon, lat]


def trip(args: argparse.Namespace) -> int:
    avoid = set(args.avoid_way)
    if args.avoid_ways:
        avoid |= {int(line) for line in args.avoid_ways.read_text().split() if line.strip()}
    if not avoid:
        raise SystemExit("name the ways to avoid: --avoid-way ID or --avoid-ways FILE")
    route = _post(
        f"{args.api}/api/route",
        {"points": [args.start, args.end], "preset": args.preset, "confirm_long": True},
        {"Host": args.host, "X-Forwarded-Proto": "https"},
    )
    coordinates = route["geometry"]["coordinates"]
    # Bicycle costing: the route only uses edges a bicycle may ride, and on a
    # router that still serves open singletrack those edges include it.
    matched = _post(
        f"{ROUTERS[route['variant']]}/trace_attributes",
        {
            "shape": [{"lon": lon, "lat": lat} for lon, lat, *_ in coordinates],
            "costing": "bicycle",
            "shape_match": "map_snap",
            "filters": {"attributes": ["edge.way_id", "edge.length"], "action": "include"},
        },
    )
    on_avoided: dict[int, float] = {}
    for edge in matched.get("edges", []):
        if edge.get("way_id") in avoid:
            on_avoided[edge["way_id"]] = on_avoided.get(edge["way_id"], 0.0) + 1000 * float(
                edge.get("length") or 0.0
            )
    metres = sum(on_avoided.values())
    print(
        f"{args.preset} on {route['variant']}: {route['distance_m'] / MILE_M:.1f} mi, "
        f"{metres / MILE_M:.2f} mi [{metres / 1000:.2f} km] on the ways to avoid"
        + (
            ": " + ", ".join(f"{w} {m:.0f} m" for w, m in sorted(on_avoided.items()))
            if on_avoided
            else ""
        )
    )
    return 1 if metres > 0 else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("locate", help="the rebuild's closure probes, on every router")
    probe.add_argument("--probes", type=Path, default=REPORTS / "bicycle-closure-probes.csv")
    probe.set_defaults(handler=locate)
    ride = commands.add_parser("trip", help="a planned route, and its distance on avoided ways")
    ride.add_argument("--preset", required=True)
    ride.add_argument(
        "--from", dest="start", type=_lonlat, required=True, help="lon,lat, written --from=LON,LAT"
    )
    ride.add_argument("--to", dest="end", type=_lonlat, required=True, help="--to=LON,LAT")
    ride.add_argument("--avoid-way", type=int, action="append", default=[])
    ride.add_argument("--avoid-ways", type=Path, help="a file of way ids, one per line")
    ride.add_argument("--api", default="http://api:8000")
    ride.add_argument(
        "--host",
        default=(os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost").split(",")[0].strip()),
        help="a host the api allows (DJANGO_ALLOWED_HOSTS)",
    )
    ride.set_defaults(handler=trip)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
