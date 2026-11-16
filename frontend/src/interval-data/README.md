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

Empty: not yet written on the build host. The layer says the stretches arrive with the next map
data update until it is.
