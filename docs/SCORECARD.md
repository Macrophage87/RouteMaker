# Route scorecard

The same trips, planned at every release and every map rebuild, scored and compared with the
last run, so a pricing change or a new map that makes routes worse somewhere is seen on a table
and not on a ride (improvement backlog 2026-11-12, item 1).

- Trips: `fixtures/scorecard/trips.json`. 38 trips between public landmarks (Metro and MARC
  stations, parks, town centres; never a home): city, suburb, country, Baltimore, and four long
  ones up to DC to Baltimore. Each trip lists its ride types; 11 also run the contrast set
  (Default, Trailmaxxing, Fast, Road Bike) and 10 run again with the start moved 150 ft north.
  93 plans in all, at weekday rush.
- Scoring and comparing: `src/routemaker/scorecard.py` (no Django, no network).
- Runner: `scripts/route_scorecard.py` (standard library only).

## What each trip gets

| Figure | From the /api/route answer |
|---|---|
| Miles, minutes | `distance_m`, `duration_s` (junction waits included) |
| Turns, turns per mile | `description` stretches entered by a left, right, bear or U-turn; a fork that stays on the same way is not counted |
| Red, orange | flagged junctions in `intersections` |
| Signals | signalized junctions in `junctions_debug` (the runner asks `debug_junctions`) |
| Wait min | `junction_delay_s`: every junction wait, signals and stops |
| LTS 3 mi, LTS 4+ mi | `stress_m`; Avoid counts with 4 |
| Path % | `facility_m.path` over the distance |
| Unpaved mi | `stress_spans` marked unpaved |
| Detour x | `detour.ratio` (against the most direct route), or against the straight line |

Two checks inside one run:

- **Stability**: the trip with its start moved 150 ft north should share at least 70% of the
  route (our default, unmeasured). Less means a small move of the pin changes the corridor.
- **Contrast**: two ride types sharing 90% or more of a trip (our default, unmeasured) planned the same thing; the report
  lists them, since ride types that never differ are not giving the rider a choice.

Comparing two runs lists a trip when it moves past these lines (all our defaults, unmeasured):
miles or minutes by 10% and at least 0.25 mi or 2 min; turns by 25% and at least 3; one more red
junction; 0.25 mi more LTS 3 or LTS 4+; path share by 10 points; unpaved by 0.5 mi; signals by 3;
the calm search stopping for a different reason; under 70% of the new route on the old line
("changed corridor"); a trip that no longer plans. The scorecard reports, it never fails a build.

## Running it

Planning only reads: /api/route saves nothing to any account (drafts come from the connector
only). Runs are kept outside the repository (project files, `reports/scorecard/`).

**On the PC, any branch or tag, through the route-check service** (the owner starts the
service; it checks out the ref and plans through the real /api/route code):

```sh
python3 scripts/route_scorecard.py queue --ref origin/release/v0.26.0 --label v0.26.0 \
    --out <route-check>/queue/req
# when <route-check>/queue/res has the answers:
python3 scripts/route_scorecard.py collect --manifest <route-check>/queue/v0.26.0.plans.json \
    --answers <route-check>/queue/res --out <project-files>/reports/scorecard/v0.26.0.json
python3 scripts/route_scorecard.py report <project-files>/reports/scorecard/v0.26.0.json --against <project-files>/reports/scorecard/v0.25.1.json
```

**Against a running stack over HTTP** (a local stack, or beta from inside):

```sh
python3 scripts/route_scorecard.py http --base-url http://localhost:8000 --label local --out <project-files>/reports/scorecard/local.json
```

`--stress 70` plans Default at one slider position (a before/after at Default); every other ride type keeps its own start, so the contrast check still means something. Go's More
direct from Default is `--stress 25` (`core.presets.stress_notches("default", 70)`).
`--only id,id`, `--no-contrast` and `--no-stability` cut the set down. Long trips go to the service one per request, so one slow calm search cannot lose other answers; `collect` lists any request that came back `busy` or `timeout` under `request_errors`: queue that file again.

## Nightly on beta

The owner, 2026-11-12, chose both: nightly on beta's own routers, and on the PC when he starts it.
The worker's `route_scorecard` task (config.procrastinate, 08:00 UTC: 3 AM Eastern in winter, 4 AM
in summer; our default) plans the whole set through the app's own /api/route code, one plan at a
time with a 2 s pause, and stops starting plans after 90 minutes (both our defaults, unmeasured).
A plan refused because the long-ride slot is held by a rider waits a minute and tries once more.
A night with a map rebuild running is skipped. Each run is kept (`ScorecardRun`, the last 60) and
compared with the night before; the run row's detail on the operations page says how many trips
moved, and `scripts/beta/alert.sh watch` posts the findings to the owner's Discord channel once
per run, only when something moved. A missed night (over 30 hours) shows on `check_operations`.

```sh
./manage.py route_scorecard --report            # the newest run against the one before
./manage.py route_scorecard --now               # run it now
```

## Not yet decided

Which of the owner's own rides join the trip list as "must not get worse" trips (public landmarks
only) is the owner's call.
