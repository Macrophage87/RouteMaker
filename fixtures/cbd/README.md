# The District's Central Business District

The sidewalk rule of OWNER-DECISIONS 104 (`src/routemaker/cbd.py`): no bicycle
riding on sidewalks inside DC's Central Business District, except on the federal
areas inside it. PLAN.md "Licensing" asks that every external source be recorded
with its licence, URL and refresh procedure; these are those records.

| File | What | Source | Licence | Credit |
| --- | --- | --- | --- | --- |
| `dc-central-business-district.geojson` | DDOT's CBD boundary, one polygon (`GIS_ID` DDOT_CBD_1) | Open Data DC, "DDOT Central Business District", <https://opendata.dc.gov/datasets/DCGIS::ddot-central-business-district> (ArcGIS item 32143ca8983d4476b64f4202162bf61e, modified 2024-09-05); layer `DCGIS_DATA/Administrative_Other_Boundaries_WebMercator/MapServer/12` | **CC BY 4.0**, District Department of Transportation | "Central Business District: District Department of Transportation (Open Data DC), CC BY 4.0" |
| `federal-exempt.geojson` | exempt federal areas: the National Mall (OSM way 1558212097), the Washington Monument Grounds (way 1552426509), The White House and President's Park (relation 7399196) | OpenStreetMap, via the project's DC extract, by the script recorded in the commit | **ODbL 1.0** | the map's existing "© OpenStreetMap contributors (ODbL)" |
| `architect-of-the-capitol.geojson` | the Architect of the Capitol's jurisdiction (`GIS_ID` AOCPly_1): the Capitol grounds and the buildings around them, exempt as federal (OWNER-DECISIONS 113) | Open Data DC, "Architect of the Capitol" (ArcGIS item d9e8c786c9694e47979ef71a5c2f1a7a, modified 2024-09-05); layer `DCGIS_DATA/Administrative_Other_Boundaries_WebMercator/MapServer/5` | **CC BY 4.0**, DC GIS (the item's own licence; PLAN.md's "CC0" for this layer is corrected here) | "Routing the Capitol grounds: Architect of the Capitol boundary, District of Columbia (Open Data DC), CC BY 4.0" (`routing.ATTRIBUTION`, `VOLUME_CREDITS`) |

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

**The licence evidence is incomplete** (review r1, S2). CC BY 4.0 above is
what the ArcGIS search reported for each item at retrieval;
neither item page's licence statement was kept verbatim, and the GeoJSON files
carry no licence metadata. The statement is to be copied here verbatim at the
next fetch of the two item pages, which waits for the owner's go-ahead.

Refresh: re-run the query when DDOT revises the boundary, and update this table.
