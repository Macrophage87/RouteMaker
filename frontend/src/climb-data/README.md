# Climbs on the map

One file the front end loads the first time the Climbs layer is turned on (`src/lib/climbs.ts`,
imported with `?url&no-inline`, so it is its own hashed file under `/assets/` and the edge and
Content-Security-Policy are unchanged, as `amenity-data/` is). The service worker leaves it out of
its precache (`LAZY_ASSET` in `src/sw/swCore.mjs`), as it does the food file, so installing the app
does not download it. The directory is not called `data/`
because the repository's `.gitignore` ignores every directory of that name.

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `climbs.json` | every categorised climb on the routable network (Cat 5 to HC) | the live segment table (OpenStreetMap, via the rebuild) and USGS 3DEP one-arcsecond elevation, by `manage.py build_climbs` (`pipeline.climb_layer`) | **ODbL 1.0** (a produced work of the OSM data); 3DEP is public domain | the map's existing "© OpenStreetMap contributors (ODbL)" and "USGS 3DEP" |

The api reads the same file (v0.6.0): Mountain Goat's hill seek routes through the climbs in it and
names those a route rides (`src/core/hillseek.py`, FOLLOWUP-HILL-SEEK), so `docker/api.Dockerfile`
copies it into the api image. Without it the api plans as before.

Each climb's name (`n`: its roads and the named hill it runs up, "Foxville Road up Catoctin
Mountain"; the owner, 2026-10-19) is read from the rebuild's extract by `pipeline.climb_names`. The
file of 2026-11-09 below is the first with these names: 3,812 of its 3,820 climbs carry one.

What counts as a climb and its category is in `routemaker.climb_categories`; how the network is
read, the keys of each entry and the one-way rule are in `pipeline.climb_layer`'s docstring.

## Status

Written on the PC on 2026-11-09 by `manage.py build_climbs` (step 2 of the v0.23.0 deploy), from the
live table right after map build 20261109T111715Z was swapped in (the cloud run of 2026-11-09, a fresh
Geofabrik extract) and the rebuild's elevation tiles: 477,324 segments read, **3,820 climbs**
(3,812 named), 398 s.

| Category | Climbs |
| --- | --- |
| HC | 0 |
| 1 | 0 |
| 2 | 2 |
| 3 | 55 |
| 4 | 385 |
| 5 | 3,378 |

1,456,535 bytes (446,394 with `gzip -9`), sha256
`c0789962e1d54f1e6f5fefc452685f3098d5c04f8f981987f28841319df9d190`. The build had no ground for four
elevation cells (N38W076, N39W076: east of 76 W; N38W079, N39W079: west of 78 W) and left out any
climb there. The first two are outside the coverage box (east edge 76.02 W); the last two reach into
it only in the strip between 78.05 W (its west edge) and 78 W, where a climb could be missing. Against the file of
2026-10-12: 856 climbs added, 786 removed, 2,096 changed, 868 the same. Writing it again is in
docs/OPERATIONS.md, "The Climbs layer".

One climb was taken off by hand on 2026-10-12: `bd93dd04dc`, a Cat 4 down into the Travilah quarry
(owner report; `src/routemaker/climb_exclusions.py`, with the same ids in
`src/lib/climbExclusions.ts`). `build_climbs` now leaves out any way whose bike access is closed, and
this file does not hold that id, so the map shows all 3,820 climbs.
