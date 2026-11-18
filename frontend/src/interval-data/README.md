# Interval stretches on the map

One file the front end loads the first time Plan's "Interval stretches" layer is turned on
(`src/app/IntervalsOverlay.tsx`, imported with `?url&no-inline`, so it is its own hashed file under
`/assets/`, left out of the service worker's precache by `LAZY_ASSET` in `src/sw/swCore.mjs`, as
`climb-data/` is). The api reads it too (`src/core/intervals_near.py`, `GET /api/intervals-near`,
the connector's `intervals_near`), so `docker/api.Dockerfile` copies it into the api image.

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `intervals.json` | every stretch an interval effort can run unbroken, 3 minutes or more at 18 mph | the live segment table and the rebuild's extract (OpenStreetMap) and USGS 3DEP one-arcsecond elevation, by `manage.py build_intervals` (`pipeline.interval_layer`) | **ODbL 1.0** (a produced work of the OSM data); 3DEP is public domain | the map's existing "© OpenStreetMap contributors (ODbL)" and "USGS 3DEP" |

What counts and the keys of each entry are in `pipeline.interval_layer`'s docstring; writing it
again is in docs/OPERATIONS.md, "The Intervals layer".

## Status

Written on the PC on 2026-11-17 by `manage.py build_intervals` from the live table (477,350 segments, map build swapped in 2026-11-15) and the rebuild's elevation tiles, by minutes: 3 minutes or more at 18 mph, slowed by climbing. **5,614 stretches** (386 both ways, 5,228 one way; 2,744 under a mile), 179 s, rebuild container peak about 2.0 GiB. 1,939,812 bytes, sha256 `2b8cc57caede157d46ec7b33c8c6a69ab4c98a2e95d0b39bf1dc09c1ebfa78dc`. No ground for N38W076, N39W076 (east of 76 W, outside the coverage box) and N38W079, N39W079 (west of 78 W): stretches there are left out, as in climb-data/README.md. The first file (2026-11-16, a mile minimum) had 2,871 stretches (321 both ways, 2,550 one way).

On 2026-11-18 the windy-path rule (`WINDY_PATH_DEG_PER_KM`: more than 200 degrees per km in tight bends, 30 degrees or more within 30 m, more on a climb) was applied to this file in place, by the builder's own `tight_turning_per_km` and `Stretch.windy_limit` on each entry: 8 path and unpaved stretches left out (the Anacostia trail by Kenilworth among them), **5,606 stretches** (385 both ways, 5,221 one way). 1,932,722 bytes, sha256 `c86fa4ffd74cd645f7ef678916f50fdd9b75ea159d25137bbdc2f63c8b2d4e58`.

This file predates the bollard rule (2026-11-18): it still cuts at bollards and has no `k`. The next `build_intervals` run rides through them and counts them.
