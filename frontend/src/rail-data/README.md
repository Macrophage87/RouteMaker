# Rail stations on the public map

Five small fixtures the front end bundles. `src/lib/railData.ts` imports them
as text, so they travel inside the app's own hashed script under `/assets/`:
no request of their own, nothing that can fail to load separately, and nothing
new for the edge - Caddy's `@frontend` rule and the Content-Security-Policy are
unchanged. (Under `frontend/public/` they would not be served at all: the
Caddyfile lists the app's paths one by one, and anything else goes to the API.)
The directory is not called `data/` because the repository's `.gitignore`
ignores every directory of that name.

PLAN.md "Licensing" asks that every external source is documented with its
licence, URL and refresh procedure; these are those records.

| File | What | Source | Licence | Credit on the map (since OWNER-DECISIONS 306, the brief form; docs/SOURCES.md has the full reference) |
| --- | --- | --- | --- | --- |
| `metro-stations.geojson` | 98 Metrorail stations, `NAME`, `LINE`, `ADDRESS`, `GIS_ID` | Open Data DC, "Metro Stations Regional", <https://opendata.dc.gov/datasets/metro-stations-regional>; ArcGIS layer `DCGIS_DATA/Transportation_Rail_Bus_WebMercator/MapServer/51` | **CC BY 4.0** | "DC Open Data (CC BY 4.0, adapted)", the map's one credit for the District's layers |
| `metro-entrances.geojson` | 260 station entrances, 86 of them elevators (`DESCRIPTION` "Metro Station Elevator" / "Metro Station Entrance"), `NAME`, `EXIT_TO_ST`, `LINE`, `CAPTUREYEAR`, `GIS_ID` | Open Data DC, "Metro Station Entrances (Regional)"; layer `.../MapServer/111` | **CC BY 4.0** | the same line |
| `metro-line-corrections.json` | lines added to `LINE` for two service changes the layer predates (below) | WMATA's own announcements, cited per change | this project's (facts, with sources) | - |
| `marc-penn-stations.geojson` | the MARC Penn Line's 9 stations from Washington Union Station to Baltimore Penn Station inclusive, and the elevators OSM maps at them | OpenStreetMap, via the project's own extract, by `scripts/build_marc_penn_stations.py` | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |
| `metro-osm-elevators.geojson` | 15 OSM elevators at the 7 Metro stations DC lists no elevator for | OpenStreetMap, via the same extract, by `scripts/check_metro_elevators.py --write` | **ODbL 1.0** (as above) | as above |

Both Open Data DC files are exactly the bytes the query below returned
(retrieved 2026-09-27, 13:39 UTC); the files themselves are not edited:

| File | Bytes | sha256 |
| --- | --- | --- |
| `metro-stations.geojson` | 23,398 | `b18dbfe0b4e2aadf9892a690d06099fdbce53f5a93279c5b7389bfa684265991` |
| `metro-entrances.geojson` | 83,626 | `332ef7bb9b1d62b27e980304636bfa13683a2699a5037e2f2433bab42341bd34` |

The two OSM-derived fixtures were generated from the extract of 2026-09-25
(`<DATA_ROOT>/extracts/source.osm.pbf`, 303,133,693 bytes, sha256
`1ac5490cc417d557a338dba868c4d039fbbbaf40d034e6c17e9ef1b1ef40577a`); a
regeneration on 2026-09-28 gave `marc-penn-stations.geojson` byte for byte
(sha256 `683c32d275ad6a51201d4e38301662d952a8e00dd4a6b9dbe5c8e479104d008a`).
`metro-osm-elevators.geojson` is sha256
`80e60ff87c593b2f431ea3e57ab32941c9b4594d47e13a6f97cc5c2c3b9c9145`.

## The licence gate

PLAN.md "Region and data" puts every source's terms to three questions at
ingest. For the two Open Data DC layers (CC BY 4.0, as the item pages state):

1. **Is redistribution permitted?** Yes: CC BY 4.0 permits sharing and
   adapting, commercially or not.
2. **Do the terms bind recipients of derived data?** Not reached. The layers
   are shown in a produced work - station symbols drawn on the map - and are
   never merged into the ODbL derived database, the alterations file or
   anything else this project publishes as data. They do not shape routing.
3. **How is attribution met?** By the credit on every map view, "Metro
   stations and entrances: District of Columbia (Open Data DC), CC BY 4.0",
   which links the licence (`RAIL_CREDITS`, `src/lib/mapStyle.ts`).

**Changes were made**, as CC BY 4.0 asks to be indicated: the map does not
show the `LINE` field as published. It adds Silver at five stations and Yellow
at nine for service the layer predates (`metro-line-corrections.json`, below);
it also parses `LINE` into line keys and gives each entrance to its nearest
station. The files in this directory are the unedited originals; the changes
are applied when the map loads (`applyCorrections`, `src/lib/railStations.ts`).

The MARC stations do **not** come from Maryland's own MARC layer: PLAN.md's
Maryland terms (Region and data) bind recipients of derived data in a way this
project cannot pass on until a waiver exists (owner decision 2026-09-27, "From
OpenStreetMap").

## What the data says

`LINE` values in the stations layer, all of which `parseLines` is tested
against (`src/lib/railStations.test.ts`): `blue`, `blue, orange, silver`,
`blue, silver`, `blue, yellow`, `green`, `green, yellow`,
`green, yellow, orange, blue, silver`, `orange`, `orange, silver`, `red`,
`red, blue, orange, silver`, `red, green`, `red, green, yellow`, `silver`,
`yellow`. The entrances layer adds orderings and spacings of the same names
(`silver, blue`, `orange, silver, blue`, `green,yellow`).

### Line corrections

The field predates two WMATA service changes, found in review and sourced to
WMATA's own announcements (cited in `metro-line-corrections.json`; the
reviewer also checked the stations' WMATA pages):

| Since | Change | Stations given the line |
| --- | --- | --- |
| 2025-06-22 | Half of Silver Line trains run Ashburn - New Carrollton | Minnesota Ave, Deanwood, Cheverly, Landover, New Carrollton (now Orange and Silver) |
| 2025-12-31 | Half of Yellow Line trains run Huntington - Greenbelt | Shaw-Howard U, U Street, Columbia Heights, Georgia Ave-Petworth, Fort Totten, West Hyattsville, Hyattsville Crossing, College Park-U of Md, Greenbelt (Fort Totten now Red, Green and Yellow; the rest Green and Yellow) |

Each correction names its station by `GIS_ID` and name. A correction whose
station no longer matches either, whose line is not a line's name, or whose
line `LINE` already carries (it is then spent and should be deleted) no longer
fits, and then:

- `npm test` fails, and so does `npm run build` on its own: a Vite plugin
  builds the stations from these files before anything else
  (`src/lib/railFixturesPlugin.mjs`), with the same code the app runs;
- a build that somehow ships it anyway does not lose the planner: the app
  leaves the rail stations off the map and says why in the console
  (`loadRailStations`, `src/lib/railFixtures.ts`).

Yellow at Gallery Place and Mt Vernon Sq was already in the field and is
current.

### Entrances and elevators

Entrances name their station differently from the stations layer
(`GALLERY PL-CHINATOWN ELEVATOR` for `Gallery Pl-Chinatown`), so they are
matched by position: each goes to the nearest station. Every one of the 260
is within 400 m of the station it goes to and shares its name's first word
(checked when the data was taken, and by the test above).

A ride started, ended or routed through a station goes to its **bike
entrance** (`bikeEntrance`, `src/lib/railStations.ts`):

1. DC's elevator nearest the station point - 64 of the 98 stations;
2. where DC lists none, OpenStreetMap's (owner decision 2026-09-28, "OSM
   elevator, else entrance") - Franconia-Springfield, Wheaton, Union Station,
   Silver Spring, Potomac Yard, West Falls Church, Forest Glen;
3. where neither has one, DC's nearest other entrance - the other 27;
4. the station point only when nothing is known - six of the seven MARC-only
   stations (all but BWI), and none of the Metro stations.

The station's card says which (`entranceNote`).

The MARC stations' elevators are OSM's too: BWI (two) and Washington Union
Station (three, inside the station building). Union Station is one station on
the map for both systems; the three are the same nodes as its three in
`metro-osm-elevators.geojson` and are counted once.

### Where DC and OSM disagree

The layer's `CAPTUREYEAR` is 2016 for 233 points, 2022 for 25 and 2023 for 2,
so `scripts/check_metro_elevators.py` lists where OpenStreetMap disagrees
(extract of 2026-09-25). PLAN.md "Region and data" records a discrepancy as a
question and resolves it by independent re-derivation; these are those
questions, open:

- 20 DC elevators have no OSM elevator within 40 m (Capitol South, Herndon,
  Loudoun Gateway, Tysons, McLean, Friendship Heights and others). DC's point
  is used; review suggests these are real elevators OSM has not mapped.
- One OSM street elevator has no DC elevator near it (Medical Center, node
  9512298306). Not used: Medical Center has DC's.
- 15 OSM elevators at 7 stations DC lists none for. These are now used (rule
  2 above).

## Refresh (by hand)

From the repository root, the Open Data DC layers - the same two queries,
nothing else (the output is the whole layer; the service's default page size
is well above either count, and `exceededTransferLimit` is absent from both
responses):

```sh
curl -fsS -o frontend/src/rail-data/metro-stations.geojson \
  'https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_Rail_Bus_WebMercator/MapServer/51/query?where=1%3D1&outFields=NAME,LINE,ADDRESS,GIS_ID&outSR=4326&f=geojson'
curl -fsS -o frontend/src/rail-data/metro-entrances.geojson \
  'https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_Rail_Bus_WebMercator/MapServer/111/query?where=1%3D1&outFields=NAME,EXIT_TO_ST,LINE,DESCRIPTION,CAPTUREYEAR,GIS_ID&outSR=4326&f=geojson'
```

then `npm test` in `frontend/` (a `LINE` value the parser does not know, or a
line correction that no longer fits, fails it, and `npm run build` too),
update the tables and dates above, and review the diff.

The OSM-derived fixtures, from the current extract (read only):

```sh
.venv311/bin/python scripts/build_marc_penn_stations.py --pbf <DATA_ROOT>/extracts/source.osm.pbf
.venv311/bin/python scripts/check_metro_elevators.py --pbf <DATA_ROOT>/extracts/source.osm.pbf --write
```

The first prints the station order it derived from the Penn Line's route
relation and stops with an error if any Penn Line variant calls south of
Baltimore Penn at a station the list lacks. The second prints the elevator
disagreements and the OSM elevators the map uses, and rewrites
`metro-osm-elevators.geojson` from that last list; update the summary above
from it, and the extract's date and sha256.

The MARC fixture's `colour` is the OSM route's own tag (a pale lavender). The
map does not read it - it draws the Penn Line in gold, `PENN_COLOUR` in
`src/lib/railStations.ts` (owner, 2026-09-28: a Purple Line opens soon) - and
it is kept as provenance: it records what OSM says, so a refresh shows if the
route's own colour changes.
