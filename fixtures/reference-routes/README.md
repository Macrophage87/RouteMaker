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

These definitions are implemented in `src/routemaker/measure.py` and asserted
against these tables by `tests/test_reference_fixtures.py`, so the number a test
checks and the number the application reports come from one place.

Gain uses a 3 metre hysteresis, applied asymmetrically: a rise must exceed the
threshold to count, while the reference tracks the running minimum with no
threshold on the way down. A symmetric threshold loses the bottom of every dip
and under-reports every route here by 5 to 25 percent.

Turns count bearing changes above 40 degrees between consecutive segments of at
least 5 metres. This definition is sampling-rate dependent and has a stated
validity domain: at spacings below about 20 metres a turn taken over 15 metres
splits into three sub-threshold steps and goes uncounted. Fourteen of the
fifteen fixtures, sampled at 39 metres and above, reproduce their recorded
counts exactly; `rural-group-loco-30`, sampled at 6.4 metres, reports 0.3 turns
per mile against roughly 1.0 for its two sibling loops. The measurement flags
that trace as unreliable rather than returning the wrong number. Decimating
dense traces to the reliable range was tried and rejected: it fixes the one
trace and loses real turns on four of the five mass rides.

Max grade is the steepest rise over a run of at least 30 metres, the minimum run
being what stops a one-metre elevation wobble between adjacent samples from
reporting a 40 percent pitch. Treat this column as provisional: it is computed
from the GPX elevation these files carry, while the application derives
elevation from 3DEP, so the two will not agree exactly. It is also a maximum,
and a maximum is not diluted by a gap in the elevation column: a run with an
elevation missing at either end is skipped, so on a trace with elevation on
some points and not others the figure is a floor rather than the steepest
pitch (30 percent of `rural-group-two-bridges`' elevations removed takes 18.99
percent to 13.43). The measurement reports `elevation_coverage` and
`grade_reliable` beside `max_grade_pct`, the way turn density is reported with
`turns_reliable`, and anything printing the one should print the other. Every
trace in this set carries elevation on every point, so no figure here is
affected.

A revisit is a place where the route comes back within 25 metres of its own line
more than 400 metres apart along the route, counted as occurrences rather than
as point pairs, so a stretch ridden twice is one revisit and not one per sample.

## Trail routes (Trailmaxxing)

| Route | Distance | Gain | Max grade | Turns/mi | Shape | Jurisdictions |
|---|---|---|---|---|---|---|
| Bethesda Loop | 31.63 mi | 701 ft | 11.8% | 2.9 | loop | DC, MD |
| Brookside Gardens | 14.65 mi | 746 ft | 8.3% | 2.9 | point-to-point | DC, MD |
| Annapolis and BWI | 75.73 mi | 2333 ft | 11.3% | 2.3 | point-to-point | DC, MD |

Supplied with the note that some roadway sections are unavoidable, which is the
point: a trail route is not trails only, it is trails plus the connectors
between them.

## Group rides

| Route | Distance | Gain | Max grade | Turns/mi | Shape | Revisits |
|---|---|---|---|---|---|---|
| Blow off steam | 11.65 mi | 661 ft | 10.9% | 2.6 | point-to-point | 0 |
| Crit Mass 2024-03 | 12.31 mi | 347 ft | 9.9% | 2.8 | point-to-point | 2 |
| Crit Mass Jan | 13.77 mi | 604 ft | 8.6% | 2.4 | point-to-point | 0 |
| Crit Mass Feb | 14.50 mi | 511 ft | 8.5% | 3.2 | point-to-point | 0 |
| Purple Line | 35.25 mi | 985 ft | 10.4% | 3.3 | loop | 2 |

City examples; the rural set below covers the other setting. Four of the five
stay inside the District. **Purple Line does not**: it crosses the District line
**four** times, into **two** different Maryland counties, and runs through
**five** jurisdiction transitions doing it.

| # | Mile | Transition | Where |
|---|---|---|---|
| 1 | 8.84 | DC to Prince George's | northeast side, out past Cheverly |
| 2 | - | Prince George's to Montgomery | inside Maryland; no District line crossed |
| 3 | 18.89 | Montgomery to DC | Eastern Avenue at Silver Spring and Takoma |
| 4 | 20.25 | DC to Montgomery | near the north cornerstone |
| 5 | 28.16 | Montgomery to DC | west side, near Little Falls |

Row 2 is the one that keeps being lost, and it is the reason the two counts
differ: the route leaves the District into Prince George's and comes back out of
Montgomery, so it handed over between the two counties somewhere in Maryland
without crossing a District line at all. A report that names the county the
route left into for the whole excursion names the wrong agency for half of it,
which is not a rounding error on a permit application.

This has now been recorded four ways. First as staying inside the District;
then as "twice, out and back", which is the shape of a route that leaves once
and returns, where this one leaves twice on opposite sides; then as four
crossings into two counties with the 18.89 re-entry attributed to Prince
George's, which is the error above. The mileages moved too - 18.90 and 20.20
were carried here against 18.89 and 20.25 measured.

So the numbers are no longer recorded from memory.
`TestThePurpleLineJurisdictionSequence` in `tests/test_reference_fixtures.py`
measures all four District-line crossings from the GPX against a polygon built
from the District's four 1791 cornerstones - a matter of record, and
reproducible without the PostGIS jurisdiction layers, which tests do not have.
The county attribution is measured the only way this repository can measure it
with Overpass blocked: the first excursion leaves at longitude -76.94 and
returns at -77.03, either side of the whole stretch of Eastern Avenue the
Montgomery / Prince George's line could meet the District boundary in, so the
two ends are in different counties however that point is placed. That the exact
point is community knowledge rather than record is why the test pins a band and
not a coordinate.

