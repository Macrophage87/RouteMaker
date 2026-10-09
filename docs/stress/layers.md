# Layers that stress feeds

[Index](README.md).

## The ride layer, z12-13 (OWNER-DECISIONS 391, 402, 402a)

At z12 and z13 the stress map is a "where to ride" view (`src/core/stress_tiles.py:35-42`,
`RIDE_LAYER` `:232-240`; `ride_layer_predicate`, `src/pipeline/schema.py:373-386`). It
draws:

| What | Rule | Threshold |
|---|---|---|
| Long, connected traffic-free paths | A path whose connected network (paths within 30 m [100 ft] of one another, `CALM_PATH_GAP_M`) or named run is long enough. No mountain-bike trails | 0.25 mi [400 m] (`RIDE_PATH_RUN_MI`, `schema.py:343`) |
| Calm roads | A continuous run of named LTS 1-2 road (`CALM_ROAD_MAX_TIER = 2`, `:345`), not a trail | 2 mi [3.2 km] (`RIDE_ROAD_RUN_MI`, `:352`; the owner's proposed bar, "not yet confirmed") |
| Timed car-free roads | Any road closed to cars at set times, whatever its length | - |

It never draws a road at LTS 3 or above. A table built before the `calm_run_m` column
falls back to the old busy level (paths plus faint LTS 3+ roads, `busy_predicate`,
`schema.py:400-414`). The legend says which applies (`frontend/src/lib/stressLegend.ts`,
`RIDE_RUN_MI` `:60`, held equal to the schema by a test).

### Calm runs (`src/pipeline/calm_roads.py`)

Stress decides a run in two places:

- **Membership.** Only named roads at LTS 1 or 2 that the map draws are candidates
  (`calm_roads.py:9-13`; `trail_routes.is_calm_candidate`). An unnamed road has no run.
- **Breaks.** A run ends at every node it shares with a road at LTS 3 or above,
  including Avoid. The busy road's tier there is the greater of its tier and its
  unsmoothed tier, as the junction model reads it (`calm_roads.py:21-29`, SQL at
  `:85-110`, `BUSY_TIER` from `src/routemaker/intersections.py:49`). A bridge or
  underpass shares no node and does not break a run.

A run follows the road straight on through a junction: along its own name if it turns
no more than `SAME_NAME_TURN_DEG`, else along the straightest road within
`STRAIGHT_ON_DEG` (`calm_roads.py:14-20`, `:58-`). The run's length is stored on each way
as `calm_run_m`. A way in two runs keeps the longer. On the 2026-10-03 build the
region's calm roads came to 1,642 mi [2,643 km], nearly all rural
(docs/OPERATIONS.md, "The ride layer (z12-13)").

Half steps (**planned**, 461a): a 2.5 road is not a calm-run member (on/off, cautious),
and a crossed or joined 2.5 road breaks a run ([stress-number.md](stress-number.md),
section 3).

## The trail seek's corridors

At the top of the slider the trail seek looks for corridors of paths and protected
ways at LTS 1 or 2, and roads closed to cars at some time
(`SEEK_INDEX_PREDICATE`, `schema.py:415-425`; `src/core/trailseek.py`). Stress limits
its candidates to the two calm tiers.

## Mass Ride capacity (OWNER-DECISIONS 325-327, 387, 394, 404)

Capacity is not stress. It is the modelled throughput of a corked group, in riders a
minute (`src/routemaker/massflow.py:1-30`):

    riders a minute = 60 x safe density 0.37/m² x utilisation 0.7 x usable width x pace 1.9 m/s

That is about 29.5 riders a minute for each metre of usable width, or about 99 per
11 ft [3.35 m] lane. It is written as `segment.mass_usable_width_m` and checked by
VALIDATE (`src/pipeline/mass_capacity.py`). The model is from the owner's counts of
DC Bike Party rides, accepted as the working model. Its sources are pending
FOLLOWUP-FLOW-CALIBRATION (docs/SOURCES.md).

How stress meets it:

| Where | What |
|---|---|
| Mass Ride tiles (`src/core/mass_tiles.py:13-14`, `:37`) | Carry each segment's `rpm` and `tier`. An Avoid stretch (tier 5) is drawn "AVOID" at every zoom, whatever its capacity |
| Road panel, Mass Ride capacity (`src/core/segment_info.py:657-679`) | Usable width and riders a minute. "Not used by a mass ride" where no width is known and the tier is 5 |
| Routing | Mass Ride's own costs: slider locked at 0 on the no-trail graph, so LTS 3 and 4 cost nothing extra, and Avoid pays the 1,800 s entry charge ([routing-costs.md](routing-costs.md)) |
| Junctions | Orange at a crossing of LTS 3, red at LTS 4 or Avoid, signalized crossings grouped (`intersections.py:548-584`, `:785-`). The calm search does not run, so junctions are reported, not used to choose the route |
| Major junctions on the route chart | A crossed or joined road at LTS 3 or above (`CORKER_TIER = BUSY_TIER`, `intersections.py:922-934`): where corkers are needed |

The Mass Ride map draws only inside the District, clipped to its boundary
([drawing.md](drawing.md)). Its usable width uses DC Roadway Block widths where they are
known (DC Open Data, CC BY 4.0, adapted).
