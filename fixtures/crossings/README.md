# Potomac and Anacostia crossings

The checked-in list the plan calls for, with expected roadway and sidepath bike
legality and the authority on each of the three layers per crossing.

It does two jobs. It seeds the override table, so a listed bridge bypasses the
midpoint heuristic entirely — Memorial Bridge is one authority end to end, the
former "14th Street Bridge" is three parallel structures under different
authorities and different answers (which is why it is three rows here, not
one), and the Wilson Bridge path is a separate structure again, so splitting at
the midpoint gives the wrong answer for each.

And it supplies two independent sets to the tile build, from two different
columns. Do not OR them together; a rebuild that did once passed its own test
while being inert, because every row where it mattered happened to agree.

* `sidepath_only` — routing-relevant, and read only by the no-trail (mass ride)
  variant. True means a mass ride cannot practically use this crossing's
  roadway even where an individual rider legally can: Key Bridge and Chain
  Bridge are ordinary, bike-legal climbs that hundreds of people cannot safely
  share, being narrow with no shoulder and no way off mid-span. This is what
  keeps the no-trail variant off the Key Bridge sidewalk — an eight-foot path
  with no way off it mid-span, for a field of hundreds — via
  `resolve_sidepath_bridge_ids` and `variants.inject()`. It says nothing about
  legality and must never be treated as a legal claim.
* `roadway_bicycle_legal` — a legal fact, read by every variant alike, because
  access is not a request-time dial. False means OSM carries `bicycle=no` on
  the roadway itself: the 14th Street freeway spans (George Mason Memorial,
  Rochambeau), the Wilson Bridge roadway, and the Theodore Roosevelt Bridge.
  True means the roadway is an ordinary, legal road, whatever its comfort -
  Key Bridge and Chain Bridge are both `true` even though `sidepath_only` is
  also `true` for both. `resolve_bridge_bicycle_legality` turns this into the
  `rm:bridge_bicycle` tag `graph.lua` already reads.

At least one row (Theodore Roosevelt Bridge, American Legion Bridge) has
`roadway_bicycle_legal: false` **and** `sidepath_only: false` — barred outright,
with no sidepath standing in as an alternative. Do not assume every legally
barred crossing has one.

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
is absent.

**Every `osm_names` entry in this file is `osm_names_verified: false`, without
exception, including the ones a round-3 reviewer supplied by name (Francis
Scott Key Bridge; George Mason Memorial Bridge, Rochambeau Bridge, Arland D.
Williams Jr. Memorial Bridge; Woodrow Wilson Memorial Bridge).** Overpass is
blocked in this environment, so nothing here has been checked against a real
extract, regardless of how confident the source. `variants.unverified_crossing_names`
returns this list; the loader (`ReferenceData.load` in `run.py`) logs it at
rebuild time, alongside the unmatched-name warning `resolve_sidepath_bridge_ids`
already produces. Both logs matter and say different things: an unmatched name
means the clip moved or the name changed and the rule is not biting at all; an
unverified name means the rule is biting, but on a spelling nobody has
confirmed against the map. Clearing `osm_names_verified` to `true` for a row is
a thing to do only after checking that row against a real extract, not as part
of a fixture edit that merely looks confident.

`osm_way_id` remains as an override for a crossing someone has pinned against
the clipped extract by hand. It is ignored when 0 rather than matched against
way 0, which exists and is not a bridge.

Nothing here is a legal statement about access. It records what a rider can use
and who to ask, and the authority names (`police`, `row_owner`, `manager`) are
the community's own working knowledge, maintained under the same not-legal-advice
line the info cards carry — this is true of every row, and especially of the
rows added in round 3 (Frederick Douglass Memorial, Whitney Young Memorial,
Benning Road, Theodore Roosevelt, American Legion), whose authorities have not
been cross-checked against any current agency list. The Wilson Bridge row
additionally carries `row_owner_verified: false`: MDTA operates the bridge, but
ownership of the connecting right-of-way on the Virginia side is genuinely
unclear rather than merely unconfirmed, and that uncertainty is called out on
the row rather than folded into the blanket "community knowledge" disclaimer
every row already carries.
