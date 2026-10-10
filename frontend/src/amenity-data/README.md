# Public water and restrooms on the map

One fixture the front end loads the first time the Water and restrooms layer is
shown (`src/lib/waterRestrooms.ts`, imported with `?url`, so it is its own
hashed file under `/assets/` and the edge and Content-Security-Policy are
unchanged, as `federal-data/` is). The directory is not called `data/` because
the repository's `.gitignore` ignores every directory of that name.

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `water-restrooms.json` | public water (drinking fountains and taps; untreated springs, wells and taps) and public restrooms (flush, portable or pit, type not mapped) in the coverage box | OpenStreetMap, via the project's own extract, by `scripts/build_water_restrooms.py` | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |

What counts as drinking or untreated water, how a restroom's type is read
from `toilets:disposal`, and what is left out (customers-only, private,
disused, historic springs), is in the script's docstring, with the OSM
wiki pages it follows.

Two rules from the owner's requests of 2026-10-10 (relayed in the v0.4.0
work; not yet in an OWNER-DECISIONS file):

- One restroom, not two. An `amenity=toilets` node inside a closed way tagged
  `amenity=toilets` or `building=toilets` is merged into that way: one point,
  with the way's id and position. Tags only one of them has are kept; where both
  have a key, the element with more of the details the layer shows
  (`DETAIL_KEYS`: name, access, fee, wheelchair, opening hours, seasonal,
  disposal, portable, drinking water, bottle) wins, and the node on a tie, as it
  is the element mapped as the restroom itself. Several nodes in one building
  become one place. If any of them is not public or not in use, the place is
  left out (unclear access is closed). A `building=toilets` with no node inside
  and no `amenity=toilets` stays out, as before.
- No historic springs. A `natural=spring` with `historic=*` (any value but
  `no`) or `ruins=yes` is a landmark, not a water source, and is left out unless
  it is also `drinking_water=yes` (or `amenity=drinking_water`), which says it
  is still usable. The file is one point per line, short keys:

| Key | Meaning |
| --- | --- |
| `id` | OSM element, `n` node or `w` way, then its id |
| `x`, `y` | longitude, latitude (5 decimals, about 3 ft (1 m); a way's mean node) |
| `w` | water: `p` drinking water, `n` untreated (filter or treat first); left out for none |
| `t` | restroom: `f` flush, `b` portable, pit, composting or other basic toilet, `u` type not mapped; left out for none |
| `n` | `name` |
| `fee` | `fee=yes` or `no` |
| `wc` | `wheelchair=yes`, `limited` or `no` |
| `h` | `opening_hours`, as mapped |
| `s` | `seasonal`, unless `no` |
| `b` | 1 for `bottle=yes` on drinking water |

## Status

The committed file predates the two 2026-10-10 rules above: it still has
restroom nodes beside their buildings and historic springs, until the next
refresh (below).

Generated on the build host on 2026-10-09 from that day's extract
(`<DATA_ROOT>/extracts/source.osm.pbf`), commit dce6451: 2,263 points, all
inside the coverage box, 141,213 bytes, sha256
`496bae39f7d0741cf2261e40d20937f6fd652c6dbea996d56c58d1a21dd281e1`.

| Kind | Points |
| --- | --- |
| drinking water | 762 (20 of them at a restroom) |
| untreated water | 175 |
| flush restroom | 206 |
| portable, pit or composting toilet | 286 |
| restroom, type not mapped | 854 |

To rebuild, from the repository root on that host:

    .venv311/bin/python scripts/build_water_restrooms.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

then update the figures above and commit the file.

## Refresh

Rerun the command above on a newer extract. Nothing else changes: the map reads
the file as it is.

The first refresh after the 2026-10-10 rules: expect fewer restrooms (each node
merged into its building drops one point, and a merged place takes the
building's `w` id in place of the node's `n` id) and fewer untreated water
points (historic springs). Update the figures and digest in "Status", drop the
note that the file predates the rules, and commit the file. The test
`test_bundled_file_is_well_formed` checks the result; the front end needs no
change.
