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
On beta, `scripts/beta/alert.sh scorecard` runs from a systemd user timer at 3 AM Eastern (our
default), on the host, beside the alert timers. It plans the whole set through the api's own
POST /api/route on 127.0.0.1, so riders' routing slots and rate limits apply to it as to anyone:
one plan at a time, a 2 s pause, a plan refused as busy (429 or 503) tries once more a minute
later, and no new plan starts after 90 minutes (all our defaults, unmeasured). Runs are kept in
`$RM_STATE/scorecard/` (the last 60, our default), never in the database or the repository.

- A run during which the api container or any graph's `current` build changed (a deploy, a map
  swap) is kept as `.mixed.json` and never compared or posted. A deploy pass running at the start
  skips the night.
- Each trip is compared with the newest earlier night where it planned (up to a week back), so a
  night with the routers down is reported once and does not hide the next night's changes.
- What moved is posted once to the owner's Discord channel (the alert webhook), only when
  something moved, at most 12 lines.

```sh
~/routemaker-beta-state/cd/bin/alert.sh scorecard-report   # the newest run's whole table
~/routemaker-beta-state/cd/bin/alert.sh scorecard          # run it now
```

Turning it on is one owner step on beta after the release that carries it:
`~/routemaker-beta-state/cd/bin/alert.sh install` (the deploy refreshes the script, not its timers).

## Not yet decided

Which of the owner's own rides join the trip list as "must not get worse" trips (public landmarks
only) is the owner's call.
