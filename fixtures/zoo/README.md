# The National Zoological Park

The Zoo rule of OWNER-DECISIONS 278 and 291(4) (`src/routemaker/zoo.py`): the
Zoo is closed to bicycles, except the public streets along its edge, the Rock
Creek Trail and Zoo Loop Trail cycleways signed for bicycles, and a short
destination-only spur from the Harvard Street NW entrance to the bike racks.

| File | What | Source | Licence |
| --- | --- | --- | --- |
| `national-zoo.geojson` | the outline: OSM area 21022241 (relation 10511120), `tourism=zoo`, `operator=Smithsonian Institute`, one ring of 121 vertices | OpenStreetMap, from the project's own extract of 2026-10-03 (no download) | ODbL 1.0, the map's existing OpenStreetMap credit |
| `zoo-access.json` | the spur's way ids, the racks, the open road classes | read from the same extract | ODbL 1.0 |

The racks are OSM node 9827008403 (`amenity=bicycle_parking`,
`bicycle_parking=stands`, `capacity=12`), standing on footway 183192886, about
190 m from the entrance gate by way 50524918, 469478150, 1430189973, 348381512,
1244165507, 1249538178 and 183192886. A way cannot be opened in part, so the spur
is those ways whole. They are written destination-only, so a route may end on
them and not pass over them.

The Smithsonian's visitor rules were not fetched. The closure is the owner's
decision as stated; no user-facing text cites a policy source.

To refresh after an OSM edit: re-run the way search around the entrance (the
spur ways are listed with what each is), check the ids still exist, and keep the
racks node in step.
