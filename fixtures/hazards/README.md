# Hazard list

Known road hazards OpenStreetMap misses or may lose, read when the rebuild writes the segments
and the route network (`src/routemaker/hazards.py`, `src/pipeline/hazard_layer.py`). A road on
the list keeps its stress rating, but routes price it as LTS 4 (paths aren't priced); a route
that still rides it marks it and names it, and the road panel's "Watch for" row says it.
A broken file stops the rebuild (`HazardListRefused`); a street whose cross streets are not
found in the extract is logged and left out, never guessed.

Each entry has an `id`, its `kinds` (`cobbles`, `rails`), a `source`, and where it is: OSM
`ways` (way ids), or a `street` by its OSM name `between` two cross streets, or both. A street
entry marks each segment piece of that street lying along the line between the two junctions,
within 20 m [65 ft] either side of it and never past either junction: 20 m [65 ft] of a piece
on that stretch, or half of it, marks the piece. It suits a straight street.

| File | Entries |
| --- | --- |
| `2026-10-19-dc-cobbles-and-rails.json` | Georgetown's O and P Streets NW from Wisconsin Ave to 35th St (setts and the old streetcar tracks); DC Streetcar's rails on H St NE (3rd St to 15th St) and Benning Rd NE (15th St to Oklahoma Ave), closed to service on 31 March 2026. |

What OSM already says is read from it first: `surface=sett`, `cobblestone`,
`cobblestone:flattened` or `unhewn_cobblestone` is cobbles; a road tagged `embedded_rails`, and
a `railway=tram` line (or an `embedded=yes` railway, or a disused tram line) lying along a road,
is rails.
