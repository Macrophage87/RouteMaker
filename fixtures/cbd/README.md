# The District's Central Business District

The sidewalk rule of OWNER-DECISIONS 104 (`src/routemaker/cbd.py`): no bicycle
riding on sidewalks inside DC's Central Business District, except on the federal
areas inside it. PLAN.md "Licensing" asks that every external source be recorded
with its licence, URL and refresh procedure; these are those records.

| File | What | Source | Licence | Credit |
| --- | --- | --- | --- | --- |
| `dc-central-business-district.geojson` | DDOT's CBD boundary, one polygon (`GIS_ID` DDOT_CBD_1) | Open Data DC, "DDOT Central Business District", <https://opendata.dc.gov/datasets/DCGIS::ddot-central-business-district> (ArcGIS item 32143ca8983d4476b64f4202162bf61e, modified 2024-09-05); layer `DCGIS_DATA/Administrative_Other_Boundaries_WebMercator/MapServer/12` | **CC BY 4.0**, District Department of Transportation | "Central Business District: District Department of Transportation (Open Data DC), CC BY 4.0" |
| `federal-exempt.geojson` | the exempt federal areas: the National Mall (OSM way 1558212097), the Washington Monument Grounds (way 1552426509), The White House and President's Park (relation 7399196), and the United States Capitol grounds (hand-drawn: OSM maps the building, way 66418809, not the grounds) | OpenStreetMap, via the project's DC extract, by the script recorded in the commit | **ODbL 1.0** for the OSM areas; this project's for the Capitol grounds | the map's existing "© OpenStreetMap contributors (ODbL)" |

The CBD file is exactly the bytes this query returned (retrieved 2026-09-30,
09:02 UTC, the one download the owner approved), not edited:

```
https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Administrative_Other_Boundaries_WebMercator/MapServer/12/query?where=1%3D1&outFields=*&outSR=4326&f=geojson
```

| File | Bytes | sha256 |
| --- | --- | --- |
| `dc-central-business-district.geojson` | 38,505 | `f86d57c8a24691a035604c907b0aa0d284225fa5322312416723ef8bac14ad54` |

Refresh: re-run the query when DDOT revises the boundary, and update this table.
The Capitol grounds are an approximation to be replaced by the Architect of the
Capitol's own polygon (Open Data DC) if the owner approves that download.
