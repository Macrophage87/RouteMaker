# Potomac and Anacostia crossings

The checked-in list the plan calls for, with expected roadway and sidepath bike
legality and the authority on each of the three layers per crossing.

It does two jobs, and neither of them is seeding the override table — that
table is the admin's, filled with reviewed rows and read by
`overrides.load_approved`, and nothing here ever reaches it.
`install_reference_data.py` copies this file to
`<DATA_ROOT>/reference/crossings.json`, `ReferenceData.load` reads it at rebuild
time, and the tile build resolves it against the clipped extract by name.

## What is in scope, and what is missing

The set is the road and path crossings of **the Potomac and the Anacostia**
inside the coverage box, plus the rail and transit structures standing at those
same crossings. On the Potomac that runs from the American Legion Bridge
downstream to the Woodrow Wilson Bridge; on the Anacostia, from the Benning Road
Bridge downstream to the confluence. Those two rivers are here because they are
where a wrong answer is expensive: each is a barrier tens of kilometres long
with a handful of crossings, so a crossing the router gets wrong does not cost a
detour of a block, it costs the ride.

Nothing else is in scope, and the absences are deliberate rather than pending:

* **Other water crossings** — Rock Creek, Four Mile Run, Cabin John Creek, the
  Northwest and Northeast Branches. They are crossed every few hundred metres
  and OSM's own tagging carries them; a structure list adds nothing, because
  there is no midpoint heuristic to override when the alternative is the next
  bridge along.
* **Crossings outside the coverage box** — Point of Rocks, White's Ferry, the
  Nice/Middleton Bridge. A row for a structure the clip does not contain
  resolves against nothing and reports itself unmatched on every rebuild.
* **The Anacostia's rail crossings.** These are a real gap and not a rule. The
  Potomac's two rail structures have rows — Long Bridge and the Fenwick Bridge —
  on the rule stated below: a structure at a crossing this file already has an
  opinion about gets a row whatever it carries, so that its identity is recorded
  here rather than rediscovered on a neighbouring row's note, which is exactly
  how Fenwick's name was found. CSX's Anacostia crossings meet that rule and
  have no rows, because nobody has reviewed them: their OSM spellings, their
  owners and which of them still carry track are all unchecked, and a row
  guessed at would be worse than an absent one. They carry no way a router can
  use, so nothing routes wrongly today; what is lost is the identity check, and
  a reviewer who can name them should add them.

The list is therefore complete for **road and path** crossings of the two rivers
and incomplete for rail. Both halves of that sentence matter: an operator
reading an unmatched-name warning needs to know whether a crossing missing from
the log is missing because the extract lost it or because this file never had
it.

The first job is to answer, per structure, the questions the midpoint
heuristic gets wrong: `resolve_sidepath_bridge_ids` decides which roadways the
no-trail variant (Mass Ride's, and any other ride's with trails off) drops,
`resolve_mass_ride_only_bridge_ids` decides
which roadways the standard and e-bike variants bar because they are for a
trails-off ride only, and
`resolve_bridge_bicycle_legality` decides what `rm:bridge_bicycle` carries into
`graph.lua` on every variant.
Memorial Bridge is one authority end to end; the "14th Street Bridge" is
**five** parallel structures with different answers (three highway spans, the
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
  sidepath-only, and the span the old single row's values described. **It is
  pinned by `osm_way_id` to way 546096009.** It claimed the plain name "11th
  Street Bridge", and on the 2026-09-24 extract that name is on one way only:
  the `bridge:name` of way 546095934, an I-695 motorway span named Southeast
  Freeway, so the row's `true` landed on an interstate (the remap's motor-only
  guard refused to grant it, but the real span got nothing). That claim is
  removed. By name the span could only be reached as "11th Street Southeast",
  which four bridge ways carry; only 546096009 crosses the Anacostia (178 m of
  its 238 m over the river's water area, and across the `waterway=river`
  centreline), and the other three are short ways south of the water. The
  owner's statement of 2026-09-25 is the cross-check: the south-westernmost of
  the three spans is the local one and carries the shared-use path on its
  south-west side. The geometry agrees — 546096009 crosses the centreline
  south-west of every I-695 way, and the path, way 546096004 (`cycleway`,
  Anacostia Riverwalk Trail, `bicycle=designated`, no access restriction), runs
  about 12 m south-west of it. The owner also confirmed that the roadway is
  legal to ride, against OSM's `bicycle=no` on it, so the remap writing
  `bicycle=yes` there is intended.
