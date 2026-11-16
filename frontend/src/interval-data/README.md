# Interval stretches on the map

One file the front end loads the first time Plan's "Interval stretches" layer is turned on
(`src/app/IntervalsOverlay.tsx`, imported with `?url&no-inline`, so it is its own hashed file under
`/assets/`, left out of the service worker's precache by `LAZY_ASSET` in `src/sw/swCore.mjs`, as
`climb-data/` is). The api reads it too (`src/core/intervals_near.py`, `GET /api/intervals-near`,
the connector's `intervals_near`), so `docker/api.Dockerfile` copies it into the api image.

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `intervals.json` | every stretch an interval effort can run unbroken, a mile or more | the live segment table and the rebuild's extract (OpenStreetMap) and USGS 3DEP one-arcsecond elevation, by `manage.py build_intervals` (`pipeline.interval_layer`) | **ODbL 1.0** (a produced work of the OSM data); 3DEP is public domain | the map's existing "© OpenStreetMap contributors (ODbL)" and "USGS 3DEP" |

What counts and the keys of each entry are in `pipeline.interval_layer`'s docstring; writing it
again is in docs/OPERATIONS.md, "The Intervals layer".

## Status

Written on the PC on 2026-11-16 by `manage.py build_intervals` from the live table (477,350 segments, map build swapped in 2026-11-15) and the rebuild's elevation tiles: **2,871 stretches** (321 both ways, 2,550 one way), 145 s, rebuild container peak about 1.6 GiB. 1,117,183 bytes, sha256 `160c850bfff1056d658c7b67e1bb4efde48747c7377ff66fff0b5bea5e3b103f`. No ground for N38W076, N39W076 (east of 76 W, outside the coverage box) and N38W079, N39W079 (west of 78 W): stretches there are left out, as in climb-data/README.md.
