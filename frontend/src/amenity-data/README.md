# Public water and restrooms on the map

One fixture the front end loads the first time the Water and restrooms layer is
shown (`src/lib/waterRestrooms.ts`, imported with `?url`, so it is its own
hashed file under `/assets/` and the edge and Content-Security-Policy are
unchanged, as `federal-data/` is). The directory is not called `data/` because
the repository's `.gitignore` ignores every directory of that name.

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `water-restrooms.json` | public water (drinking fountains and taps; untreated springs, wells and taps) and public restrooms (flush, portable or pit, type not mapped) in the coverage box | OpenStreetMap, via the project's own extract, by `scripts/build_water_restrooms.py`; plus the open units of `throne-restrooms.json` | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |
| `throne-restrooms.json` | Throne smart restrooms (Throne Labs) in DC, Maryland and Virginia: a hand list, read by the build, not by the front end | city, county, parks and news pages, each unit with its URL and the date read; positions from the US Census Bureau geocoder (public domain) for the address each source gives | facts with sources; no third-party database copied (never Google Maps) | none needed; a list unit's card says "From Throne Labs and city sources" |

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
  become one place. A building that is not public or not in use is left out
  with what is inside it (unclear access is closed); a non-public node inside a
  public building is left out on its own. A `building=toilets` with no public node inside
  and no `amenity=toilets` stays out, as before.
- No historic springs. A `natural=spring` with `historic=*` (any value but
  `no`) or `ruins=yes` is a landmark, not a water source, and is left out unless
  it is also `drinking_water=yes` (or `amenity=drinking_water` or
  `amenity=water_point`), which says it is still usable.

Two more from the owner's requests of 2026-10-11 (RESTROOMS-FIX in the v0.5.0
plan):

- Not where the public can walk in. A point inside an area tagged
  `aeroway=aerodrome` or `aeroway=terminal` (airside), `landuse=military` or
  `military=*` (every value but `no` and `danger_area`), or `amenity=prison` is
  left out, water as well as restrooms. Areas are closed ways and multipolygon
  relations; a point in a hole of the area stays. The build prints how many it
  left out, by kind.
- Throne smart restrooms. The owner: "missing some restrooms that were
  established by Throne Labs, which are often along major biking routes";
  "They are in Maryland and Virginia too". OSM has few of them and no DC open
  dataset lists them, so `throne-restrooms.json` holds each unit found with a
  name, position, jurisdiction, status (`open`, `opens soon`, `unverified`), how
  it was placed and its sources with the date read. Only `open` units are
  merged into the map's file. A unit within 50 ft (15 m) of an OSM restroom, or
  within 500 ft (150 m) of one already tagged as a Throne (operator, brand or
  name), is that restroom: the OSM point stays and is marked `op: "Throne"`.
  Otherwise the unit is added with its `throne-...` id as a flush restroom,
  free and wheelchair accessible, as Throne describes every unit
  (<https://thronelabs.co/how-it-works>, read 2026-10-11). The card and lists
  then say how to open the door (the app, a text to 202-751-3694, or a free
  entry card; 10 minutes a visit).

The list found 17 of the 18 units the owner's Throne app shows (sweep of
2026-10-11):

| Unit | Jurisdiction | Status |
| --- | --- | --- |
| Dupont Circle | DC | open |
| Columbia Heights Civic Plaza | DC | open |
| Indiana Plaza by DC Superior Court | DC | open |
| Alethia Tanner Park | DC | open |
| Oxon Run Park | DC | open |
| Eastern Market Metro plaza | DC | open |
| Ellington Plaza (7th and T St NW) | DC | unverified (FY2026 plan) |
| Watkins Recreation Center | DC | unverified (FY2026 plan) |
| Starburst Plaza | DC | unverified (FY2026 plan) |
| Marvin Gaye Park | DC | unverified (FY2026 plan) |
| Yards Park | DC | unverified (2024 source) |
| Perry Street Park and Ride, Mount Rainier | MD | open |
| University Hills Duck Pond Park, Hyattsville | MD | open |
| 38th Avenue Neighborhood Park, Hyattsville | MD | opens soon |
| Old Town Square, Fairfax | VA | open |
| Van Dyck Park, Fairfax | VA | open |
| Fairfax Blvd (former Hy-Way Motel lot) | VA | unverified (2023 source; may have moved) |

Not found: a second unit near Navy Yard, and two or three more in the
Hyattsville and University Park area, which the owner's app screenshots show.
Positions are the site, not the exact unit (within about 500 ft (150 m)). When
someone confirms a unit, set its status to `open` (or move it to the spot seen)
and run `--throne-only` (below). Throne's app has a live map; a location feed
from Throne would replace this list.

The file is one point per line, short keys:

| Key | Meaning |
| --- | --- |
| `id` | OSM element, `n` node or `w` way, then its id; or `throne-...`, a unit from `throne-restrooms.json` |
| `x`, `y` | longitude, latitude (5 decimals, about 3 ft (1 m); a way's mean node) |
| `w` | water: `p` drinking water, `n` untreated (filter or treat first); left out for none |
| `t` | restroom: `f` flush, `b` portable, pit, composting or other basic toilet, `u` type not mapped; left out for none |
| `n` | `name` |
| `fee` | `fee=yes` or `no` |
| `wc` | `wheelchair=yes`, `limited` or `no` |
| `h` | `opening_hours`, as mapped |
| `s` | `seasonal`, unless `no` |
| `b` | 1 for `bottle=yes` on drinking water |
| `op` | `Throne` for a Throne smart restroom |

The file also has `"also"`, naming the Throne list as the second source.

## Status

The committed file predates the two 2026-10-10 rules and the 2026-10-11
secured-site rule above: it still has restroom nodes beside their buildings,
historic springs, and any restroom inside an airport, base or prison, until
the next refresh (below). Its Throne units are current: on 2026-10-11
`--throne-only` added the 10 open units (none was within 50 ft (15 m) of an
OSM restroom), giving 2,273 points, 142,769 bytes, sha256
`e462821aa491dde5687c59fcd34c87a13c1ff0b7788e41e1845ce88b86830472`. Three OSM
restroom nodes lie near listed units and may be the same Throne mapped in OSM
(their tags are not in the file): `n11958790038` about 550 ft (169 m) from
Columbia Heights, `n11958790039` about 700 ft (215 m) from the Superior Court
unit, and `n12026098603` about 90 ft (28 m) from Eastern Market. The rebuild
merges them if they carry `operator=Throne` (or brand or name); otherwise check
them on the map and move the listed unit onto the node.

The figures below are the 2026-10-09 build's, before the Throne units.

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

To merge the Throne list again without an extract (after a unit's status or
position changes), anywhere with the repository:

    .venv311/bin/python scripts/build_water_restrooms.py --throne-only

It keeps the file's OSM points and replaces its Throne units. An OSM point
marked as a Throne by its own tags in a full build is matched again only within
50 ft (15 m) here, as the file does not keep those tags.

## Refresh

Rerun the command above on a newer extract. Nothing else changes: the map reads
the file as it is.

The first refresh after the 2026-10-10 and 2026-10-11 rules: expect fewer
restrooms (airside, on base and in prisons, as well as the merges below), the
count the build prints as "left out inside airports, military sites and
prisons" to check against the map; and fewer restrooms (each node
merged into its building drops one point, and a merged place takes the
building's `w` id in place of the node's `n` id) and fewer untreated water
points (historic springs). Update the figures and digest in "Status", drop the
note that the file predates the rules, and commit the file. The test
`test_bundled_file_is_well_formed` checks the result; the front end needs no
change.
