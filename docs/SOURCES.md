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
  Line stations and the Metro elevators DC does not list, and the public drinking water and
  restrooms layer.
- Dataset: OpenStreetMap, the regional extract from Geofabrik
  (<https://download.geofabrik.de/>), rebuilt weekly (docs/OPERATIONS.md, "The weekly
  rebuild").
- Publisher: OpenStreetMap contributors (OpenStreetMap Foundation).
- Licence: Open Database License 1.0 (<https://opendatacommons.org/licenses/odbl/1-0/>);
  credit form per <https://www.openstreetmap.org/copyright>.
- Retrieved: weekly; the extract's date is the rebuild's (`check_operations`).
- Records: `frontend/src/rail-data/README.md` (the MARC and elevator fixtures);
  `frontend/src/amenity-data/README.md` (public drinking water and restrooms, the Water and
  restrooms layer, by `scripts/build_water_restrooms.py`).
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
  tiers' Virginia counts. Retrieved 2026-09-25; the file installed is 100,789,629 bytes,
  sha256 `aa298951bb3707c2c2dd4e640679fd1c348eb9935d1ffa2ef4b89a567bac5204`. The
  dataset's own URL on the portal was not recorded at ingest; the next refresh records
  it here.
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
  climb, the effort model and the Hills slider. Retrieved by each rebuild's ELEVATION
  stage, which records the tiles and their dates in its run's log; never fetched on the
  development host (docs/OPERATIONS.md says why).
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
  (`core.gbfs`, `core.bikeshare`). Read live while a rider plans, about once a minute for the whole
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
  `reports/owner/cyclist_packing_density.md`), indicative, good to about ±25% (item
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

## Used inside the project only (no credit)

These are shown nowhere: no tile, route, fixture or page carries anything read from
them (OWNER-DECISIONS 152, 153, 155, 162).

- Arlington County's Bike Comfort Index and the City of Alexandria's Transport
  Streets: internal comparison only, held outside the repository.
- The City of Alexandria's Bike Lane Routes (CC0): a cross-check of OSM's bike
  lanes.
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
