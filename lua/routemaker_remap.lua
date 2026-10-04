-- RouteMaker's derived-tag remap.
--
-- Valhalla's tile schema is fixed and unknown tags are dropped, so every derived
-- value that must influence routing has to be expressed through an attribute the
-- bicycle costing already reads. This module is the mapping, kept separate from
-- Valhalla's own graph.lua so that it can be unit tested and so that a Valhalla
-- upgrade is a rebase of their file rather than a merge of ours into it.
--
-- Two attributes are deliberately never written: `highway` and `maxspeed`.
-- They are not free fields. `highway` sets DirectedEdge::classification() and
-- use(), which decide the hierarchy level an edge lands on, whether shortcuts
-- are built over it, the road-class factor in bicycle costing, hierarchy-limit
-- pruning in bidirectional A*, and whether Odin emits a maneuver at all.
-- Downgrading a high-stress arterial so Beginner avoids it would also penalise
-- it for Mass Ride, which wants that roadway at maximum use_roads, demote it out
-- of the arterial hierarchy, and change the maneuver counts other invariants are
-- asserted on. One global remap cannot serve use_roads 0 and use_roads 1 through
-- the same field, so the stress signal travels by use_roads at layer 2 and
-- stress-weighted ranking at layer 4 instead.

local M = {}

-- A tag this remap wants *removed* rather than rewritten. Lua tables cannot
-- carry a nil value, so a removal has to be signalled by a value the entry point
-- recognises. An earlier version wrote a `_clear_<key>` marker key instead,
-- which nothing consumed: the permissive access tag stayed, gate_cost stayed
-- inert on exactly the nodes it exists for, and the marker itself leaked into
-- Valhalla's tag table as a junk key. A unique table cannot collide with any
-- real tag value.
M.REMOVE = setmetatable({}, { __tostring = function() return "<remove>" end })

-- Reporting a rule violation from inside the transform.
--
-- `error()` does not halt a tile build. `LuaTagTransform::Transform` runs each
-- entry point under lua_pcall and, when the call fails, returns an *empty* tag
-- map for that element. So an element that trips an error() guard is not
-- refused, it is silently stripped of every tag and dropped out of the graph,
-- and the build reports success. Every guard here was written as error(), which
-- made each of them do the opposite of its comment: the border-control guard
-- exists to keep a state crossing passable and would have deleted the crossing
-- node instead.
--
-- A violation is therefore loud and leaves the element intact. The offending
-- change is not applied, a line goes to stderr under a fixed prefix that the
-- build-log check searches for, a sentinel tag is set on the element, and the
-- violation is appended here so an in-process harness can read it back.
--
-- The sentinel is deliberately a key Valhalla does not read: it cannot reach a
-- tile and cannot change routing, which is the point - it marks the element for
-- whoever is watching the transform without becoming a fact about the graph. It
-- sits outside the `rm:` namespace so the entry point does not strip it before
-- anything can see it.
M.VIOLATION_TAG = "rm_violation"
M.VIOLATION_LOG_PREFIX = "ROUTEMAKER-VIOLATION"
M.violations = {}

