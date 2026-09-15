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

## Trail routes (Trailmaxxing)

| Route | Distance | Gain | Max grade | Turns/mi | Shape | Jurisdictions |
|---|---|---|---|---|---|---|
| Bethesda Loop | 31.63 mi | 701 ft | 12.2% | 2.9 | loop | DC, MD |
| Brookside Gardens | 14.65 mi | 746 ft | 12.2% | 2.9 | point-to-point | DC, MD |
| Annapolis and BWI | 75.73 mi | 2333 ft | 11.8% | 2.3 | point-to-point | DC, MD |

Supplied with the note that some roadway sections are unavoidable, which is the
point: a trail route is not trails only, it is trails plus the connectors
between them.

## What the two sets establish together

The presets differ on almost every axis except turn density, which is worth
knowing because turn count alone does not separate a trail route from a road one.

| | Mass Ride | Trailmaxxing |
|---|---|---|
| Distance | 5 to 7 mi | 15 to 76 mi |
| Gain | 63 to 164 ft | 701 to 2333 ft |
| Max grade | 4.4 to 6.3% | 11.8 to 12.2% |
| Turns per mile | 2 to 4 | 2.3 to 2.9 |
| Jurisdictions | District only | crosses into Maryland |

- **Grade tolerance is per-modality, not global.** Trail routes hit 12%, roughly
  double what a mass ride ever sees. A single cap would either reject these or
  be useless for mass rides.
- **Trail routes cross the District line as a matter of course.** Every one of
  the three does. This is why the state-crossing penalty defaults off for every
  modality except Mass Ride; were it on, none of these routes could be produced.
- **Point spacing is 40 to 54 metres** across both sets, so every fixture
  arrives as a track and is map-matched, the intended import path.

## What the mass rides establish

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
