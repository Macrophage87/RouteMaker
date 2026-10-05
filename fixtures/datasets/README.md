# Agency street and bike layers

PLAN.md "Licensing" asks that every external source be recorded with its
licence, URL and refresh procedure; these are those records for the layers the
owner approved on 2026-09-30 and 2026-10-01 (OWNER-DECISIONS 149-162), in the
pattern of `fixtures/cbd/README.md`.

**The data is not in this repository.** The files are 0.8 to 152 MB, and the
derivative the rebuild reads is `<DATA_ROOT>/reference/roadway.json`, installed
by `scripts/install_reference_data.py --roadway-block ... --baltimore-centerline
...` (docs/DEVELOPMENT.md, "Agency street layers"). The raw layers were stored
on the development host under `/home/steph/rmdata/datasets/<slug>/`, each beside
a `README.md` the downloader wrote with the same record as the tables below.
Each was downloaded once, by `scripts/fetch_agency_layer.py`, paged at the
service's `maxRecordCount` and written unedited (GeoJSON, WGS 84,
`where=1=1`, `outFields=*`, ordered by the id field) - except the Baltimore
trails, whose query left out the proposed alignments, below. The script refuses
to run again where its output exists.

## How each is used

| Layer | Used for | May it reach published output? |
| --- | --- | --- |
| DC Roadway Block | posted speed, lanes by direction, one-way, bike-lane type and width, parking, AADT, conflated onto DC's OSM ways at classification (`pipeline.conflation.road_facts_by_way`, `routemaker.agency_roads`); the travel-lane, bike-lane and parking widths and lanes by direction also give the Mass Ride usable width (`routemaker.massflow`, OWNER-DECISIONS 404) | yes: CC BY 4.0, credited |
| Montgomery Planning Bicycle LTS | a comparison and calibration set; its LTS 5 roads are **loaded as Avoid** (OWNER-DECISIONS 181), `fixtures/overrides/2026-10-01-owner-moco-lts5-avoid.json` | yes with attribution (open licence; the ODbL gate below), credited |
| Baltimore street centerline | posted speed (the city's `speed` field, **only where OSM has no `maxspeed`**, OWNER-DECISIONS 184) and one-way, conflated onto Baltimore's OSM ways | yes: open licence by city code, credited |
| Baltimore bike facilities and multiuse trails | a candidate list of facilities OSM lacks, and **loaded** override rows (OWNER-DECISIONS 182), `fixtures/overrides/2026-10-01-owner-baltimore-facilities.json` | yes (as above), credited |
| Alexandria Bike Lane Routes | a cross-check of OSM's bike lanes | yes: CC0 |
| Arlington Bike Comfort Index | **internal comparison only** (OWNER-DECISIONS 152, 155) | **no**; never in tiles, routes, fixtures or this repository |
| Alexandria Transport Streets | **internal comparison only** (OWNER-DECISIONS 153, 155) | **no**; as above |

Not downloaded: MDOT's "Road Separated Bike Routes" web map (iMAP item
66bf7d61948b4ef48aea94327b504f86): its terms bar trip-planning use, so it is
check-only (OWNER-DECISIONS 162). Anne Arundel County's layers were dropped
(OWNER-DECISIONS 161).

## The records

All retrieved on 2026-10-01 (UTC times below), each item's metadata read once
for its licence text. "Licence" is the item's `licenseInfo` as plain text,
verbatim.

