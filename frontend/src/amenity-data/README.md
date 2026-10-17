# Public water and restrooms on the map, and places to eat

Two fixtures the front end loads when first needed: water and restrooms the
first time the Water and restrooms layer is shown, and places to eat on the
first "Find food" search (see "Places to eat" at the end). Each is imported
with `?url` (`src/lib/waterRestrooms.ts`, `src/App.tsx` for `food.json`), so
it is its own hashed file under `/assets/` and the edge and
Content-Security-Policy are unchanged, as `federal-data/` is. The directory is not called `data/` because
the repository's `.gitignore` ignores every directory of that name.

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `water-restrooms.json` | public water (drinking fountains and taps; untreated springs, wells and taps), public restrooms (flush, portable or pit, type not mapped), public bike repair stands, and bike shops (for Go's Repair chip only) in the coverage box | OpenStreetMap, via the project's own extract, by `scripts/build_water_restrooms.py`; plus the open units of `throne-restrooms.json` | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |
| `food.json` | places to eat (restaurants, fast food, cafes, ice cream, pubs, beer gardens, food courts, farm stands and markets) in the coverage box, for the planner's Find food search | OpenStreetMap, via the project's own extract, by `scripts/build_food.py` | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |
| `places.json` | places to see (museums, historic sites, lighthouses, gardens, viewpoints, markets, zoos, waterfalls and peaks, bridges, breweries and wineries) in the coverage box, for Plan's Places to see tab, Go's Sights and the Places to see layer | OpenStreetMap, via the project's own extract, by `scripts/build_places.py` | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |
| `trail-miles.json` | trail mile markers (posted figures, each with its named trail) and a line from mile 0 for each long trail whose mile 0 is known (its own posts, or a short table of known trails), for the 311 report, "Where am I?", the road panel and the markers on the map | OpenStreetMap, via the project's own extract, by `scripts/build_trail_miles.py` | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)"; the tap card says "From OpenStreetMap." |
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
  `military=*` (every value but `no` and `danger_area`, and not on an area also
  tagged `historic=*`, an old fort or battery that is a park now), or
  `amenity=prison` is
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
  within 1,000 ft (300 m) of one already tagged as a Throne (operator, brand or
  name), is that restroom: the OSM point stays and is marked `op: "Throne"`
  (and `tu`, the unit's id, when OSM does not tag it a Throne itself). Each OSM
  restroom stands for one unit at most. The wide reach is because the list's
  positions are street addresses: the three OSM nodes below lie 90 to 700 ft
  (28 to 215 m) from the units they look like.
  Otherwise the unit is added with its `throne-...` id as a flush restroom,
  free and wheelchair accessible, as Throne describes every unit
  (<https://thronelabs.co/how-it-works>, read 2026-10-11). The card and lists
  then say how to open the door (the app, a text to 202-751-3694, or a free
  entry card; 10 minutes a visit). An added unit carries `ap: 1` unless the
  list marks it `"exact": true` (placed from OSM or imagery), and its card says
  the location is approximate: placed from the site's street address, so the
  unit may be a block or so from the pin.

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
Positions are the site's street address, not the exact unit (Mount Rainier's
is across the street from its address point), so each added unit's card says
the location is approximate. When
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
| `tu` | the Throne list unit that marked an OSM restroom not tagged a Throne in OSM (so `--throne-only` can unmark it) |
| `ap` | 1 for an approximate position (a Throne list unit placed from a street address) |
| `rs` | a public bike repair stand (`amenity=bicycle_repair_station`): its kit as letters, `p` pump, `t` tools, `c` chain tool; `""` when none is mapped |
| `bs` | 1 for a bike shop (`shop=bicycle`): Go's Repair chip lists it; it is never drawn on the map |
| `web` | a bike shop's `website` (or `contact:website`), only an `http(s)://` address |

The file also has `"also"`, naming the Throne list as the second source.

## Status

Generated on the build host on 2026-10-11 for the v0.5.0 rebuild, from the
2026-10-09 extract that rebuild builds from (`<DATA_ROOT>/extracts/source.osm.pbf`),
with the 2026-10-10 rules and the 2026-10-11 secured-site rule above: 2,152
points, 134,834 bytes, sha256
`d4f4d7bf71275dabc9cba3c318deb33b7b1162e004d37e07fedc1eeaeccbc9d0`. 106 left
out inside airports, military sites and prisons (airport 91, military 15).
Throne: 6 units added from the list and 4 matched to OSM restrooms (the
`operator=Throne` merge above); 7 listed units not open or not confirmed are
left off the map.

| Kind | Points |
| --- | --- |
| drinking water | 734 (20 of them at a restroom, so the rows add to 2,172) |
| untreated water | 174 |
| flush restroom | 173 |
| portable, pit or composting toilet | 284 |
| restroom, type not mapped | 807 |

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

### Repair stands and bike shops (v0.7.0)

The v0.7.0 build reads `amenity=bicycle_repair_station` and `shop=bicycle` too
(the rules are in the script's docstring). The committed file predates that
change, so it has no stands or shops until the next full build on the build
host (the command above); until then Go's Repair chip says none are known.
Record the stand and shop counts the build prints here.

## Refresh

Rerun the command above on a newer extract. Nothing else changes: the map reads
the file as it is.

Update the figures and digest in "Status" and commit the file. The test
`test_bundled_file_is_well_formed` checks the result; the front end needs no
change.

## Places to eat

`food.json` is the Find food search's data (`src/lib/food.ts`; FOOD-SEARCH in
the v0.5.0 plan, owner 2026-10-11: "search for a midride crab restaurant or
pizza place"; "Mostly let's do a map search for it. People are willing to
detour for good food."). What counts (the OSM tags, public access, the
secured-site rule shared with the water layer, duplicates merged by name
within 200 ft (60 m)) is in the docstring of `scripts/build_food.py`. No
ratings: there is no open source for them, and Google's data is never copied.

One place per line, short keys:

| Key | Meaning |
| --- | --- |
| `id` | OSM element, `n` node, `w` way or `r` relation, then its id |
| `x`, `y` | longitude, latitude (5 decimals; a way or relation at its outer ring's mean) |
| `k` | kind: `r` restaurant, `f` fast food, `c` cafe, `i` ice cream, `p` pub, `b` beer garden, `fc` food court, `fs` farm stand (`shop=farm`), `m` market (`amenity=marketplace`) |
| `n` | `name` (or `brand` where there is no name) |
| `c` | `cuisine`, normalised: lower case, `_` for spaces, `;` between values, no repeats, at most 6 |
| `h` | `opening_hours`, as mapped |
| `web` | `website` (or `contact:website`), only an `http(s)://` address |

### Status

Generated on the build host on 2026-10-11 for the v0.5.0 rebuild, from the
2026-10-09 extract that rebuild builds from (`<DATA_ROOT>/extracts/source.osm.pbf`):
15,480 places, 12,940 of them with a cuisine; 197 left out inside airports,
military sites and prisons (airport 133, military 63, prison 1).
2,262,385 bytes (555,199 with `gzip -9`), sha256
`e02ac7c38d7dc963048dffb8e07e6880427a1459e165b213c744c500ebcc508f`.

| Kind | Places |
| --- | --- |
| restaurant | 8,040 |
| fast food | 5,061 |
| cafe | 1,537 |
| ice cream | 496 |
| pub | 300 |
| food court | 34 |
| beer garden | 12 |

To rebuild, on the build host, from the repository root:

    .venv311/bin/python scripts/build_food.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It prints the places by kind, how many have a cuisine, how many were left out
inside airports, military sites and prisons, and the file's size (and warns
over 3,000,000 bytes, as the front end fetches the whole file on the first
search). Record the counts, size and sha256 here and commit the file. `test_bundled_file_is_well_formed` in
`tests/test_build_food.py` checks it.

The v0.7.0 build adds farm stands (`shop=farm`, `fs`) and markets
(`amenity=marketplace`, `m`). The committed file predates that change: the
next build on the build host adds them; record the counts here.

## Places to see

`places.json` is Plan's Places to see tab, Go's Sights (behind More) and the
Places to see map layer (`src/lib/places.ts`; the owner, 2026-10-14: "Let's
categorize by things like museums, lighthouses, gardens, farmers markets,
etc."). What counts, by category, and what is left out (unnamed places,
private or unclear access, small plaques, production-only breweries, secured
sites) is in the docstring of `scripts/build_places.py`.

One place per line, short keys:

| Key | Meaning |
| --- | --- |
| `id` | OSM element, `n` node, `w` way or `r` relation, then its id |
| `x`, `y` | longitude, latitude (5 decimals; a way or relation at its outer ring's mean) |
| `k` | category: `museum`, `historic`, `lighthouse`, `garden`, `viewpoint`, `market`, `zoo`, `nature`, `bridge`, `drink` |
| `n` | `name`; a covered bridge's `bridge:name` where it has one |
| `h` | `opening_hours`, as mapped |
| `web` | `website` (or `contact:website`), only an `http(s)://` address |
| `cv` | `1` on a covered bridge (`bridge=covered`), left out otherwise: the Scenic layer (v0.8.0, `src/lib/scenicLayer.ts`) draws the covered bridges and the viewpoints from this file |

### Status

Not built yet: the committed file has no places (the cloud cannot reach the
extract). The tab, Sights and the layer say so until it is built. On the
build host, from the repository root:

    .venv311/bin/python scripts/build_places.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It prints the places by category, how many were left out inside airports,
military sites and prisons, and the file's size. Record the counts, size and
sha256 here and commit the file. `test_bundled_file_is_well_formed` in
`tests/test_build_places.py` checks it.

## Trail mile markers

`trail-miles.json` is the trail mile markers (`src/lib/trailMiles.ts`; OWNER-DECISIONS
465: "some trails like the MBT and CCT should have mile markers as they can go
a distance without crossing a road"; Stephen, 2026-10-16: "Make sure the mile
markers are added to 311 when built"). The 311 report, "Where am I?" and the
road panel name a trail's nearest posted marker, or its computed mile, worked
out on the device; the map draws the markers from zoom 14 in. What counts as a
marker and as a trail, how a trail's line is found and which end is mile 0 is
in the docstring of `scripts/build_trail_miles.py`. App fetches it once the map
reaches zoom 14, a ride starts or the road panel opens; it is precached (not a
lazy asset), so a ride has it offline.

Two lists, one row per line, short keys:

| Key | Meaning |
| --- | --- |
| `trails[].n` | the trail's OSM `name` |
| `trails[].s` | the metres at the line's first point: from the posts where they fit (one or more), else 0 at a known trail's mile-0 end |
| `trails[].l` | the line from mile 0, `[lon, lat]` pairs, simplified to about 30 ft (10 m), 5 decimals |
| `markers[].id` | the OSM node, `n` then its id |
| `markers[].x`, `y` | longitude, latitude (5 decimals) |
| `markers[].t` | the name of the trail it stands on (the nearest named trail within 80 ft, 25 m) |
| `markers[].m` | the posted figure, in miles |

### Status

Generated on the build host on 2026-10-16, from the 2026-10-09 extract the
live stack builds from (`<DATA_ROOT>/extracts/source.osm.pbf`): 10 trail lines
over 2 miles and 52 markers on 5 trails; 32 left out as not on a named trail
and 1 as nearer a main road than the trail (the Washington, Baltimore &
Annapolis Trail's mile 0, `n8960887982`, 49 ft (15 m) from the trail; its line
still starts at mile 0 from the other posts). No interstate's posts (I-66,
I-495, I-270) are among the markers. 25,052 bytes, sha256
`81765e6da213ecc5cb3bcd44db35e26bf630b9b542bcd1bf57eabd2a676cc341`.

| Trail | Markers | Lines (mile at the first point) |
| --- | --- | --- |
| Chesapeake and Ohio Canal Trail | 44 | 4 (0.33 at Georgetown; 22.1, 54.8, 93.4 from posts) |
| Torrey C. Brown Trail | 3 | 1 (0, from posts) |
| Washington, Baltimore & Annapolis Trail | 3 | 2 (0, from posts) |
| Chesapeake and Ohio Canal Towpath | 1 | 1 (19.6, from its post) |
| Washington & Old Dominion Trail | 1 | 1 (0.10 at Shirlington) |
| Capital Crescent Trail | 0 | 1 (0 at Georgetown, 7.5 mi to Bethesda) |

The Metropolitan Branch Trail has no line yet: in OSM its Union Station piece
(1.6 mi) and its Brookland piece (1.8 mi) are about 2,500 ft (760 m) apart,
near 38.926 to 38.932 N, more than the quarter-mile join, and each is under
2 miles. The towpath named "Chesapeake and Ohio Canal Towpath" from about
mile 9 to 13 (3.9 mi, near Great Falls) has no posts and is not at mile 0, so
it has no line either.

To rebuild, from the repository root on that host:

    .venv311/bin/python scripts/build_trail_miles.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It prints the trail lines kept, the markers and the trails they are on (the
eight with most), how many were left out as not on a named trail or as a main
road's milepost, and the file's size. Over 600,000 bytes it fails (exit 1) and
writes nothing, as the front end keeps the file offline. Lines are drawn only
from cycleways and `bicycle=yes`/`designated` ways (and any way of a table
trail), and only where mile 0 is known: the trail's own posts, or the script's
`MILE_ZERO` table (the C&O Canal towpath and the Capital Crescent Trail from
Georgetown, the Metropolitan Branch Trail from Union Station, the W&OD from
Shirlington). Check that those four are there and their mile 0 is the right
end, and that no road's posts (I-66, I-495) are on a trail; record the counts,
size and sha256 here and commit the file. Add a trail to `MILE_ZERO` only once
its posts' numbering is checked (the Mount Vernon and Custis trails are not
yet).
`test_bundled_file_is_well_formed` in `tests/test_build_trail_miles.py` checks
it. No map rebuild is needed: the tiles and the routing graph do not change.
