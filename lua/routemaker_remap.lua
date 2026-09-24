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

--- Whether a way's own tags leave bicycle access unrestricted.
function M.access_is_unrestricted(tags)
  for _, key in ipairs(M.ACCESS_KEYS) do
    local value = tags[key]
    if value ~= nil and not M.PERMISSIVE_ACCESS[value] then
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
  if
    derived.stress_tier == 1
    and not M.declares_cycleway(tags)
    and not derived.is_trail_class
    and M.access_is_unrestricted(tags)
  then
    out.cycleway = "track"
  end

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

  if derived.lit ~= nil then
    out.lit = derived.lit and "yes" or "no"
  end

  for key, value in pairs(M.remap_conditional_access(tags)) do
    out[key] = value
  end

  return out
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

--- Resolve conditional access onto the directional keys Valhalla reads.
function M.remap_conditional_access(tags)
  local out = {}
  -- The undirected conditional applies to both directions unless a directional
  -- one is present for that direction, which is the wiki's own precedence.
  local both = tags["bicycle:conditional"]

  for _, side in ipairs({ "forward", "backward" }) do
    local key = "bicycle:" .. side
    local conditional = tags[key .. ":conditional"] or both
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

return M
