# Potomac and Anacostia crossings

The checked-in list the plan calls for, with expected roadway and sidepath bike
legality and the authority on each of the three layers per crossing.

It does two jobs, and neither of them is seeding the override table — that
table is the admin's, filled with reviewed rows and read by
`overrides.load_approved`, and nothing here ever reaches it.
`install_reference_data.py` copies this file to
`<DATA_ROOT>/reference/crossings.json`, `ReferenceData.load` reads it at rebuild
time, and the tile build resolves it against the clipped extract by name.

The first job is to answer, per structure, the two questions the midpoint
heuristic gets wrong: `resolve_sidepath_bridge_ids` decides which roadways the
no-trail (mass ride) variant drops, and `resolve_bridge_bicycle_legality`
decides what `rm:bridge_bicycle` carries into `graph.lua` on every variant.
Memorial Bridge is one authority end to end; the "14th Street Bridge" is
**six** parallel structures with different answers (three highway spans, the
Long Bridge carrying rail, and the Charles R. Fenwick Bridge carrying Metro's
Yellow Line); the "11th Street Bridge" is **three** (one local span that
carries bikes and two I-695 freeway spans that do not); and the Wilson Bridge
path is a separate structure again. Splitting any of them at the midpoint gives
the wrong answer. The second job is the authority columns, below.

The 14th Street complex has been wrong here twice and is worth stating plainly,
because the names do not say which structure is which:

* **Arland D. Williams Jr. Memorial Bridge** — the 1950 **highway** span,
  carrying I-395 **northbound into** the District. It is the span Air Florida
  flight 90 struck in January 1982, renamed in 1985 for the passenger who
  passed the rescue line to others and drowned. This file previously recorded
  it as the Metrorail bridge carrying the Mount Vernon Trail connection; it is
  neither of those things, and that is a matter of record rather than an OSM
  question. The *direction* is not: that is community knowledge at medium-high
  confidence, and this file had it backwards until round 5.
* **George Mason Memorial Bridge** — the 1962 highway span, I-395
  **southbound out of** the District, and the one carrying the shared-use path:
  the Mount Vernon Trail connection that ramps to Columbia Island on the
  Virginia side and Ohio Drive SW on the District side is a sidewalk on this
  span. Two community-knowledge claims here, both medium-high and neither a
  matter of record: *which* highway span carries the path (from the reviewer
  who rides it), and which direction each of these two spans carries — the
  pair was swapped until round 5. The rows say so.
* **Rochambeau Bridge** — the 1972 span, carrying the US-1 local lanes.
* **Charles R. Fenwick Bridge** — the Metro (Yellow Line) crossing, absent from
  this file entirely until its name turned up on the Williams row's note. A
  Metro bridge carries no roadway and no path, so it has no bicycle access of
  any kind.
* **Long Bridge** — freight and commuter rail, and a row of its own since
  round 5. It had none, on a stated rule — "no row for anything rail-only, it
  carries no way a router can use" — that this file then broke for Fenwick,
  which is rail-only in exactly the same sense. One rule for both: a structure
  at a crossing this deployment has an opinion about gets a row, whatever it
  carries, so that its identity is recorded here rather than rediscovered on
  somebody else's row. `roadway_bicycle_legal` and `sidepath_only` false
  together is what "no bicycle access of any kind" looks like in these two
  columns, and Fenwick and Long Bridge now both read that way.

The 11th Street crossing is three structures and was one row, whose note said
the local span carries bikes and the freeway spans do not — two answers to the
two columns the pipeline reads, written where nothing reads them:

* **11th Street Bridge (local span)** — 11th Street SE, a bike-legal roadway
  with Anacostia Riverwalk connections at either end. Neither barred nor
  sidepath-only, and the span the old single row's values described.
* **11th Street Bridge (I-695 inbound)** and **(I-695 outbound)** — the two
  freeway spans, barred outright. Their OSM spellings are the least confident
  claim in this file and may well resolve against nothing; unlike the Theodore
  Roosevelt Bridge, which is `trunk`, these are motorway class, so a ride is
  kept off them by highway class even when the name misses.

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
* `roadway_bicycle_legal` — a legal fact about the **roadway**, read by every
  variant alike, because access is not a request-time dial. False means OSM
  carries `bicycle=no` on the roadway itself, or that there is no roadway at
  all: the three 14th Street highway spans, the two 11th Street freeway spans,
  the Wilson Bridge roadway, the Theodore Roosevelt and American Legion
  bridges, and the two rail structures. True
  means the roadway is an ordinary, legal road, whatever its comfort - Key
  Bridge and Chain Bridge are both `true` even though `sidepath_only` is also
  `true` for both. `resolve_bridge_bicycle_legality` turns this into the
  `rm:bridge_bicycle` tag `graph.lua` already reads.

  **The roadway, and not the path on it.** A shared-use path on a bridge is
  mapped as its own `highway=cycleway` or `footway` way, tagged `bridge=yes`
  and named after the structure — that is what the Wilson path, the 14th Street
  path and the Key Bridge sidewalk all look like in OSM. The resolver excludes
  trail-class ways from the name match for that reason. Without the exclusion
  the column barred the path as well as the roadway, on every variant, and the
  remap's `bicycle=no` then deleted the only bicycle crossing of the Potomac at
  those points from all three graphs.

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

