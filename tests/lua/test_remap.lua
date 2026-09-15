-- Run with: lua5.4 tests/lua/test_remap.lua
package.path = "lua/?.lua;" .. package.path
local M = require("routemaker_remap")

local failures, checks = 0, 0
local function check(name, ok)
  checks = checks + 1
  if not ok then
    failures = failures + 1
    io.write("FAIL: ", name, "\n")
  end
end

-- The remap must never touch road class or speed.
local function writes_forbidden(out)
  for key in pairs(M.FORBIDDEN_KEYS) do
    if out[key] ~= nil then return true end
  end
  return false
end

check("stress tier never rewrites highway class", not writes_forbidden(
  M.remap_way({ highway = "primary", maxspeed = "45 mph" }, { stress_tier = 4 })))

check("low stress never rewrites maxspeed", not writes_forbidden(
  M.remap_way({ highway = "residential" }, { stress_tier = 1 })))

check("reviewer penalty never rewrites highway class", not writes_forbidden(
  M.remap_way({ highway = "tertiary", surface = "paved" },
              { reviewer_surface_penalty = "path" })))

-- A penalty must not make an edge impassable for any configured bicycle_type.
local capped = M.remap_way({ highway = "unclassified", surface = "paved" },
                           { reviewer_surface_penalty = "impassable" })
check("surface downgrade is capped at the strictest ridable threshold",
  M.SURFACE_ORDER[capped.surface] <= M.REVIEWER_PENALTY_FLOOR)

check("surface downgrade never improves a surface",
  M.SURFACE_ORDER[M.bounded_surface("gravel", "paved_smooth")] >= M.SURFACE_ORDER.gravel)

-- Narrow-gap furniture has to reach gate_cost.
check("cycle_barrier becomes a gate",
  M.remap_node({ barrier = "cycle_barrier" }).barrier == "gate")
check("narrow bollard becomes a gate",
  M.remap_node({ barrier = "bollard", maxwidth = "1.2" }).barrier == "gate")
check("unrestricted bollard is left alone",
  M.remap_node({ barrier = "bollard" }).barrier == nil)

-- Valhalla multiplies gate_cost by (not tagged_access), so a permissive access
-- tag left in place makes the Cargo preset's gate dial inert on exactly the
-- nodes it exists for. A Lua table cannot hold a nil, so the removal is
-- signalled by a sentinel the entry point applies; an earlier version wrote a
-- `_clear_<key>` marker that nothing consumed, and nothing noticed.
check("a permissive access tag on a converted barrier is marked for removal",
  M.remap_node({ barrier = "cycle_barrier", bicycle = "yes" }).bicycle == M.REMOVE)
check("a restrictive access tag is left alone",
  M.remap_node({ barrier = "cycle_barrier", bicycle = "no" }).bicycle == nil)
check("the removal sentinel is not a string that could collide with a tag value",
  type(M.REMOVE) == "table")
check("a removal counts as a removal when checking border access",
  not M.denies_bicycle_at_border(
    { barrier = "border_control", bicycle = "yes" },
    { bicycle = M.REMOVE }))

-- The border node must stay passable.
local border = { barrier = "border_control" }
check("border control node denies no bicycle access",
  not M.denies_bicycle_at_border(border, M.remap_node(border)))
check("a mapping that denied access would be caught",
  M.denies_bicycle_at_border(border, { bicycle = "no" }))

-- Bridge legality is expressed through access, which is what it actually is.
check("bridge legality sets bicycle access",
  M.remap_way({ highway = "trunk" }, { bridge_bicycle_legal = false }).bicycle == "no")

-- Directional conditional access, for the parkway reversal. Valhalla reads
-- bicycle:forward and bicycle:backward and reads no *:conditional key at all -
-- its own graph.lua carries a bare "TODO access:conditional" - so a road signed
-- against bicycles except at certain hours reaches the graph as simply barred,
-- in both directions, at every hour of the week.

local function only(t, key) return t[key] end

check("a conditional grant opens the direction it applies to",
  only(M.remap_conditional_access(
    { bicycle = "no", ["bicycle:forward:conditional"] = "yes @ (Sa,Su)" }), "bicycle:forward")
    == "yes")

