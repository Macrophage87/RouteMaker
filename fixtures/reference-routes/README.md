# Reference routes

Real DC Bike Party mass rides, supplied by the project owner, used to tune the
Mass Ride modality and to assert the per-modality invariants in the Quality bar.
These are the ground truth: a route the router produces for the same waypoints
under the Mass Ride preset should look like these.

## Measured properties

| Route | Distance | Gain | Max grade | Turns | Revisits |
|---|---|---|---|---|---|
| 2025-05 (BTR) | 5.08 mi | 63 ft | 6.2% | 14 | 0 |
| 2025-12 | 6.17 mi | 113 ft | 6.3% | 18 | 0 |
| 2026-04 | 7.23 mi | 133 ft | 4.4% | 17 | 0 |
| 2026-07 | 6.00 mi | 164 ft | 4.8% | 28 | 0 |

Gain is computed with a 3 metre hysteresis threshold. Turns count bearing
changes above 40 degrees between consecutive segments over 5 metres. A revisit
is any pair of points within 25 metres of each other but more than 400 metres
apart along the route.

## What they establish

- **Distance sits between 5 and 7.5 miles.** Shorter than a club ride, because
  the constraint is how long a thousand people take to clear an intersection,
  not how far anyone can pedal.
- **They are close to flat.** 63 to 164 feet of gain, with brief pitches to
  around 6%. A grade cap near 6% matches practice; anything lower would reject
  these real routes.
- **Turn density is 2 to 4 per mile**, low for a city grid, consistent with
  keeping a long field together.
- **No route revisits its own line.** Zero across all four, which is the
  empirical basis for the self-crossing and doubling-back check.
- **All four stay inside the District**, which is why Mass Ride defaults the
  state-crossing penalty high.
- **They are point-to-point from a fixed start**, near 17th and Church NW, and
  finish in a different quadrant each time. December finishes about half a mile
  from the start, so near-loops happen but are not the rule.
- **December carries a `Midpoint` waypoint**, the mid-ride stop, which is a rest
  control point in the route model.

## Anonymization

Author names and Strava route and athlete links have been stripped from every
file, and the creator attribute is set to this project. Geometry, elevation, the
route names, and the `Midpoint` waypoint are untouched, and the OpenStreetMap
copyright element is preserved because attribution is required. Nothing in the
tests reads any of the removed fields.

Git history was rewritten so the original metadata does not survive in any
commit. Every blob in every commit has been scanned to confirm it. These routes
are mass rides, whose ride purpose defaults to First Amendment assembly, which is
the category the attribution rule in the plan protects; recreational routes are
attributed normally.

## Provenance

Exported from Strava as route files, roughly 50 metre point spacing, carrying
Strava's elevation values. On import they exceed the route-point threshold and
are map-matched as tracks, which is the intended path.
