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

What counts as a climb and its category is in `routemaker.climb_categories`; how the network is
read, the keys of each entry and the one-way rule are in `pipeline.climb_layer`'s docstring.

## Status

Written on the build host on 2026-10-12 by `manage.py build_climbs --schema staging`, from build
20261011T215845Z (the v0.5.0 cloud rebuild, imported and not yet swapped in; 2026-10-09 extract)
and the rebuild's elevation tiles: 484,351 segments read, **3,750 climbs**, 85 s.

| Category | Climbs |
| --- | --- |
| HC | 0 |
| 1 | 0 |
| 2 | 2 |
| 3 | 54 |
| 4 | 367 |
| 5 | 3,327 |

1,325,586 bytes (402,989 with `gzip -9`), sha256
`2921963b0f42d61fef6907228ca7e516a92f782c4c950e9503d411134bf7331a`. The build named 19 elevation
cells it had no ground for (N36-N37 and the cells east of 76 W or west of 78 W); all are outside
the coverage box, so no climb inside it is left out. Writing it again is in docs/OPERATIONS.md,
"The Climbs layer".