* **11th Street Bridge (I-695 inbound)** and **(I-695 outbound)** — the two
  freeway spans, barred outright, which the owner confirmed on 2026-09-25.
  Their OSM spellings are the least confident claim in this file, and on the
  2026-09-24 extract neither resolves: no way carries either. They are
  motorway class, so a ride is kept off them by highway class whatever the
  name does. **The inbound row is pinned to way 546095934**, the only freeway
  way that crosses the river drawn — and, being oneway, travelled — north-west
  toward the Southeast Freeway. **The outbound row is not pinned:** that side
  splits north of the river into the I-295 mainline (546095942) and the DC-295
  ramp (546095943), both crossing the centreline, and one `osm_way_id` cannot
  name two ways. It needs a list of ids, or stays unmatched, which it does
  today. A miss is said out loud: neither row is
  `sidepath_only`, and until `resolve_bridge_bicycle_legality` started returning
  its own unmatched names, only the sidepath resolver reported anything — so
  these two, and the twelve other legality-only rows, could resolve against
  nothing on every rebuild and appear in no log at all.

And it supplies four independent answers to the tile build, from four
different columns. Do not OR them together; a rebuild that did once passed its
own test while being inert, because every row where it mattered happened to
agree.

* `sidepath_only` — routing-relevant, and read only by the no-trail variant
  (Mass Ride's layer 1), which drops the roadway of a row that sets it: true means a mass
  ride cannot practically use this crossing's roadway. It is set today on
  Chain Bridge, which the owner decided on 2026-09-26 is "Not a mass-ride
  crossing" (its District approach, Canal Road NW, stays barred; the row's
  note has the three statements in order and why the roadway is dropped
  rather than left as a dead end), and where the roadway is barred anyway
  (the George Mason span and the Wilson Bridge roadway). Key Bridge carried
  it until the owner's decision of 2026-09-26 — "Mass ride can cross the
  Potomac at Chain Bridge, Key Bridge, and Memorial bridge without using a
  trail." — and with it the no-trail variant had no crossing there at all,
  since the sidewalk beside the roadway is trail class and dropped as such.
  Key Bridge is now the one mass-ride crossing into Virginia. The no-trail
  variant is kept off every bridge sidewalk by `is_trail_class`, not by this
  column. It says nothing about legality and must never be treated as a legal
  claim.
