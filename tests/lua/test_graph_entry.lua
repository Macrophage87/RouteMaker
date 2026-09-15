-- Run with: ROUTEMAKER_LUA_DIR=lua lua5.4 tests/lua/test_graph_entry.lua
--
-- This exercises lua/graph.lua against the *genuinely vendored* Valhalla
-- transform in lua/vendor. The previous version of this check installed a
-- module-shaped stub into package.loaded - `{ways_proc = function() end, ...}` -
-- and so asserted a contract upstream does not have. Upstream defines its entry
-- points as globals and returns nothing, which meant the shipped wrapper raised
-- "attempt to index a boolean value" on the first way of every tile build while
-- the test stayed green. A test that builds the interface it is meant to pin
-- cannot fail; the fixture here is the real file.

local failures, checks = 0, 0
local function check(name, ok, detail)
  checks = checks + 1
  if not ok then
    failures = failures + 1
    io.write("FAIL: ", name, detail and (" - " .. tostring(detail)) or "", "\n")
  end
end

assert(os.getenv("ROUTEMAKER_LUA_DIR"), "ROUTEMAKER_LUA_DIR must point at the lua/ directory")

-- Capture upstream's own globals first, so the delegation checks below can tell
-- the wrapper's entry points apart from the ones it wraps.
package.path = "lua/vendor/?.lua;" .. package.path
require("graph_upstream")
local raw_ways, raw_nodes, raw_rels = ways_proc, nodes_proc, rels_proc
check("the vendored upstream installs globals rather than returning a module",
  type(raw_ways) == "function" and package.loaded["graph_upstream"] == true)

dofile("lua/graph.lua")

check("ways_proc is defined", type(ways_proc) == "function")
check("nodes_proc is defined", type(nodes_proc) == "function")
check("rels_proc is defined", type(rels_proc) == "function")
check("the wrapper replaced upstream's entry points rather than aliasing them",
  ways_proc ~= raw_ways and nodes_proc ~= raw_nodes and rels_proc ~= raw_rels)
check("upstream's rel_members_proc is left in place",
  type(rel_members_proc) == "function")

-- A low-stress residential way. Two things must be true at once: this project's
-- remap must have run, and upstream's transform must have run after it on the
-- remapped tags. bike_forward is upstream's own derived attribute and exists in
-- no RouteMaker code, so its presence is what proves the delegation happened.
local way = { highway = "residential", ["rm:stress_tier"] = "1" }
local filter, out = ways_proc(way, 2)
check("a way is kept by upstream", filter == 0, filter)
check("the remap ran: low stress writes cycleway", out.cycleway == "track", out.cycleway)
check("upstream ran on the remapped tags: bike_forward is derived",
  out.bike_forward ~= nil, out.bike_forward)
check("the rm: namespace never reaches the tile build", out["rm:stress_tier"] == nil)

-- The same derived tier on a trail-class way must not turn bicycle access on for
-- every sidewalk in the District.
local trail = { highway = "footway", ["rm:stress_tier"] = "1", ["rm:trail_class"] = "yes" }
local _, trail_out = ways_proc(trail, 3)
check("a trail-class way gets no cycleway write", trail_out.cycleway == nil, trail_out.cycleway)

-- A cycle barrier carrying permissive access. Valhalla applies gate_cost only
-- where the node is a gate and carries no access tags, so the permissive tag has
-- to be *removed*, not merely left unwritten.
local barrier = { barrier = "cycle_barrier", bicycle = "yes" }
local _, barrier_out = nodes_proc(barrier, 2)
check("a cycle barrier becomes a gate", barrier_out.barrier == "gate", barrier_out.barrier)
check("the permissive access tag is removed so gate_cost applies",
  barrier_out.bicycle == nil, barrier_out.bicycle)
check("no marker key leaks into the tag table", barrier_out["_clear_bicycle"] == nil)

-- A restrictive tag is a real refusal and is left alone.
local closed = { barrier = "cycle_barrier", bicycle = "no" }
local _, closed_out = nodes_proc(closed, 2)
check("a restrictive access tag survives the conversion", closed_out.bicycle == "no")

-- A border-control node must stay passable rather than halt the build.
local border_ok = pcall(nodes_proc, { barrier = "border_control", access = "no" }, 2)
check("upstream's own closed border crossing does not halt the build", border_ok)

check("rels_proc delegates", ({ rels_proc({ type = "route", route = "bicycle" }, 2) })[1] ~= nil)

-- Loading twice would capture this file's own entry points as "upstream".
local twice_ok, twice_err = pcall(dofile, "lua/graph.lua")
check("a second load is refused rather than left to recurse",
  not twice_ok and tostring(twice_err):find("loaded twice", 1, true) ~= nil, twice_err)

io.write(string.format("%d checks, %d failures\n", checks, failures))
os.exit(failures == 0 and 0 or 1)