The count matters beyond the arithmetic. It is the reference route the
`route_crossings` re-entry behaviour is grounded in - a route that visits an
area twice must report two crossings and not one averaged pair - and a fixture
that says "twice" makes the two-county, five-transition case look like an
untested edge rather than the one real route this set has for it.

PLAN's "all five city group rides stay inside the District" claim did not
survive this either, and the sentence there now carries the same five.

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
| VPRD TNL | 24.32 mi | 2219 ft | 91 | 14.5% | 1.1 | loop | 1000 |
| Loudoun 30 CCW | 30.12 mi | 2361 ft | 78 | 16.9% | n/a | loop | 7538 |
| Two Bridges CW | 30.11 mi | 2232 ft | 74 | 19.0% | 1.0 | loop | 919 |

**This table lists three rows, but the rural set is two distinct loops, not
three.** Loudoun 30 CCW and Two Bridges CW are the same loop ridden in opposite
directions - their bounding boxes and start/end points coincide (39.11-39.22N,
77.71-77.56W, starting and finishing within about 100 m of each other), and the
CCW/CW labels say as much. Only VPRD TNL is a genuinely separate loop, covering
different roads (39.07-39.12N, 77.70-77.56W). Treat "the rural set" as one loop
ridden both ways plus one other loop, not as three independent routes -
anywhere that counts fixtures by geography rather than by file should count
two, not three.

Loudoun 30 CCW reports no turn density: at 6.4 metre sampling it falls outside
the turn definition's validity domain, which the measurement flags rather than
guessing. Its recorded 0.9 was measured before that limit was understood.

Northern Loudoun County, and group rides rather than a separate gravel category.
The owner notes they favour gravel because rural gravel carries less traffic,
which is the important point: unpaved is being chosen as a proxy for low stress,
not for the surface itself.

**Turn density finally separates something, and it is not the preset.** At 1.0 to
1.1 turns per mile the two measurable rural loops are a third as busy as the same
club's city rides at 2.4 to 3.3. What that measure distinguishes is rural from urban, so it can inform a
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
| Distance | 5 to 7.5 mi | 12 to 35 mi | 24 to 30 mi | 15 to 76 mi |
| Gain | 63 to 164 ft | 347 to 985 ft | 2219 to 2361 ft | 701 to 2333 ft |
| Max grade | 4.4 to 6.3% | 8.5 to 10.9% | 14.5 to 19.0% | 8.3 to 11.8% |
| Turns per mile | 2.3 to 4.7 | 2.4 to 3.3 | 1.0 to 1.1 | 2.3 to 2.9 |
| Shape | point-to-point | mostly point-to-point | loop | either |
| May revisit its line | no | yes | yes | yes |

- **Grade tolerance is per-modality, not global.** Trail routes hit 11.8%, roughly
  double what a mass ride ever sees. A single cap would either reject these or
  be useless for mass rides.
- **Trail routes cross the District line as a matter of course.** Every one of
  the three does, which is why the state-crossing penalty defaults off for every
  modality, Mass Ride included; were it on, none of these would be reproduced. A crossing penalty is additive
  and capped, so it never makes a route unroutable; it makes a different route
  win, which is what the reproduction invariant tests.
- **Point spacing runs 6 to 54 metres** across the four sets, so every fixture
  exceeds the route-point threshold, arrives as a track, and is map-matched,
  which is the intended import path.

## What the mass rides establish

- **Distance sits between 5 and 7.5 miles.** Shorter than a club ride, because
  the constraint is how long a thousand people take to clear an intersection,
  not how far anyone can pedal.
- **They are close to flat.** 63 to 164 feet of gain, with brief pitches to
  around 6%. A grade cap near 6% matches practice; anything lower would reject
  these real routes.
- **Turn density is 2.3 to 4.7 per mile**, low for a city grid, consistent with
  keeping a long field together.
- **Planning pace is 5 to 9 mph, defaulting to 6.** Above the band a random
  slowdown propagates backward through a dense field as a shock wave; below it
  riders fall under balance speed. Six is what these rides plan to, with a
  deliberately slow front; a ride that actually rolls at eight is inside the
  band. Only a value outside 5 to 9 warns. The 2026-07 ride is the top of that range at 28
  turns over 6.00 miles, so an invariant drawn at 5 per mile would have almost no
  headroom and the plan uses 6.
- **Turn counts here are geometric**, per the definition below, and are not the
  same number as a routing engine's maneuver count, which suppresses maneuvers
  where the road name continues and splits others. Any invariant comparing the
  two must compute both sides the same way.
- **No route revisits its own line.** Zero across all four, which is the
  empirical basis for the self-crossing and doubling-back check.
- **All four stay inside the District**, and so does the owner's experience:
  these are DC Bike Party rides, and mass rides elsewhere run under a different
  permitting posture with pace, field size, and marshalling practice that the
  organizers who run them know first-hand. Reference routes from Maryland and
  Virginia mass ride organizers are a standing request. Until they arrive, the
  Mass Ride preset is tuned on District geometry and the plan says so rather
  than implying the defaults transfer. Staying inside the District is in any
  case a property of these four routes rather than a constraint on the preset. They are 5 to 7 mile rides
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
