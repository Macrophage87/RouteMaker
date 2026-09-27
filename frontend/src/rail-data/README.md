# Rail stations on the public map

Three small fixtures the front end bundles. `src/lib/railData.ts` imports them
as text, so they travel inside the app's own hashed script under `/assets/`:
no request of their own, nothing that can fail to load separately, and nothing
new for the edge - Caddy's `@frontend` rule and the Content-Security-Policy are
unchanged. (Under `frontend/public/` they would not be served at all: the
Caddyfile lists the app's paths one by one, and anything else goes to the API.)
The directory is not called `data/` because the repository's `.gitignore`
ignores every directory of that name.

PLAN.md "Licensing" asks that every external source is documented with its
licence, URL and refresh procedure; these are those records.

| File | What | Source | Licence | Credit on the map |
| --- | --- | --- | --- | --- |
| `metro-stations.geojson` | 98 Metrorail stations, `NAME`, `LINE`, `ADDRESS`, `GIS_ID` | Open Data DC, "Metro Stations Regional", <https://opendata.dc.gov/datasets/metro-stations-regional>; ArcGIS layer `DCGIS_DATA/Transportation_Rail_Bus_WebMercator/MapServer/51` | **CC BY 4.0** | "Metro stations and entrances: District of Columbia (Open Data DC), CC BY 4.0" |
| `metro-entrances.geojson` | 260 station entrances, 86 of them elevators (`DESCRIPTION` "Metro Station Elevator" / "Metro Station Entrance"), `NAME`, `EXIT_TO_ST`, `LINE`, `CAPTUREYEAR`, `GIS_ID` | Open Data DC, "Metro Station Entrances (Regional)"; layer `.../MapServer/111` | **CC BY 4.0** | the same line |
| `marc-penn-stations.geojson` | the MARC Penn Line's 9 stations from Washington Union Station to Baltimore Penn Station inclusive, and the elevators OSM maps at them | OpenStreetMap, via the project's own extract, by `scripts/build_marc_penn_stations.py` | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |

Both Open Data DC files are exactly the bytes the query below returned
(retrieved 2026-09-27, 13:39 UTC), unedited:

| File | Bytes | sha256 |
| --- | --- | --- |
| `metro-stations.geojson` | 23,398 | `b18dbfe0b4e2aadf9892a690d06099fdbce53f5a93279c5b7389bfa684265991` |
| `metro-entrances.geojson` | 83,626 | `332ef7bb9b1d62b27e980304636bfa13683a2699a5037e2f2433bab42341bd34` |

CC BY 4.0 asks for the credit and a note of changes. The files are unchanged;
the map derives from them (line keys parsed from `LINE`, each entrance given to
its nearest station), which the credit's wording does not need to spell out
but this note records.

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

Entrances name their station differently from the stations layer
(`GALLERY PL-CHINATOWN ELEVATOR` for `Gallery Pl-Chinatown`), so they are
matched by position: each goes to the nearest station. Every one of the 260
is within 400 m of the station it goes to and shares its name's first word
(checked when the data was taken, and by the test above).

64 of the 98 stations have an elevator in the layer; the other 34, mostly
surface and elevated stations (Union Station, Silver Spring, Wheaton...),
have none, and a tap on them puts the point on the station itself.

The layer's `CAPTUREYEAR` is 2016 for 233 points, 2022 for 25 and 2023 for 2,
so `scripts/check_metro_elevators.py` lists where OpenStreetMap disagrees
(run against the extract of 2026-09-25): 20 DC elevators have no OSM elevator
within 40 m; one OSM street elevator (Medical Center, node 9512298306) has no
DC elevator near it; and 15 OSM elevators sit at stations DC gives no
elevator (Franconia-Springfield, Wheaton, Union Station, Silver Spring,
Potomac Yard, West Falls Church, Forest Glen). None of the OSM-only ones are
used for Metro: DC's layer is the map's source for Metro elevators, and the
list is for review.

The MARC stations' elevators are OSM's (the coordinator's instruction: OSM's
where tagged, else the station). Two stations have any: BWI (two) and
Washington Union Station (three, inside the station building). Union Station
is one station on the map for both systems, and DC lists no Metro elevator
there, so its bike entrance is OSM's elevator nearest the station point -
one of the three the check above also lists.

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

then `npm test` in `frontend/` (a `LINE` value the parser does not know fails
it), update the table and dates above, and review the diff.

The MARC stations, from the current extract (read only):

```sh
.venv311/bin/python scripts/build_marc_penn_stations.py --pbf <DATA_ROOT>/extracts/source.osm.pbf
.venv311/bin/python scripts/check_metro_elevators.py --pbf <DATA_ROOT>/extracts/source.osm.pbf
```

The first prints the station order it derived from the Penn Line's route
relation and stops with an error if any Penn Line variant calls south of
Baltimore Penn at a station the list lacks. The second prints the elevator
disagreements; update the summary above from it.
