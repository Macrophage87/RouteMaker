# The District's Central Business District

The sidewalk rule of OWNER-DECISIONS 104 (`src/routemaker/cbd.py`): no bicycle
riding on sidewalks inside DC's Central Business District, except on the federal
areas inside it. PLAN.md "Licensing" asks that every external source be recorded
with its licence, URL and refresh procedure; these are those records.

| File | What | Source | Licence | Credit |
| --- | --- | --- | --- | --- |
| `dc-central-business-district.geojson` | DDOT's CBD boundary, one polygon (`GIS_ID` DDOT_CBD_1) | Open Data DC, "DDOT Central Business District", <https://opendata.dc.gov/datasets/DCGIS::ddot-central-business-district> (ArcGIS item 32143ca8983d4476b64f4202162bf61e, modified 2024-09-05); layer `DCGIS_DATA/Administrative_Other_Boundaries_WebMercator/MapServer/12` | **CC BY 4.0**, District Department of Transportation | "Central Business District: District Department of Transportation (Open Data DC), CC BY 4.0" |
| `federal-exempt.geojson` | exempt federal areas: the National Mall (OSM way 1558212097), the Washington Monument Grounds (way 1552426509), The White House and President's Park (relation 7399196) | OpenStreetMap, via the project's DC extract, by the script recorded in the commit | **ODbL 1.0** | the map's existing "© OpenStreetMap contributors (ODbL)" |
| `architect-of-the-capitol.geojson` | the Architect of the Capitol's jurisdiction (`GIS_ID` AOCPly_1): the Capitol grounds and the buildings around them, exempt as federal (OWNER-DECISIONS 113; the Capitol Police Board's US Capitol Grounds Traffic Regulations: "There shall be no prohibition against any person riding a bicycle on a sidewalk so long as that person does not create a hazard.", <https://www.uscp.gov/sites/evo-subsites/www.uscp.gov/files/documents/Capitol%20Police%20Board%20US%20Capitol%20Grounds%20Traffic%20Regulations%20-%20For%20Public%20Release.pdf>, cited by the owner 2026-10-17) | Open Data DC, "Architect of the Capitol" (ArcGIS item d9e8c786c9694e47979ef71a5c2f1a7a, modified 2024-09-05); layer `DCGIS_DATA/Administrative_Other_Boundaries_WebMercator/MapServer/5` | **CC BY 4.0**, DC GIS (the item's own licence; PLAN.md's "CC0" for this layer is corrected here) | "Routing the Capitol grounds: Architect of the Capitol boundary, District of Columbia (Open Data DC), CC BY 4.0" (`routing.ATTRIBUTION`, `VOLUME_CREDITS`) |
| `nps-land.geojson` | every National Park Service property with a corner inside the CBD, 70 polygons (Lafayette Square, Farragut Square, McPherson Square, Franklin Square, Dupont, Scott, Thomas and Washington Circles, the Mall's parcels, the reservation triangles, ...), exempt: DDOT's DC Bike Law Pocket Guide (Oct 2012, <https://ddot.dc.gov/sites/default/files/dc/sites/ddot/publication/attachments/DC-Bike-Law-Pocket-Guide-Oct2012.pdf>): "Within the CBD, bicycling is allowed on lands under the jurisdiction of the National Park Service including places like Lafayette Park, Farragut Square Park, the National Mall and Dupont Circle." (the owner, 2026-10-17) | DC GIS, National Parks (NPS Map A), as `scripts/build_federal_land.py` simplified it into `frontend/src/federal-data/federal-land.json`; the `kind=nps` features with a vertex inside `dc-central-business-district.geojson`, name kept | **CC BY 4.0**, DC GIS | routing's "DC Open Data (CC BY 4.0, adapted)" line |

The CBD file is exactly the bytes this query returned (retrieved 2026-09-30,
09:02 UTC, the one download the owner approved), not edited:

```
https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Administrative_Other_Boundaries_WebMercator/MapServer/12/query?where=1%3D1&outFields=*&outSR=4326&f=geojson
```

| File | Bytes | sha256 |
| --- | --- | --- |
| `dc-central-business-district.geojson` | 38,505 | `f86d57c8a24691a035604c907b0aa0d284225fa5322312416723ef8bac14ad54` |
| `architect-of-the-capitol.geojson` | 15,366 | `03e440f70147d42515dafe8bcc52eac3f88fd59d8ed824706ccbb776d1298d5f` |

The AOC file was retrieved 2026-09-30, 09:34 UTC (the one download the owner
approved, OWNER-DECISIONS 113), with the same query on `MapServer/5`.

**The licence statements, verbatim** (review r1, S2; re-read once each with
the owner's go-ahead, OWNER-DECISIONS 146: "Yes, re-read them"; item metadata
only, no data downloaded). The GeoJSON files carry no licence metadata, so
these are the record:

| Item | Read from | Retrieved (UTC) | `licenseInfo`, as text | `accessInformation` (credit) |
| --- | --- | --- | --- | --- |
| DDOT Central Business District (32143ca8983d4476b64f4202162bf61e, modified 2024-09-05) | <https://www.arcgis.com/sharing/rest/content/items/32143ca8983d4476b64f4202162bf61e?f=json> | 2026-09-30 12:22:29 | "This work is licensed under a Creative Commons Attribution 4.0 International License." (linking <https://creativecommons.org:443/licenses/by/4.0/>) | "District Department of Transportation" |
| Architect of the Capitol (d9e8c786c9694e47979ef71a5c2f1a7a, modified 2024-09-05) | <https://www.arcgis.com/sharing/rest/content/items/d9e8c786c9694e47979ef71a5c2f1a7a?f=json> | 2026-09-30 12:22:29 | "This work is licensed under a Creative Commons Attribution 4.0 International License." (linking <http://creativecommons.org/licenses/by/4.0/>) | "DC GIS" |

The CBD item's own description also says: "Bicycles are not permitted on
sidewalks within the central business district."

Refresh: re-run the query when DDOT revises the boundary, and update this table.
