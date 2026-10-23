# Major bike corridors

The well-known corridors the owner named, which the map always draws as the most
popular class (`bike_popular` 3, tile property `popular`), whatever the Capital
Bikeshare model (`pipeline.bikeshare_corridors`) gives them. Read by the rebuild from
its image (`pipeline.major_corridors`); nothing here is loaded into the database.

A file is `{"version": 1, "corridors": [...]}`. A corridor is `id`, `names` (regular
expressions, matched case-insensitively against the whole of a way's `name`, its long
route relation's name, or the street of the bike lane beside it (`sidepath_name` less
"bike lane")) and `box` (`[west, south, east, north]`; a way counts when the middle point
of its line is inside). With `"bike_ways_only": true` only a way tagged `highway=cycleway`,
`path` or `footway`, or one named for the street it runs beside, counts: the street's
cycle track, not the road. `ways` (`{"osm id": "name"}`) adds ways OSM leaves unnamed, labelled by that name. A corridor that matches no way is warned about in the rebuild
log, with the miles each corridor matched, so a name OSM spells differently shows up.

| File | Decision |
|---|---|
| `2026-10-21-owner-major-corridors.json` | The owner, 2026-10-21: Rock Creek Trail, the Capital Crescent Trail, the Metropolitan Branch Trail, Q and R Streets NW, Pennsylvania Avenue NW (Washington Circle to the Capitol), K Street NW, the W&OD, the Mount Vernon Trail and the Sligo Creek Trail; and, for the owner's "etc." ("All work"), the Anacostia River Trail, the Custis Trail, Four Mile Run Trail, the Northwest Branch Trail and the 15th Street NW protected bike lane (its bike ways only); then the C&O Canal Towpath, the WB&A Trail, the B&A Trail and the BWI Trail; and the major Baltimore trails (Gwynns Falls, Jones Falls, Herring Run, the Inner Harbor Promenade, the Torrey C. Brown Trail, the Grist Mill Trail); the Irving Street NW bikeway with Kenyon Street NW's cycle track (its bike ways only; 2026-10-23 "Add the Irving and Kenyon bikeway"); the Millennium Trail, the Matthew Henson Trail, the ICC Trail, Ohio Drive at Haines Point the Broadneck Peninsula Trail, the Fairfax County Parkway Trail and the Cross County Trail (its mountain-bike parts keep their own look). |