* `roadway_mass_ride_only` — routing-relevant, the other way round: true means
  the owner reserves the roadway for a trails-off ride (a mass ride, or any
  ride with "Allow bike paths and trails" off), so the no-trail variant keeps
  it and the standard and e-bike variants bar it (`variants.inject()` writes
  `bicycle=no`, and on a directional `bicycle:forward`/`:backward` key already
  present, and `inject_tags` withholds the row's `rm:bridge_bicycle`
  on those two variants so the transform cannot grant the roadway back). An
  ordinary rider then crosses by the sidepath, which is its own trail-class
  way that no resolver reaches. The owner set it on 2026-09-26 for Key Bridge
  ("I wouldn't route someone onto that outside of a mass ride.") and
  Arlington Memorial Bridge ("Same with memorial bridge."); both have a
  bike-legal sidewalk or cycleway on the structure for the other two variants
  to use, which the rows' notes name. A row may not combine it with
  `sidepath_only` or with `roadway_bicycle_legal: false` — the roadway would
  be in no graph — and `variants.check_crossing_rows_consistent` refuses
  either at load. It is a routing rule, not a legal claim, and for that reason
  it stands over an approved `bicycle=yes` access override on the same way:
  the override says the roadway is legal, which `roadway_bicycle_legal`
  already says, and not that ordinary riders are routed onto it. The bar also
  sets any `bicycle:conditional`, `bicycle:forward:conditional` or
  `bicycle:backward:conditional` present to a bare `no`, because
  `routemaker_remap.remap_conditional_access` would otherwise reopen a
  direction from a conditional's least restrictive branch.

  **The no-trail variant is not a mass-ride-only variant.** PLAN.md:99 gives
  Group Ride's "Allow bike paths and trails" toggle, when off, the no-trail
  variant as well, and PLAN.md:86 puts every dial on every preset, so any
  trails-off ride is routed on the Key and Memorial roadways. The owner was
  asked on 2026-09-26 whether a trails-off Group Ride should be kept off
  them, and answered "No, allow them" ("A trails-off Group Ride may use those
  bridge roadways like a mass ride."); and on 2026-09-26 what trails-off
  should do for the other ride types, and answered "Every type, roadways ok"
  ("Offer trails-off on every ride type; like Group Ride, it may use the Key
  and Memorial roadways."). So these roadways are for any trails-off ride.
  `variants.variant_for` gives the no-trail variant to every request with
  trails off; it takes the two toggles and no ride name. The route API asks
  `core.presets.variant_for_ride`, which gives the no-trail graph to a request
  with `trails_off` (the "Trails off" switch, built from OWNER-DECISIONS 463,
  on every ride type) and, through the preset's own variant, to Mass Ride,
  which is always trails off and does not pass through `variant_for`.
  The bar also closes the tags upstream's `graph.lua` would otherwise grant
  bicycle access from over `bicycle=no` - every `cycleway*` key and
  `vehicle:forward`/`:backward` set to `no`, `oneway:bicycle` to `yes`
  (`variants.REOPENING_KEYS`) - by rewriting them, since the extract writer
  can only lay values over the source's tags and never remove one.
* `roadway_bicycle_legal` — a legal fact about the **roadway**, read by every
  variant alike, because access is not a request-time dial. False means OSM
  carries `bicycle=no` on the roadway itself, or that the roadway is a class
  bicycles are barred from (the Rochambeau and Theodore Roosevelt spans are
  `motorway` with no `bicycle` tag at all), or that there is no roadway at
  all: the three 14th Street highway spans, the two 11th Street freeway spans,
  the Wilson Bridge roadway, the Theodore Roosevelt and American Legion
  bridges, and the two rail structures. True
  means the roadway is an ordinary, legal road, whatever its comfort - Key
  Bridge and Memorial Bridge are both `true` even though
  `roadway_mass_ride_only` keeps ordinary riders off them.
  `resolve_bridge_bicycle_legality` turns this into the
  `rm:bridge_bicycle` tag `graph.lua` already reads.

  **The roadway, and not the path on it.** A shared-use path on a bridge is
  mapped as its own `highway=cycleway` or `footway` way, tagged `bridge=yes`
  and named after the structure — that is what the Wilson path, the 14th Street
  path and the Key Bridge sidewalk all look like in OSM. The resolver excludes
  trail-class ways from the name match for that reason. Without the exclusion
  the column barred the path as well as the roadway, on every variant, and the
  remap's `bicycle=no` then deleted the only bicycle crossing of the Potomac at
  those points from every graph.

* `ordinary_ride_penalty_way_ids` — retired on 2026-09-27 (the owner: "Retire
  it (Recommended)"). It put a routing penalty on the 11th Street local span
  (546096009) and its ten south-landing ways for the owner's "Steer to the
  path" of 2026-09-26 ("Keep it legal but add a penalty on that roadway for
  ordinary rides so the Riverwalk wins when it's close in length."). Those
  ways are curated LTS 4 now (`fixtures/overrides/2026-09-27-owner-stress.json`;
  the owner: "11th street is LTS4"), and the stress penalty of LTS 3-4 is the
  same `bicycle=use_sidepath` write; the owner's words stand in those rows. A
  file that still carries the column is refused at load
  (`variants.MalformedCrossingRow`), so an old installed copy cannot pass.
  The owner's acceptance of what the penalty did to trips that start or end
  on those ways stands for the tier that replaced it (2026-09-27): "Yes, keep
  it. For recreational rides, getting there enjoyably trumps a higher stress
  shorter route. We can change this gor more commute centric routes." (quoted
  as typed).

### The approaches: owner decisions of 2026-09-26

A crossing is only as usable as the roads at either end of it, and those are
not this file's to open. The owner answered, for each Potomac and Anacostia
roadway a mass ride was given that day, what happens at its ends:

* **Key Bridge**, the Virginia approaches (North Fort Myer Drive and North Lynn
  Street, US 29, `bicycle=no` in OSM): "Bikes are legal, but there's a side
  path that's a better option for most." Opened for every variant by approved
  access overrides; ordinary riders keep to the sidewalk because the bridge's
  roadway is `roadway_mass_ride_only`.
* **Chain Bridge**, the District approach (Canal Road NW, `bicycle=no`): "No".
  Left barred. The Clara Barton Parkway, the other road off that end, was not
  in the question and stays as OSM tags it (`bicycle=no`). Asked whether that
  leaves Chain Bridge a mass-ride crossing: "Not a mass-ride crossing" — so
  the row is `sidepath_only` and the no-trail variant drops the roadway.
* **Arlington Memorial Bridge**, the Virginia landing on Columbia Island
  (motorway or `bicycle=no` exits only): "Turn at Memorial Circle". An
  out-and-back for a mass ride; no access change.
* **11th Street local span**, the south landing (11th Street SE,
  `bicycle=no`): "Yes, legal for all". The landing runs on through three more
  11th Street SE ways and three Martin Luther King Jr Avenue SE ways, also
  `bicycle=no`, before a bicycle may leave it, and of those the owner said,
  the same day, "Legal for all. It might be discouraged as it's a very busy
  road". Legal for all, so all ten are opened for every variant by approved
  access overrides; "might be discouraged" is not an access decision. What
  follows is this project's reading, not the owner's words: nothing in the
  graph discourages those ways on account of their stress tier. The tier
  reaches the router only as a comfort tag on tier-1 ways (the remap's
  `cycleway=track`), and Default is a layer-2 preset with no stress-weighted
  ranking. Measured on a rebuilt graph of the 2026-09-24 extract with the
  rows loaded: a standard or e-bike route southbound from the Navy Yard
  (38.8760, -76.9950) to 38.8660, -76.9880 took the local span's roadway
  (546096009) and Martin Luther King Jr Avenue SE, 2.455 km, where without
  the rows it took the Anacostia Riverwalk Trail (546096004), 2.538 km. The
  owner was asked whether the planner should steer those riders back to the
  path, and chose "Steer to the path" ("Keep it legal but add a penalty on
  that roadway for ordinary rides so the Riverwalk wins when it's close in
  length."). That was `ordinary_ride_penalty_way_ids`, above, retired
  2026-09-27 for the curated LTS 4 of those ways.

Access corrections go through the override table, the plan's one audited path
for them, never through this file: the rows are checked in at
`fixtures/overrides/2026-09-26-owner-bicycle-access.json` and loaded as
approved, audited `Override` rows by `manage.py load_access_overrides` (see
`fixtures/overrides/README.md`). They depend on this file's rows of the same
day - opening Key Bridge's Virginia approaches is safe for ordinary riders only
because `roadway_mass_ride_only` bars them from the roadway - so they are loaded
only after this file is reinstalled under `<DATA_ROOT>/reference/`, which the
rebuild checks (docs/OPERATIONS.md, "A deploy that changes the crossings
fixture or loads access overrides").

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

**Matching is also restricted to the region this file is about**, because a
name is not a place. `variants.CROSSINGS_SCOPE` is a box, west/south/east/north
(-77.20, 38.77, -76.94, 38.99), and a row's names reach only a way whose every
located point lies inside it; a way the extract cannot locate at all is refused.
It exists because the coverage region grew: when the owner extended it to
Baltimore and the Mason-Dixon line on 2026-09-24, the "Key Bridge" row began
matching Baltimore's Francis Scott Key Bridge — four I-695 motorway ways that
carry the name in `bridge:name` — as well as the four US 29 trunk ways across
the Potomac. The box is the extent of the ways this file's rows correctly reach
on the 2026-09-24 extract (-77.1800 to -76.9607, 38.7924 to 38.9711: the
American Legion Bridge to the Benning Road Bridge, and the Wilson Bridge's
roadway) rounded out by 0.02 degrees on every side. One box for the whole file,
not a point per row: it answers "is this way about these two rivers at all",
which is one question for every row, and which structure *within* the region a
name means is still the name's job — the box cannot stop a row landing on the
wrong span of the same crossing, as the 11th Street local span did. Both
resolvers take it from one function, `variants.is_crossing_candidate`, with the
bridge and trail-class guards, so they cannot disagree about which ways are
eligible. A row added for a crossing outside the box will never match until the
box is widened, and says so in the unmatched log.

A row's names are matched against **both `name` and `bridge:name`** on the way.
`name` on a road way is the *street*: the way across the Anacostia at
Pennsylvania Avenue SE carries `name=Pennsylvania Avenue Southeast`, because
that is what the road is called, and "John Philip Sousa Bridge" is on it only in
`bridge:name` — which is OSM's conventional home for a structure's own name on a
road. Reading `name` alone meant every row named for the structure rather than
for the street could only resolve where a mapper happened to put the structure's
name in both, and the miss looked exactly like a stale way id: the row reported
unmatched and its columns did nothing. Both keys are read; neither widens *which
ways* are eligible, which is still bridge-tagged and not trail class.

A name may be claimed by one row only. The names merge into one flat dict, so a
name claimed twice would resolve to whichever row was written last — silently,
and with the two rows disagreeing about the columns this file exists to record.
`variants.check_crossing_names_unique` refuses that at load time, and the same
reasoning is why the unplaceable alias "George Kennan Memorial Bridge" has been
removed from the American Legion row: an alias nothing places can only ever
match the wrong way.

**Thirteen rows are `osm_names_verified: true`, checked against the Geofabrik
DC+MD+VA extract of 2026-09-24 clipped to COVERAGE_BBOX; five are not.** Overpass
is blocked in this environment, so the check was made on the extract itself:
every bridge-tagged way in it carrying any of the file's names was read with
`extract.read_ways` and put through `variants.is_crossing_candidate` and
`variants.way_names`, exactly as the resolvers do, and each row's matches were
compared by highway class, `ref`, `name`, `bridge:name`, `bicycle`, oneway
direction and location against the structure the row's note describes. A row
is `true` only where every name it claims lands on that structure and nothing
else. What the check found and changed:

* Three rows matched nothing on the spelling they claimed, and now claim what
  the extract carries: "Theodore Roosevelt Memorial Bridge" (seventeen
  motorway ways — not `trunk`, as this file and the row's note said),
  "Arland D. Williams Junior Memorial Bridge" (six motorway ways, Junior
  written out) and, for the Wilson Bridge path row, the four spellings its
  twenty I-95/I-495 roadway ways carry across `name` and `bridge:name`.
  "Woodrow Wilson Bridge" is also the `name` of the path itself, which is
  trail class and so never reached.
* The Whitney Young row's second alias, "Whitney M. Young Jr. Memorial
  Bridge", is on no way and is removed; the first matches.
* The Rochambeau row's note said the span carries the US-1 local lanes; the
  extract has it as I-395's express lanes (`ref=I 395 EXPR`), with US 1 on the
  Williams and George Mason spans.
* The Key Bridge roadway (all four ways) carries `bicycle=no` and `foot=no`,
  and the Frederick Douglass roadway `bicycle=use_sidepath`. Both rows say
  `roadway_bicycle_legal: true`, and the remap writes `bicycle=yes` over those
  tags. The check did not change the columns; the owner confirmed both claims
  on 2026-09-25, so the override is intended, and each row's note records it.
* Not verified: the three 11th Street spans (above), and the two rail
  structures. Two of the 11th Street rows are pinned by way id, and a pin is
  checked by geometry rather than by name, so their `osm_names_verified` stays
  `false`: it describes the names, which are still unconfirmed. The Fenwick Bridge's spelling is right — it is the `bridge:name`
  of two `railway=subway` ways — and Long Bridge's name is on no way; neither
  can ever match, because `extract.read_ways` keeps highway ways only.

`variants.unverified_crossing_names` returns the rows still `false`; the loader
(`ReferenceData.load` in `run.py`) logs it at rebuild time, alongside the unmatched-name warning the two resolvers produce
between them — one line over the union of what
`resolve_sidepath_bridge_ids` and `resolve_bridge_bicycle_legality` each failed
to find, because a crossing the extract does not carry is one fact about one
bridge however many of this file's columns it silences. Both logs matter and
say different things: an unmatched name
means the clip moved or the name changed and the rule is not biting at all; an
unverified name means the rule is biting, but on a spelling nobody has
confirmed against the map. Clearing `osm_names_verified` to `true` for a row is
a thing to do only after checking that row against a real extract, not as part
of a fixture edit that merely looks confident.

`osm_way_id` remains as an override for a crossing someone has pinned against
the clipped extract by hand. It is ignored when 0 rather than matched against
way 0, which exists and is not a bridge. Two rows carry one: the 11th Street
local span (546096009) and inbound freeway span (546095934), both chosen by
where the ways cross the river on the 2026-09-24 extract. A pin is honoured as
written, outside the region check, and it goes out for its id even when the
extract no longer carries that way — but since the owner's decision of
2026-09-25 that case is **reported**: both resolvers name a row whose pinned way
is not among the ways they were given (`variants.crossing_misses`, shared by
the two), and it joins the one "crossings not found in the extract" warning
`ReferenceData.load` logs. A warning, not a refusal; the rebuild still runs. A
pin the map has split or replaced therefore shows up in the rebuild log on the
first rebuild after it happens, and is re-pinned from there.

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
