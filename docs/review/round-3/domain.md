### Cycling / DC-region domain — REVISE (3 blocking)

Round-2 domain fixes verified genuinely better: urban/rural speed split is real and plumbed from
the Census layer per way, Loudoun gravel is no longer top-tier, `cycleway=no` no longer counts as a
facility, boundary-street handling is correct and Eastern Avenue now names Prince George's, lanes
are normalised per direction before the Furth tables (the mistake most LTS implementations make),
bike-lane width reads the cycleway's own width, elevation tile naming/banding is right for this
region, and the reference-route measurements reproduce the README tables exactly.

**B1. Shoulder credit is unbounded by speed and lane count.** CONFIRMED BY ME:

    VA-7, 55 mph, 8 lanes, 8ft shoulder       -> LTS3  "mixed traffic, 35 mph or above, rideable shoulder"
    VA-7, 55 mph, 8 lanes, painted bike lane  -> LTS4  "bike lane, 40 mph or above"
    VA-7, 55 mph, 8 lanes, nothing            -> LTS4

A painted bike lane is strictly better provision than a shoulder, and the classifier rates the
shoulder a tier safer. `_bike_lane_tier` floors at LTS4 for >=40 mph; the mixed-traffic path has no
floor, so the credit reaches across it. `is_top_tier` is LTS4 only, and Beginner's "zero top-tier
stress distance" invariant and the road-exposure report both key on it — so on Leesburg Pike,
River Road (MD-190), and any 45-55 mph road with a surveyed `shoulder:width`, Beginner routes onto
it and reports nothing. MINE: I wrote the shoulder tests this session using a 45 mph two-lane
secondary and never tested multilane or >=40 mph. Fix: floor the credit at LTS4 for >=40 mph and
never on a multilane road, or route shoulders through `_bike_lane_tier` so there is one table.

**B2. Three of five sidepath-only crossings still match nothing, and the fixture is not wired in.**
(a) "Key Bridge" != OSM's `Francis Scott Key Bridge`; "14th Street Bridge (Mount Vernon Trail
connection)" is a label, not a name (OSM has George Mason Memorial / Rochambeau / Arland D.
Williams Jr. Memorial); "Woodrow Wilson Bridge path" != `Woodrow Wilson Memorial Bridge`. Only
Chain Bridge matches. The mechanism changed from dead ids to unmatchable names; the data did not,
and the Key Bridge row is still inert — third round on this file. (b) `ReferenceData.load` reads
`<DATA_ROOT>/reference/crossings.json`; nothing in the repo, compose or docs puts the checked-in
fixture there. (c) The legality half is dead code: `graph.lua` reads `rm:bridge_bicycle` and the
remap turns it into `bicycle=yes/no`, but no stage ever emits it — `run.py` writes only
`trail_class`, `stress_tier`, `lit`. The Quality bar's "legality tagger test" has no tagger.

**B3. Key Bridge and Chain Bridge are recorded roadway-illegal; both roadways are bike-legal.**
Bicycles are permitted on both (Chain Bridge is a standard climb out of Georgetown). The row
conflates "the roadway is illegal" with "the only provision is a sidepath" — different claims,
true of different bridges in this list. It bites today because Chain Bridge is the row that
matches: `is_trail_class` returns true for the Chain Bridge *roadway* on every variant, so
Trailmaxxing's road-exposure report counts a roadway bridge as trail and Group Ride's trail-share
invariant is measured against a polluted denominator.

**SHOULD-FIX:** S1 a real VDOT count cannot relieve a rural road — the relief is gated on
`speed_mph <= 35` which reads the *assumed* 50, so evidence can only ever hurt (Snickersville
Turnpike at AADT 900 -> LTS4; posted 35 -> LTS3 "low volume"). The high-volume bump has no speed
gate at all. S2 `trunk`/`trunk_link` are in neither speed table (US-1, US-50, New York Ave NE).
S3 conflation lets a parallel trail take a motor-traffic count and the tie-break is extract order —
reversing way order moves a VDOT count from two GW Parkway blocks onto the Mount Vernon Trail, and
one-to-one exclusivity then denies it to both roadway blocks. S4 `group-purple-line` is 51% in
Maryland; README and PLAN both say all five city rides stay inside the District. S5 the segment
table drops most per-way derived values the plan names — stress time windows (Beach Drive /
Sligo Creek weekend closures have nowhere to live), jurisdiction layers (`_jurisdictions` is
computed and read by nothing), sharp bends per mile (implemented, tested, called by nothing),
lane count and width. S6 the parkway reversal cannot be expressed by the chosen mechanism: nothing
produces the conditional tags (OSM uses `oneway:conditional`, nothing converts it) and
`least_restrictive` can only ever relax, never restrict — so the named motivating case cannot work.
S7 the fixture omits Frederick Douglass, Whitney Young, Benning Road (all bike-legal), Theodore
Roosevelt (prohibited, `trunk` so not caught by MOTOR_ONLY) and American Legion. S8 every
region-defining layer has no producer: no coverage polygon, no osmium extract, no jurisdiction
loader, no reference-data producer — so `_state_at` returns None everywhere, no border node is ever
inserted, and the whole state-crossing dial does nothing on a real build. Also: no `Closure` model
or admin, though phase 1 names "closure editing".

**NIT:** grade5 dirt farm track -> LTS1 via the `track: 15.0` speed default, reintroducing exactly
what `classes.py` excludes `track` from TRAIL_CLASS to prevent; bare numeric `maxspeed` read as
km/h (45 -> 28 mph -> LTS2); shoulder width key list narrower than the presence list; **`BorderCrossing`'s
docstring still says node ids come from a reserved NEGATIVE range** — a round-1 bug described as
current design in the model the admin displays; reference README gain 2361 vs test 2360;
`DEFAULT_MAXSPEED_MPH` referenced nowhere; DC traffic-circles fixture absent (phase 2, recorded).
