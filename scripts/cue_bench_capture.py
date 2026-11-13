"""Plan the cue bench's trips (fixtures/cues/trips.json) on a RouteMaker server and keep each
answer as fixtures/cues/<name>.json, cut to the fields Ride, the exports and the connector's cue
cards read.

The trips are made-up start and end points round junctions where a cue went wrong before; nothing
here is anyone's ride. The server is given on the command line (a local stack, or the beta) and is
never written to the repo. A plan saves nothing on the server.

    python scripts/cue_bench_capture.py http://localhost:8000            # every trip
    python scripts/cue_bench_capture.py http://localhost:8000 kenyon-warder

Then run the bench (frontend: node scripts/cueBench.ts --update) to write the new transcripts, and
read their diff: it shows every cue the new map or server changed.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "fixtures" / "cues"
# What rideModel (frontend/src/lib/navigate.ts), routeDescription.ts and core/cue_cards.py read.
KEPT = (
    "preset",
    "geometry",
    "distance_m",
    "duration_s",
    "time_marks",
    "description",
    "leg_ends",
    "arrival_side",
    "leg_arrival_sides",
    "stress_spans",
)


def trimmed(answer: dict) -> dict:
    out = {k: answer[k] for k in KEPT if k in answer}
    # Work zones change by the day and say nothing about turns: left out so a fixture stays put.
    out["description"] = [e for e in out.get("description") or [] if e.get("kind") != "workzone"]
    return out


def plan(server: str, trip: dict) -> dict:
    ask = {"points": trip["points"], "preset": trip["preset"], "candidates": False}
    body = json.dumps(ask).encode()
    req = urllib.request.Request(
        server.rstrip("/") + "/api/route",
        data=body,
        headers={"content-type": "application/json", "user-agent": "routemaker-cue-bench"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    server, wanted = argv[0], set(argv[1:])
    trips = json.loads((HERE / "trips.json").read_text())["trips"]
    for trip in trips:
        if wanted and trip["name"] not in wanted:
            continue
        answer = trimmed(plan(server, trip))
        fixture = {"name": trip["name"], "about": trip["about"], "route": answer}
        (HERE / f"{trip['name']}.json").write_text(json.dumps(fixture, indent=1) + "\n")
        turns = sum(1 for e in answer["description"] if e.get("turn"))
        print(f"{trip['name']}: {answer.get('distance_m', 0):.0f} m, {turns} turns")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
