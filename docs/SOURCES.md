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
  Line stations and the Metro elevators DC does not list, the public drinking water,
  restrooms and bike repair stands layer, Go's Repair chip (stands and bike shops), Find food
  (with farm stands and markets), the places to see (Plan's Places to see, Go's Sights), and the
  trail mile markers (the 311 report, "Where am I?", the road panel and the map).
  The Scenic layer (v0.8.0) reads three things from it: the East Coast Greenway and the US
  Bicycle Routes, from route relations (`type=route`, `route=bicycle`, `network=ncn`,
  `ref="USBR N"`, per <https://wiki.openstreetmap.org/wiki/WikiProject_U.S._Bicycle_Route_System>,
  and the forms also in use: a bare `ref=N` with `cycle_network=US:US` or `US`, or a name
  "U.S. Bicycle Route N";
  USBR 1 is relation 3022887, USBR 11 is 12126554, USBR 50 is 2532740; the Greenway is relation
  1774795, `network=ncn` with no USBR ref, and a section relation takes its parent's name;
  the ids are the sources note's, to be confirmed on the extract, docs/OPERATIONS.md);
  covered bridges, `bridge=covered` (<https://wiki.openstreetmap.org/wiki/Key:covered>: not
  `covered=yes`), named by `bridge:name`; and viewpoints, `tourism=viewpoint`. Read
  2026-10-16. Maryland's covered bridges per the Maryland Manual are Roddy Road, Loy's
  Station and Utica Mills in Frederick County and Jericho in Baltimore and Harford counties;
  whether OSM maps each as `bridge=covered` was not checked.
- Dataset: OpenStreetMap, the regional extract from Geofabrik
  (<https://download.geofabrik.de/>), rebuilt weekly (docs/OPERATIONS.md, "The weekly
  rebuild").
- Publisher: OpenStreetMap contributors (OpenStreetMap Foundation).
- Licence: Open Database License 1.0 (<https://opendatacommons.org/licenses/odbl/1-0/>);
  credit form per <https://www.openstreetmap.org/copyright>.
- Retrieved: weekly; the extract's date is the rebuild's (`check_operations`).
- Records: `frontend/src/rail-data/README.md` (the MARC and elevator fixtures);
  `frontend/src/amenity-data/README.md` (public drinking water and restrooms, the Water and
  restrooms layer, by `scripts/build_water_restrooms.py`); the same README's "Places to
  eat" (restaurants, cafes and the like, farm stands and markets, the planner's Find food
  search, by `scripts/build_food.py`); and its "Places to see" (points of interest by
  category, by `scripts/build_places.py`); and its "Trail mile markers" (posted trail mile
  markers and the long named trails' lines, for the 311 report, "Where am I?", the road panel and
  the markers on the map, by `scripts/build_trail_miles.py`). The water file also holds bike repair stands and
  bike shops (`scripts/build_water_restrooms.py`). The layer's Throne smart
  restrooms are not OSM: a hand list, `frontend/src/amenity-data/throne-restrooms.json`, each
  unit with its city, county, parks or news source URL and the date read (2026-10-11), placed
  with the US Census Bureau geocoder (<https://geocoding.geo.census.gov/>, public domain).
- Also: **the District of Columbia's boundary** on the Mass Ride map (OWNER-DECISIONS 418,
  418a: the grey outside DC, the capacity tiles' clip, the route's "outside DC" notice). It is the
  extract's `boundary=administrative`, `admin_level=4`, `ISO3166-2=US-DC` relation, joined into rings
  by the rebuild's own `pipeline.states` code and simplified to about 30 ft (10 m) by
  `scripts/build_dc_boundary.py`; nothing was downloaded for it. Written 2026-10-05 from the
  2026-10-03 extract (`district-of-columbia-latest.osm.pbf`; the merged extract gives the same
  bytes): 1 polygon, 163 vertices, 3,630 bytes, about 68.3 sq mi (177 km², land and water).
  The two copies, `frontend/src/massride-data/dc-boundary.json` (the map) and
  `src/core/geodata/dc-boundary.geojson` (the tiles), are the same bytes
  (`tests/test_mass_tiles.py`). Credit: the line above, on the map, and "District of Columbia
  boundary: © OpenStreetMap contributors (ODbL)." under the Mass Ride legend.

## Protomaps base map

- Credit: `Protomaps`
- What it is used for: the base map's vector style and the tile archive layout
  (`@protomaps/basemaps`, light flavour), served from `/basemap/region.pmtiles`.
- Publisher: Protomaps (<https://protomaps.com/>); the data in the archive is
  OpenStreetMap's (above).
- Version: the daily build `20260926` (`PROTOMAPS_BUILD` in `scripts/fetch_basemap.sh`,
  <https://build.protomaps.com/20260926.pmtiles>), cut to the region; retrieved 2026-09-26.
  The style package is `@protomaps/basemaps` 5.7.2 (`frontend/package.json`).
- Licence: `@protomaps/basemaps` is BSD-3-Clause (in the shipped `licenses.txt`).
- Records: docs/DEPLOYMENT.md (`scripts/fetch_basemap.sh`); docs/OPERATIONS.md, "The
  base map".

## DC Open Data (District of Columbia)

- Credit: `DC Open Data (CC BY 4.0, adapted)`
- Publisher: the District of Columbia, Open Data DC (<https://opendata.dc.gov/>),
  each layer's credit field as recorded.
- Licence: Creative Commons Attribution 4.0 International
  (<https://creativecommons.org/licenses/by/4.0/>), each item's licence text recorded
  verbatim in the READMEs below. "Adapted": the counts are normalised, the street
  attributes conflated onto OSM ways, the polygons merged and simplified.
- The layers, each with its own reference:
  - **2024 Traffic Volume** (District Department of Transportation; the layer's own
    name is `Traffic_Volume_-_2024`): annual average daily traffic, the stress tiers'
    District counts. Retrieved 2026-09-25; the file installed is
    `ddot-aadt-2024.geojson`, 19,021,354 bytes, sha256
    `e85b6024a1eeb6864f235f1cd12bad8f190d9ef332584a7cd74ca522225f0d0b`. The item id and
    the query URL were not recorded at ingest; the next refresh records them here.
    docs/PLAYBOOK.md, "The three reference inputs"; docs/DEVELOPMENT.md, "Reference
    data".
  - **Bicycle Level of Traffic Stress, 2020** (District Department of Transportation),
    downloaded with `scripts/fetch_agency_layer.py` as `ddot-lts-2020`; approved as a
    rating source (`routemaker.agency_lts.AGENCIES`, ranked with a county's). Installed
    into `reference/agency-lts.json` by `scripts/install_agency_lts.py` (docs/OPERATIONS.md,
    "Agency stress ratings (agency-lts.json)"); the road panel names "DDOT" beside its
    level. Item id, size, sha256 and the licence text verbatim: the download's README, to
    be copied here.
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
    lanes, one-way streets, bike lanes, parking and fallback counts in the District;
    and, since OWNER-DECISIONS 404, the Mass Ride capacity map's usable widths in the
    District (travel-lane, bike-lane and parking widths and lanes by direction,
    `routemaker.massflow`), credited on the Mass Ride legend in the credit line's own
    words with OpenStreetMap beside it. `fixtures/datasets/README.md`. The block's
    reversible-lane count is NOT trusted for the Mass Ride width (OWNER-DECISIONS
    405): the District ended Connecticut Avenue NW's reversible lanes in 2020, so the
    layer's count is stale there, and reversible lanes count as zero for the width
    everywhere unless a reviewed block is allowlisted. The LTS classifier and the
    crossing stress do count them, in each direction (OWNER-DECISIONS 425: "These tend
    to be high stress commuter roads"), except on Connecticut Avenue NW. The reason, and the owner's source for
    it: DCist, "Say goodbye to reversible lanes on Connecticut Avenue and hello to a
    bike-friendly redesign", 2021-12-15 (dcist.com), credited here. Connecticut Avenue
    NW north of Calvert St is then given three travel lanes each way by the owner's own
    knowledge (OWNER-DECISIONS 412, 2026-10-05: "Connect is 3 but one is sometimes used
    for parking, though double and even triple parking also happens."), overriding the
    layer's 1 + 1 plus 2 reversible: `fixtures/lane_overrides/`. The owner is the source;
    the Dupont Circle underpass's bike access and LTS 4 are decision 416.
  - **Metro Stations Regional** (<https://opendata.dc.gov/datasets/metro-stations-regional>;
    ArcGIS layer `DCGIS_DATA/Transportation_Rail_Bus_WebMercator/MapServer/51`) and
    **Metro Station Entrances (Regional)** (the same service, layer 111), retrieved
    2026-09-27, 13:39 UTC, sha256
    `b18dbfe0b4e2aadf9892a690d06099fdbce53f5a93279c5b7389bfa684265991` and
    `332ef7bb9b1d62b27e980304636bfa13683a2699a5037e2f2433bab42341bd34`; the station and
    entrance markers. The ArcGIS item ids were not recorded; the layer paths above are
    what was queried. `frontend/src/rail-data/README.md`.
  - **Traffic Signals** (District Department of Transportation; the layer's own name is
    "DDOT Traffic Signals"), item `ca6ad078a6f6415389e220704b7698ac`, ArcGIS layer
    `DCGIS_DATA/Transportation_Signs_Signals_Lights_WebMercator/MapServer/170`
    (<https://opendata.dc.gov/datasets/traffic-signal>); licence CC BY 4.0 (the item's,
    read 2026-10-19), item modified 2026-10-05, 1,597 signals, every `STATUS` Active.
    Marks the junctions at a District signal OSM does not map as one (v0.10.0;
    `pipeline.agency_signals`, docs/OPERATIONS.md "Agency traffic signals"); a record
    with `HAWK` yes marks the crosswalk it stands at. Fetched at rebuild time; size and
    sha256: the download's README, to be copied here.
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

## DDOT Pavement Condition Index (DC-PCI)

- Credit: `DDOT Pavement Condition Index (DC GIS)`
- Dataset: **Pavement Condition Index FY-25**, layer 5 of DC GIS's
  `DDOT/PavementConditionIndex` FeatureServer
  (<https://rh.dcgis.dc.gov/dcgis/rest/services/DDOT/PavementConditionIndex/FeatureServer/5>;
  layers 0 to 5 are FY-12 to FY-25). Polylines with `PCI` (0 to 100), `PCICTEGORY`,
  `ROUTENAME`, `FROMSTREET`/`TOSTREET`, `ROUTEID`, `FROMMEASURE`/`TOMEASURE` and three
  unlabelled date fields, `DATE1`, `CONST_DATE` and `LSTMJRWRKD`; 1,000 records a
  page. Read from the service's metadata and two sample records on 2026-10-11 (the
  sample's `DATE1` values are 2026-02-27 and 2026-03-02). The District streets'
  smoothness reading, over OSM's `smoothness` (the owner, 2026-10-11: "DC score in
  most cases takes priority over OSM data"): 70 and over good, 55 to 69 fair (a small
  penalty), under 55 poor (rough), on streets only; alleys and trails keep OSM's.
  Fetched at rebuild time with `scripts/fetch_agency_layer.py` (docs/OPERATIONS.md,
  "DC pavement condition (DC-PCI)"); not yet downloaded, so no size or sha256 yet.
- Publisher: District Department of Transportation and DC GIS (the service's
  `accessInformation`: "DDOT and DC GIS").
- Licence: the District's data terms
  (<https://dc.gov/page/terms-and-conditions-use-district-data>, "Terms and Conditions
  of Use for District Data", sent by the owner 2026-10-16): CC0 1.0 by default, CC BY
  4.0 where an item says so; credited either way, as the owner asked ("The distinction
  doesn't matter here as we're going to cite them"). This layer's own `copyrightText`,
  description and `licenseInfo` are empty (read 2026-10-11). Owner confirmation
  2026-10-16; `routemaker.pavement.LICENCE_CONFIRMED` is True.
- Assumption to confirm: `DATE1` is taken as the survey date; the service does not
  say which date field is which.
- Records: the download's README; `fixtures/pavement/overrides.json` for the owner's
  corrections; the rebuild's `dc-pavement-pci.csv` report.

## VDOT traffic volume

- Credit: `VDOT`
- Dataset: VDOT's annual traffic volume (AADT) export, Virginia Roads open data
  portal (<https://www.virginiaroads.org/>), `vdot-aadt-2024.geojson`; the stress
  tiers' Virginia counts. Retrieved 2026-09-25; the file installed is 100,789,629 bytes,
  sha256 `aa298951bb3707c2c2dd4e640679fd1c348eb9935d1ffa2ef4b89a567bac5204`. The
  dataset's own URL on the portal was not recorded at ingest; the next refresh records
  it here.
- Publisher: Virginia Department of Transportation.
- Licence: open data, no restrictions stated (PLAN.md, "Licensing").
- Records: docs/PLAYBOOK.md, "The three reference inputs"; docs/DEVELOPMENT.md,
  "Reference data".
- Dataset: **HMMS Traffic Signals (2023 Snapshot)** (v0.10.0), ArcGIS item
  `0d4c36cd061f4be280691d9ff6d36419`
  (<https://www.virginiaroads.org/datasets/0d4c36cd061f4be280691d9ff6d36419_0>), layer
  <https://services.arcgis.com/p5v98VHDX9Atv3l7/arcgis/rest/services/HMMS_Traffic_Signals_Flat_NEW/FeatureServer/0>,
  from VDOT's Traffic Engineering Division: "a snapshot of Traffic Signal data recorded in
  VDOT HMMS up through October 2023" (signal records have since left HMMS, so it is not
  updated). 3,153 records on 2026-10-19; `ASSET_SUBTYPE` Traffic Signal and Pedestrian
  Hybrid Beacon with `STATUS` Active are read, Intersection Flashers left out. **Report
  only** (`pipeline.agency_signals.REPORT_ONLY`): being stale, it marks nothing; the
  rebuild's `reports/agency-signals.csv` lists each signal OSM lacks as "would add", for
  comparison (the owner, 2026-10-19: "Since it's stale, just report it for comparison.
  It's likely OSM is better."). Licence: the item's VDOT disclaimer
  (sent by the owner 2026-10-19: use "at its own risk", "provided without any guarantee
  of accuracy, timeliness or completeness"), the portal's terms as for the counts above.
  Fetched at rebuild time; size and sha256: the download's README, to be copied here.

## Maryland traffic counts (MDOT SHA)

- Credit: `State of Maryland (MDOT SHA)`
- Dataset: **MDOT SHA Annual Average Daily Traffic (AADT)**, ArcGIS item
  `77010abe7558425997b4fcdab02e2b64`, layer 1 "MDOT SHA Annual Average Daily Traffic
  (AADT) Segments"
  (<https://services.arcgis.com/njFNhDsUCentVYJW/arcgis/rest/services/MDOT_SHA_Annual_Average_Daily_Traffic/FeatureServer/1>),
  also listed on Maryland iMAP. The stress tiers' Maryland counts where no other
  count reaches a road (FOLLOWUP-MDOT-AADT, OWNER-DECISIONS 429; first case MD 185,
  Connecticut Ave, from the DC line to MD 410, which the layer counts at 39,141 a day,
  OBJECTID 161492). The field `AADT` is the latest year, both directions together;
  the layer's description, read 2026-10-11, says it "is for the year 2024". Download
  approved by the owner for the v0.5.0 rebuild (2026-10-10); fetched at rebuild time
  with `scripts/fetch_agency_layer.py` (docs/OPERATIONS.md, "Maryland traffic counts
  (MDOT SHA)"), which records the size, sha256 and the item's licence text verbatim
  in the download's README. Downloaded for the v0.5.0 rebuild on 2026-10-11 at
  17:57 UTC, clipped to the coverage box: `mdot-sha-aadt.geojson`, 31,486,316 bytes,
  sha256 `494667299550afca312d20dfe47e4c62bdc45db92321fc231c11ba19182cb8e1`, 8,625
  features (the service reported 8,625; item modified 2026-08-27), installed as 8,625
  count lines.
- Publisher: Maryland Department of Transportation State Highway Administration
  (the item's `accessInformation` also names the Traffic Monitoring System team and
  Maryland iMAP).
- Licence: Maryland iMAP's terms, which PLAN.md ("Licensing") records verbatim: "The
  Data can be freely distributed as long as the metadata entry is not modified or
  deleted. Any data derived from the Data must acknowledge the State of Maryland in
  the metadata." The item's own `licenseInfo` (read 2026-10-11) is a disclaimer: the
  data is provided "AS IS" without warranty. So the credit names the State of
  Maryland, and the conditional arrangement in PLAN.md stands: every segment a
  Maryland count reached carries `volume_source = 'mdot-sha'`, and no published
  derivative exists that could carry it (none is built); one that is built must
  withhold those segments or wait for the waiver PLAN.md asks the owner to request.
- Records: the download's README; docs/DEVELOPMENT.md, "Reference data".

### Maryland Bicycle Level of Traffic Stress (MDOT SHA, v0.8.1)

- Credit: the line above, `State of Maryland (MDOT SHA)`; the road panel names "MDOT SHA"
  beside its level.
- Dataset: **Maryland Bicycle Level of Traffic Stress (LTS)** (2022), on Maryland's open
  data portal (item `fc3c7b650076475ba9a4b0232f6d8655`), downloaded with
  `scripts/fetch_agency_layer.py` as `mdot-lts`, clipped to the coverage box. Approved as
  a rating source (`routemaker.agency_lts.AGENCIES`, rank state: a county's rating wins).
  Field `LTS_ADJUSTED`, per MDOT's "Bicycle Level of Traffic Stress (LTS) Metadata and
  Methodology" (<https://www.mdot.maryland.gov/OPCP/MDOT_LTS_Metadata_Methodology_Full.pdf>);
  installed into `reference/agency-lts.json` by `scripts/install_agency_lts.py`
  (docs/OPERATIONS.md, "Agency stress ratings (agency-lts.json)"). Size and sha256: the
  download's README, to be copied here. Its 5 ("Bicycle access is prohibited by managing
  roadway agency") closes a road to bicycles (v0.9.1; the owner, 2026-10-19), and the
  road panel's Bike access row credits it to the line above.
- Publisher: Maryland Department of Transportation.
- Licence: Maryland iMAP's terms, as for the counts above; the download's README keeps
  the item's licence text verbatim.

### Maryland Scenic Byways (MDOT SHA, v0.8.0)

- Credit: the line above, `State of Maryland (MDOT SHA)`, on the map since v0.8.0; the
  road panel's Scenic row names "MDOT SHA".
- Dataset: **MDOT SHA Scenic Byways**, ArcGIS item `dc571b56e48a4f4292986c97a119e88a`
  (<https://www.arcgis.com/home/item.html?id=dc571b56e48a4f4292986c97a119e88a>), layer
  <https://services.arcgis.com/njFNhDsUCentVYJW/arcgis/rest/services/MDOT_SHA_Scenic_Byways/FeatureServer/0>,
  on Maryland iMAP. The Scenic layer's "`<name>` Scenic Byway" (a name that already ends
  in "Byway" is kept as it is), matched to the roads it lies along; never a stress input.
  Found 2026-10-16 (the v0.8.0 sources note); the service lists only JSON, so whether it
  answers `f=geojson` is unverified. Fetched with `scripts/fetch_agency_layer.py`, clipped
  to the coverage box (docs/OPERATIONS.md, "The Scenic layer (v0.8.0)"); not yet
  downloaded, so no size or sha256 yet.
- Publisher: Maryland Department of Transportation State Highway Administration.
- Licence: Maryland iMAP's terms, as for the counts above: "The Data can be freely
  distributed as long as the metadata entry is not modified or deleted." The download's
  README keeps the item's metadata unedited.
- Dataset: **MDOT SHA Traffic Signals** (v0.10.0), ArcGIS service
  `UtilitiesCommunication/TrafficSignals_Maryland_MDOTSHA`, layer 0
  (<https://gisportalapps.sha.maryland.gov/arcgis/rest/services/UtilitiesCommunication/TrafficSignals_Maryland_MDOTSHA/MapServer/0>),
  owned by the MDOT SHA Office of Traffic & Safety, updated weekly (Friday evenings).
  5,803 traffic control devices on 2026-10-19, 3,403 of them traffic control signals
  (`TCD_Type` 1, the only ones read as signals; `OWNER_DESC` Proposed left out); county and city
  signals included, none in Baltimore City. Marks the junctions at a Maryland signal OSM
  does not map as one (`pipeline.agency_signals`). Its Intersection Control Beacons
  (`TCD_Type` 2, 221) and Warning Beacons (`TCD_Type` 3, 674) are read too: a junction
  OSM maps with a signal at one is priced with no signal
  (`core.flashing_signals`; docs/OPERATIONS.md, "Flashing beacons"). Fetched at rebuild time; size and
  sha256: the download's README, to be copied here.
- Licence: Maryland iMAP's terms, as for the counts above. The layer is on SHA's own map
  server rather than iMAP and its `licenseInfo` is empty, as the counts' is; the same
  publisher (MDOT SHA OIT Enterprise Information Services), so the owner took it under the
  same terms (2026-10-19).

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

## City of Alexandria

- Credit: `City of Alexandria`
- Publisher: City of Alexandria, Virginia, GIS (ArcGIS organisation "City of
  Alexandria GIS", owner `AlexGIS_AlexGIS`), on the city's OpenData portal
  <https://cityofalexandria-alexgis.opendata.arcgis.com/>, linked from
  <https://www.alexandriava.gov/gis/open-data>.
- Licence: CC0 (City of Alexandria OpenData portal), confirmed by Alex311 reply
  2026-10-16, request 26-00041150: "Any of the data found on our OpenData portal is
  under the CC0 license and is allowed to be used for your application."
- Datasets:
  - **Transport Streets**, item `dccf9eda6b6c443b8133abf2542854b1`
    (<https://services2.arcgis.com/ChYV69FhfjwkvRmy/arcgis/rest/services/Transport%20Streets/FeatureServer/0>,
    modified 2026-04-07), retrieved 2026-10-01, sha256
    `5e8f8765cb368243cf9a231cc858f4951840050b9022222ec66c1e7306c8f1f0`. On the portal
    (<https://cityofalexandria-alexgis.opendata.arcgis.com/datasets/AlexGIS::transport-streets>,
    and in the group "Open Data Group for the City of Alexandria, Virginia"; checked
    2026-10-16). Its item licence field reads only "City of Alexandria, VA GIS", which
    is why it was internal comparison only until the city's reply (OWNER-DECISIONS
    153, 155). Used for: the posted speed (`SPEED_LIMIT`) of a street where OSM maps
    none (PLAN.md item 183; `agency_roads.parse_alexandria_transport_streets`). Its
    one-way record is not read.
  - **Bike Lane Routes**, item `74341781de91444a8f03620efc5c0514`
    (<https://services2.arcgis.com/ChYV69FhfjwkvRmy/arcgis/rest/services/Transit_BikeLaneRoutes/FeatureServer/0>),
    retrieved 2026-10-01, sha256
    `138de101daaee5074853d6e3d1648a4271e8ffdee5862a5fdbdff78dc2a914c5`; its item
    licence field is "cc0", and it is on the same portal. A cross-check of OSM's bike
    lanes (`reports/data-comparison/alexandria-bike-lanes-check.md`); nothing in the
    map is read from it.
  - **Smart Mobility Data**, layers 9 (signalised intersections, "Single point file
    representing intersections with signals throughout the city") and 0, which
    serve the same 257 intersections (2026-10-20); the HAWKs are the 4 whose
    `signal_type` is HAWK, the other 253 signals
    (<https://geoportal.alexandriava.gov/server/rest/services/Hosted/Smart_Mobility_Data/FeatureServer>),
    on the city's GIS portal. Marks the
    junctions at a city signal OSM does not map as one (v0.10.0;
    `pipeline.agency_signals`). Its item licence field is empty; the portal's CC0
    reply above covers it. Fetched at rebuild time; size and sha256: the download's
    README, to be copied here.
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
- Also (v0.8.0): **Rustic Roads**, ArcGIS item `0aa34f13d8fb4e4c9500e363ad5a4e07`
  (<https://www.arcgis.com/home/item.html?id=0aa34f13d8fb4e4c9500e363ad5a4e07>), layer
  <https://montgomeryplans.org/server/rest/services/Overlays/Rustic_Roads/MapServer/1>
  (lines, GeoJSON, 2,000 a request). `CLASSLABEL2` is "Rustic Road" or "Exceptional Rustic
  Road"; the Scenic layer and the road panel say "Rustic Road (Montgomery County)" or
  "Exceptional Rustic Road (Montgomery County)", matched to the roads the lines lie along;
  never a stress input. Licence, from the item (recorded in the v0.8.0 sources note, 2026-10-16;
  the download's README keeps it verbatim): "You can copy, modify,
  distribute, and perform analysis on the data, even for commercial purposes"; credit to
  Montgomery County Planning is requested, so the road panel's Scenic row names it and the
  map credit above stands. Not yet downloaded, so no size or sha256 yet (docs/OPERATIONS.md,
  "The Scenic layer (v0.8.0)").

## Scenic designations checked and left out (v0.8.0, 2026-10-16)

No credit: nothing from these is used.

- **Virginia Rural Rustic Roads**: VDOT's Rural Rustic Roads are a paving programme, not a
  scenic designation, and no statewide or county layer was found (Loudoun, Fauquier, Prince
  William, Fairfax and Clarke checked; absence unverified). Loudoun's Unpaved Roads item
  (`7e52417b213f439c887090c20d77a3cb`) has a disclaimer only, so reuse is unclear.
- **Virginia's Byways (VDOT)**, item `1ffabeb189414cb0a83bcd77056ebf34`: the disclaimer
  limits it to "official Commonwealth of Virginia business", and DCR's copy says
  "Copyrighted to VDOT. Permission for duplication is required". Left out without VDOT's
  written permission.
- **Frederick County draft rustic roads**
  (<https://services5.arcgis.com/o8KSxSzYaulbGcFX/arcgis/rest/services/Rustic_Roads/FeatureServer>):
  a draft with no licence; left out unless the county gives one.
- **WVDOT Byways & Backways**: no licence stated.

## USGS 3D Elevation Program

- Credit: `USGS 3DEP`
- Dataset: 3DEP one-arcsecond elevation tiles (<https://www.usgs.gov/3d-elevation-program>,
  fetched from `prd-tnm.s3.amazonaws.com` by the rebuild's ELEVATION stage); the
  climb, the effort model and the Hills slider. Retrieved by each rebuild's ELEVATION
  stage, which records the tiles and their dates in its run's log; never fetched on the
  development host (docs/OPERATIONS.md says why).
- Dataset: 3DEP 1/3 arc-second DEM (about 33 ft (10 m) a pixel), the four one-degree cells over the
  coverage (n40w078, n40w077, n39w078, n39w077) at
  <https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/> (listed 2026-10-11:
  370 to 500 MB each, last modified 2026-04-09 to 2026-05-12); the Topo lines map layer's contours,
  made by `scripts/build_contours.py` on the build host (docs/OPERATIONS.md, "Topo lines").
- Publisher: U.S. Geological Survey.
- Licence: U.S. public domain.
- Records: docs/OPERATIONS.md (the ELEVATION stage).

## U.S. Census Bureau

- Credit: `U.S. Census Bureau`
- Dataset: **TIGER/Line 2024 Urban Areas** (`tl_2024_us_uac20`, converted with
  `ogr2ogr -f GeoJSON -t_srs EPSG:4326`, installed as
  `<DATA_ROOT>/reference/urban-areas.json`); the stress tiers' urban and rural
  defaults (`routemaker.stress`). Retrieved 2026-09-25: `tl_2024_us_uac20.zip`,
  73,763,076 bytes, sha256 `efa943399ad65d81421167502732a0ee3774be663da499681b25e0b412cd81f9`;
  the GeoJSON made from it, 9,086,929 bytes, sha256
  `ee1aceeaa74792b95561276aff977deda81d75220b547a57cb2bf9c85a6b63c0`.
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

## Capital Bikeshare

- Credit: `Capital Bikeshare`
- Dataset: station information, station status, free-floating e-bike status, pricing plans and
  system alerts, from the operator's official GBFS 1.1 feed (discovery feed
  <https://gbfs.capitalbikeshare.com/gbfs/gbfs.json>, which lists the feeds on `gbfs.lyft.com`);
  the Bikeshare ride type's docks and bike counts and its lists of the nearest stations
  (`core.gbfs`, `core.bikeshare`); and, from v0.7.0, the docks and free e-bikes drawn on the map
  while their Layers switch is on (by default in the bikeshare ride types only), for the rider's map view only (`core.micromobility`, GET
  /api/bikeshare/docks: a bounded view, capped counts, no bike ids, nothing kept), a live
  display and not the data handed on as a dataset. Read live while a rider plans, about once a minute for the whole
  deployment, kept as one shared latest copy and never as history; there is no raw-file record and
  no sha256, because nothing is downloaded to keep. The sampled test fixtures
  (`tests/data/gbfs`) are a test sample, not a dataset.
- Publisher: Capital Bikeshare, operated by Lyft. Named in text only, as a factual description of
  where the data comes from: no logo, no wording of affiliation or endorsement
  (OWNER-DECISIONS 304, 466).
- Licence: the Capital Bikeshare Data License Agreement
  (<https://capitalbikeshare.com/data-license-agreement>, read 2026-10-04; the owner read it again 2026-10-09,
  OWNER-DECISIONS 300, 466). Non-exclusive, royalty-free, perpetual, any lawful purpose. It forbids
  hosting, distributing or selling the data as a stand-alone dataset, using the operator's marks
  without written permission, stating or implying affiliation or endorsement, data mining or other
  extraction, correlating the data with personal information, and access other than through the
  provided interface. No attribution is required: the credit is the owner's choice (item 301). The
  operator may terminate at will. Not legal advice.
- Not used: the operator's no-parking zones, which exist only inside its app (OWNER-DECISIONS 305);
  its undocumented map endpoints and its points values (OWNER-DECISIONS 451).
- Records: docs/OPERATIONS.md, "Bikeshare feeds"; docs/DEVELOPMENT.md, "Bikeshare".

## Other bikeshare and e-bike operators (left out)

Capital Bikeshare is the only service on the map and the only one routing uses
(`core.micromobility.OPERATORS`). The dockless e-bike operators in DDOT's and the counties' permit
programs were left out because neither has usable terms (the owner, 2026-10-15):

- Lime: its feed is internal-only; there is no public feed with terms to use.
- Veo: it publishes no data terms.

Neither is listed, fetched or shown, and the Layers sheet has no switch for either. Another
operator is added only once its public GBFS feed and its licence or terms have been read, the owner
has confirmed them (as for Capital Bikeshare), and a section for it is added here with its Credit,
Dataset and Licence lines; then it is listed with `licensed` set in `core.micromobility`
(tests/test_micromobility.py holds every licensed operator to its section here). A feed whose terms
do not allow display stays out.

## Work zones (WZDx: Maryland DOT SHA and VDOT)

- Citation: in the heads-up of each zone on a route, `Source: Maryland DOT SHA work zones (WZDx,
  CC0).` or `Source: VDOT work zones (WZDx, SmarterRoads).`, and in the answer's `work_zones.sources`;
  plain text, no logo, no wording of affiliation (OWNER-DECISIONS 301, 346). Not a line of the
  map's attribution, because most routes pass no zone.
- Dataset: the live Work Zone Data Exchange (WZDx) feeds, read by the worker about every five
  minutes and kept as one shared latest copy, never as history (`core.workzones`,
  `routemaker.workzones`); nothing is downloaded to keep, so there is no raw-file record and no
  sha256. Feeds, from the WZDx Feed Registry (datahub.transportation.gov, read 2026-10-11):
  - Maryland: <https://filter.ritis.org/wzdx_v4.1/mdot.geojson>, WZDx v4.1, refreshed every minute,
    no key.
  - Virginia: VDOT's WZDx v4 feed through SmarterRoads,
    `https://data.511-atis-ttrip-prod.iteriscloud.com/smarterRoads/workzone/workZoneJSON/current/workZone.json`,
    with the owner's key as `token` (`SMARTERROADS_TOKEN`, on the worker only). Off without it.
  The field names are WZDx v4.2's (<https://github.com/usdot-jpo-ode/wzdx>, read 2026-10-11). The
  proxy this was built behind reached neither feed, so the parser has been run on hand-made
  fixtures (`tests/data/workzones`) only; docs/OPERATIONS.md, "Work zones", has the first check.
- Publishers: Maryland Department of Transportation State Highway Administration (through RITIS);
  Virginia Department of Transportation (through SmarterRoads).
- Licence: Maryland's feed is CC0 (OWNER-DECISIONS 342(1)). VDOT's under the SmarterRoads Data
  Sharing Use Agreement, accepted by the owner (OWNER-DECISIONS 343, 346): the key stays on the
  server; polling about every five minutes; attribution notices kept, as a plain-text citation
  only; no name, logo or implied relationship; a work-zone disclaimer on the site; the planner
  says when the feed is unavailable; any public announcement about using VDOT data allows for
  VDOT's review. Not legal advice.
- Disclaimer (346), with every route that passes a zone: "Work zones are the transportation
  agencies' own data, read every few minutes. They may be out of date or wrong, and are not a
  guarantee the way is open or closed."
- Not used: VDOT's road closures, planned events, incidents and weather streams (347-349:
  follow-ups, FOLLOWUP-WORKZONES in PLAN.md). DC's TOPS permits, left out on 2026-10-11, came in
  with v0.7.0 (below, "DC closures").
- Records: docs/OPERATIONS.md, "Work zones".

## DC closures (v0.7.0: DDOT TOPS permits, MPD, AlertDC, NPS)

The WZDx registry has no DC feed, so DC's closures come from four sources (v0.7.0 plan, "DC
closures source"), read by the worker (`core.closure_sources`, `routemaker.dc_closures`) and
kept as one shared latest copy, never as history. They feed the same closure model as the work
zones: on the route's map (a red closed stretch, amber for a blocked bike lane, a park marker),
in the route's words, and in the closure check (`POST /api/closures/check`). None of the four
hosts was reachable from the cloud container this was built in; the readers were built on saved
sample pages (`tests/data/closures`), and docs/OPERATIONS.md, "DC closures", has the first check.

### DDOT occupancy permits (TOPS)

- Credit: `Road closures: DDOT (TOPS permits), CC BY 4.0`
- Dataset: "Occupancy Permits (via DDOT TOPS)",
  <https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/TOPS/MapServer/1> (data.gov record
  <https://catalog.data.gov/dataset/occupancy-permits-via-ddot-tops>; opendata.dc.gov item
  80216437707b4135963eeb95047caeac). Fields per DDOT's wiki
  (<https://ddotwiki.atlassian.net/wiki/spaces/GIS0107/pages/1875290657/Road+Closures>): Status,
  IssuedDate, ExpirationDate, IsRoadClosed, BikeLaneLength, CurbLaneLength, TravelLane1-4Length.
  Read every hour (DDOT refreshes it nightly); active permits only.
- Use: `IsRoadClosed` closes the block the permit's point is snapped to; `BikeLaneLength` > 0
  without a road closure is a "Bike lane blocked" warning, not a closure. Lane-only travel
  closures are ignored. DDOT's own limits: one point a permit, start and end times unreliable,
  NPS and Park Police closures often missing; the card says "Permit: road closed until Oct 20".
- Publisher: District Department of Transportation.
- Licence: CC BY 4.0 (confirmed by the owner, 2026-10-15 20:22 UTC). Not legal advice.

### MPD traffic advisories

- Credit: `MPD traffic advisories`
- Pages: the "TRAFFIC ADVISORY" releases in MPD's newsroom, <https://mpdc.dc.gov/newsroom>, read
  every 15 minutes. Only releases whose title says "Traffic Advisory" are fetched; every other
  release is passed over on its title and never read or kept. Each "X from A to B" under a time
  window becomes a closure on the ways of X between the cross streets; Emergency No Parking lists
  are skipped; a line that will not parse, or a street that cannot be found, is kept as text with
  the link under "Check before you go", never guessed.
- Publisher: Metropolitan Police Department, District of Columbia.
- Terms: public government releases (inferred public; not a licensed dataset). Not legal advice.

### AlertDC

- Credit: `AlertDC (HSEMA)`
- Feed: <https://trainingtrack.hsema.dc.gov/NRss> (the host name says "training" but it carries
  current alerts), read every 15 minutes. Only traffic and road items are read; every other alert
  type (crime first) is dropped before its text is read, and is never stored, logged or shown.
- Publisher: DC Homeland Security and Emergency Management Agency.
- Terms: public government alerts (inferred public). Not legal advice.

### NPS alerts

- Credit: `NPS alerts`
- API: <https://developer.nps.gov/api/v1/alerts>, parks rocr, nama, gwmp, choh and anac, read every
  30 minutes with the owner's key (`NPS_API_KEY`, on the worker only, sent as `X-Api-Key`; off
  without it). Alerts of category Park Closure, Danger and Caution; no geometry, so each is a
  park-level "Check before you go" notice with its link, never a closure.
- Publisher: U.S. National Park Service.
- Terms: NPS API terms of service (public domain U.S. government data). Not legal advice.

## Atkinson Hyperlegible (the panel's font; not a map credit)

This is a bundled asset, like maplibre-gl and Noto Sans, not a data source: it has no
`Credit:` line and is not in the map's credits (301 is about data sources;
`tests/test_credits.py` needs every `Credit:` line to be displayed). It is credited in
the shipped `licenses.txt`, which the map's "Software licences" link opens (384:
"credited in licenses.txt").

- What it is: the typeface the panel is set in (OWNER-DECISIONS 312, 384), self-hosted as
  `frontend/src/fonts/atkinson-hyperlegible-regular.woff2` (400) and
  `atkinson-hyperlegible-bold.woff2` (700), served as hashed `/assets/*.woff2` files.
- Publisher: Braille Institute of America, Inc. (copyright 2020).
- Licence: SIL Open Font License 1.1, the full text in `frontend/src/fonts/OFL.txt`
  (sha256 `f32d22b3908fcad2c86a74000614ec22e6a7f66ea7e867e616026a27aebdc143`) and, with the
  credit, in the built `licenses.txt` (the `licenceNotices` plugin,
  `frontend/src/licences/notices.mjs`). Font files, sha256:
  regular `d64ba838ef5472bba248620ec4fd8b5aa7cf0db2908e0bb230600caf279ba7bc`, bold
  `140e2bd25a7315c8a062508391426b0d8c3297400c947b8d847be28f73a199f0`.
- Records: docs/DEVELOPMENT.md, "The sidebar (312)", "The font".

## Atkinson Hyperlegible Next (the map's labels; not a map credit)

A bundled asset like Atkinson Hyperlegible above, credited in the shipped `licenses.txt`.

- What it is: the face every map label is set in (the owner, 2026-10-20): Regular (400) where the
  layers name Noto Sans Regular, SemiBold (600) for Noto Sans Medium and the street names, Italic
  (400) for Noto Sans Italic. MapLibre glyph files for the three Latin ranges, made with
  `scripts/make_map_glyphs.mjs` from the variable fonts (Version 2.001; sha256 upright
  `5a455d1cfa099b601ab70751bb9673e8fe1854dc4500c80e1a220d0d75e31745`, italic
  `ce9cffed32742ad2d9238c561a93220385e5934cdc02b8eb4097a50efa957dc6`) and bundled as
  `frontend/src/fonts/map-glyphs/atkinson-next-<face>-<range>.pbf`, served as hashed
  `/assets/*.pbf` files (`frontend/src/lib/mapGlyphs.ts`). Code points the font lacks in those
  ranges are filled from the base map's matching Noto Sans face (basemaps-assets, the commit
  `scripts/fetch_basemap.sh` pins), and other ranges are the base map's.
- Publisher: The Atkinson Hyperlegible Next Project Authors (copyright 2020-2024),
  https://github.com/googlefonts/atkinson-hyperlegible-next
- Licence: SIL Open Font License 1.1, the full text in `frontend/src/fonts/map-glyphs/OFL.txt`
  (sha256 `aca6a428580965d2297d1b718042dd427c2a9443ece3b0d02d758e161e0c4030`). Glyph files, sha256:
  - regular: 0-255 `6ed278792352ca425ac22636a42b3301b6d276302977f0293541852409f8baca`, 256-511
    `001a52f1b8e70d07f239f88f3c08a630dcb6c481be7f40baa4b35e123656268e`, 8192-8447
    `2b1fca09b8aa06fe3d4ba1cad2941a573b28be16e321413254e456c979e0ab3f`
  - semibold: 0-255 `35d921ecbcf66b3dbd22d8f3b477b0439e1964aad6e02f7d0ba6db04ed35de23`, 256-511
    `a1b1951c109b13efd912668ccfac033d23e1f9e4212cbf61f4c363cddbd6c519`, 8192-8447
    `9c672386bad4edf1bdc08667f7afa9e2e09937cf04a39f148b035323fc10aa2f`
  - italic: 0-255 `59c8fd80148386ba0eb39be4638da48084586872d0b6a81288f5c2cb75fbcf8c`, 256-511
    `c800e0c0e1b4d296ab019a697f40ef3b13d6c2119e8d0db1688cabf5a420deaa`, 8192-8447
    `1ded461996e956998dea030e91d4467aae85637c1f18b727f481903e4bff73f8`
- Records: docs/DEVELOPMENT.md, "The map's label font".

## Helvetica character widths (the PDF cue sheets; not a map credit)

Not a data source and no `Credit:` line: a table of numbers the PDF writer lays text out with.
No font is bundled or embedded; the cue sheets name the PDF standard fonts Helvetica and
Helvetica-Bold, which every PDF reader supplies.

- What it is: the advance widths of WinAnsi codes 32 to 255 in Helvetica and Helvetica-Bold, in
  `frontend/src/lib/pdf.ts` (`HELVETICA`, `HELVETICA_BOLD`), so lines wrap where the reader's
  font will break them.
- Publisher: Adobe Systems, the Core 14 AFM metrics (`Helvetica.afm`, `Helvetica-Bold.afm`):
  "Copyright (c) 1985, 1987, 1989, 1990, 1997 Adobe Systems Incorporated. All Rights Reserved."
  Helvetica is a trademark of Linotype-Hell AG and/or its subsidiaries. Copied 2026-10-16 from the
  same figures as ReportLab 5.0.1 carries them (`reportlab/pdfbase/_fontdata_widths_helvetica*.py`,
  BSD), indexed by its WinAnsi table.
- Licence: Adobe's notice accompanying the Core 14 AFM files reads: "This file and the 14
  PostScript(R) AFM files it accompanies may be used, copied, and distributed for any purpose and
  without charge, with or without modification, provided that all copyright notices are retained;
  that the AFM files are not distributed without this file; that all modifications to this file or
  any of the AFM files are prominently noted in the modified file(s); and that this paragraph is not
  removed or modified." Only width figures derived from the AFM files are reproduced here (two
  arrays of numbers, re-indexed by WinAnsi code), not the AFM files themselves; Adobe's copyright
  line is kept here and in a comment above the arrays in `pdf.ts`.
- Records: docs/DEVELOPMENT.md, "PDF cue sheets".

## Noto Emoji skull and crossbones (the Avoid-rated junction marker; not a map credit)

A bundled asset, like the panel's font, not a data source: no `Credit:` line and not in the
map's credits (301 is about data sources). It is credited where the font is, in the shipped
`licenses.txt`, which the map's "Software licences" link opens.

- What it is: the skull and crossbones (U+2620) the Avoid-rated junction marker draws on a
  ringed disc (FOLLOWUP-ISECT-AVOID, OWNER-DECISIONS 309, 310), inlined into the page from
  `frontend/src/icons/noto-emoji-u2620.svg` (nothing is fetched at run time). The junction
  list, the notice and the description use the Unicode character itself (310); the legend has
  no row for it (the owner, 2026-10-10).
- Publisher: Google (Noto Emoji, <https://github.com/googlefonts/noto-emoji>).
- The one file downloaded, with the owner's approval of 2026-10-10 13:57 UTC: `2D/svg/emoji_u2620.svg`
  at commit `e20cbc2bbec1926686be9f9bee7d1d2cfa1fea0e` (the repository's `main` that day),
  <https://raw.githubusercontent.com/googlefonts/noto-emoji/e20cbc2bbec1926686be9f9bee7d1d2cfa1fea0e/2D/svg/emoji_u2620.svg>,
  retrieved 2026-10-10. The repository now keeps its SVGs under `2D/svg/`; `svg/emoji_u2620.svg`,
  the path first named, answers 404 at that commit. 8,320 bytes, sha256
  `4baff1c033110775d495b6fe6da05a7bdf94452af12f8a9207c00de28364535e`, committed unmodified.
- Inspected before use (downloaded into an empty directory first): an Adobe Illustrator export
  of `<svg>`, `<g>`, `<path>` and `<ellipse>` with inline fills only; no script, no event
  attribute, no link or `href`, no external reference (the only URLs are the SVG and XLink
  namespace names). `frontend/src/lib/avoidJunctions.test.ts` holds the sha256 and these checks.
- Licence: Apache License 2.0. The repository's README says its "Tools and most image
  resources are under the Apache license, version 2.0" and its fonts under the SIL Open Font
  License; the root `LICENSE` file at that commit is the OFL text (for the fonts), and the SVG
  directory's own `2D/svg/LICENSE` is the Apache 2.0 notice ("Copyright 2013 Google, Inc. All
  Rights Reserved. Licensed under the Apache License, Version 2.0 ..."), which governs this file.
  That notice, verbatim, is `frontend/src/icons/NOTICE-noto-emoji.txt`; the full licence text is
  `frontend/src/icons/LICENSE-Apache-2.0.txt` (the standard text, sha256
  `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`, taken from the build host's
  `/usr/share/common-licenses/Apache-2.0`, not downloaded). Both are added to `licenses.txt` by
  the `licenceNotices` plugin (`frontend/src/licences/notices.mjs`, `BUNDLED_ICONS`).
- Records: `fixtures/icons/README.md`; docs/DEVELOPMENT.md, "Avoid-rated junctions".

## The Mass Ride flow model (literature checked; video check pending: FOLLOWUP-FLOW-CALIBRATION)

- Credit: on the chart's source line, "Riders per minute: estimated from road widths (in
  DC, DC Open Data, Roadway Block, CC BY 4.0, adapted; elsewhere OpenStreetMap) and DC
  Bike Party counts; indicative (level roads about ±25%; hill adjustment not yet
  checked)." The chart reads the segment's usable width (`mass_usable_width_m`), which in
  DC is the District Department of Transportation's Roadway Block (above) and elsewhere
  OpenStreetMap's lanes and widths; the DC Bike Party counts are the owner's (PLAN item 173).
- What: `routemaker.flow`, the riders-a-minute figure of the Mass Ride route chart
  (OWNER-DECISIONS 328, 332) and of the capacity map (387 part 1).
- The named corridors' ratings (`fixtures/corridors/`): North Capitol Street (OWNER-DECISIONS
  284, 286, 295, 296), Connecticut Avenue NW R St to Calvert St (408, 409, 411, 413) and
  South Capitol Street, Martin Luther King Jr Ave SE to Mississippi Ave SE, LTS 4 (432:
  "There's no other routes through there"; its axis is DC Open Data's Roadway Block centre
  line, CC BY 4.0) are the owner's own local knowledge, cited by decision in each file; not a
  published source.
- The curated bike lanes (`fixtures/bike_lanes/`): Veirs Mill Road's painted lane (OWNER-DECISIONS
  433, "Yes, it should be marked") is the owner's own local knowledge, cited by decision in the
  file, until it is mapped in OpenStreetMap; not a published source.
- The military areas the rebuild closes to bicycles (`pipeline.restricted_areas`) are
  OpenStreetMap's own `landuse=military` and `military=*` polygons (© OpenStreetMap
  contributors, ODbL), read from the same extract as the ways.
- Basis: the level figure (0.37 riders/m2, a utilisation of 0.7, 1.9 m/s) rests on the
  owner's counts of three DC Bike Party rides (PLAN item 173,
  `reports/owner/cyclist_packing_density.md` (not in the repository)), indicative, good to about ±25% (item
  175). The grade factors (the climb's 12 per unit of grade above 1%, the 150 m
  set-in, the descent's 5 per unit past 4%, the 30% and 60% floors) are not from a
  measurement; the climb factor agrees with Parkin and Rotheram (2010) up to about 6%
  (below), and no source was found for the descent.
- Status: accepted as the working model (OWNER-DECISIONS 394). FOLLOWUP-FLOW-CALIBRATION's
  literature half is done (below, and [FLOW-CALIBRATION.md](FLOW-CALIBRATION.md) for
  each constant, its range and the recommendation); no constant was changed. The
  owner's DC event videos, the other half, are pending.

### The Mass Ride flow model: literature checked

Read for FLOW-CALIBRATION.md (2026-10-10). Bicycle traffic, not mass rides: no rigorous
study of a Critical Mass or Bike Party ride was found. Figures are as published; the
per-foot conversions are on FLOW-CALIBRATION.md.

- Guo, N., Jiang, R., Wong, S. C., Hao, Q.-Y., Xue, S.-Q. and Hu, M.-B. (2021).
  "Bicycle flow dynamics on wide roads: Experiments and simulation." *Transportation
  Research Part C* 125, 103012. https://doi.org/10.1016/j.trc.2021.103012 (preprint read:
  https://arxiv.org/abs/1904.06084). 100 riders on a 10 ft (3 m) wide ring track. "The
  flow rate then becomes almost constant until the density reaches 0.50 bicycles/m²";
  free flow below 0.17/m²; "The density in the jam is around ρ1 =0.8 bicycles/m²";
  the moving ("go") flow inside the stop-and-go waves of its densest run "~0.55
  bicycles/s/m" (the paper gives no single plateau figure); "The maximum speed of a bicycle is around 15
  km/h." Used for: density, pace and the level figure.
- Guo, N., Wong, W., Jiang, R., Wong, S. C., Hao, Q.-Y. and Wu, C.-Y. (2024). "Bicycle
  Flow Dynamics of Cyclist Loading and Unloading Processes at Bottlenecks."
  *Transportation Science* 58(2), 340-354. https://doi.org/10.1287/trsc.2023.0193 (read:
  https://hub.hku.hk/bitstream/10722/342964/1/content.pdf). An exit width of 4.9 ft
  (1.5 m) on a 10 ft (3 m) track, 80 riders; capacity "approximately 1.15 cyclists/s" unloading
  and "approximately 1.3 cyclists/s" loading; critical densities "approximately 0.125"
  and "0.2 cyclists/m2"; congested speed "approximately 0.8 m/s"; "a common desired
  speed of about 3.8 m/s". Used for: compression, density, pace.
- Wierbos, M. J., Knoop, V. L., Hänseler, F. S. and Hoogendoorn, S. P. (2019).
  "Capacity, Capacity Drop, and Relation of Capacity to the Path Width in Bicycle
  Traffic." *Transportation Research Record* 2673(5), 693-702.
  https://doi.org/10.1177/0361198119840347. Delft, 34 riders, bottlenecks 1.6 to 4.9 ft
  (0.50 to 1.50 m). "The reported capacity values show a large range between 2,600 and 8,100 bicycles
  per hour"; "For an additional meter of path width ... the capacity increases by 1.11
  cyc/s"; "the flow rate drops 0.45 cyc/s when the cycling conditions change from free
  flow to congested." Used for: the level figure's range, compression.
- Kaths, H., Roosta, A., Fischer, J., Kathmann, T. and Pušica, A. (2025). "Mapping
  Bicycle Traffic Flow Across the Width of a Bicycle Path to Inform Facility Design."
  *Transportation Research Record*. https://doi.org/10.1177/03611981251353715. Its Table 1
  lists capacities per metre of width: experiments ~4,500 (Navin), ~3,600 (Zhang et al.),
  ~2,000 (Wierbos, 1 m path; Kaths' source for this is Wierbos' 2021 PhD thesis, not
  read), ~1,800 (Guo et al.); field 1,500 (Greibe and Buch), 1,531
  (Hoogendoorn and Daamen). Density "built first on the right-hand side"; "Only very low
  densities occurred on the far left-hand sublane." Used for: the level figure's range
  (Navin, Zhang and Hoogendoorn and Daamen are cited from this table only; their papers
  were not read), utilisation.
- Buch, T. S. and Greibe, P. (2014). *Bredde af cykelstier: Analyse af adfærd og
  kapacitet* (Width of cycle tracks: analysis of behaviour and capacity). Trafitec, for
  the Danish Cykelpuljen.
  https://trafitec.dk/wp-content/uploads/2023/05/183-Bredde-af-cykelstier-Analyse-af-adfaerd-og-kapacitet-Baggrundsrapport.pdf.
  Eight Copenhagen one-way tracks, 5.7 to 9.4 ft (1.73 to 2.85 m). "Kapaciteten for en 2,0 meter bred sti
  (ekskl. kantsten) er ca. 3.000 cykler pr. time" (about 3,000 an hour on a 6.6 ft (2.0 m) track);
  mean speed 13.5 mph (21.7 km/h); second rider abreast with the front wheel 4.3 to 6.1 ft (1.30 to 1.85 m) from the kerb; a third
  abreast "Kun i få tilfælde og kun på de fire bredeste stier" (only in a few cases, and
  only on the four widest tracks). Used for: the level figure, utilisation, pace.
- Seriani, S., Fernández, R. and Hermosilla, E. (2015). "Experimental study for
  estimating capacity of cycle lanes." *Transportation Research Procedia* 8, 192-203.
  https://doi.org/10.1016/j.trpro.2015.06.054. Saturation flow 2,070 bicycles/h on a 3.3 ft (1.0 m)
  and 4,657 on a 6.6 ft (2.0 m) cycle track (Santiago), 4,320 on 3.3 ft (London, Tavistock Square);
  "the saturation flow grows almost linearly with the width." Used for: the level figure.
- Yuan, Y., Goñi-Ros, B., Poppe, M., Daamen, W. and Hoogendoorn, S. P. (2019). "Analysis
  of Bicycle Headway Distribution, Saturation Flow and Capacity at a Signalized
  Intersection using Empirical Trajectory Data." *Transportation Research Record*
  2673(6), 10-21. https://doi.org/10.1177/0361198119839976. Amsterdam, a 6.6 ft (2 m) path:
  saturation flow 4,376 to 4,626 cyc./h. Used for: the level figure, compression at signals.
- Federal Highway Administration (1998). *Capacity Analysis of Pedestrian and Bicycle
  Facilities: Recommended Procedures for the "Bicycles" Chapter of the Highway Capacity
  Manual.* FHWA-RD-98-108.
  https://www.fhwa.dot.gov/publications/research/safety/pedbike/98108/chapter2.cfm and
  chapter3.cfm. "A "lane" for bicycles ... is considered to be approximately 1.0 m (3.3
  ft)"; lanes up to 1.8 m (6 ft) "will operate with two effective lanes"; "a saturation
  flow rate of 2,000 bicycles/h of green be used as an average value"; "The ideal
  saturation flow rate may be as high as 2,600 bicycles/h of green"; path speeds "a mean
  of 18 km/h (11.2 mi/h)". Used for: the level figure, utilisation, pace.
- Parkin, J. and Rotheram, J. (2010). "Design speeds and acceleration characteristics of
  bicycle traffic for use in planning, design and appraisal." *Transport Policy* 17(5),
  335-341. Read: https://uwe-repository.worktribe.com/OutputFile/987474. "on the flat, the
  mean speed of cyclists is 6.01 m/s (21.6 kph)"; "for every additional 1% of uphill
  gradient, the mean speed is reduced by 0.4002 m/s"; downhill "increased by 0.2379 m/s".
  Used for: the climb and descent factors.
- Attalla, S., Robertson, R. and Kodsi, S. (2015). "Cyclist's Choice of Speed, Radius and
  Lateral Acceleration While Negotiating a Curve: A Closed Course Pilot Study." *Accident
  Reconstruction Journal*, 19-21.
  https://jsheld.com/uploads/Cyclists-Choice-of-Speed-Radius-and-Lateral-Acceleration-While-Negotiating-a-Curve.pdf.
  42 riders, each riding alone. Speed in the turns 6.6 mph (10.6 km/h), radius 12.8 ft (3.9 m), lateral acceleration 0.23 g. Used for: pace
  at turns (a small pilot).
- National Association of City Transportation Officials. *Urban Street Design Guide*,
  "Lane Width."
  https://nacto.org/publication/urban-street-design-guide/street-design-elements/lane-width/.
  "Lane widths of 10 feet are appropriate in urban areas"; "Lanes greater than 11 feet
  should not be used"; "Parking lane widths of 7–9 feet are generally recommended." Used
  for: the lane, parking and wide-lane width rules (OWNER-DECISIONS 404, 407).
- National Cooperative Highway Research Program (2014). *Recommended Bicycle Lane Widths
  for Various Roadway Characteristics.* NCHRP Report 766. National Academies Press.
  https://doi.org/10.17226/22350 (read: the report PDF as NACTO hosts it,
  https://nacto.org/wp-content/uploads/Part-III-Section-2-Citation-19_-NCHRP-766-1.pdf).
  Summary, p. 3, design guidance item 5: "the open door zone width of parked vehicles
  extends approximately 11 ft from the curb", "assuming the 95th-percentile parked
  vehicle displacement and an open door width of 45 in". Summary, p. 2, design guidance
  item 3: "In most situations where a bicycle lane is adjacent to on-street parking, the
  suggested width for the parking lane is 8 ft". Used for: the door zone and
  parking width (OWNER-DECISIONS 404 (1), 407 (1) and (2)).

## Transit timetables (GTFS) and bike rules (TRANSIT-ASSIST)

The two transit ride types, Own Bike + 🚆🚌 and Bikeshare + 🚶🚆🚌, plan from each system's
published static GTFS timetable. The times are scheduled, and every plan says "about" and
"scheduled", except a Metro or Metrobus departure WMATA predicts on a plan for now, which says
"live" (WMATA's live data, below). Each plan names its sources under its steps, so these are plan credits and not
map credits:

- Credit: WMATA GTFS (scheduled times). Shown with a plan that uses Metro or Metrobus.
- Credit: WMATA, wmata.com (typical service). Shown with a plan that uses Metro on its typical
  timetable (below).
- Credit: MDOT MTA GTFS (scheduled times). Shown with a plan that uses MARC, Light RailLink or
  Metro SubwayLink.
- Credit: VRE GTFS (scheduled times). Shown with a plan that uses VRE.
- Credit: Data: WMATA. Shown with every live value (v0.7.0, below): a Metro station card's next
  trains, an elevator out, a rail incident, and a plan's live lines.

### WMATA live data (v0.7.0; Metrobus and vehicle positions v0.9.0)

- **Data:** WMATA's developer API, <https://developer.wmata.com/>: `Rail.svc/json/jStations`
  (stations, codes and points; read once a day), `StationPrediction.svc/json/GetPrediction/All`
  (next trains), `Incidents.svc/json/Incidents` (rail incidents) and
  `Incidents.svc/json/ElevatorIncidents` (elevators and escalators out). From v0.9.0, for
  Metrobus: `NextBusService.svc/json/jPredictions?StopID=<7-digit stop id>` (a stop's next buses,
  by route and direction, each with its bus), `Bus.svc/json/jStops?Lat=&Lon=&Radius=` (the stops
  near a point, with WMATA's StopID and their routes) and `Bus.svc/json/jBusPositions?RouteID=`
  (a route's buses and their points); and for where Metro's next train is,
  `TrainPositions/TrainPositions?contentType=json` (each train's track circuit, line and
  direction) and `TrainPositions/StandardRoutes?contentType=json` (each line's circuits in order
  along each track, the station named at a station's circuits; read once a day).
- **The bus stop.** The installed timetable keeps no GTFS stop code: a bus stop there is a name and
  a point (`scripts/build_transit_schedule.py`), and carrying WMATA's 7-digit StopID would need
  the schedule file rebuilt. So the boarding stop is found by its point: `jStops` within 120 m,
  the nearest stop within 60 m that the step's route serves (WMATA's variants, "52v1", count as
  the timetable's "52"). Each point's answer is kept a day.
- **Terms:** WMATA Transit Data Terms of Use, <https://developer.wmata.com/license>. A developer
  key is required (`WMATA_API_KEY` on the server, the same key as the static GTFS fetch); it is
  sent only in WMATA's `api_key` header, never in a URL, a log line or a page (a URL whose query
  names a key is refused before it is sent; a log line names the path, never the query). Limits:
  10 calls a second, 50,000 a day. RouteMaker's calls, all only while someone is asking:
  - Metro's reading: at most three calls every 45 s (5,760 a day), shared by every worker.
  - Train positions: at most one call every 20 s (4,320 a day), shared by every worker, and only
    while a rider is waiting at a Metro boarding; the standard routes once a day.
  - Metrobus (next buses, stops, bus positions): every call counted deployment-wide in one row of
    `bikeshare_feed_cache` (key `wmata-budget`), at most 18 a minute (25,920 a day) and 4 a second;
    a call over that is not made, and nothing live is shown for it. A plan asks only for its
    chosen trip's bus steps, at most 4 stops, at once, and waits for them at most 1.5 s. Each
    stop's next buses are kept 40 s and each route's bus positions 20 s in each worker.
  - **Worst case:** about 36,000 calls a day and 9 a second (3 + 2 + 4), under WMATA's 50,000
    and 10, however many riders and workers. A rider waiting at a boarding asks the server
    every 25 s (Ride mode, GET /api/transit/next-vehicle), and stops when they board or leave.
- **Kept:** the latest reading only, one row of `bikeshare_feed_cache` (key `wmata`), replaced
  in place; no history. The train positions likewise (key `wmata-trains`); the call count's
  row holds this minute's and this second's counts only (key `wmata-budget`). Bus answers are
  kept in each worker's memory for under a minute (a stop's place, a day), never stored.
- **Shown:** each live time says "live", each timetable time "scheduled"; with no reading the
  timetable is shown alone. On a plan for now (within 2 minutes, a reading under 3 minutes old),
  a Metro step boards WMATA's next train its line and way that the rider reaches the station in
  time for, and on the chosen trip a Metrobus step its next bus (v0.10.0): the wait is to that
  train or bus and the step says "live"; the time on board stays the timetable's, since WMATA
  predicts arrivals at the boarding station only. A step with no such prediction keeps its
  timetable time. An elevator out where a rider takes their own bike is a warning
  ("Elevator out at X: carry your bike on the stairs."), never an avoidance; it costs the trip 2
  minutes in the ranking only. A Metrobus step adds its route's next buses its way, as a Metro
  step adds its trains: "Live: bus 52 in 4 min, 13 min." (the way: the stop's only one for the
  route, or where it sees both, the one whose compass word, "North to ...", is nearest the
  step's heading). While a rider waits at a Metro or Metrobus boarding in Ride mode, where the next
  one is: "Next Red Line train is at Dupont Circle, 2 stations away." (WMATA gives trains no map
  point: the train is placed by its circuit between the stations, and marked at the station or
  halfway between the two) or "Bus 52 is 0.8 mi away (1.3 km), 3 stops back." (the bus by its
  VehicleID from the next-bus answer; the stops back from the timetable's stop sequence, else the
  distance alone), with a mark on the map named in the same words. Every value: "Data: WMATA".
- Code: `src/core/wmata_live.py`, `src/core/transit_live.py`, `src/core/wmata_bus.py`,
  `src/core/wmata_trains.py`; fixtures shaped as WMATA documents the answers in
  `tests/data/wmata/`.

### MDOT MTA and VRE real-time feeds (checked 2026-10-15, not used)

Public GTFS-Realtime feeds exist, but the build environment cannot reach them and their terms are
not yet checked, and reading Protocol Buffers needs a dependency the project does not declare. Not
built in v0.7.0; listed so they can be added:

- MARC trip updates and vehicle positions:
  `https://mdotmta-gtfs-rt.s3.amazonaws.com/MARC+RT/marc-tu.pb` and `.../marc-vp.pb` (no key).
- MDOT MTA service alerts, every mode: `https://feeds.mta.maryland.gov/alerts.pb`.
- MTA Light RailLink, Metro SubwayLink and buses: real-time is published through MTA's developer
  page (<https://www.mta.maryland.gov/developer-resources>); the URLs were not listed publicly.
- VRE trip updates: `https://gtfs.vre.org/containercdngtfsupload/TripUpdateFeed`
  (Mobility Database `tld-1127-tu`).

### Metro's typical timetable (until WMATA's rail GTFS is built)

WMATA's GTFS needs a developer key; this is the fallback when no WMATA rail GTFS is built. The owner, 2026-10-12:
"Just use defaults. The wmata website has a typical timetable for rail." and "Rail is so frequent
that it's not a major issue. It's bus where the API helps." Until a schedule with WMATA's rail GTFS
is built, Metro runs on `src/core/transitdata/metro-typical.json`. Once one is built, it replaces
the typical timetable automatically. Metrobus stays out until its GTFS is built, and plans say
nothing about it. The file holds facts and a documented estimate, not WMATA data files, so it is
committed. No WMATA GTFS is committed.

- **Opening hours and trains per hour.** Each line's page on wmata.com, read 2026-10-12:
  <https://www.wmata.com/ridertools/line/red/info>, and `.../orange/info`, `.../blue/info`,
  `.../green/info`, `.../yellow/info` and `.../silver/info`.
  - Hours, every line: Monday to Thursday 5:00 am to 12:00 am; Friday 5:00 am to 2:00 am;
    Saturday 6:00 am to 2:00 am; Sunday 6:00 am to 12:00 am.
  - Bands: weekdays open to 7 am, 7 to 9 am (AM rush), 9 am to 4 pm, 4 to 6 pm (PM rush), 6 to
    9:30 pm, and 9:30 pm to close; Saturday and Sunday open to 9:30 pm, and 9:30 pm to close.
  - Minutes between trains, as published: Red 6, rush 4-5, late night 10 (weekends 6 and 10).
    Orange, Blue and Silver 12, rush 9-10, late night 15 (weekends 12 and 15, except Orange on
    Sunday late night, which its page gives as 10). Green and Yellow 6, weekday late night 7-8
    (weekends 8 all day). "Every 4-5 min" is used as every 4.5 min.
  - A federal holiday uses the Sunday hours and frequency. This is an assumption: WMATA publishes
    each holiday's service separately (wmata.com, "Holiday and event schedules").
- **Branches.** Half of the Silver Line's trains run to New Carrollton and half of the Yellow
  Line's to Greenbelt. These are the same WMATA announcements the map cites in
  `frontend/src/rail-data/metro-line-corrections.json`. The typical timetable alternates each
  line's trains between its two ends.
- **Stations.** The map's 98 Metro stations (`frontend/src/rail-data/`, sources above in that
  folder's README), each with the bike entrance the GTFS build picks. A test holds them equal to
  `scripts/build_transit_schedule.py`'s `metro_stations()`.
- **Run times between stations: an estimate.** wmata.com's line pages give no run times, and the
  station pages give only live arrivals. Each hop is the straight-line distance between the two
  stations' map points at 33 mph (53 km/h), Metro's average speed including stops ("All trains
  have a maximum speed of 75 mph (121 km/h), and average 33 mph (53 km/h), including stops.",
  <https://en.wikipedia.org/wiki/Washington_Metro>, citing WMATA's Metro facts). Each hop is at
  least 90 s, so a short downtown hop still counts its stop, and is rounded to the nearest 10 s.
  Red, Shady Grove to Glenmont, comes to about an hour.
- **What the rider sees.** The wait is half the published interval, or the time to the first or
  the last train. No Metro departure is named or counted down. The step says "every 6 min,
  scheduled", the same word as a timetable's, and the plan's credit line names the source:
  "WMATA, wmata.com (typical service)".

The feeds, and the compact file built from them (`transit-schedule.json`), stay on the host. They
are never committed (see the terms below). The tests use a small fixture invented for the purpose
(`tests/data/transit/make_fixture.py`), which holds no agency data. Fetch and build steps:
docs/OPERATIONS.md, "Transit schedule". Systems, rules and sources are listed in one file:
`src/core/transitdata/systems.json`.

### In use (v0.6.0)

- **WMATA Metrorail and Metrobus.** Feeds:
  `https://api.wmata.com/gtfs/rail-gtfs-static.zip` and `.../bus-gtfs-static.zip`. Both need a
  developer key (<https://developer.wmata.com/signup/>). The key is read from `WMATA_API_KEY` on
  the host only and is never committed or printed.
  - Terms: WMATA Transit Data Terms of Use (<https://developer.wmata.com/license>). The data is used
    in the app under those terms. Redistributing the raw feeds is not assumed, so they are not
    committed (owner question 1 in the design note).
  - Bike rules, Metrorail: <https://www.wmata.com/ride/guides/bikes/bikes-on-rail.html>. Bikes are
    allowed at all hours. Use the elevators (never escalators), board at a car's end doors, at most
    four bikes a car. Metro may restrict bikes during special events or crowding.
  - Blackout dates: July 4 every year, plus dates added by hand in
    `src/core/transitdata/metro-bike-blackouts.json`. The owner: bikes are allowed "at all times
    except" those days, so on them Own Bike + 🚆🚌 uses no Metro and says "Bikes aren't allowed
    on Metro today (July 4)." Bikeshare + 🚶🚆🚌, on foot, still rides Metro.
  - Bike rules, Metrobus: <https://www.wmata.com/ride/guides/bikes/bikes-on-bus.html>. Each bus has
    a front rack for two bikes.
  - What a plan says, once per system it takes a bike on (systems.json `bike.rule`, one short
    line; the owner, 2026-10-12: "We need to streamline over bloat."): Metro "Use the elevators and
    a car's end doors."; Metrobus "Use the front bike rack."; MARC "Ride in the car marked for
    bikes."; Light RailLink and Metro SubwayLink "Use the elevators; ride in the priority seating
    area."; VRE "Board last; bungee it to a car's south-end bench."
- **MDOT MTA: MARC, Light RailLink and Metro SubwayLink.** Feeds:
  `https://feeds.mta.maryland.gov/gtfs/marc`, `.../light-rail` and `.../metro`. No key is needed.
  - Terms: the developer page (<https://www.mta.maryland.gov/developer-resources>) states no
    licence. The site's terms (<https://www.mta.maryland.gov/terms-conditions>, read 2026-10-12) do
    not address redistribution. The feeds are treated as not committable (owner question 1).
  - Bike rules, MARC: <https://www.mta.maryland.gov/MARCbikes>. Full-size bikes are allowed on every
    MARC train on all three lines. Ride in a car marked with the green Bicycle Entrance decal or
    light, one bike each, and bring two bungee cords. If the racks are full, wait for the next
    train.
  - Bike rules, Light RailLink and Metro SubwayLink: <https://www.mta.maryland.gov/bike>. Bikes are
    allowed at most two a vehicle, in the priority seating area. Use the elevators, never the
    escalators. On a train crowded at rush hour, riders wait for the next one: that is advice, not a
    ban.
    - Applied as every trip takes a bike. The owner, 2026-10-12: "In general the rule is that you
      can use it unless it's too crowded to do so. No API knows how many people can fit." There is
      no crowding model and no crowding note ("It's common courtesy.").
    - Every MARC, Light RailLink and Metro SubwayLink station takes a bike. The owner, 2026-10-12:
      "I believe all stations have ways to board with either ramps or elevators. Most people can
      carry bikes up and down stairs in a pinch." GTFS `wheelchair_boarding` is not read. Each
      system's own rule above (which trains or cars, how many bikes) still applies.
- **VRE (Virginia Railway Express): the Fredericksburg and Manassas Lines.** Added 2026-10-12 (the
  owner: "The VRE timetable can be added"). Feed:
  `https://gtfs.vre.org/containercdngtfsupload/google_transit.zip`, as VRE's mobile developer page
  gives it (<https://vre.org/assets/1/6/VRE_Mobile_Developer_2024.pdf>, read 2026-10-12). No key is
  needed.
  - Terms (the same page): the site and its feeds and databases are VRE's property, "for your
    personal, non-commercial use", and "You may not reproduce, redistribute, or frame VRE website
    content without express written permission in advance from VRE." Queries to its data feeds are
    allowed. No attribution is required; the plan credit above is given all the same. The feed and
    the schedule built from it stay on the host and are never committed (owner question 1).
  - Bike rules: <https://www.vre.org/about/onboard-policies/> (Baggage/Bicycles, read 2026-10-12).
    "Full-size and collapsible bicycles are allowed on all trains." Tether the bike with a bungee
    cord to the bench seats at a car's south end (the north-end bench is priority seating); bikes
    board and leave last, after everyone else; check with the conductor. Applied as every trip
    takes a bike (`vehicle` all).
  - Every VRE station takes a bike (the owner's rule for commuter rail, as MARC above).
  - The feed's route short names are numbers (2, 4), so a step names a line by its long name
    ("the VRE Manassas Line"; systems.json `route_name` long).

### Checked, for the next PR (not used yet)

Unclear bike access counts as closed for a rider with their own bike. A walk to or from a stop
needs no bike access.

- **MTA Local and CityLink buses** (`https://feeds.mta.maryland.gov/gtfs/local-bus`).
  <https://www.mta.maryland.gov/bike>: a front rack for two bikes, no bikes inside. The feed terms
  are as for MARC above.
- **MTA Commuter Bus** (`https://feeds.mta.maryland.gov/gtfs/commuter-bus`). The bike page does not
  cover commuter buses, so bike access is unclear and counts as closed. Bikeshare + 🚶🚆🚌 could
  still walk to them.
- **Fairfax Connector**
  (`https://www.fairfaxcounty.gov/connector/sites/connector/files/assets/connector_gtfs.zip`).
  The terms require the line "Visit fairfaxconnector.com for more information" and use that helps
  transit riders.
- **DASH** (`http://dashbus.com/google_transit.zip`) and **ART**. Both feeds are listed by Virginia
  DRPT's GTFS clearinghouse (the design note has ART's address).
- **Ride On and TheBus.** Feeds and bike rules are not yet checked.
- **DC Streetcar.** Service ended March 31, 2026 (DDOT), so there is nothing to add.

### Limits

- GTFS-Realtime service alerts are not used (WMATA's own live API is, above). The other
  agencies' real-time endpoints cannot be reached from the build environment, and their terms
  have not been checked. Planned closures that an
  agency publishes in its static timetable (`calendar_dates.txt`) are used, but unplanned track
  work is not, except as it shows in WMATA's predicted departures. A plan with a timetable
  departure says "Scheduled service: check for track work and service alerts before you go."

## Street photos (Mapillary, v0.7.0)

- **Data:** Mapillary's Graph API, `GET https://graph.mapillary.com/images` (fields `id`,
  `captured_at`, `compass_angle`, `thumb_1024_url`, `geometry`, `is_pano`, `creator`), asked for
  a box about 200 ft (60 m) across around the point on the road the panel describes.
  <https://www.mapillary.com/developer/api-documentation>.
- **Licence:** the imagery is CC BY-SA 4.0 (<https://www.mapillary.com/terms>).
- Credit: Mapillary (CC BY-SA), linked, with the photo's date and its creator's name where
  Mapillary gives one. Shown under the road panel's photo only.
- **Token:** Mapillary's client access token (`MAPILLARY_ACCESS_TOKEN` on the server; the owner's
  app, no user sign-in), sent only in the `Authorization` header from the server. The server
  fetches the image file from Mapillary's image host (`*.fbcdn.net`) and serves the browser its
  own copy at `/api/street-photo/image/<id>`, so the CSP's `img-src` stays same-origin and the
  browser never contacts Mapillary; a worker that did not show the photo looks its file up
  again at `graph.mapillary.com/<id>`. The panel opens Mapillary's viewer in a new tab; no
  Mapillary script is loaded.
- **Kept:** each answer for an hour in the api's memory; nothing is stored.
- Code: `src/core/street_photo.py`, `frontend/src/lib/streetPhoto.ts`; fixture
  `tests/data/mapillary/`.

## Known road hazards (v0.10.0: cobblestones, rails in the road)

Read from OpenStreetMap (credited there): `surface=sett`, `cobblestone`,
`cobblestone:flattened` or `unhewn_cobblestone`; `embedded_rails`; and `railway=tram`, an
`embedded=yes` railway or a disused tram line matched onto the road it lies along
(`src/routemaker/hazards.py`, `src/pipeline/hazard_layer.py`). A short reviewed list adds
what OSM may miss (`fixtures/hazards/`), each entry with its source:

- Georgetown's O and P Streets NW, Wisconsin Ave to 35th St, setts and streetcar tracks:
  The Georgetowner, "O and P Streets Project to Mark Completion in a Few Weeks"
  (<https://georgetowner.com/?p=93557>), on DDOT's O and P Streets Rehabilitation Project.
- DC Streetcar's H Street NE and Benning Road NE rails: the line closed on 31 March 2026
  and its rails stay in the street (<https://en.wikipedia.org/wiki/H_Street/Benning_Road_Line>).

Facts only, no data copied. The route network prices a hazard road as LTS 4; its rating is
unchanged, and the map marks it only on a route that rides it.

## 311 websites (the 311 checklist; facts, no credit)

The 311 checklist (frontend/src/lib/report311Log.ts JURISDICTIONS) names, for each place, the
public website that takes reports of road problems. Each was read on 2026-10-20 from the
jurisdiction's own page that links it:

- DC: 311.dc.gov (ouc.dc.gov/page/311-about). DC's Text to 311 (32311) answered every
  message, even a plain NEW, with only "Welcome to DC311" (a rider's test, 2026-10-20), so the
  app no longer texts it.
- Montgomery County: MC311 (montgomerycountymd.gov/department-transportation/request-road-repairs).
- Prince George's County: PGC311 (princegeorgescountymd.gov, PGC311).
- Baltimore City: Baltimore 311 (baltimorecity.gov/311services).
- Baltimore County: baltimorecountymd.gov/report-problem (streetlights go to BGE).
- Howard County: Tell HoCo (howardcountymd.gov/public-works/pothole-repair).
- Anne Arundel County: aacounty.org's potholes page.
- Frederick County: FCG FixIt (frederickcountymd.gov/8235/FCG-FixIT).
- Carroll County: See Click Report (carrollcountymd.gov/scr; its app takes the report).
- Harford County: You Click We Fix (harfordcountymd.gov/139/Report-a-Concern).
- Charles County: See Click Report (charlescountymd.gov/services/e-services/see-click-report).
- Arlington County: its Online Service Request Tool
  (arlingtonva.us/Government/Topics/Report-Problem/Online-Service-Request-Tool).
- Alexandria: Alex311 (alexandriava.gov/Potholes; Alex311 replaced Call.Click.Connect in 2020).
- City of Fairfax: fairfaxva.gov's Report Road Problems (by phone).
- Falls Church: RequestTracker (fallschurchva.gov/155/Public-Works).
- Manassas: Report a Concern (manassasva.gov/public_works).
- Manassas Park: its Public Works request page.
- Fairfax, Loudoun and Prince William counties: My VDOT (my.vdot.virginia.gov), since VDOT keeps
  their roads (fairfaxcounty.gov/transportation/roads-conditions-maintenance, loudoun.gov/3919).
- Maryland's numbered state roads, and Calvert County, which has no online form: MDOT SHA
  Customer Care (roads.maryland.gov, "Contact Us").

Which applies to a spot: inside DC from DC's boundary (core/geodata/dc-boundary.geojson); elsewhere
from the county or city the self-hosted Photon names for the spot (OpenStreetMap's administrative
boundaries; core/report_log.py).

## Used inside the project only (no credit)

These are shown nowhere: no tile, route, fixture or page carries anything read from
them (OWNER-DECISIONS 152, 155, 162).

- Arlington County's Bike Comfort Index: internal comparison only, held outside the
  repository, while Arlington's terms are pending.
- Arlington County's Intersection Points
  (<https://arlgis.arlingtonva.us/arcgis/rest/services/Open_Data/od_Intersection_Points/FeatureServer/0>),
  319 signalised intersections (2026-10-19): installable as a signal list
  (`pipeline.agency_signals`) but not read while Arlington's terms are pending (its
  item says only "Please review the Arlington County data disclaimer").
- MDOT's Road Separated Bike Routes web map: check-only (its terms bar trip-planning
  use).

## WMATA service announcements (facts, no credit)

- Credit: none. Two service changes the Open Data DC Metro layers predate are added
  to a station's lines by hand (`frontend/src/rail-data/metro-line-corrections.json`),
  each with the WMATA announcement it rests on cited in that file and in
  `frontend/src/rail-data/README.md`. What is taken is the fact (which lines stop
  where), not WMATA's text or data, so there is no licence to follow and no credit on
  the map; it is listed here so every source is cited (301).

## Links the map offers (no data taken)

- Credit: none; nothing is read from these sites. They are pages the map links to,
  named in text only (trademarks; OWNER-DECISIONS 441), each opened in a new tab with no
  opener or referrer, and only when the rider follows the link (441c).
- **Google Street View** (OWNER-DECISIONS 441): the road panel's "Street View" button
  is Google's public Maps URL,
  `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=LAT,LON`
  (<https://developers.google.com/maps/documentation/urls/get-started>). No Google code,
  key or request is in the app; the spot is sent to Google only if the rider follows the
  link, which the panel says beside it.
- **OpenStreetMap's editor** (OWNER-DECISIONS 441m): the road panel's "Edit in OSM" button
  is `https://www.openstreetmap.org/edit?way=<id>`, the way the panel describes. Editing
  needs the rider's own OpenStreetMap account; the panel says not to copy from Google
  Street View (OpenStreetMap's licence forbids it).
- **WMATA station pages** (441b): `https://www.wmata.com/ridertools/station/<slug>`, the
  slug for each of the 98 Metro stations from the curated table
  `frontend/src/rail-data/wmata-station-slugs.json`, checked once, read only, against
  wmata.com on 2026-10-07 under the owner's permission (441f). WMATA's short station names
  are the pattern ("Rhode Island Av", "Naylor Rd", "U St"); a wrong slug answers 404.
- **MARC Penn Line timetable** (441d, 441e): Maryland Transit Administration,
  <https://www.mta.maryland.gov/schedule/timetable/marc-penn>, checked 2026-10-07 (the
  page lists Perryville to Washington Union Station). Offered at every Penn Line station
  the map draws; only the Penn Line is drawn.
- **MORE trail pages** (OWNER-DECISIONS 454; the owner's defaults of 2026-10-11 for the
  Mountain Bike ride type, docs/MTB-TOPO-PLAN.md, slice 6): the road panel gives a
  mountain-bike trail one link to MORE (Mid-Atlantic Off-Road Enthusiasts): its trail
  system's page, `https://more-mtb.org/products/<slug>`, or MORE's trail guide,
  <https://more-mtb.org/collections/trails>, where the trail's names place it in no system.
  The systems, their slugs and the words they are matched by are in
  `src/routemaker/more_links.py`, from MORE's trail list (pages 1 and 2 of
  <https://more-mtb.org/collections/trails>, read 2026-10-11), limited to systems inside
  the planner's coverage or at its edge; skills parks and pump tracks are left out. Only
  the names and page addresses are kept; no trail data is taken from MORE.