A name may be claimed by one row only. The names merge into one flat dict, so a
name claimed twice would resolve to whichever row was written last — silently,
and with the two rows disagreeing about the columns this file exists to record.
`variants.check_crossing_names_unique` refuses that at load time, and the same
reasoning is why the unplaceable alias "George Kennan Memorial Bridge" has been
removed from the American Legion row: an alias nothing places can only ever
match the wrong way.

**Every `osm_names` entry in this file is `osm_names_verified: false`, without
exception, including the ones a round-3 reviewer supplied by name (Francis
Scott Key Bridge; George Mason Memorial Bridge, Rochambeau Bridge, Arland D.
Williams Jr. Memorial Bridge; Woodrow Wilson Memorial Bridge) and the ones
round 5 added (John Philip Sousa Bridge; the three 11th Street spans; Long
Bridge).** Overpass is
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

## The authority columns

The Potomac spans are one authority end to end, not two. The DC–Virginia
boundary on the Potomac is the **1791 Virginia shoreline**, not the channel, so
a span from the District to Virginia lies within the District along essentially
its whole length and MPD's jurisdiction runs the full distance. The Arlington
Memorial Bridge row had that shape from the start; Key Bridge and Chain Bridge
were recorded with a police split down the middle, which is the midpoint
heuristic this file exists to override, written into the data. Chain Bridge's
Virginia end was also named as Fairfax County when the abutment is in Arlington
County — wrong twice over, since above the shoreline it is not a Virginia
authority's to police at all.

The Wilson Bridge is the exception that proves it: it is the one Potomac
crossing that touches all three jurisdictions, so its row names Alexandria,
Prince George's County **and** MPD. Its `row_owner` moved from MDTA to MDOT SHA
— MDTA is Maryland's toll authority and this bridge is toll-free, which is the
tell — and keeps `row_owner_verified: false`, because the Virginia-side
connecting right-of-way may be VDOT's again.

The American Legion Bridge is the same reasoning with the line in a different
place. Above Washington the Potomac is Maryland's to the Virginia bank, which
*Virginia v. Maryland* (2003) left undisturbed as to the boundary itself while
deciding what Virginia may do from its own shore — so that span lies
essentially in Maryland along its whole length, and its row names Montgomery
County Police and the Maryland State Police, with Fairfax County reached only at
the Virginia approach beyond the abutment. That is the shape the Key Bridge row
gives VDOT and Arlington County, and the split down the middle it replaces was
the midpoint heuristic again. Medium confidence.

One agency, one spelling: `row_owner` reads **MDOT SHA**, never "Maryland SHA",
which this file used in one row while using MDOT SHA in another. A test refuses
either retired spelling in any authority value; both are still discussed in the
notes, which is where the reasoning belongs.

**The authority columns are pinned by a test, by hand, against literals.** The
round-4 corrections — the shoreline putting Key and Chain Bridge wholly under
MPD, Chain Bridge's Virginia end being Arlington rather than Fairfax, the Wilson
Bridge naming all three jurisdictions, Wilson's owner moving to MDOT SHA —
lived only in this file and in prose, and a reviewer reverted every one of them
with the whole suite green. `EXPECTED_CROSSINGS` in `tests/test_variants.py` now
carries `police` and `row_owner` beside the two flags, so reverting one fails by
name.

Boundaries are a matter of record; the policing and ownership that follow from
them are the community's own working knowledge, at the confidence each row's
note states, and are not legal statements.

Nothing here is a legal statement about access. It records what a rider can use
and who to ask, and the authority names (`police`, `row_owner`, `manager`) are
the community's own working knowledge, maintained under the same not-legal-advice
line the info cards carry — this is true of every row, and especially of the
rows added in round 3 (Frederick Douglass Memorial, Whitney Young Memorial,
Benning Road, Theodore Roosevelt, American Legion) and round 5 (Long Bridge, the
two 11th Street freeway spans), whose authorities have not been cross-checked
against any current agency list. The Wilson Bridge row additionally carries
`row_owner_verified: false`: MDOT SHA operates the bridge — not MDTA, which is
the toll authority and which this paragraph still named after the row had been
corrected — but ownership of the connecting right-of-way on the Virginia side
is genuinely unclear rather than merely unconfirmed, and that uncertainty is
called out on the row rather than folded into the blanket "community knowledge"
disclaimer every row already carries. The Long Bridge row carries it for a
kindred reason: the structure is CSX's, the trains that use it are not all
CSX's, and nothing here has checked which entity holds the right-of-way at
either abutment.