| Layer | Source layer and item | Retrieved (UTC) | Features | Bytes | sha256 |
| --- | --- | --- | --- | --- | --- |
| Roadway Block (DDOT, DC GIS) | <https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/MapServer/163>, item `6fcba8618ae744949630da3ea12d90eb` (modified 2026-09-26) | 20:44:20 | 13,833 (7 pages) | 44,917,086 | `45066cff69065adeb0fb3ba3376abaaf58862bd37e3baba63d92062e68bb8108` |
| Bicycle Level of Traffic Stress (Montgomery County Planning) | <https://montgomeryplans.org/server9/rest/services/Overlays/MCAtlas_Transportation_Planned/MapServer/8>, item `fb903d1ffbc84b219bdb47629bd02b82` (modified 2026-03-31) | 20:44:49 | 59,148 (30 pages) | 66,878,261 | `89be5b63b86a69329d696e999565ac1a498ffed5a8bdf736d277f24a89a7505e` |
| Bike Lane Routes (City of Alexandria) | <https://services2.arcgis.com/ChYV69FhfjwkvRmy/arcgis/rest/services/Transit_BikeLaneRoutes/FeatureServer/0>, item `74341781de91444a8f03620efc5c0514` (modified 2026-04-07) | 20:45:23 | 593 | 842,508 | `138de101daaee5074853d6e3d1648a4271e8ffdee5862a5fdbdff78dc2a914c5` |
| DOT BMC Bike Facilities (City of Baltimore) | <https://services3.arcgis.com/ZTvQ9NuONePFYofE/arcgis/rest/services/BCDOT_Bike_Facilities_Open_/FeatureServer/18>, item `dbef46a0caf948debba8516f0d95fe4c` (modified 2025-02-20) | 20:45:24 | 628 | 955,956 | `29ea6582753bc920f091c02c4a4b80861da6f482d38947cbca416abf12d8b639` |
| Multiuse Trails (City of Baltimore) | <https://services1.arcgis.com/UWYHeuuJISiGmgXx/ArcGIS/rest/services/multiuseTrails2023/FeatureServer/0>, item `34260bfb3df74d3994e0c73fde47630b` (modified 2026-07-01) | 20:45:25 | 162 of 163 | 434,452 | `a0346799b9e519e56b7add57e186f484f051f8ba555adca334e7fe4023ed7eed` |
| Street Centerline (Native) (City of Baltimore) | <https://baltegis.baltimorecity.gov/mapping/rest/services/Address_Points/Street_Centerline_Native/FeatureServer/0>, item `69d9eb1e37044f1c9cc9941df1797c43` (modified 2026-08-14) | 20:45:26 | 48,522 (25 pages) | 152,214,630 | `b386865bca7d95826008a0b825d035926453db2ac51a0f103ecabb6bf67f9dd8` |
| Bike Comfort Index (Arlington County) - internal | <https://services1.arcgis.com/JrtUzVcH8S2wnzVH/arcgis/rest/services/Bike_Comfort_Index/FeatureServer/0>, item `d0fe44f631c1460089a49ecaa1377fa9` (modified 2026-07-10) | 20:46:19 | 6,694 | 12,204,740 | `2acc22a157e7afdae1d5f79060581be7c0bd85d3cf412ebc97772c6608f2765a` |
| Transport Streets (City of Alexandria) - internal | <https://services2.arcgis.com/ChYV69FhfjwkvRmy/arcgis/rest/services/Transport%20Streets/FeatureServer/0>, item `dccf9eda6b6c443b8133abf2542854b1` (modified 2026-04-07) | 20:46:26 | 5,677 | 5,032,968 | `5e8f8765cb368243cf9a231cc858f4951840050b9022222ec66c1e7306c8f1f0` |

(The Arlington and Alexandria Transport Streets rows are the record of a
download held outside the repository, in `rmdata/datasets/internal-only/`; the
files and anything read from them are not checked in.)

The Baltimore Multiuse Trails layer holds current and proposed trails (OWNER-
DECISIONS 158). The proposed alignments are `mainSpur = 'Future Alignment'`,
and the query excluded them (`where=mainSpur IS NULL OR mainSpur <> 'Future
Alignment'`): 162 of the layer's 163 features were downloaded.

### Licences, verbatim

