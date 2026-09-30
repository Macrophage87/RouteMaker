"""The weekday-trails acceptance check (OWNER-DECISIONS 68, 69; scripts/acceptance.py A7).

The owner, item 68: "In many of these cases, there's a nearby trail. It's
better to go on that trail during the week." And item 69: "it depends on the
ride. People riding at 20 mph will probably use the road anyways." Measured on
the r6 box graph (FOLLOWUP-WEEKDAY-TRAILS) the router already does this; this
check holds it there on the promoted graph, at every rebuild review.

For each corridor - a road closed to cars at weekends with an off-road path
beside it - trips along it are planned on each ride type at the two weekday
settings, both directions. It fails when:

- Default, Cargo, E-bike or Trailmaxxing puts more than MAX_ROAD_M on a
  weekday parkway that has a path within 60 m for most of its length; or
- Fast stops taking lower Sligo Creek Parkway on the sligo-lower trip.

Group Ride and Mass Ride are reported, not asserted ("likely" in item 69; Mass
Ride routes on the no-trail graph, which has no trails). The parkway ways come
from the segment table (car_free_when, and a path within 60 m for at least half
their length), not from a list of ids. Prints the road/trail table, then one
JSON line with the verdict; exits 1 on a failure.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import connection

from core import routing
from core.routing import Dials

TRIPS = {
    # name: (start, end), along each corridor (the r6 measurement's).
    "sligo-lower": ((-76.9990, 38.9800), (-77.0060, 38.9975)),
    "sligo-lower-long": ((-76.9960, 38.9760), (-77.0150, 39.0050)),
    "sligo-upper": ((-77.0290, 39.0280), (-77.0335, 39.0120)),
    "little-falls": ((-77.1050, 38.9570), (-77.0990, 38.9730)),
    "beach-moco": ((-77.0870, 39.0095), (-77.1030, 39.0222)),
}
STRESS_AVERSE = ("default", "cargo", "ebike", "trailmaxxing")
REPORTED = ("group-ride", "fast", "mass-ride")
WHENS = ("weekday_rush", "weekday_offpeak")
MAX_ROAD_M = 100.0
NEAR_M = 60.0

PARKWAYS_WITH_TRAILS = """
WITH cf AS (
  SELECT osm_way_id, ST_Collect(geometry) AS g
  FROM {schema}.segment WHERE car_free_when <> '{{}}' GROUP BY 1
), pts AS (
  SELECT cf.osm_way_id,
         (ST_DumpPoints(ST_Segmentize(cf.g::geography, 20)::geometry)).geom AS p
  FROM cf
)
SELECT osm_way_id FROM pts
GROUP BY osm_way_id
HAVING avg((EXISTS (
  SELECT 1 FROM {schema}.segment s
  WHERE s.facility = 'path' AND s.is_trail_class AND s.car_free_when = '{{}}'
    AND ST_DWithin(pts.p::geography, s.geometry::geography, %s)))::int) >= 0.5
"""


def parkways(schema: str) -> set[int]:
    with connection.cursor() as cursor:
        cursor.execute(PARKWAYS_WITH_TRAILS.format(schema=schema), [NEAR_M])
        return {row[0] for row in cursor.fetchall()}


class Command(BaseCommand):
    help = "Hold weekday routes to the trail beside a weekend-car-free parkway (items 68, 69)."

    def handle(self, *args, **options) -> None:
        from django.conf import settings

        from pipeline.schema import validate_schema_name

        schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
        roads = parkways(schema)
        captured: dict = {}
        real = routing.breakdown

        def spy(pieces, when, roadway_only=False):
            per_way: dict[int, float] = {}
            for p in pieces:
                per_way[p.way_id] = per_way.get(p.way_id, 0.0) + p.metres
            captured["per_way"] = per_way
            return real(pieces, when, roadway_only)

        failures = []
        rows = []
        routing.breakdown = spy
        try:
            for trip, (a, b) in TRIPS.items():
                for points in ([list(a), list(b)], [list(b), list(a)]):
                    for preset in STRESS_AVERSE + REPORTED:
                        for when in WHENS:
                            captured.clear()
                            try:
                                routing.plan(points, preset, dials=Dials(when=when))
                            except Exception as error:  # noqa: BLE001 - reported, not raised
                                rows.append((trip, preset, when, None, str(error)[:80]))
                                continue
                            on_road = sum(
                                m for w, m in captured.get("per_way", {}).items() if w in roads
                            )
                            rows.append((trip, preset, when, round(on_road), ""))
                            if preset in STRESS_AVERSE and on_road > MAX_ROAD_M:
                                failures.append(
                                    f"{preset} {when} {trip}: {on_road:.0f} m on a parkway"
                                )
        finally:
            routing.breakdown = real
        fast = [r for r in rows if r[0] == "sligo-lower" and r[1] == "fast" and r[3] is not None]
        if not fast or max(r[3] for r in fast) < MAX_ROAD_M:
            failures.append("fast no longer takes lower Sligo Creek Parkway on sligo-lower")
        for trip, preset, when, metres, error in rows:
            self.stdout.write(f"{trip:18} {preset:13} {when:16} parkway {metres!s:>6} m {error}")
        self.stdout.write(json.dumps({"parkway_ways": len(roads), "failures": failures}))
        if failures:
            raise SystemExit(1)
