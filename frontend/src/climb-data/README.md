# Climbs on the map

One file the front end loads the first time the Climbs layer is turned on (`src/lib/climbs.ts`,
imported with `?url&no-inline`, so it is its own hashed file under `/assets/` and the edge and
Content-Security-Policy are unchanged, as `amenity-data/` is). The directory is not called `data/`
because the repository's `.gitignore` ignores every directory of that name.

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `climbs.json` | every categorised climb on the routable network (Cat 5 to HC) | the live segment table (OpenStreetMap, via the rebuild) and USGS 3DEP one-arcsecond elevation, by `manage.py build_climbs` (`pipeline.climb_layer`) | **ODbL 1.0** (a produced work of the OSM data); 3DEP is public domain | the map's existing "© OpenStreetMap contributors (ODbL)" and "USGS 3DEP" |

What counts as a climb and its category is in `routemaker.climb_categories`; how the network is
read, the keys of each entry and the one-way rule are in `pipeline.climb_layer`'s docstring.

## Status

The committed file is **empty** (`"climbs": []`): it needs the build host (the live table and the
elevation tiles). Until it is filled the layer's switch says "No climbs yet". Writing it is in
docs/OPERATIONS.md, "The Climbs layer".