function M.record_violation(kv, reason)
  M.violations[#M.violations + 1] = reason
  if kv ~= nil then
    kv[M.VIOLATION_TAG] = reason
  end
  io.stderr:write(M.VIOLATION_LOG_PREFIX .. ": " .. reason .. "\n")
end

-- Access values that say no more than "the public may use this way".
--
-- An allowlist, not a deny list. Upstream's own `access` table maps six values
-- to false - no, agricultural, forestry, discouraged, emergency, psv - and six
-- more onto its private (destination-only) flag, and a deny list written from
-- memory catches `no` and misses the rest. Each of the six was checked through
-- the real transform; `no`, `agricultural`, `forestry` and `discouraged` are
-- dropped outright (filter 1) and `emergency` and `psv` arrive with bicycle
-- access already false.
M.PERMISSIVE_ACCESS = {
  yes = true,
  permissive = true,
  designated = true,
  official = true,
  public = true,
  allowed = true,
}

-- The keys that carry a way-level access statement this remap must not talk
-- over. `vehicle` belongs here and is easy to miss: OSM's `vehicle` includes
-- bicycles and upstream reads `vehicle=no` as barring them, so a cycleway write
-- flips that way from unroutable to routable exactly as `access=no` does.
M.ACCESS_KEYS = { "access", "vehicle", "bicycle", "bicycle:forward", "bicycle:backward" }

-- The values of `oneway` upstream's `oneway` table reads as one-way for motor
-- traffic, and the junctions it makes one-way whatever `oneway` says. The same
-- two lists as Python's `pipeline.variants.ONEWAY_VALUES` and
-- `ONEWAY_JUNCTIONS`; `reversible`, `alternating`, `no` and a way that says
-- nothing are two-way for this purpose.
M.MOTOR_ONEWAY = { yes = true, ["true"] = true, ["1"] = true, ["-1"] = true }
M.ONEWAY_JUNCTION = { roundabout = true, circular = true }

--- Whether a way is one-way for motor traffic, as upstream reads it.
function M.is_motor_oneway(tags)
  return M.MOTOR_ONEWAY[tags.oneway] or M.ONEWAY_JUNCTION[tags.junction] or false
end

-- What `pipeline.variants.close_contraflow` writes onto a one-way's
-- `bicycle:backward` on the no-trail graph: `none`, the value upstream's bicycle
-- table reads as false without mistaking it for a second direction. It closes
-- the direction against the traffic, which no rider on a one-way had by the
-- way's own class anyway, and says nothing about whether a bicycle may ride
-- the way with the traffic. So on a one-way it is not a restriction here:
-- read as one, a one-way tagged `bicycle:backward=yes` (a contraflow grant)
-- would turn restricted on the no-trail graph alone, and lose the stress
-- penalty and the lane removal that graph's rides are priced by.
M.CLOSED_REVERSE_BICYCLE = "none"

--- Whether a way's own tags leave bicycle access unrestricted.
function M.access_is_unrestricted(tags)
  for _, key in ipairs(M.ACCESS_KEYS) do
    local value = tags[key]
    if
      value ~= nil
      and not M.PERMISSIVE_ACCESS[value]
      and not (
        key == "bicycle:backward"
        and value == M.CLOSED_REVERSE_BICYCLE
        and M.is_motor_oneway(tags)
      )
    then
      return false
    end
  end
  return true
end

-- The four key forms a cycleway tag arrives in, and the same list Python's
-- `tags.CYCLEWAY_KEYS` holds. `cycleway` and `cycleway:both` speak for both
-- sides of the road, `cycleway:left` and `cycleway:right` for one side each.
M.CYCLEWAY_KEYS = { "cycleway", "cycleway:both", "cycleway:left", "cycleway:right" }

-- The precedence within one side, most specific first: the side key answers for
-- its side, `:both` for a side the side key leaves unsaid, and the bare key for
-- whatever is left. The same table as Python's `tags.CYCLEWAY_SIDE_KEYS`, which
-- the classifier reads, and `tests/test_lua_remap.py` holds the two together:
-- this file and the classifier have to agree about what a side says, or the
-- guard below and the tier it is guarding would be reading different roads.
M.CYCLEWAY_SIDE_KEYS = {
  left = { "cycleway:left", "cycleway:both", "cycleway" },
  right = { "cycleway:right", "cycleway:both", "cycleway" },
}

--- What one side of the road says about a cycleway, or nil if nothing does.
--
-- The value of the most specific key present, as Python's `_first` reads it:
-- an empty value is no value.
function M.cycleway_on_side(tags, side)
  for _, key in ipairs(M.CYCLEWAY_SIDE_KEYS[side]) do
    local value = tags[key]
    if value ~= nil and value ~= "" then return value end
  end
  return nil
end

--- Whether the way already says something about a cycleway on any side.
--
-- Presence, not value. A way tagged `cycleway:both=no` has been surveyed and
-- found to have none, and a way tagged `cycleway:left=lane` has a painted lane
-- on one side; writing `cycleway=track` over either is this file asserting a
-- separated track the mapper did not tag, and on the second it also overwrites
-- what they did tag. The guard read the bare `cycleway` key alone, so both of
-- those passed straight through it - and a one-sided lane is how most of the
-- District's network is written.
--
-- Read side by side, through the classifier's precedence, rather than key by
-- key: the question is whether either side of the road has been spoken for,
-- which is the question the classifier's side record answers before it scores
-- the way. The bare `cycleway=track` this file writes is, by the same
-- precedence, a statement about any side nobody has spoken for - so it may be
-- written only where neither side has been.
function M.declares_cycleway(tags)
  for _, side in ipairs({ "left", "right" }) do
    if M.cycleway_on_side(tags, side) ~= nil then return true end
  end
  return false
end

-- The way-level access statement the crossings fixture may not talk over. It is
-- `ACCESS_KEYS` minus the bicycle keys, and the difference between the two lists
-- is the whole of the fixture's authority; see `M.bridge_may_be_granted`.
M.WAY_ACCESS_KEYS = { "access", "vehicle" }

-- Classes where "the roadway is bike-legal" cannot be true whatever a fixture
-- row says. `trunk` is deliberately absent: US-1, US-50 and New York Avenue NE
-- are `trunk` here and are routinely bicycle-legal, which is the same call
-- `stress.MOTOR_ONLY` makes.
M.MOTOR_ONLY_HIGHWAY = { motorway = true, motorway_link = true }

--- Whether the fixture's `roadway_bicycle_legal: true` may be written onto this way.
--
-- The write is a *widening* one, so it needs the guard the cycleway write has,
-- and it needs a different one, because the two writes answer to different
-- authorities.
--
-- What the fixture may override: an explicit `bicycle=no` on the roadway. PLAN
-- names this write as "bridge legality sets `bicycle=yes/no` per roadway or
-- sidepath way", and a row saying a bridge's roadway is legal is exactly a
-- reviewed correction to OSM's own `bicycle` tagging on that bridge - which is
-- the thing the fixture exists to carry, at the confidence its note states.
-- Refusing the override would leave the `yes` half of the write able to do
-- nothing at all: a bridge whose roadway OSM already leaves unrestricted needs
-- no row to be routable.
--
-- What it may not override: the way's own `access` or `vehicle` statement. A
-- crossing row is community knowledge about whether bicycles may use a roadway;
-- it is not a claim that a way tagged `access=no` or `access=private` is open to
-- the public, and `vehicle=no` bars bicycles under OSM semantics. Upstream
-- drops `access=no` outright (filter 1, no edge at all), so writing `bicycle=yes`
-- over it is the same widening the cycleway write was guarded against in round
-- 4 - a legal claim in the widening direction with no override row and no
-- review, bypassing the table the plan makes the sole audited path for an
-- access correction.
--
-- Nor a motor-only class. No row in the fixture claims a motorway roadway is
-- legal and none should; a row that did would be a fixture error, and this is
-- the one place it could turn into `bicycle=yes` on an interstate.
--
-- The `false` half needs no guard at all and gets none: it only ever narrows,
-- and a fixture that says a roadway is barred agreeing with tagging that
-- already bars it costs nothing.
function M.bridge_may_be_granted(tags)
  if M.MOTOR_ONLY_HIGHWAY[tags.highway] then return false end

  -- `electric_bicycle` is deliberately *not* read here, and this file used to
  -- read it.
  --
  -- The e-bike variant is built by writing `bicycle=no` onto every way tagged
  -- `electric_bicycle=no` (`variants.inject_tags`), because Valhalla's bicycle
  -- costing is what reads the bicycle tag and there is no e-bike access mask to
  -- write to. That change is made in the extract; this transform then runs over
  -- the extract, sees a bridge whose roadway the fixture calls legal and whose
  -- `bicycle=no` looks exactly like OSM's own tagging on a barred bridge, and
  -- would override it back to `yes`, reverting the variant's whole decision on
  -- the one class of way this file is allowed to widen.
  --
  -- The protection is real and it belongs in the injection, not here. One Lua
  -- script serves all three extracts - `mjolnir.graph_lua_name` is a single
  -- path in every build config - so a guard in this file cannot tell which
  -- variant is being parsed and has to decline the legality row on the standard
  -- and no-trail extracts too, where the row applies and nothing has written
  -- `bicycle=no`. `inject_tags` knows the variant, so it suppresses the
  -- bridge-legality tag on an `electric_bicycle=no` way for the EBIKE variant
  -- alone and leaves the other two extracts carrying it. Declining the grant
  -- here as well would take the row away from the two variants that are
  -- entitled to it, so this function stays silent about the key.
  for _, key in ipairs(M.WAY_ACCESS_KEYS) do
    local value = tags[key]
    if value ~= nil and not M.PERMISSIVE_ACCESS[value] then
      return false
    end
  end
  return true
end

-- Increasing roughness, matching Valhalla's surface enum ordering.
M.SURFACE_ORDER = {
  paved_smooth = 1, paved = 2, paved_rough = 3, compacted = 4,
  dirt = 5, gravel = 6, path = 7, impassable = 8,
}

-- The minimum ridable surface per bicycle_type. Valhalla refuses outright any
-- edge worse than this; avoid_bad_surfaces does not relax it.
M.MIN_RIDABLE = { Road = 4, Hybrid = 5, Cross = 6, Mountain = 7 }

-- The strictest configured type's threshold. Used as a ceiling on roughness: a
-- reviewer penalty may not push a surface past it.
--
-- The reason is narrower than an earlier comment here claimed. Valhalla's hard
-- exclusion arms only when avoid_bad_surfaces is exactly 1.0; below that,
-- surface is a cost multiplier and nothing is refused outright. So this cap is
-- not usually the difference between a route and no route - it is what keeps a
-- penalty from making an edge disproportionately expensive, and what keeps it
-- safe for any preset that does arm the exclusion by setting the dial to its
-- maximum.
M.MAX_PENALISED_ROUGHNESS = M.MIN_RIDABLE.Road
M.REVIEWER_PENALTY_FLOOR = M.MAX_PENALISED_ROUGHNESS  -- retained name, see above

--- Cap a surface downgrade so it stays ridable under every configured type.
--
-- Two bounds, and the second is easy to omit. A penalty may not push a surface
-- past the strictest ridable threshold, and it may not *improve* one that is
-- already rougher than that threshold: clamping naively lifts a genuine gravel
-- road to compacted, which would quietly overwrite surveyed data with the cap
-- and make the rural references look better surfaced than they are.
function M.bounded_surface(current, proposed)
  local now = M.SURFACE_ORDER[current] or M.SURFACE_ORDER.paved
  local want = M.SURFACE_ORDER[proposed] or now
  local ceiling = math.max(now, M.REVIEWER_PENALTY_FLOOR)
  local capped = math.min(math.max(want, now), ceiling)
  for name, rank in pairs(M.SURFACE_ORDER) do
    if rank == capped then return name end
  end
  return current
end

--- Remap one way's tags. Returns a table of *changes* only.
-- What a way inside a cemetery is made (remap_way): destination-only.
M.CEMETERY_ACCESS = "destination"

function M.remap_way(tags, derived)
  derived = derived or {}
  local out = {}

  -- Stress tier travels through the facility and comfort attributes the bicycle
  -- costing already reads, never through road class.
  -- Never on a trail-class way. Upstream's transform derives bike access from
  -- the cycleway tag, so writing cycleway=track onto a footway, a sidewalk or
  -- steps that carry no explicit bicycle tag turns bicycle access *on* for them.
  -- DC's sidewalk mapping is extensive, and it would put every preset on the
  -- pavement. Those ways already land on a cycleway or path use class and get
  -- upstream's accommodation factor, so the write gains nothing there anyway.
  --
  -- And never on a way whose own tags restrict access. This is the same
  -- mechanism as the trail-class case and it is the more serious half of it:
  -- upstream derives bicycle access from the cycleway tag, so writing
  -- cycleway=track onto a way tagged access=no takes it from dropped
  -- (filter=1, no edge at all) to routable in both directions. `classify()`
  -- rates a private farm track, a closed NPS service road and a gated living
  -- street LTS1 - correctly, it grades stress and not access - and the write
  -- then turned each of them into a legal claim in the widening direction, with
  -- no override row and no review, bypassing the table the plan makes the sole
  -- audited path for an access correction. That is the geometry the rural Group
  -- Ride references sit on.
  --
  -- The guard is wider than the ways that demonstrably flip today. A way tagged
  -- access=private, destination, customers, permit or residents keeps its
  -- bicycle access under upstream's tables but arrives marked private,
  -- destination-only; writing "there is a separated cycle track here" onto it
  -- asserts provision the tagging denies. The write only ever carried a comfort
  -- signal that use_roads at layer 2 and stress-weighted ranking at layer 4
  -- carry anyway, so declining it on a restricted way costs nothing that
  -- matters and removes a whole class of this failure rather than one instance.
  --
  -- Superseded, 2026-09-27. Stress used to reach the graph as `cycleway=track`
  -- on every tier-1 roadway, which priced a quiet residential street exactly as
  -- a protected cycle track and below an off-road trail, and priced tiers 3 and
  -- 4 no differently from tier 2. The owner's order (`routemaker.facility`)
  -- puts ordinary streets last whatever their stress, and asks for a slider
  -- that runs from the fastest legal route to "low stress routes are used
  -- unless there's no other option". So the signal now travels two separate
  -- ways: the facility class (`M.apply_facility`), and the stress penalty below
  -- (`M.STRESS_PENALTY_TIER`), whose weight is the request's `use_roads`.
  --
  -- The cautions above still bind both: neither writes a cycleway key onto a
  -- trail-class way, and neither widens access.
  M.apply_facility(tags, derived, out)
  -- On the no-trail variant the neutral rewrite has already removed the
  -- value, so the split finds nothing to copy there.
  M.split_both(tags, out)

  if derived.reviewer_surface_penalty then
    out.surface = M.bounded_surface(tags.surface or "paved", derived.reviewer_surface_penalty)
  end

  -- Bridge legality is per roadway or sidepath way, from the crossings fixture
  -- rather than from the midpoint heuristic.
  --
  -- The two halves are not symmetric and were written as though they were. `no`
  -- only narrows and is always written. `yes` widens - it is the same class of
  -- write as `cycleway=track` above, and on a way tagged `access=no` upstream
  -- takes it from dropped to routable - so it goes through
  -- `bridge_may_be_granted`, which lets the fixture override an explicit
  -- `bicycle=no` on the roadway (that is what a legality row *is*) but never an
  -- `access` or `vehicle` restriction, and never on a motor-only class.
  if derived.bridge_bicycle_legal == false then
    out.bicycle = "no"
  elseif derived.bridge_bicycle_legal and M.bridge_may_be_granted(tags) then
    out.bicycle = "yes"
  end

  -- A way bicycles may not ride on any current ride type: a sidewalk in the
  -- District's Central Business District (OWNER-DECISIONS 104; `routemaker.cbd`
  -- decides which, and never a way signed bicycle=designated or a road), or
  -- mountain-bike singletrack (OWNER-DECISIONS 111; `routemaker.singletrack`).
  -- Only narrows. Singletrack is closed rather than charged: upstream sets a
  -- trail's use from its highway class and ignores `service` there, so the
  -- tier-5 entry charge cannot reach it, and `highway` may not be rewritten.
  --
  -- `bicycle=no` alone does not close every way. Upstream lets a directional
  -- key decide its own direction over plain `bicycle`, so the directions are
  -- closed too, last, below (`M.close_both_directions`). And a way that carries
  -- a mountain-bike rating, as nearly every singletrack way does, is reopened
  -- by Valhalla's C++ parser after the transform: lua/graph.lua strips the
  -- ratings from whatever upstream's transform leaves closed
  -- (`M.strip_ratings_if_closed`).
  if derived.no_bicycle then
    out.bicycle = "no"
  end

  -- The stress penalty: `bicycle=use_sidepath` on every way the classifier or
  -- a curated override rates tier 3 or more (never a trail-class way).
  -- Upstream's transform reads `use_sidepath` as bicycle access in both
  -- directions, exactly as `yes`, and Valhalla adds `3 * (1 - use_roads)` to
  -- the accommodation factor of such an edge (sif/bicyclecost.cc,
  -- `sidepath_factor_`) without changing its speed: a cost, not a bar, and no
  -- change to a route's reported duration. The request's `use_roads` - the
  -- stress slider - scales it from nothing at the fastest-legal end to "unless
  -- there's no other option" at the other, so one graph serves every position.
  -- `use_sidepath` is used here only for its cost; its OSM meaning, a
  -- compulsory sidepath, is not claimed, and nothing user-facing reads it.
  --
  -- It replaced the crossings fixture's ordinary-ride penalty (retired by the
  -- owner, 2026-09-27: "Retire it (Recommended)"), which wrote the same tag on
  -- the 11th Street local span and its south landing for the owner's "Steer to
  -- the path" of 2026-09-26 ("Keep it legal but add a penalty on that roadway
  -- for ordinary rides so the Riverwalk wins when it's close in length."); those
  -- ways are now curated LTS 4 (fixtures/overrides/2026-09-27-owner-stress.json)
  -- and so carry it by their tier.
  --
  -- Only where the way is already open to a bicycle, because `use_sidepath`
  -- grants access like `yes` and so must never be written over a refusal: not
  -- over `bicycle=no` (OSM's own, the e-bike variant's bar, a mass-ride-only
  -- roadway's bar, or a legality of false above), nor over a value that says
  -- more than "may ride" (`dismount`, `destination`, ...). On a way with no
  -- bicycle tag, only where nothing else restricts it *and* its road class
  -- admits a bicycle by default: upstream reads `use_sidepath` as "true" over
  -- the class default, so on an untagged motorway, footway or platform it
  -- would open a way the class keeps closed. Nor on an untagged
  -- `impassable=yes` way of an open class: upstream closes every mode there,
  -- and then reads `use_sidepath` as "true" all the same.
  --
  -- OSM's own alleys pay it too, whatever their tier (OWNER-DECISIONS 100 and
  -- 110: "Alley cut throughs should only be used if the roads are very
  -- problematic nearby", then "Stronger"): an alley is priced like an LTS 3
  -- street, so a route takes one only where the way round is LTS 4 or worse.
  -- Its stress tier - what the map shows - is unchanged, and it is not graded.
  if
    derived.stress_tier ~= nil
    and (derived.stress_tier >= M.STRESS_PENALTY_TIER or M.is_real_alley(tags))
    and not derived.is_trail_class
  then
    if M.may_penalise(tags, out.bicycle or tags.bicycle) then
      out.bicycle = M.STRESS_PENALTY_BICYCLE
    end
  end

  -- Graded (the owner, 2026-09-28: "Yes, grade them (Recommended)" - "LTS 4
  -- penalised more than LTS 3 at every slider position" - and "I'd probably
  -- want LTS 4 to be twice the stress level of LTS 3 at least."). A way's
  -- stress level is the cost its tier adds per metre over the same edge with
  -- no tier, as a multiple of the time cost (docs/DEVELOPMENT.md, "Graded
  -- stress"). With the penalty above alone the two tiers add the same, so a
  -- slider move could swap a tier-3 street for a shorter tier-4 one.
  --
  -- Valhalla 3.5.1's bicycle costing has no per-tier weight; what it prices
  -- per edge is fixed by the edge (sif/bicyclecost.cc): the roadway stress
  -- grows with the lane count (`0.05 * road_factor` a lane) and is multiplied
  -- by a speed penalty that rises with the edge's speed, and both are then
  -- multiplied by the accommodation factor the `use_sidepath` penalty lifts.
  -- So LTS 4 and up are given the graph's top speed and lane count - speed
  -- `maxspeed:practical` 140 (kMaxOSMSpeed), 15 lanes each way
  -- (kMaxLaneCount) - which lifts their added cost to at least twice LTS 3's
  -- at every slider position above 0 on roads posted up to 50 mph (the table
  -- in docs/DEVELOPMENT.md; faster tier-4 roads come to 1.75 or more). Only the
  -- cost moves: a bicycle's time comes from its own speed, not the edge's, and
  -- access from the bicycle keys. Only where the stress penalty holds (the
  -- way is open to a bicycle), never on a trail-class way, and not on the
  -- no-trail variant: Mass Ride's slider is locked at 0 and a mass ride takes
  -- the big roads by design.
  if
    derived.stress_tier ~= nil
    and derived.stress_tier >= M.GRADED_TIER
    and not derived.is_trail_class
    and not derived.facility_neutral
    and (out.bicycle or tags.bicycle) == M.STRESS_PENALTY_BICYCLE
  then
    out["maxspeed:practical"] = M.GRADED_SPEED
    out["lanes:forward"] = M.GRADED_LANES
    out["lanes:backward"] = M.GRADED_LANES
  end

  -- "Legal but avoid" (stress tier 5; the owner, 2026-09-27: "Maybe make a
  -- 5th category for legal but to be avoided"), charged only there (the
  -- owner's "Only tier-5 roads (Recommended)": "Rework it so only 'legal but
  -- avoid' roads pay the penalty; local-access streets stay normal."). On top
  -- of the stress penalty above, which Mass Ride's use_roads of 1.0 weighs at
  -- nothing, the roadway is given upstream's alley use (`service=alley`, which
  -- upstream reads onto `use` whatever the road class): Valhalla charges
  -- `alley_penalty` (core.presets.AVOID_ENTRY_PENALTY_S) each time a route
  -- enters an alley from something that is not one - cost only, no time, on
  -- every preset, and the edge stays routable. Nothing else in bicycle costing
  -- reads the alley use, and the road keeps its class. Bicycle costing reads
  -- no toll (it disables toll booth costs) and destination-only is shared with
  -- OSM's own local-access ways, which is why neither is the mechanism.
  --
  -- Only where the way is open to a bicycle and says nothing about service
  -- already. OSM's own alleys (`highway=service` + `service=alley`) would pay the
  -- same charge, so on them the service value is removed: they become the
  -- service roads they are, priced by `service_penalty` (Valhalla's 15 s) in
  -- place of `alley_penalty` (its 5 s).
  if
    derived.stress_tier == M.AVOID_TIER
    and not derived.is_trail_class
    and tags.highway ~= "service"
    and tags.service == nil
    and out.bicycle ~= "no"
    and (tags.bicycle == M.STRESS_PENALTY_BICYCLE or M.may_penalise(tags, tags.bicycle))
  then
    out.service = M.AVOID_SERVICE
  elseif tags.service == M.AVOID_SERVICE and tags.highway == "service" then
    out.service = M.REMOVE
  end

  if derived.lit ~= nil then
    out.lit = derived.lit and "yes" or "no"
  end

  for key, value in pairs(M.remap_conditional_access(tags)) do
    out[key] = value
  end

  -- A way inside a cemetery (`rm:cemetery`, pipeline.restricted_areas): no
  -- through-route, only a trip that starts or ends inside. The owner,
  -- 2026-09-29: "I don't want to encourage a cemetary cut through as it's
  -- disrespectful." (OWNER-DECISIONS 98). `access=destination` is upstream's
  -- destination-only (its `private` flag), so a route may enter only to reach
  -- a point inside. Written only where the way's own `access` leaves it open:
  -- a stricter statement (no, private) stays as it is, and a narrowing is
  -- never a widening.
  if derived.cemetery and (tags.access == nil or M.PERMISSIVE_ACCESS[tags.access]) then
    out.access = M.CEMETERY_ACCESS
  end

  -- Last, so no line above can grant a direction back: the conditional-access
  -- resolution writes `bicycle:forward` / `:backward` from OSM's own
  -- `bicycle=no` + `bicycle:conditional=yes @ ...`.
  if derived.no_bicycle then
    M.close_both_directions(out)
  end

  return out
end

-- `rm:no_bicycle` closes both directions, whatever else the way says.
--
-- `bicycle=no` is not upstream's last word on a direction. Its transform reads
-- `bicycle:forward`, then `vehicle:forward`, over plain `bicycle`, and before
-- that `oneway:bicycle=no`, `cycleway=opposite*` and the `cycleway:*` lane
-- tables can each set a direction open. So a singletrack way OSM also tags
-- `bicycle:forward=yes`, `oneway=yes` + `oneway:bicycle=no` or
-- `cycleway=opposite_lane` kept that direction open under `bicycle=no` alone
-- (SINGLETRACK-review-r0, finding 8). No singletrack or CBD sidewalk carries
-- any of them today; the NO-BIKE-PATHS rules will reach ways that do.
--
-- Writing both directional keys is the whole remedy. Upstream applies them
-- after every one of those grants (graph_upstream.lua's `:forward` and
-- `:backward` overrides follow the oneway and cycleway handling), and nothing
-- after them sets bicycle access true: the later lines only swap the two
-- directions (`oneway=-1`, `oneway:bicycle=-1`) or close them.
function M.close_both_directions(out)
  out["bicycle:forward"] = "no"
  out["bicycle:backward"] = "no"
end

-- Mountain-bike ratings reopen a closed way, in Valhalla's C++ and not its Lua.
--
-- Valhalla 3.5.1's PBF parser reads `mtb:scale`, `mtb:scale:imba`,
-- `mtb:scale:uphill` and `mtb:description` itself, after the Lua transform has
-- run, and any of them, whatever its value, `0` included, sets bicycle access
-- on the way, in each direction a one-way leaves to bicycles (a one-way's reverse
-- stays closed). It overrides `bicycle=no`, `bicycle=none`,
-- `access=no` and `vehicle=no`, on a path, footway, track or service road
-- alike. Upstream's graph.lua never reads these keys (only bare `mtb`, which
-- does not reopen anything), so neither this remap's suites nor
-- `supported_keys.txt`, which is extracted from that file, could see it. Only a
-- real tile build shows it (tests/test_tile_build_access.py).
--
-- That is why `rm:no_bicycle=singletrack` (OWNER-DECISIONS 90, 91, 111) never
-- reached the live graphs. `routemaker.singletrack` picks a way *by* its
-- `mtb:scale` rating, the remap writes `bicycle=no`, and the parser opens the
-- way again from the same rating. 753 of the 920 singletrack ways (461 km) were
-- routable in the 2026-10-03 build. The other 167 were closed only because
-- they also carry `foot=no`, so upstream's transform drops them before the
-- parser gets to them. 27 OSM-tagged `bicycle=no` / `access=no` rated ways had
-- been reopened the same way.
--
-- So lua/graph.lua calls this on the table upstream's transform returns, which
-- is the last thing the parser sees. Upstream has already settled access by
-- then, so its own `bike_forward` and `bike_backward` say whether the way is
-- closed, with no second reading of the access tags to drift from it. Where
-- either direction is closed, every `mtb:*` key is removed, and the tile
-- carries exactly the access upstream's transform decided.
--
-- One direction closed counts as closed. With the rating left on, the parser
-- reopens a direction `bicycle:forward=no` or `bicycle:backward=no` closed,
-- which is what stock Valhalla does. Without it, the tile holds
-- upstream's reading: the closed direction stays closed and the open one stays
-- open. "Closed" is anything but "true", as the parser reads it: a value
-- upstream's tables do not know leaves `bike_forward` unset, which the parser
-- takes as no access.
--
-- What the rating costs where it is removed: besides access, the parser also
-- reads a rating as the edge's surface. An open dirt path rated `mtb:scale=2`
-- gets the surface class `path`, and `dirt` without the rating. So the
-- strip is not made where access does not need it.
--
-- A one-way open to bicycles in its own direction keeps its ratings: the
-- parser keeps a one-way's reverse closed whatever the rating
-- (tests/test_tile_build_access.py), so there is nothing for it to reopen, and
-- stripping cost the Green Loop Trail (ways 1324891525 and 1324891526,
-- `oneway=yes`, `mtb:scale=3`, asphalt) its `path` surface class
-- (SINGLETRACK-review-r1). Upstream's output says it is that case without a
-- second reading of the access tags: `oneway` is "true", and the direction the
-- one-way runs - `bike_forward`, or `bike_backward` where `oneway_reverse` is
-- "true" (`oneway=-1`, which upstream has already swapped) - is "true". A
-- one-way closed in its own direction is stripped like any closure. A way open
-- both ways is untouched too: the C&O towpath keeps its `mtb:scale:imba=0`.
M.MTB_RATING_PREFIX = "mtb:"

--- Remove every `mtb:*` key from upstream's output when either direction is
-- closed to bicycles, but for a one-way's own reverse. Takes and changes the
-- table upstream's `ways_proc` returned; returns whether it removed anything.
function M.strip_ratings_if_closed(kv)
  if kv.bike_forward == "true" and kv.bike_backward == "true" then return false end
  if kv.oneway == "true" then
    local own = kv.oneway_reverse == "true" and kv.bike_backward or kv.bike_forward
    if own == "true" then return false end
  end
  local keys = {}
  for key in pairs(kv) do
    if type(key) == "string" and key:sub(1, #M.MTB_RATING_PREFIX) == M.MTB_RATING_PREFIX then
      keys[#keys + 1] = key
    end
  end
  for _, key in ipairs(keys) do kv[key] = nil end
  return #keys > 0
end

-- Directional conditional access, for the parkway reversal.
--
-- Valhalla reads `bicycle:forward` and `bicycle:backward` - both are in the
-- checked-in supported-key list - and does not read any `*:conditional` key at
-- all. Its own graph.lua carries a bare `-- TODO access:conditional`. So a road
-- signed against bicycles except at certain hours arrives in the graph as simply
-- barred, in both directions, at every hour of the week.
--
-- The static resolution is the *least* restrictive value across the base tag and
-- the conditional branches, never the most. A tile build cannot represent time,
-- so the choice is between a way that is routable when it is legal and a way
-- that is unroutable when it is legal too. An unroutable edge also tells the
-- rider nothing: the route simply goes another way and no part of the interface
-- can say why.
--
-- What this expresses, plainly, because the name it was given claims more than
-- it does. It opens a way that its base tags bar and a conditional permits: a
-- parkway signed `bicycle=no` with `bicycle:forward:conditional=yes @ (Sa,Su)`
-- becomes rideable in that direction at every hour, not only at the permitted
-- ones. It cannot express the reverse, and the Rock Creek and Potomac Parkway
-- rush-hour reversal it is named for is the reverse: a carriageway that is open
-- most of the week and closed, or reversed, during weekday rush hours is barred
-- only during those hours, and a static graph that tightened on the conditional
-- would bar it for the whole week. This remap therefore leaves that case
-- exactly as the base tags leave it. The reversal is not represented in the
-- graph at all; representing it needs either the time-conditioned report that
-- is phase 3's or the carriageway split named as the fallback in the plan.
--
-- Never tightening is the deliberate half of that and is not up for quiet
-- revision: tightening on a conditional is the one direction that would make
-- the graph assert a legal claim, which is the thing this project does not do.
M.ACCESS_RANK = {
  no = 1, private = 2, customers = 3, destination = 4,
  permissive = 5, designated = 6, yes = 6,
}

-- The values upstream's own `bicycle` table carries, read out of
-- lua/vendor/graph_upstream.lua rather than remembered. A value outside it maps
-- to nil there, which drops the override rather than granting it, so emitting
-- one is a silent no-op: it looks like a relaxation in this file and reaches the
-- graph as nothing. `customers` is the one rank above that upstream does not
-- carry. It stays in ACCESS_RANK because it can appear on an OSM way as the base
-- value a conditional is compared against, and it is never written.
M.EMITTABLE_BICYCLE = {
  no = true, private = true, destination = true,
  permissive = true, designated = true, yes = true,
}

--- Parse an OSM conditional value into a list of { value, condition } entries.
--
-- The separator is not parsed. Conditions carry `;` and `,` inside them, so the
-- rules are matched as `value @ (condition)` wherever they appear, which is
-- exact for every shape the wiki documents and cannot be tripped by a separator
-- inside a condition.
function M.parse_conditional(value)
  local out = {}
  if not value then return out end
  for branch, condition in value:gmatch("([%a_]+)%s*@%s*%(([^)]*)%)") do
    out[#out + 1] = { value = branch, condition = condition }
  end
  if #out == 0 and value:match("^%s*[%a_]+%s*$") then
    -- A bare value with no condition is not conditional at all, but it appears
    -- in the wild on these keys and reads as unconditional.
    out[#out + 1] = { value = value:match("^%s*([%a_]+)%s*$"), condition = nil }
  end
  return out
end

--- A conditional value that is less restrictive than the base, or nil.
--
-- An absent base tag counts as fully permissive, not as unknown. Valhalla's own
-- defaults already allow a bicycle on an untagged road, so there is nothing to
-- open and a time-limited restriction must not be written as a permanent one:
-- that is the tightening this remap does not do.
function M.least_restrictive(base, conditional_value)
  local branches = M.parse_conditional(conditional_value)
  if #branches == 0 then return nil end

  local best, best_rank = nil, M.ACCESS_RANK[base] or M.ACCESS_RANK.yes
  for _, branch in ipairs(branches) do
    local rank = M.ACCESS_RANK[branch.value]
    if rank and rank > best_rank and M.EMITTABLE_BICYCLE[branch.value] then
      best, best_rank = branch.value, rank
    end
  end
  return best
end

-- What on a one-way's own tags gives a bicycle the direction against the traffic,
-- as `pipeline.variants.has_contraflow_tag` reads them: `oneway:bicycle` waived
-- (or reversed), an `opposite*` cycleway value, a reverse-direction grant.
M.CONTRAFLOW_ONEWAY_BICYCLE = { no = true, ["false"] = true, ["0"] = true, ["-1"] = true }
M.REVERSE_GRANT = { yes = true, designated = true, permissive = true }

--- Whether a one-way's own tags speak for the direction against its traffic:
-- they grant contraflow, or carry a `bicycle:backward:conditional`, which is the
-- mapper's statement about that direction and no other.
function M.speaks_for_reverse(tags)
  if M.CONTRAFLOW_ONEWAY_BICYCLE[tags["oneway:bicycle"]] then return true end
  if M.REVERSE_GRANT[tags["bicycle:backward"]] or M.REVERSE_GRANT[tags["vehicle:backward"]] then
    return true
  end
  if tags["bicycle:backward:conditional"] ~= nil then return true end
  for _, key in ipairs(M.CYCLEWAY_KEYS) do
    local value = tags[key]
    if value ~= nil and value:sub(1, #"opposite") == "opposite" then return true end
  end
  return false
end

--- Resolve conditional access onto the directional keys Valhalla reads.
--
-- On a one-way for motor traffic the undirected `bicycle:conditional` speaks
-- for the traffic's direction only, and the reverse is not widened from it
-- unless the way itself speaks for the reverse (`speaks_for_reverse`). Written
-- as `bicycle:backward`, the widening is read by upstream as a second
-- direction: Pulaski Highway (`highway=trunk`, `oneway=yes`, `bicycle=no`,
-- `bicycle:conditional=yes @ (Sa-Su dawn-dusk; PH dawn-dusk)`) came out
-- rideable both ways on the standard, weekend and e-bike graphs, a remap
-- artifact and not a contraflow lane (contraflow review r1). `forward` and
-- `backward` are relative to the one-way's direction in upstream's reading,
-- `oneway=-1` included, so `backward` is the reverse on every one-way.
function M.remap_conditional_access(tags)
  local out = {}
  -- The undirected conditional applies to both directions unless a directional
  -- one is present for that direction, which is the wiki's own precedence.
  local both = tags["bicycle:conditional"]
  local reverse_closed = M.is_motor_oneway(tags) and not M.speaks_for_reverse(tags)

  for _, side in ipairs({ "forward", "backward" }) do
    local key = "bicycle:" .. side
    local conditional = tags[key .. ":conditional"] or both
    if side == "backward" and reverse_closed then conditional = nil end
    if conditional then
      -- Nothing is recorded about the condition here. An earlier version wrote
      -- `rm:access_conditional_<side>` for phase 3 to report on, and the entry
      -- point stripped it three lines later, before anything could read it: a
      -- write with no reader, and a comment claiming a consumer that does not
      -- exist. The source tag is still on the way in the extract, which is where
      -- phase 3's reporting will read it from when there is something to report
      -- it to.
      local base = tags[key] or tags.bicycle
      local resolved = M.least_restrictive(base, conditional)
      if resolved and resolved ~= base then
        out[key] = resolved
      end
    end
  end

  return out
end

-- One foot, in metres. OSM's maxwidth is metres unless a unit says otherwise,
-- and the unit that appears here is feet: the wiki's own imperial form is
-- `5'6"`, with `3'`, `3 ft` and `3 feet` all in use.
M.FOOT_M = 0.3048

--- An OSM maxwidth value in metres, or nil if it cannot be read.
--
-- The earlier version was `tonumber((value:gsub("[^%d%.]", "")))`, which does
-- not fail on the forms it cannot read - it silently returns a different
-- number. `3'` came out as 3 rather than 0.91, and `1,5` as fifteen metres
-- rather than one and a half: both a bollard the Cargo preset should be charged
-- for, read as a gap wide enough to ignore.
--
-- Anything this cannot read returns nil and the node keeps upstream's own
-- reading, which is the direction to fail in. Converting a bollard to a gate
-- adds cost; refusing to convert one leaves the rider's route no more expensive
-- than Valhalla already makes it, so an unreadable value costs an unmodelled
-- squeeze rather than a detour around a barrier that is not there.
function M.parse_width_m(value)
  if type(value) ~= "string" then return nil end
  local text = (value:lower():gsub("%s", ""))

  -- Comma as the decimal separator: "1,5" is one and a half metres. Only when
  -- it separates digits and appears once, so a list like "1,5,2" is refused
  -- rather than guessed at.
  local whole, fraction = text:match("^(%d+),(%d+)$")
  if whole then text = whole .. "." .. fraction end

  -- Feet, with or without inches: 5'6", 3', 3ft, 3feet.
  local feet, inches = text:match([[^(%d+%.?%d*)'(%d+%.?%d*)"?$]])
  if not feet then
    feet = text:match([[^(%d+%.?%d*)'$]])
      or text:match("^(%d+%.?%d*)ft$")
      or text:match("^(%d+%.?%d*)feet$")
  end
  if feet then
    return tonumber(feet) * M.FOOT_M + (tonumber(inches) or 0) * M.FOOT_M / 12
  end

  -- Metres, with or without the unit spelled out.
  local metres = text:match("^(%d+%.?%d*)$") or text:match("^(%d+%.?%d*)m$")
  return metres and tonumber(metres) or nil
end

--- Remap one node's tags.
function M.remap_node(tags)
  local out = {}

  -- gate_cost and gate_penalty apply only at gate nodes, while the narrow-gap
  -- furniture on trails here is overwhelmingly bollards and cycle barriers, for
  -- which Valhalla exposes no cost of its own. Mapping them onto the gate node
  -- type is what makes the Cargo preset's gate dial bite.
  -- gate_cost applies only where the node is a gate *and* carries no access
  -- tags: Valhalla multiplies the cost by (not tagged_access), and it sets
  -- tagged_access to 1 if *any* of access, motorcar, motor_vehicle, hgv, bus,
  -- taxi, psv, foot, wheelchair, bicycle, moped, mofa, motorcycle or hov is
  -- present, whatever the value says. Converting the barrier alone would leave
  -- the Cargo preset's dial inert on exactly the nodes it exists for.
  --
  -- Two lists, because they are two different questions.
  --
  -- A *permissive* value on a key that speaks about a bicycle grants nothing
  -- that an untagged node does not already grant, so clearing it changes no
  -- access and arms the cost. A restrictive value on those keys is left exactly
  -- alone: that is a real refusal, and clearing it would be this graph asserting
  -- a legal claim in the widening direction.
  --
  -- A key that speaks *only* about motor vehicles is cleared whatever its value,
  -- because it says nothing about whether a bicycle can pass the barrier, and it
  -- is the common case that made the dial inert - a trail bollard or cycle
  -- barrier tagged `motor_vehicle=no`. Checked through the real transform: the
  -- bicycle bit of access_mask is unchanged by the removal and tagged_access
  -- falls from 1 to 0.
  --
  -- `vehicle` is deliberately in neither list, though a round-3 note pairs it
  -- with motor_vehicle. It is not a motor-vehicle key - OSM's `vehicle` covers
  -- bicycles and upstream reads `vehicle=no` as barring them, so clearing it
  -- would widen bicycle access - and it appears nowhere in upstream's
  -- tagged_access test, so it was never what held the dial off. A node tagged
  -- `vehicle=no` alone already reaches tagged_access 0 on its own.
  -- `wheelchair` is likewise left alone: it is a statement about people on foot,
  -- and a residual tagged_access from one is accepted rather than laundered.
  local BICYCLE_ACCESS_KEYS = { "access", "bicycle", "foot" }
  local PERMISSIVE_NODE_ACCESS = { yes = true, permissive = true, designated = true }
  local MOTOR_VEHICLE_ONLY_KEYS = {
    "motor_vehicle", "motorcar", "hgv", "motorcycle", "moped", "mofa",
    "bus", "taxi", "psv", "hov",
  }

  local function clear_access_that_holds_off_gate_cost(out_table)
    for _, key in ipairs(BICYCLE_ACCESS_KEYS) do
      if PERMISSIVE_NODE_ACCESS[tags[key]] then
        out_table[key] = M.REMOVE
      end
    end
    for _, key in ipairs(MOTOR_VEHICLE_ONLY_KEYS) do
      if tags[key] ~= nil then
        out_table[key] = M.REMOVE
      end
    end
  end

  -- The gap a bollard has to leave before it is furniture a rider slows for
  -- rather than street decoration. A metre and a half is a loaded cargo bike or
  -- a trailer with room to spare; wider than that and there is nothing to
  -- charge for, so the node stays a bollard and keeps upstream's own reading.
  local barrier = tags.barrier
  if barrier == "cycle_barrier" then
    out.barrier = "gate"
    clear_access_that_holds_off_gate_cost(out)
  elseif barrier == "bollard" and tags.maxwidth then
    local width = M.parse_width_m(tags.maxwidth)
    if width and width < M.NARROW_GAP_M then
      out.barrier = "gate"
      clear_access_that_holds_off_gate_cost(out)
    end
  end

  return out
end

--- Whether a set of remapped tags is safe to apply.
-- A border-control node exists to be charged for, not to refuse passage: a
-- mapping that denied bicycle access there would make every state crossing
-- unroutable rather than merely costly.
function M.denies_bicycle_at_border(tags, remapped)
  if tags.barrier ~= "border_control" then return false end
  local merged = {}
  for k, v in pairs(tags) do merged[k] = v end
  for k, v in pairs(remapped) do
    if v == M.REMOVE then merged[k] = nil else merged[k] = v end
  end
  return merged.bicycle == "no" or merged.access == "no"
end

-- Attributes this remap must never write, asserted by the test suite rather
-- than left to review.
M.FORBIDDEN_KEYS = { highway = true, maxspeed = true }

M.NARROW_GAP_M = 1.5

-- The stress penalty's value, and the bicycle values it may replace: the ones
-- upstream's own `bicycle` table maps to plain access, so the swap changes the
-- cost and nothing about who may ride.
M.STRESS_PENALTY_BICYCLE = "use_sidepath"
M.PENALISABLE_BICYCLE = { yes = true, designated = true, permissive = true }

-- The road classes upstream's highway table opens to a bicycle when the way
-- says nothing about bicycles (`bike_forward = "true"`). An allow list rather
-- than a list of the barred classes, so a class this file does not know -
-- `construction`, or one a future upstream adds - fails closed: the penalty
-- is simply not written there. It never includes `MOTOR_ONLY_HIGHWAY`, and
-- tests/lua/test_graph_entry.lua holds it equal to upstream's table.
M.BICYCLE_BY_DEFAULT_HIGHWAY = {
  trunk = true, trunk_link = true, primary = true, primary_link = true,
  secondary = true, secondary_link = true, tertiary = true, tertiary_link = true,
  unclassified = true, residential = true, residential_link = true,
  living_street = true, service = true, road = true, track = true,
  cycleway = true, path = true, steps = true,
}

--- Whether the use_sidepath penalty may replace this way's bicycle value.
--
-- The guard the stress penalty is written with. See the comment at its call
-- in `remap_way`.
function M.may_penalise(tags, bicycle)
  return M.PENALISABLE_BICYCLE[bicycle]
    or (
      bicycle == nil
      and M.BICYCLE_BY_DEFAULT_HIGHWAY[tags.highway]
      and M.access_is_unrestricted(tags)
      and tags.impassable ~= "yes"
    )
    or false
end

-- The stress tiers the penalty lands on: LTS 3 and 4, the two the classifier
-- says most adults will not ride in mixed traffic.
M.STRESS_PENALTY_TIER = 3

-- The tier that costs more again (see `remap_way`): LTS 4, and so 5, at the
-- graph's top speed (kph) and lane count.
M.GRADED_TIER = 4
M.GRADED_SPEED = "140"
M.GRADED_LANES = "15"

-- "Legal but avoid", and the write that carries it (see `remap_way`).
M.AVOID_TIER = 5
M.AVOID_SERVICE = "alley"

--- An alley as OSM maps it, as distinct from the tier-5 roads this file marks
-- `service=alley` for the entry charge (`M.AVOID_TIER`).
function M.is_real_alley(tags)
  return tags.highway == "service" and tags.service == M.AVOID_SERVICE
end

-- --- Facility ------------------------------------------------------------------
--
-- The owner's order (2026-09-27, quoted in `routemaker.facility`): off-road
-- paths first, protected lanes next, painted lanes well behind them, ordinary
-- streets last, and sharrows counting for nothing.
-- The class is computed once, in Python (`routemaker.facility`), written onto
-- the segment table, and handed here as `rm:facility`. What this does with it
-- is choose, for each class, the cycle-lane state Valhalla's bicycle costing
-- prices it at (sif/bicyclecost.cc, 3.5.1; `u` is the request's use_roads):
--
--   highway=cycleway, any class: as upstream, `0.8u`       (no pedestrians)
--   off-road footpath or path:  segregated, `0.1 + 0.9u`   (upstream: 0.2 + u)
--   protected, on the roadway:  track,      `(0.15 + 0.6u) * stress`
--   car-free road (a path):     track,      `(0.15 + 0.6u) * stress`
--   painted lane:               shared,     `(0.9 + 0.05u) * stress`
--   sharrow, ordinary street:   none,       `1.0 * stress`
--
-- `stress` is the roadway term, below 1 on a slow street and above it on a
-- fast one. Upstream's own reading would price a painted lane at
-- `0.4 + 0.45u`, within a few per cent of a protected lane on the same street,
-- which is not the wide gap the owner asked for, and an off-road path open to walkers at
-- `0.2 + u`, dearer than a protected lane; both are moved. What is not moved,
-- because nothing but an access tag could move it: upstream prices every
-- `highway=cycleway` it reads as closed to pedestrians at `0.8u`, and DC maps
-- most of its protected lanes as exactly that, so a separately mapped
-- protected lane and an off-road cycleway tie. Writing `foot=yes` would
-- separate them and is an access claim; it is not written.
--
-- The writes are comfort signals the costing reads and nothing user-facing
-- reads: `segregated` on a trail-class way is read by upstream's transform for
-- its cycle-lane state and for nothing else, and the roadway rewrites only move
-- a value between the three cycle-lane classes upstream reads, every one of
-- which it already reads as bicycle access (`shared`, `dedicated`,
-- `separated`), or remove one only where the way is open to a bicycle without
-- it. So none of them can open or close a way.

-- The roadway values that name a cycle lane of one of upstream's three classes,
-- other than the contraflow ones: `opposite*` also carries access against a
-- one-way's traffic (upstream's `bike_reverse`) and is never touched.
M.LANE_VALUES = { lane = true, buffered_lane = true }
M.TRACK_VALUES = { track = true }
M.SHARED_VALUES = { shared_lane = true, shared = true, share_busway = true }

-- The value a painted lane is rewritten to: upstream's shared class.
M.PAINTED_LANE_VALUE = "shared_lane"

--- Whether a roadway's cycle-lane values may be moved or removed.
--
-- Upstream opens a way to bicycles in both directions when both sides (or
-- `:both`) carry a lane of any class, over `bicycle=no` if need be, so a
-- removal there could close a way. Only where nothing but the road class
-- decides access, and the class opens it anyway.
function M.lanes_may_move(tags)
  return not M.TRAIL_CLASS_HIGHWAY[tags.highway]
    and M.BICYCLE_BY_DEFAULT_HIGHWAY[tags.highway]
    and (tags.bicycle == nil or M.PENALISABLE_BICYCLE[tags.bicycle])
    and M.access_is_unrestricted(tags)
    or false
end

M.TRAIL_CLASS_HIGHWAY = {
  cycleway = true, footway = true, path = true, pedestrian = true,
  bridleway = true, steps = true,
}

--- Rewrite each cycleway key's value through `rewrite(value)`.
local function rewrite_lanes(tags, out, rewrite)
  for _, key in ipairs(M.CYCLEWAY_KEYS) do
    local value = tags[key]
    if value ~= nil then
      local new = rewrite(value)
      if new ~= nil and new ~= value then out[key] = new end
    end
  end
end

function M.apply_facility(tags, derived, out)
  local facility = derived.facility
  if derived.facility_neutral then
    -- The no-trail variant, which Mass Ride routes on. The owner, 2026-09-27:
    -- "Mass rides don't need to consider these. Even protected bike lanes
    -- aren't used." A field of hundreds takes the general roadway, so no lane
    -- of any class makes a street cheaper for it.
    if M.lanes_may_move(tags) then
      rewrite_lanes(tags, out, function(value)
        if M.LANE_VALUES[value] or M.TRACK_VALUES[value] or M.SHARED_VALUES[value] then
          return M.REMOVE
        end
      end)
    end
    return
  end
  if facility == nil then return end

  if M.TRAIL_CLASS_HIGHWAY[tags.highway] then
    -- Only where the mapper has not said, and never a cycleway key.
    if tags.segregated == nil and facility == "path" then
      out.segregated = "yes"
    end
    return
  end

  if facility == "path" then
    -- A road closed to motor traffic (for good, or for the weekend on the
    -- weekend graph). Only where the way is already open to a bicycle by its
    -- own tags: the Python class is computed from those same tags, and this
    -- repeats the check at the write. Sharrows count for nothing here as
    -- anywhere, so they are taken off first - Beach Drive NW's weekend span is
    -- tagged `cycleway=shared_lane`, and a sharrow left on it priced the
    -- closed road as a street. `cycleway=track` is then written only where no
    -- side is spoken for by anything else, as the tier-1 write it replaces was.
    if
      M.BICYCLE_BY_DEFAULT_HIGHWAY[tags.highway]
      and (M.PENALISABLE_BICYCLE[tags.bicycle] or (tags.bicycle == nil and M.access_is_unrestricted(tags)))
    then
      local spoken = false
      for _, key in ipairs(M.CYCLEWAY_KEYS) do
        local value = tags[key]
        if M.SHARED_VALUES[value] then
          out[key] = M.REMOVE
        elseif value ~= nil and value ~= "" then
          spoken = true
        end
      end
      if not spoken then out.cycleway = "track" end
    end
    return
  end

  if not M.lanes_may_move(tags) then return end
  rewrite_lanes(tags, out, function(value)
    if M.SHARED_VALUES[value] then return M.REMOVE end
    if M.LANE_VALUES[value] then
      -- A painted lane with a physical separation tagged is protected.
      if facility == "protected" then return "track" end
      return M.PAINTED_LANE_VALUE
    end
  end)
end

--- Spell `cycleway:both` out as the two sides upstream prices.
--
-- Upstream's transform reads `cycleway:both` for access (both sides carrying a
-- lane opens a way both ways) and never for the cycle-lane state the costing
-- prices: that comes from `cycleway`, `cycleway:right` and `cycleway:left`
-- alone. So a street mapped `cycleway:both=track` was priced as a street with
-- no lane at all - 308 ways in the DC box. Copying the value (after the
-- facility rewrite above) onto a side nobody has spoken for changes the price
-- and nothing else: the access override reads both sides already, and it is
-- satisfied the same way by the copy. Only a painted lane or a track (a
-- sharrow counts for nothing), never a contraflow value (`opposite*` also
-- carries access against a one-way's traffic), and only where the facility
-- rewrite may move lanes at all (`lanes_may_move`: never a trail-class way,
-- nor a way whose own tags restrict access).
function M.split_both(tags, out)
  local original = tags["cycleway:both"]
  if not (M.LANE_VALUES[original] or M.TRACK_VALUES[original]) then return end
  if not M.lanes_may_move(tags) then return end
  local both = out["cycleway:both"] or original
  if both == M.REMOVE then return end
  for _, key in ipairs({ "cycleway:left", "cycleway:right" }) do
    if tags[key] == nil and out[key] == nil then out[key] = both end
  end
end

return M
