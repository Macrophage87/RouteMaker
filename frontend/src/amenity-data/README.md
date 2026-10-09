# Public water and restrooms on the map

One fixture the front end loads the first time the Water and restrooms layer is
shown (`src/lib/waterRestrooms.ts`, imported with `?url`, so it is its own
hashed file under `/assets/` and the edge and Content-Security-Policy are
unchanged, as `federal-data/` is). The directory is not called `data/` because
the repository's `.gitignore` ignores every directory of that name.

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `water-restrooms.json` | public drinking water (fountains, taps, water points) and public restrooms in the coverage box | OpenStreetMap, via the project's own extract, by `scripts/build_water_restrooms.py` | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |

What counts as public water or a public restroom, and what is left out
(customers-only, private, disused), is in the script's docstring, with the OSM
wiki pages it follows. The file is one point per line, short keys:

| Key | Meaning |
| --- | --- |
| `id` | OSM element, `n` node or `w` way, then its id |
| `x`, `y` | longitude, latitude (5 decimals, about 3 ft (1 m); a way's mean node) |
| `k` | `w` drinking water, `t` restroom, `wt` a restroom with drinking water |
| `n` | `name` |
| `fee` | `fee=yes` or `no` |
| `wc` | `wheelchair=yes`, `limited` or `no` |
| `h` | `opening_hours`, as mapped |
| `s` | `seasonal`, unless `no` |
| `b` | 1 for `bottle=yes` on water |

## Status

**The committed file has no points yet.** The extract lives on the project's
build host, which the change that added the layer could not reach; until the
file is regenerated there the layer's switch says it is unavailable. To build
it, from the repository root on that host:

    .venv311/bin/python scripts/build_water_restrooms.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

then record the extract's date, size and sha256 and the file's sha256 here, as
`rail-data/README.md` does, and commit the file.

## Refresh

Rerun the command above on a newer extract. Nothing else changes: the map reads
the file as it is.