check("and leaves the other direction alone",
  only(M.remap_conditional_access(
    { bicycle = "no", ["bicycle:forward:conditional"] = "yes @ (Sa,Su)" }), "bicycle:backward")
    == nil)

check("an undirected conditional applies to both directions",
  only(M.remap_conditional_access(
    { bicycle = "no", ["bicycle:conditional"] = "designated @ (Sa,Su 07:00-19:00)" }),
    "bicycle:backward") == "designated")

-- A static graph cannot represent time, so a time-limited restriction must not
-- be written as a permanent one. An unroutable edge is also the answer that
-- tells the rider nothing: the route goes another way and nothing can say why.
check("a conditional restriction never denies access the base tags allow",
  only(M.remap_conditional_access(
    { bicycle = "yes", ["bicycle:backward:conditional"] = "no @ (Mo-Fr 16:00-19:00)" }),
    "bicycle:backward") == nil)

check("nor does one on an otherwise untagged way",
  only(M.remap_conditional_access(
    { ["bicycle:conditional"] = "no @ (Mo-Fr 07:00-09:30)" }), "bicycle:forward") == nil)

check("the condition is kept whether or not it changed the graph",
  only(M.remap_conditional_access(
    { ["bicycle:conditional"] = "no @ (Mo-Fr 07:00-09:30)" }), "rm:access_conditional_forward")
    == "no @ (Mo-Fr 07:00-09:30)")

check("a way with no conditional tag is untouched",
  next(M.remap_conditional_access({ highway = "residential" })) == nil)

-- The separator is not parsed: conditions carry ; and , inside them.
local multi = M.parse_conditional("no @ (Mo-Fr 07:00-09:00); yes @ (Sa,Su 10:00-16:00)")
check("both rules of a multi-rule conditional are read", #multi == 2)
check("a condition containing a comma survives intact",
  multi[2].condition == "Sa,Su 10:00-16:00")
check("a bare value with no condition reads as itself",
  M.parse_conditional("no")[1].value == "no")
check("an unparseable value yields no rules",
  #M.parse_conditional("@@@ (") == 0)

check("the remap reaches a way through remap_way",
  M.remap_way({ bicycle = "no", ["bicycle:forward:conditional"] = "yes @ (Su)" },
              {})["bicycle:forward"] == "yes")

-- The LTS1 remap may not grant access the tags do not grant.
--
-- classify() grades stress, not access, so a gated service road or a private
-- farm track - empty of traffic precisely because nobody may drive on it -
-- scores LTS1. Writing cycleway=track there makes upstream derive bicycle
-- access for it. Confirmed against real tiles: a way tagged access=no is absent
-- from the built graph, and the same way with cycleway=track added is present
-- and routable. The graph would be asserting a legal claim in the widening
-- direction, with no override row and no review.
local function lts1_cycleway(tags)
  return M.remap_way(tags, { stress_tier = 1 }).cycleway
end

check("a private farm track is not given a cycleway",
  lts1_cycleway({ highway = "track", access = "no" }) == nil)

check("a gated service road is not given a cycleway",
  lts1_cycleway({ highway = "service", access = "private" }) == nil)

check("a customers-only way is not given a cycleway",
  lts1_cycleway({ highway = "service", access = "customers" }) == nil)

check("an access value we do not recognise is treated as a restriction",
  lts1_cycleway({ highway = "track", access = "permit" }) == nil)

check("bicycle=no bars the remap even where general access is open",
  lts1_cycleway({ highway = "residential", bicycle = "no" }) == nil)

-- The guard is about access, not about being cautious: it must not cost the
-- remap the ways it exists for.
check("an explicit bicycle=yes overrides a restrictive access tag",
  lts1_cycleway({ highway = "service", access = "no", bicycle = "yes" }) == "track")

check("access=destination is not a restriction",
  lts1_cycleway({ highway = "residential", access = "destination" }) == "track")

check("an ordinary quiet street is still remapped",
  lts1_cycleway({ highway = "residential" }) == "track")

io.write(string.format("%d checks, %d failures\n", checks, failures))
os.exit(failures == 0 and 0 or 1)
