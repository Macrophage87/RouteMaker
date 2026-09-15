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

`osm_way_id` is 0 where the id has not yet been recorded against the clipped
extract. The loader ignores those rows rather than matching way 0, so filling
them in is a prerequisite for the sidepath rule actually biting; the pipeline
test asserts the loader's behaviour on a row with a real id.

Nothing here is a legal statement about access. It records what a rider can use
and who to ask, and the authority names are the community's own working
knowledge, maintained under the same not-legal-advice line the info cards carry.