| Layer | Licence text | Credit field (`accessInformation`) |
| --- | --- | --- |
| Roadway Block | "This work is licensed under a Creative Commons Attribution 4.0 International License." (linking <https://creativecommons.org/licenses/by/4.0/>) | "District Department of Transportation" |
| Montgomery Bicycle LTS | "You can copy, modify, distribute, and perform analysis on the data, even for commercial purposes, all without asking permission, but please provide attribution to the Montgomery County Planning Department. The Planning Department makes no warranties about the data, and disclaims liability for all uses of the data, to the fullest extent permitted by applicable law." | "Information Technology & Innovation (ITI), Montgomery County Planning Department, MNCPPC" |
| Alexandria Bike Lane Routes | "cc0" | "Bike Lanes, Transit City of Alexandria, VA GIS" |
| Baltimore DOT BMC Bike Facilities, Multiuse Trails, Street Centerline (Native) | the three items carry no licence text. The basis is Baltimore City Code Art. 1 §9-1(h) (<https://codes.baltimorecity.gov/us/md/cities/baltimore/code/1/9-1#(h)>), as the owner quoted it (OWNER-DECISIONS 159): "Datasets published on the Open Data Portal shall be available to the public on an open license basis, with no restrictions on copying, publishing, further distributing, modifying, or using the data for any non-commercial or commercial purpose." | facilities: "City of Baltimore. Baltimore City Department of Transportation (DOT)"; trails: "City of Baltimore. Department of Recreation & Parks (BCRP). Department of Transportation (DOT)"; centerline: none |
| Arlington Bike Comfort Index | "Please review the Arlington County data disclaimer." (a pointer, not a licence) | "Arlington County, Virginia; Department of Environmental Services" |
| Alexandria Transport Streets | "City of Alexandria, VA GIS" (not a licence) | none |

### Credits

These were the credit lines until 2026-10-04. OWNER-DECISIONS 306 made every credit
brief ("DC Open Data (CC BY 4.0, adapted)", "Open Baltimore", "Montgomery County
Planning Department"); the full references are in docs/SOURCES.md.

| Layer | Credit line | Where |
| --- | --- | --- |
| Roadway Block | "Street speeds, lanes, one-way streets, bike lanes, parking and traffic counts in the District: Roadway Block, District Department of Transportation (DDOT) / DC GIS (Open Data DC), adapted, CC BY 4.0" | `routing.ATTRIBUTION`, `VOLUME_CREDITS` in `frontend/src/lib/mapStyle.ts` |
| Baltimore centerline, facilities and trails | "Street speeds, one-way streets, bike facilities and trails in Baltimore: City of Baltimore, Open Baltimore" (the owner's line, OWNER-DECISIONS 159; the items carry no credit field of their own for the centerline) | both lists |
| Montgomery Planning | "Roads to avoid in Montgomery County: Bicycle Level of Traffic Stress, Montgomery County Planning Department" (the licence: "please provide attribution to the Montgomery County Planning Department") | both lists, added in the change that loads the Avoid rows (OWNER-DECISIONS 181) |

### Montgomery Planning through PLAN's three questions (2026-10-01)

PLAN.md's ingest procedure puts every source's terms to three questions before
anything derived from it reaches the published derivative. Montgomery
Planning's terms, quoted above, were put to them when the owner approved
loading its LTS 5 as Avoid (OWNER-DECISIONS 181):

1. **May it be redistributed at all?** Yes: "You can copy, modify, distribute,
   and perform analysis on the data, even for commercial purposes, all without
   asking permission".
2. **May it be relicensed under ODbL without carrying its own conditions onto
   downstream recipients?** Yes, on what is taken. The one condition is
   attribution to the Planning Department; it binds this project as the user,
   not the recipients of a derived database, and the terms carry no
   share-alike, no non-commercial clause, no bar on derivatives and no
   condition to preserve metadata, which is what the Maryland iMAP case turned
   on. What reaches the derivative is a tier of 5 on 409 OSM ways, a fact about
   each way derived by this project's own matching, not the county's geometry
   or its LTS values. The disclaimer of warranty and liability is not a
   condition on anyone.
3. **Is its attribution satisfiable by the produced-work notice?** Yes: the
   credit line above is on every map view and in every route response
   (`routing.ATTRIBUTION`), and the data page carries the licence record.

So the layer passes, credited, and the PLAN's older "check-only" note for it is
superseded (PLAN.md, "Owner amendments", 2026-10-01). Arlington's Bike Comfort
Index and Alexandria's Transport Streets did not reach the gate: their licence
fields are a pointer and an agency name, and they stay internal comparison only
(OWNER-DECISIONS 155).

## What was found in the data

Facts a reader of the parsers (`src/routemaker/agency_roads.py`) would
otherwise rediscover; each is pinned by a test.

* **DC `SPEEDLIMITS_IB` is empty on all 13,833 blocks**; `SPEEDLIMITS_OB` holds
  the limit (20 mph on 8,846 blocks, 25 on 2,513, 30 on 584; 1,738 have none).
  Five blocks read 0 and one reads 5, which are not read as limits (below
  10 mph); five read 10 and are kept.
* DC's lane, parking and bike-lane **widths are totals over the block's lanes,
  in feet**: two bike lanes of five feet read `10`.
* DC's **reversible lanes** (`TOTALTRAVELLANESREVERSIBLE`; Connecticut Avenue
  NW's) are in `TOTALTRAVELLANES` and in neither direction's count: a block of
  one lane each way and two reversible has `TOTALTRAVELLANES` 4.
* DC's `OB` is the block's digitising direction and `IB` is against it: on the
  one-way blocks `SUMMARYDIRECTION` `OB` runs with the line 1,023 times to 49,
  and `IB` against it 888 to 33 (review r1). The matcher records which way each
  OSM way runs along its block, so each carriageway takes its own direction.
* DC's `BIKELANE_PARKINGLANE_ADJACENT` (`IB`, `OB` or `BD`, on 925 blocks) says
  which direction's bike lane runs beside a parking lane; only there is the
  parking lane's width added to the lane's for Furth's reach.
* For the Mass Ride width (OWNER-DECISIONS 404, `routemaker.massflow`): the
  travel-lane width (`TOTALTRAVELLANEWIDTH`, per lane after the parser) is read as
  excluding the parking lanes, which DC records apart (`TOTALPARKINGLANEWIDTH`): an
  8 ft lane each way between two 8 ft parking lanes is the usual 32 ft DC street.
  So curb to curb less the parked cars is the travel and bike lanes. Of the 13,833
  blocks, 220 record no lanes and 220 no lane width, and 11 read a lane of 1 to 4 ft
  (read as errors); those fall back to OSM. The commonest lane is 8 ft (4,660
  blocks, 4,034 of them one lane each way between two parking lanes); 195 two-way
  blocks of one lane each way read 16 ft lanes and no parking lane.
* DC's lane totals include bus lanes (`BUSLANE_INBOUND`, `BUSLANE_OUTBOUND`), and
  reversible lanes are counted as operating in the peak direction; both are the
  conservative reading (OWNER-DECISIONS 179).
* DC's `FHWAFUNCTIONALCLASS` never reaches the classifier: the Furth tables
  take no class, and the classifier's class is OSM's `highway`. The matcher reads
  it once: a freeway-class OSM way takes a block naming a different street only
  where the block is class 1 or 2 (Baltimore's `sha_class` INT or FWY; review
  r2, Canal Road NW took M Street NW's block).
* DC's `BIKELANE_CONTRAFLOW` is the only reliable sign of a contraflow lane: on
  one-way blocks without it, the bike lane's `IB`/`OB` label points against the
  traffic 200 times and with it 56 where OSM maps a with-flow lane, while all 43
  OSM-mapped contraflow lanes carry the flag (review r2). A lone lane on an
  unflagged one-way block is read as the with-flow lane.
* **Baltimore's `fr_speed_limit` and `to_speed_limit` hold 19 values, all 0.**
  The layer's `speed` field carries 25 on 26,722 of its 48,522 lines and `1` on
  its alleys; it is read as the speed limit, with the source named in the
  segment's `attr_sources`, and only where OSM has no `maxspeed` (OWNER-DECISIONS
  184). It is the city's own field, not a survey of signs; the owner should
  treat the Baltimore speeds as "the city's street database". Its `lane_count`
  is filled on 5 lines and `traffic_count_aadt` on none. The layer marks only
  one-way streets (`oneway` FT or TF), never a two-way one.
* Montgomery's `LTS_EXIST` takes 0.5, 1, 2, 2.5, 3, 4 and 5: **3 and 4 are
  separate** (OWNER-DECISIONS 149, confirmed), and so are 2 and 2.5.
* Alexandria's Transport Streets has `SPEED_LIMIT` and `ONEWAY`; `LANES` is
  empty on all 5,677 lines and there is no LTS.
* Arlington's Bike Comfort Index has an `LTS` field (`LTS 0` to `LTS 4`,
  `Not Applicable`, `Check`).

## Refresh

Re-run `scripts/fetch_agency_layer.py` into a new directory when an agency
revises a layer, with the owner's go for the download, and update the tables
above. The refetch needs a new `--out-dir` because the script refuses to
overwrite. Then reinstall: `scripts/install_reference_data.py --roadway-block
... --baltimore-centerline ...`.

## Federal land (2026-10-03)

The Mass Ride map's federal-land shading (PLAN.md FOLLOWUP-FEDERAL-LAYER, owner
items 236-239; docs/DEVELOPMENT.md, "The federal-land overlay"). The owner
approved the downloads for this item. Each layer was fetched once by
`scripts/fetch_agency_layer.py` into
`/home/steph/rmdata/datasets/federal/<slug>/`, unedited (GeoJSON, WGS 84,
`where=1=1`, `outFields=*`), each beside the `README.md` the downloader wrote.
The raw files are not in this repository; the derivative the front end loads,
`frontend/src/federal-data/federal-land.json`, is.

| Layer | Source layer and item | Retrieved (UTC) | Features | Bytes | sha256 |
| --- | --- | --- | --- | --- | --- |
| National Parks (NPS Map A: Park Service and other government-owned land) | <https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Recreation_WebMercator/MapServer/10>, item `14eb1c6b576940c7b876ebafb227febe` (item `modified` 2025-02-10, re-read 2026-10-03; PLAN's 2025-02-07 is the layer's last-edit date from the service metadata, a different field) | 2026-10-03 19:15:30 | 456 (1 page) | 2,302,138 | `d2038ab8bb43ab947c8b377e01f47fb58e4b2cd16acd6d6dfe992a66b9184310` |
| Reservations (U.S. Reservations) | <https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Property_and_Land_WebMercator/MapServer/37>, item `0ac4302b2e354fad986f07199e73a19e` (modified 2026-10-03) | 2026-10-03 19:15:31 | 939 (1 page) | 2,414,557 | `e4e34e2c425a052b40b04eef142448042cde6a57000b4ba5d81daea8168c364f` |
| Military Bases | <https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Property_and_Land_WebMercator/MapServer/11>, item `21ee426eddc14014b80535cd6b8316e7` (modified 2025-05-16) | 2026-10-03 19:15:32 | 9 (1 page) | 26,365 | `951c9119eebfd879474bc03f305b5fff8941420b5edc15458a4e7def032407c5` |
| Architect of the Capitol (reused, not fetched again) | `fixtures/cbd/architect-of-the-capitol.geojson`, item `d9e8c786c9694e47979ef71a5c2f1a7a`, retrieved 2026-09-30 (above, `fixtures/cbd/README.md`) | | 1 | 15,366 | `03e440f70147d42515dafe8bcc52eac3f88fd59d8ed824706ccbb776d1298d5f` |

**Licences, verbatim** (each item's `licenseInfo` as plain text, read when the
layer was fetched; each item's `accessInformation` is its credit field):

| Layer | Licence text | Credit field |
| --- | --- | --- |
| National Parks | "This work is licensed under a Creative Commons Attribution 4.0 International License." (linking <https://creativecommons.org/licenses/by/4.0/>) | "DC GIS" |
| Reservations | "This work is licensed under a Creative Commons Attribution 4.0 International License." (linking <https://creativecommons.org:443/licenses/by/4.0/>) | "District of Columbia" |
| Military Bases | "This work is licensed under a Creative Commons Attribution 4.0 International License." (linking <https://creativecommons.org/licenses/by/4.0/>) | "DC Office of the Chief Technology Officer" |

The layers' own service descriptions say what they are: National Parks, "Digital
version of the National Park Service Map A, indicating Park Service properties
and other government-owned land"; Reservations, lands "acquired for use by the
Federal Government after the original founding of the city", "almost all" under
the National Park Service (the layer names no agency per lot, so the popup says
"National Park Service (most U.S. Reservations)" and nothing more specific);
Military Bases, DC OCTO's military facilities (the layer names no agency either,
so none is shown).

**Not downloaded: Federal Land (RPTA Ownership)**,
`.../Property_and_Land_WebMercator/MapServer/50`. It is a derived layer with no
Open Data DC item of its own (a search of DCGISopendata's items by title found
none), so there is no licence text to record for it; the service carries only
"District of Columbia" as copyright text, and describes itself as built "from
various polygon feature classes of the District's Vector Property Mapping
program", regenerated daily with attributes from the Integrated Tax System
Public Extract. Its source "Common Ownership Lots" item (`1f6708b1f3774306bef2fa81e612a725`)
reads CC BY 4.0, but that is a different item and is not read as this layer's
licence. The layer also carries tax-assessment and owner fields for every lot
(`OWNERNAME`, sale prices, tax balances), which an overlay does not need. Per the
rule for an unclear licence, it was stopped and reported rather than worked
around. The overlay does without it: the National Parks layer is most of the
land (the owner's item 237), and the Reservations, Military Bases and Capitol
polygons cover the rest of what the owner named; what it would have added is
other federally owned lots, which are mostly GSA office buildings, the one
class item 238 leaves out. `build_federal_land.py --federal` reads such a file
(dropping lots whose owner names GSA) if the owner later clears a source for it;
the `federal` kind is in the legend's code but not in its data.

**How the derivative is made** (`scripts/build_federal_land.py`, run with the
four files above; the output is reproducible byte for byte):

* every polygon is made valid, simplified to 0.00003 degrees (about 10 ft, 3 m)
  and snapped to a 0.00001-degree grid (about 3 ft, 1 m);
* a patch belongs to one kind only: Capitol, then military, then National Park
  Service, then Reservation, a lower kind clipped around a higher one, so the
  map shades it once;
* retired Reservation lots (`KILL_DT` set) and slivers under 60 m² (650 ft²) are
  dropped;
* names: the layer's `NAME`, else its `LABEL`; the generic ones ("Triangle",
  "Center Parking", "Curb Parking", "Park") get their reservation number; a
  Reservation is "U.S. Reservation N"; the Capitol is "U.S. Capitol grounds"
  (agency: Architect of the Capitol).

The result: 1,002 areas (1 Capitol, 9 military, 424 National Park Service, 568
Reservation), 501,462 bytes (about 87 KB gzipped), sha256
`773f230f94c5a5b5ce576b17c09b83a3a4e10d5b8627f1d2c0e972d2b10ce4af`.

| Credit line (on every map view; `FEDERAL_CREDITS` in `frontend/src/lib/mapStyle.ts`) | Basis |
| --- | --- |
| "Federal land on the Mass Ride map: National Parks, Reservations and Military Bases, District of Columbia (Open Data DC), adapted, CC BY 4.0" | the three items' CC BY 4.0, adapted (merged, clipped and simplified); the Capitol polygon in the file is the Architect of the Capitol boundary already credited in `VOLUME_CREDITS` |

To refresh: fetch each layer into a new directory with
`scripts/fetch_agency_layer.py` (it refuses to overwrite) with the owner's go,
rerun `build_federal_land.py`, and update the table above.
