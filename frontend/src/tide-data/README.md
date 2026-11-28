# Low tides for the beach path

| File | What | Source | Licence | Credit |
| --- | --- | --- | --- | --- |
| `tides.json` | predicted low tides (UTC minutes, tenths of a foot above MLLW) for eight Gulf stations by the Southwest Florida beaches, about 400 days from the day it was made | NOAA CO-OPS tide predictions API, by `scripts/build_tides.py` | **public domain** (a US Government work) | "Tides: NOAA" beside the times |

Loaded with `?url` only when a route uses a beach path (`src/lib/tides.ts`). Re-made with
every map rebuild; predictions are astronomical, so a missed run is still right until the
file's `to` date.
