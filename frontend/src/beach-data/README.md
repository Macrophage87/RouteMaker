# Beaches and the beach path

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `beaches.json` | the beaches in Southwest Florida (simplified, with their names) and the beach paths along their tide line, each with its OSM way id | OpenStreetMap, via the project's own extract, by `scripts/build_beaches.py` (the same rules the rebuild routes by, `pipeline.beaches`) | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |

Loaded with `?url` only on a map with a second area (`src/lib/beaches.ts`). Empty until a map
with Southwest Florida is built; `scripts/refresh_places.py` rebuilds it after every map
rebuild (docs/OPERATIONS.md, "The beach path (Southwest Florida)").
