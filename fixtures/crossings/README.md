# Potomac and Anacostia crossings

The checked-in list the plan calls for, with expected roadway and sidepath bike
legality and the authority on each of the three layers per crossing.

It does two jobs. It seeds the override table, so a listed bridge bypasses the
midpoint heuristic entirely — Memorial Bridge is one authority end to end, the
14th Street bridges are several parallel structures under different ones, and
the Wilson Bridge path is a separate structure again, so splitting at the
midpoint gives the wrong answer for each.

And it supplies the sidepath-only set to the tile build. A bridge whose only
bike provision is a narrow sidewalk has to be trail-class on the no-trail
variant, or the router will hand a mass ride the Key Bridge sidewalk — an
eight-foot path with no way off it mid-span, for a field of hundreds.

Crossings resolve against the extract **by name**, not by way id. An OSM way id
is the wrong thing to check into a repository: it changes whenever a mapper
splits a bridge into two ways or replaces it, and a fixture full of stale ids
fails silently. This one did — every row carried `osm_way_id` 0, so the sidepath
set was empty, so the no-trail variant treated the Key Bridge sidewalk as an
ordinary roadway, and nothing reported it. A name ages at the pace of the bridge
rather than the pace of the map, which is how the authority columns here already
work.

Matching is restricted to ways tagged as bridges, so a street approaching a
crossing and named after it does not inherit the crossing's legality. Where the
name in this file differs from the `name` tag on the bridge in OSM, add an
`osm_names` array listing the tagged spellings; the row's `name` is used when it
is absent. **These have not been verified against a real extract** — the rebuild
logs every crossing it could not find, and an empty `osm_names` on a row that
appears in that log is the thing to fix.

`osm_way_id` remains as an override for a crossing someone has pinned against
the clipped extract by hand. It is ignored when 0 rather than matched against
way 0, which exists and is not a bridge.

Nothing here is a legal statement about access. It records what a rider can use
and who to ask, and the authority names are the community's own working
knowledge, maintained under the same not-legal-advice line the info cards carry.
