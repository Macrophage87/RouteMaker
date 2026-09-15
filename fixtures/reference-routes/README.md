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

## Group rides

| Route | Distance | Gain | Max grade | Turns/mi | Shape | Revisits |
|---|---|---|---|---|---|---|
| Blow off steam | 11.65 mi | 661 ft | 9.5% | 2.6 | point-to-point | 0 |
| Crit Mass 2024-03 | 12.31 mi | 347 ft | 9.9% | 2.8 | point-to-point | 5 |
| Crit Mass Jan | 13.77 mi | 604 ft | 8.6% | 2.4 | point-to-point | 0 |
| Crit Mass Feb | 14.50 mi | 511 ft | 9.7% | 3.3 | point-to-point | 0 |
| Purple Line | 35.25 mi | 985 ft | 13.0% | 3.3 | loop | 10 |

City examples; the rural set below covers the other setting. All five stay
inside the District.

Two of these matter more than their numbers.

**Critical Mass is a group ride here, not a mass ride.** Three of the five carry
that name. These are rides of roughly twenty people moving at a brisk riding
pace, travelling with traffic rather than taking the roadway at parade pace, and
that is what places them here. The roadway-takeover definition does the work the
name cannot. Classify by pace and posture, never by title or headcount.

**Group rides revisit their own line.** Two of the five do, once by five points
and once by ten. The no-revisit check therefore belongs to Mass Ride alone,
where it is grounded, and applying it to a group ride would reject real routes.

## Rural group rides

| Route | Distance | Gain | ft/mi | Max grade | Turns/mi | Shape | Points |
|---|---|---|---|---|---|---|---|
| VPRD TNL | 24.32 mi | 2219 ft | 91 | 15.0% | 1.1 | loop | 1000 |
| Loudoun 30 CCW | 30.12 mi | 2360 ft | 78 | 4.7% | 0.9 | loop | 7538 |
| Two Bridges CW | 30.11 mi | 2232 ft | 74 | 19.0% | 1.0 | loop | 919 |

Northern Loudoun County, and group rides rather than a separate gravel category.
The owner notes they favour gravel because rural gravel carries less traffic,
which is the important point: unpaved is being chosen as a proxy for low stress,
not for the surface itself.

**Turn density finally separates something, and it is not the preset.** At 0.9 to
1.1 turns per mile these are a third as busy as the same club's city rides at 2.4
to 3.3. What that measure distinguishes is rural from urban, so it can inform a
route's character but must never be used to infer a modality.

**They are loops.** Every one, where the city group rides were mostly
point-to-point, because a rural ride starts and finishes at the same parking lot.

**Grade tolerance is far higher than the city rides suggested**, reaching 19%,
and gain runs 74 to 91 feet per mile against a fraction of that in the city.

One file carries 7538 points at 6 metre spacing, dense enough to be worth a
check against the map-matching shape limit even though it stays under it.

## What the four sets establish together

The presets differ on almost every axis except turn density, which is worth
knowing because turn count alone does not separate a trail route from a road one.

| | Mass Ride | Group Ride, city | Group Ride, rural | Trailmaxxing |
|---|---|---|---|---|
| Distance | 5 to 7 mi | 12 to 35 mi | 24 to 30 mi | 15 to 76 mi |
| Gain | 63 to 164 ft | 347 to 985 ft | 2219 to 2360 ft | 701 to 2333 ft |
| Max grade | 4.4 to 6.3% | 8.6 to 13.0% | 4.7 to 19.0% | 11.8 to 12.2% |
| Turns per mile | 2 to 4 | 2.4 to 3.3 | 0.9 to 1.1 | 2.3 to 2.9 |
| Shape | point-to-point | mostly point-to-point | loop | either |
| May revisit its line | no | yes | yes | yes |

- **Grade tolerance is per-modality, not global.** Trail routes hit 12%, roughly
  double what a mass ride ever sees. A single cap would either reject these or
  be useless for mass rides.
- **Trail routes cross the District line as a matter of course.** Every one of
  the three does, which is why the state-crossing penalty defaults off for every
  modality, Mass Ride included; were it on, none of these would be reproduced. A crossing penalty is additive
  and capped, so it never makes a route unroutable; it makes a different route
  win, which is what the reproduction invariant tests.
- **Point spacing is 40 to 54 metres** across both sets, so every fixture
  arrives as a track and is map-matched, the intended import path.

## What the mass rides establish

- **Distance sits between 5 and 7.5 miles.** Shorter than a club ride, because
  the constraint is how long a thousand people take to clear an intersection,
  not how far anyone can pedal.
- **They are close to flat.** 63 to 164 feet of gain, with brief pitches to
  around 6%. A grade cap near 6% matches practice; anything lower would reject
  these real routes.
- **Turn density is 2.3 to 4.7 per mile**, low for a city grid, consistent with
  keeping a long field together. The 2026-07 ride is the top of that range at 28
  turns over 6.00 miles, so an invariant drawn at 5 per mile would have almost no
  headroom and the plan uses 6.
- **Turn counts here are geometric**, per the definition below, and are not the
  same number as a routing engine's maneuver count, which suppresses maneuvers
  where the road name continues and splits others. Any invariant comparing the
  two must compute both sides the same way.
- **No route revisits its own line.** Zero across all four, which is the
  empirical basis for the self-crossing and doubling-back check.
- **All four stay inside the District**, which is a property of these four
  routes rather than a constraint on the preset. They are 5 to 7 mile rides
  starting and finishing near 17th and Church, so they had no reason to leave.
  Memorial Bridge into Arlington and the Anacostia crossings into Prince
  George's are ordinary mass-ride moves here. The state-crossing penalty is off
  by default for every modality including Mass Ride, and a crossing is reported
  rather than avoided.
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
Strava's elevation values. The application derives gain from 3DEP instead, so
every gain figure in this README carries a systematic offset against what the
application will report. This matters most for the mass rides, whose total gain
of 19 to 50 metres is only a few multiples of the 3 metre hysteresis, so the
absolute gain bounds are treated as approximate and the per-modality invariants
are written with headroom rather than to these numbers exactly. On import they exceed the route-point threshold and
are map-matched as tracks, which is the intended path.
