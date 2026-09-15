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
  if derived.stress_tier == 1 and not tags.cycleway and not derived.is_trail_class then
    out.cycleway = "track"
  end

  if derived.reviewer_surface_penalty then
    out.surface = M.bounded_surface(tags.surface or "paved", derived.reviewer_surface_penalty)
  end

  -- Bridge legality is per roadway or sidepath way, from the crossings fixture
  -- rather than from the midpoint heuristic.
  if derived.bridge_bicycle_legal ~= nil then
    out.bicycle = derived.bridge_bicycle_legal and "yes" or "no"
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
-- can say why. Reporting *when* the restriction applies is phase 3's, which is
-- why the condition text is preserved rather than discarded here.
--
-- This never denies access the base tags allow. Tightening on a conditional is
-- the one direction that would make the graph assert a legal claim, which is
-- the thing this project does not do.
M.ACCESS_RANK = {
  no = 1, private = 2, customers = 3, destination = 4,
  permissive = 5, designated = 6, yes = 6,
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
    if rank and rank > best_rank then
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
      -- Recorded whenever one applies, whether or not it changes the graph, so
      -- phase 3 can report when the restriction is in force. Namespaced, so the
      -- entry point strips it before Valhalla sees it.
      out["rm:access_conditional_" .. side] = conditional

      local base = tags[key] or tags.bicycle
      local resolved = M.least_restrictive(base, conditional)
      if resolved and resolved ~= base then
        out[key] = resolved
      end
    end
  end

  return out
end

--- Remap one node's tags.
function M.remap_node(tags)
  local out = {}

  -- gate_cost and gate_penalty apply only at gate nodes, while the narrow-gap
  -- furniture on trails here is overwhelmingly bollards and cycle barriers, for
  -- which Valhalla exposes no cost of its own. Mapping them onto the gate node
  -- type is what makes the Cargo preset's gate dial bite.
  -- gate_cost applies only where the node is a gate *and* carries no access
  -- tags: Valhalla multiplies the cost by (not tagged_access). Cycle barriers
  -- and bollards on trails here very often carry bicycle=yes or access=yes, so
  -- converting the barrier alone would leave the Cargo preset's dial inert on
  -- exactly the nodes it exists for. The permissive access tags are cleared
  -- with it; a restrictive one is left alone, since that is a real refusal.
  local function clear_permissive_access(out_table)
    for _, key in ipairs({ "access", "bicycle", "foot" }) do
      if tags[key] == "yes" or tags[key] == "permissive" or tags[key] == "designated" then
        out_table[key] = M.REMOVE
      end
    end
  end

  local barrier = tags.barrier
  if barrier == "cycle_barrier" then
    out.barrier = "gate"
    clear_permissive_access(out)
  elseif barrier == "bollard" and tags.maxwidth then
    local width = tonumber((tags.maxwidth:gsub("[^%d%.]", "")))
    if width and width < 1.5 then
      out.barrier = "gate"
      clear_permissive_access(out)
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

return M
