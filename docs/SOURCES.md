# Data sources

Every data source RouteMaker shows the work of, with its full reference
(OWNER-DECISIONS 301: "Even if the license doesn't require crediting them, sources
need citing"; 306: "keep it brief and put the full information in documentation.
Sort of like how you'd cite in a paragraph").

The map, the route answer and the GPX export carry only the short credit given
under each source here, as an in-text citation would; this page is the reference
list. Where a licence fixes the wording, the credit keeps it: OpenStreetMap's ODbL
form "© OpenStreetMap contributors". Where it asks for the licence and the change to
be named (CC BY 4.0), the short credit says both ("DC Open Data (CC BY 4.0,
adapted)") and this page gives the rest. A source with no credit line is used
inside the project only and is shown nowhere.

`tests/test_credits.py` holds every credit the API and the front end display
(`routing.ATTRIBUTION`, `geocode.ATTRIBUTION`, `frontend/src/lib/credits.json`) to a
`Credit:` line on this page, and the fuller records (raw-file sizes and sha256,
item metadata, the licence texts verbatim) are in the fixture READMEs named below.

## OpenStreetMap

- Credit: `© OpenStreetMap contributors`
- What it is used for: every route, its roads, paths and facilities, the stress
  tiers' road attributes, the base map, place names and place search, the MARC Penn
  Line stations and the Metro elevators DC does not list.
- Dataset: OpenStreetMap, the regional extract from Geofabrik
  (<https://download.geofabrik.de/>), rebuilt weekly (docs/OPERATIONS.md, "The weekly
  rebuild").
- Publisher: OpenStreetMap contributors (OpenStreetMap Foundation).
- Licence: Open Database License 1.0 (<https://opendatacommons.org/licenses/odbl/1-0/>);
  credit form per <https://www.openstreetmap.org/copyright>.
- Retrieved: weekly; the extract's date is the rebuild's (`check_operations`).
- Records: `frontend/src/rail-data/README.md` (the MARC and elevator fixtures).

## Protomaps base map

- Credit: `Protomaps`
- What it is used for: the base map's vector style and the tile archive layout
  (`@protomaps/basemaps`, light flavour), served from `/basemap/region.pmtiles`.
- Publisher: Protomaps (<https://protomaps.com/>); the data in the archive is
  OpenStreetMap's (above).
- Licence: `@protomaps/basemaps` is BSD-3-Clause (in the shipped `licenses.txt`).
- Records: docs/DEPLOYMENT.md (`scripts/fetch_basemap.sh`).

## DC Open Data (District of Columbia)

- Credit: `DC Open Data (CC BY 4.0, adapted)`
- Publisher: the District of Columbia, Open Data DC (<https://opendata.dc.gov/>),
  each layer's credit field as recorded.
- Licence: Creative Commons Attribution 4.0 International
  (<https://creativecommons.org/licenses/by/4.0/>), each item's licence text recorded
  verbatim in the READMEs below. "Adapted": the counts are normalised, the street
  attributes conflated onto OSM ways, the polygons merged and simplified.
- The layers, each with its own reference:
  - **2024 Traffic Volume** (District Department of Transportation): annual average
    daily traffic, the stress tiers' District counts (`ddot-aadt-2024.geojson`,
    docs/PLAYBOOK.md, "The three reference inputs"; docs/DEVELOPMENT.md, "Reference
    data").
  - **DDOT Central Business District** (District Department of Transportation), item
    `32143ca8983d4476b64f4202162bf61e`, retrieved 2026-09-30; decides which sidewalks
    bicycles may not ride. Record and sha256: `fixtures/cbd/README.md`.
  - **Architect of the Capitol jurisdiction** (DC GIS), item
    `d9e8c786c9694e47979ef71a5c2f1a7a`, retrieved 2026-09-30, sha256
    `03e440f70147d42515dafe8bcc52eac3f88fd59d8ed824706ccbb776d1298d5f`; the Capitol
    grounds' sidewalks, and the Capitol polygon of the federal-land overlay.
    `fixtures/cbd/README.md`.
  - **Roadway Block** (District Department of Transportation / DC GIS), item
    `6fcba8618ae744949630da3ea12d90eb`, retrieved 2026-10-01, sha256
    `45066cff69065adeb0fb3ba3376abaaf58862bd37e3baba63d92062e68bb8108`; posted speed,
    lanes, one-way streets, bike lanes, parking and fallback counts in the District.
    `fixtures/datasets/README.md`.
  - **Metro Stations Regional** and **Metro Station Entrances (Regional)**
    (<https://opendata.dc.gov/datasets/metro-stations-regional>); the station and
    entrance markers. `frontend/src/rail-data/README.md`.
  - **National Parks** (NPS Map A: Park Service and other government-owned land; DC
    GIS), item `14eb1c6b576940c7b876ebafb227febe`, retrieved 2026-10-03, sha256
    `d2038ab8bb43ab947c8b377e01f47fb58e4b2cd16acd6d6dfe992a66b9184310`;
    **Reservations** (U.S. Reservations; District of Columbia), item
    `0ac4302b2e354fad986f07199e73a19e`, retrieved 2026-10-03, sha256
    `e4e34e2c425a052b40b04eef142448042cde6a57000b4ba5d81daea8168c364f`; **Military
    Bases** (DC Office of the Chief Technology Officer), item
    `21ee426eddc14014b80535cd6b8316e7`, retrieved 2026-10-03, sha256
    `951c9119eebfd879474bc03f305b5fff8941420b5edc15458a4e7def032407c5`. The Mass Ride
    map's federal-land shading (`frontend/src/federal-data/federal-land.json`, sha256
    `773f230f94c5a5b5ce576b17c09b83a3a4e10d5b8627f1d2c0e972d2b10ce4af`).
    `fixtures/datasets/README.md`, "Federal land".

## VDOT traffic volume

- Credit: `VDOT`
- Dataset: VDOT's annual traffic volume (AADT) export, Virginia Roads open data
  portal (<https://www.virginiaroads.org/>), `vdot-aadt-2024.geojson`; the stress
  tiers' Virginia counts.
- Publisher: Virginia Department of Transportation.
- Licence: open data, no restrictions stated (PLAN.md, "Licensing").
- Records: docs/PLAYBOOK.md, "The three reference inputs"; docs/DEVELOPMENT.md,
  "Reference data".

## Open Baltimore

- Credit: `Open Baltimore`
- Publisher: City of Baltimore (Open Baltimore, <https://data.baltimorecity.gov/>).
- Datasets: **Street Centerline (Native)**, item `69d9eb1e37044f1c9cc9941df1797c43`,
  sha256 `b386865bca7d95826008a0b825d035926453db2ac51a0f103ecabb6bf67f9dd8`;
  **DOT BMC Bike Facilities** (Baltimore City Department of Transportation), item
  `dbef46a0caf948debba8516f0d95fe4c`, sha256
  `29ea6582753bc920f091c02c4a4b80861da6f482d38947cbca416abf12d8b639`; **Multiuse
  Trails** (Department of Recreation & Parks, Department of Transportation), item
  `34260bfb3df74d3994e0c73fde47630b`, sha256
  `a0346799b9e519e56b7add57e186f484f051f8ba555adca334e7fe4023ed7eed`; all retrieved
  2026-10-01. Baltimore's speeds where OSM has none, its one-way streets, and the
  bike lanes and trail access the 2026-10-01 override file corrects.
- Licence: open, by Baltimore City Code Art. 1 §9-1(h)
  (<https://codes.baltimorecity.gov/us/md/cities/baltimore/code/1/9-1#(h)>).
- Records: `fixtures/datasets/README.md`.

## Montgomery County Planning

- Credit: `Montgomery County Planning Department`
- Dataset: **Bicycle Level of Traffic Stress**, item
  `fb903d1ffbc84b219bdb47629bd02b82`, retrieved 2026-10-01, sha256
  `89be5b63b86a69329d696e999565ac1a498ffed5a8bdf736d277f24a89a7505e`; its LTS 5 roads
  are loaded as Avoid (OWNER-DECISIONS 181).
- Publisher: Montgomery County Planning Department (M-NCPPC).
- Licence: open with attribution ("please provide attribution to the Montgomery
  County Planning Department"), recorded verbatim in `fixtures/datasets/README.md`.

## USGS 3D Elevation Program

- Credit: `USGS 3DEP`
- Dataset: 3DEP one-arcsecond elevation tiles (<https://www.usgs.gov/3d-elevation-program>,
  fetched from `prd-tnm.s3.amazonaws.com` by the rebuild's ELEVATION stage); the
  climb, the effort model and the Hills slider.
- Publisher: U.S. Geological Survey.
- Licence: U.S. public domain.
- Records: docs/OPERATIONS.md (the ELEVATION stage).

## U.S. Census Bureau

- Credit: `U.S. Census Bureau`
- Dataset: **TIGER/Line 2024 Urban Areas** (`tl_2024_us_uac20`, converted with
  `ogr2ogr -f GeoJSON -t_srs EPSG:4326`, installed as
  `<DATA_ROOT>/reference/urban-areas.json`); the stress tiers' urban and rural
  defaults (`routemaker.stress`).
- Publisher: U.S. Census Bureau (<https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html>).
- Licence: U.S. public domain.
- Records: docs/PLAYBOOK.md, "The three reference inputs".

## Photon

- Credit: `Photon`
- What it is: the place-search engine (Photon 1.3.0, image
  `docker.io/rtuszik/photon-docker:2.4.0`) over an index of OpenStreetMap's places
  (above).
- Publisher: komoot (<https://github.com/komoot/photon>).
- Licence: Apache 2.0 (the software); the places are OpenStreetMap's, ODbL.
- Records: docs/DEPLOYMENT.md, "Photon".

## Used inside the project only (no credit)

These are shown nowhere: no tile, route, fixture or page carries anything read from
them (OWNER-DECISIONS 152, 153, 155, 162).

- Arlington County's Bike Comfort Index and the City of Alexandria's Transport
  Streets: internal comparison only, held outside the repository.
- The City of Alexandria's Bike Lane Routes (CC0): a cross-check of OSM's bike
  lanes.
- MDOT's Road Separated Bike Routes web map: check-only (its terms bar trip-planning
  use).
