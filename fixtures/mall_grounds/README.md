# The Washington Monument grounds and Constitution Gardens

The Mall grounds rule (`src/routemaker/mallgrounds.py`; the owner, 2026-10-25, on the
Monument grounds: "there's several parts here that aren't listed, they are available
for bicycling", and on Constitution Gardens: "Some parts here are closed, such as the
memorial itself, but not the path to it."): the untagged walks on these grounds open to
bicycles, except inside the walk-only places.

| File | What | Source | Licence |
| --- | --- | --- | --- |
| `grounds.geojson` | 2 polygons: the Washington Monument Grounds (OSM way 1552426509, the same shape as `fixtures/cbd/federal-exempt.geojson`'s) and Constitution Gardens with the Vietnam Veterans Memorial's grounds (the outer ways 897999944 and 1534377349 of OSM relation 21050367, without its inner hole, which is the memorial's park, way 1534164632) | OpenStreetMap, API 0.6, retrieved 2026-10-25 | ODbL 1.0, "© OpenStreetMap contributors" (the map's existing credit) |
| `walk-only.geojson` | 6 polygons where riders walk: the Monument's plaza (40 m round the obelisk, way 766761337, taking in the plaza's ring walk, way 895025351), the Vietnam Veterans Memorial (way 173932971, the wall), The Three Soldiers (way 895985388), the Vietnam Women's Memorial (way 895985390), Signers Island (way 26572842, the Memorial to the 56 Signers of the Declaration of Independence) and a 25 m band along the Tidal Basin's shore inside the Monument grounds (way 26755238, buffered and clipped to the grounds) | the same | the same |

Why these are walk-only: National Mall and Memorial Parks' compendium, 36 CFR 4.30
(<https://home.nps.gov/nama/learn/management/superintendent-s-compendium.htm>, read
2026-10-25): "Bicycles are prohibited on the steps, colonnades, or within the chambers
of ... the Washington Monument" and "Bicyclists must walk their bicycles through the
memorials and along Tidal Basin walks". The memorials are every closed OSM way tagged
`historic=memorial|monument` (or `memorial=*`, not a park) or `place=islet` whose
centroid is on the grounds.

| File | Bytes | sha256 |
| --- | --- | --- |
| `grounds.geojson` | 4,294 | `17e4f51f0b3314ddc00473472924df0e7899e4d952a765275cddd3a7289ab037` |
| `walk-only.geojson` | 6,782 | `15264549428a49997210d06f1b7632efe180384443c92eaf008fcfa417edc259` |

Refresh: re-read the ways and relation above from the OSM API and rebuild the same
selection when a memorial is added to the grounds or the grounds' boundary moves.
