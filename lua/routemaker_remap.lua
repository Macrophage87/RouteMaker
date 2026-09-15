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

-- Increasing roughness, matching Valhalla's surface enum ordering.
M.SURFACE_ORDER = {
  paved_smooth = 1, paved = 2, paved_rough = 3, compacted = 4,
  dirt = 5, gravel = 6, path = 7, impassable = 8,
}

-- The minimum ridable surface per bicycle_type. Valhalla refuses outright any
-- edge worse than this; avoid_bad_surfaces does not relax it.
M.MIN_RIDABLE = { Road = 4, Hybrid = 5, Cross = 6, Mountain = 7 }

-- The strictest configured type. A reviewer penalty may never push a surface
-- past this, because doing so would remove the edge from the graph for that
-- preset and return "no route" instead of a penalised route, which inverts the
-- stated posture that the router degrades rather than fails.
M.REVIEWER_PENALTY_FLOOR = M.MIN_RIDABLE.Road

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
  if derived.stress_tier == 1 and not tags.cycleway then
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

  return out
end

--- Remap one node's tags.
function M.remap_node(tags)
  local out = {}

  -- gate_cost and gate_penalty apply only at gate nodes, while the narrow-gap
  -- furniture on trails here is overwhelmingly bollards and cycle barriers, for
  -- which Valhalla exposes no cost of its own. Mapping them onto the gate node
  -- type is what makes the Cargo preset's gate dial bite.
  local barrier = tags.barrier
  if barrier == "cycle_barrier" then
    out.barrier = "gate"
  elseif barrier == "bollard" and tags.maxwidth then
    local width = tonumber((tags.maxwidth:gsub("[^%d%.]", "")))
    if width and width < 1.5 then out.barrier = "gate" end
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
  for k, v in pairs(remapped) do merged[k] = v end
  return merged.bicycle == "no" or merged.access == "no"
end

-- Attributes this remap must never write, asserted by the test suite rather
-- than left to review.
M.FORBIDDEN_KEYS = { highway = true, maxspeed = true }

return M
