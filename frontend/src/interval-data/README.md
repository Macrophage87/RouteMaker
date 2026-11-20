# Interval stretches on the map

One file the front end loads the first time the "Interval stretches" layer (Go or Plan) is turned on
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

That file predated the bollard rule (2026-11-18): it cut at bollards and had no `k`.

## Current file (2026-11-18)

Written on the PC on 2026-11-18 by `manage.py build_intervals` with release/v0.28.0 code (542e04108), from the same live table and elevation tiles, with the bollard rule and the windy-path rule both in the builder. **5,614 stretches** (387 both ways, 5,227 one way; 2,746 under a mile), 189 s, rebuild container peak about 2.1 GiB. Stretches now ride through bollards and count them in `k`: 15 stretches hold bollards (22 bollards in all). The Klingle Valley Trail is now in (1,033 m, 3.6 min, 2 bollards). 1,935,901 bytes, sha256 `0461ec1acbd23fa120bd36db0f4963b95dbe537083936cd9d85c6940556579ca`. It replaces the 2026-11-17 file and its in-place windy-path edit described above.

On 2026-11-18 (after v0.28.0) the windy-cluster and overlap rules were applied to this file in place, by the builder's own `Stretch.windy_path` and `without_overlaps`: 2 windy path stretches (the Mount Vernon Trail by Daingerfield Island, the Paint Branch Trail) and 16 lying along a longer one (Ohio Drive's sidepath at Hains Point among them) left out, **5,596 stretches** (384 both ways, 5,212 one way). 1,929,702 bytes, sha256 `6cc0407d0fed56312f1629eda6be74db7ddd5b98c6be3b88b65b18eea6f1191c`.
