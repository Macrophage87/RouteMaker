# Hazard list

Known road hazards OpenStreetMap misses or may lose, added to the map's hazard symbols and the
road panel's "Watch for" row when the rebuild writes the segments (`src/routemaker/hazards.py`,
`src/pipeline/hazard_layer.py`). Display only: no entry changes a stress rating or a route.
A broken file stops the rebuild (`HazardListRefused`); a street whose cross streets are not
found in the extract is logged and left out, never guessed.

Each entry has an `id`, its `kinds` (`cobbles`, `rails`), a `source`, and where it is: OSM
`ways` (way ids), or a `street` by its OSM name `between` two cross streets, or both. A street
entry marks each segment piece of that street whose middle lies in the box round the two
junctions (30 m [100 ft] wider each way), so it suits a straight street.

| File | Entries |
| --- | --- |
| `2026-10-19-dc-cobbles-and-rails.json` | Georgetown's O and P Streets NW from Wisconsin Ave to 35th St (setts and the old streetcar tracks); DC Streetcar's rails on H St NE (3rd St to 15th St) and Benning Rd NE (15th St to Oklahoma Ave), closed to service on 31 March 2026. |

What OSM already says is read from it first: `surface=sett`, `cobblestone`,
`cobblestone:flattened` or `unhewn_cobblestone` is cobbles; a road tagged `embedded_rails`, and
a `railway=tram` line (or an `embedded=yes` railway, or a disused tram line) lying along a road,
is rails.
