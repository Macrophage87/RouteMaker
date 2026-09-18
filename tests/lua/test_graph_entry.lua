-- Run with: ROUTEMAKER_LUA_DIR=lua luajit tests/lua/test_graph_entry.lua
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

-- ---------------------------------------------------------------------------
-- The stress remap may not grant bicycle access on a way Valhalla drops.
--
-- Asserted here, through the real transform, and not at the remap's own output
-- table, because that is exactly how this shipped: both Lua suites checked what
-- remap_way returned and neither ever pushed a restricted way through
-- filter_tags_generic. `classify()` rates all three of these LTS1 - it grades
-- stress, not access - and the cycleway write then took them from filter=1, no
-- edge at all, to filter=0 with bike access true in both directions.
-- ---------------------------------------------------------------------------

local function transform_way(tags)
  local kv, n = {}, 0
  for k, v in pairs(tags) do kv[k] = v ; n = n + 1 end
  local filter, out = ways_proc(kv, n)
  return filter, out
end

local restricted = {
  { name = "private farm track", tags = { highway = "track", access = "no", surface = "gravel" } },
  { name = "closed service road", tags = { highway = "service", access = "no" } },
  { name = "gated living street", tags = { highway = "living_street", access = "no" } },
  { name = "agricultural track", tags = { highway = "track", access = "agricultural" } },
  { name = "forestry track", tags = { highway = "track", access = "forestry" } },
  { name = "discouraged lane", tags = { highway = "unclassified", access = "discouraged" } },
}

for _, case in ipairs(restricted) do
  local tags = { ["rm:stress_tier"] = "1" }
  for k, v in pairs(case.tags) do tags[k] = v end

  local bare_filter = transform_way(case.tags)
  local filter, out = transform_way(tags)

  check("upstream drops a " .. case.name .. " on its own", bare_filter == 1, bare_filter)
  check("a " .. case.name .. " at tier 1 is still dropped", filter == 1, filter)
  check("no cycleway is written onto a " .. case.name, out.cycleway == nil, out.cycleway)
end

-- access=emergency and access=psv are not dropped, but arrive with bicycle
-- access already false, so the write would flip that instead of the filter.
for _, value in ipairs({ "emergency", "psv" }) do
  local _, out = transform_way({ highway = "service", access = value, ["rm:stress_tier"] = "1" })
  check("access=" .. value .. " keeps bicycle access off", out.bike_forward == "false",
    out.bike_forward)
  check("no cycleway is written onto access=" .. value, out.cycleway == nil, out.cycleway)
end

-- `vehicle` is the one that reads as a motor-vehicle key and is not: OSM's
-- vehicle covers bicycles, and upstream bars them on vehicle=no.
local _, vehicle_out = transform_way({ highway = "track", vehicle = "no", ["rm:stress_tier"] = "1" })
check("a way tagged vehicle=no keeps bicycle access off",
  vehicle_out.bike_forward == "false", vehicle_out.bike_forward)
check("no cycleway is written onto vehicle=no", vehicle_out.cycleway == nil, vehicle_out.cycleway)

-- A destination-only way keeps bicycle access under upstream's tables, so this
-- one is about the claim rather than the access: the way arrives marked private
-- and a separated-track write would assert provision the tagging denies.
local _, private_out =
  transform_way({ highway = "service", access = "private", ["rm:stress_tier"] = "1" })
check("a private way is still routable", private_out.bike_forward == "true")
check("but carries no cycleway write", private_out.cycleway == nil, private_out.cycleway)
check("and is marked private by upstream", private_out.private == "true", private_out.private)

-- The way the guard must not catch: an ordinary low-stress street still gets
-- its write, and a permissively tagged one does too.
local open_filter, open_out =
  transform_way({ highway = "residential", access = "yes", ["rm:stress_tier"] = "1" })
check("an access=yes residential street still gets the write", open_out.cycleway == "track",
  open_out.cycleway)
check("and is kept", open_filter == 0, open_filter)

-- ---------------------------------------------------------------------------
-- `rm:bridge_bicycle` reaches the graph as the bicycle tag it names.
--
-- The two halves of the join were each pinned and the join itself was not: the
-- pipeline's side asserts that the tag is injected, and test_remap.lua asserts
-- what `remap_way` does with `derived.bridge_bicycle_legal`, but nothing ran a
-- way carrying the tag through `derived_from`. Inverting that one comparison -
-- `== "yes"` to `~= "yes"` - left both suites and the whole Python suite green
-- while every fixture-legal bridge in the region (Memorial, Sousa, the 11th
-- Street local span, Douglass, Whitney Young, Benning) arrived in the graph
-- barred to bicycles, on all three variants.
--
-- Read at upstream's own derived attributes rather than at the tag alone:
-- `bike_tag` is upstream's record that a bicycle key was read at all, so it
-- tells a way this remap wrote nothing to apart from one it wrote `no` onto.
-- ---------------------------------------------------------------------------

local bridge = { highway = "secondary", bridge = "yes", name = "Memorial Bridge", bicycle = "no" }

local _, legal_out = transform_way({
  highway = "secondary", bridge = "yes", name = "Memorial Bridge",
  bicycle = "no", ["rm:bridge_bicycle"] = "yes",
})
check("a fixture-legal roadway bridge is granted bicycle access",
  legal_out.bicycle == "yes", legal_out.bicycle)
check("and upstream reads the grant in both directions",
  legal_out.bike_forward == "true" and legal_out.bike_backward == "true",
  tostring(legal_out.bike_forward) .. "/" .. tostring(legal_out.bike_backward))
check("the derived tag itself never reaches the tile build",
  legal_out["rm:bridge_bicycle"] == nil)

local _, illegal_out = transform_way({
  highway = "secondary", bridge = "yes", name = "Memorial Bridge",
  ["rm:bridge_bicycle"] = "no",
})
check("a fixture-illegal roadway bridge is barred",
  illegal_out.bicycle == "no", illegal_out.bicycle)
check("and upstream reads the bar in both directions",
  illegal_out.bike_forward == "false" and illegal_out.bike_backward == "false",
  tostring(illegal_out.bike_forward) .. "/" .. tostring(illegal_out.bike_backward))

-- The third case is what tells an inverted comparison from a merely wrong one:
-- a way the fixture has no opinion about must arrive exactly as OSM tagged it,
-- with no bicycle key read at all.
local _, silent_out = transform_way({
  highway = "secondary", bridge = "yes", name = "Memorial Bridge",
})
check("a bridge with no fixture row keeps upstream's own reading",
  silent_out.bicycle == nil and silent_out.bike_tag == nil,
  tostring(silent_out.bicycle) .. "/" .. tostring(silent_out.bike_tag))
check("and stays routable on upstream's defaults", silent_out.bike_forward == "true",
  silent_out.bike_forward)

-- The untouched case is the base tagging the two writes above are measured
-- against: without the fixture row this bridge is barred by its own `bicycle=no`.
local _, base_out = transform_way(bridge)
check("the bridge's own bicycle=no bars it without a fixture row",
  base_out.bike_forward == "false", base_out.bike_forward)

-- ---------------------------------------------------------------------------
-- gate_cost applies only where tagged_access is 0.
-- ---------------------------------------------------------------------------

local function transform_node(tags)
  local kv, n = {}, 0
  for k, v in pairs(tags) do kv[k] = v ; n = n + 1 end
  local _, out = nodes_proc(kv, n)
  return out
end

-- The bicycle bit of upstream's access mask, which must not move when a
-- motor-vehicle key is cleared.
local function bike_allowed(out)
  return math.floor(tonumber(out.access_mask) / 4) % 2 == 1
end

local motor_barrier = transform_node({ barrier = "cycle_barrier", motor_vehicle = "no" })
check("a cycle barrier tagged motor_vehicle=no becomes a gate",
  motor_barrier.gate == "true", motor_barrier.gate)
check("and reaches tagged_access 0, so gate_cost applies",
  motor_barrier.tagged_access == 0, motor_barrier.tagged_access)
check("with bicycle access unchanged", bike_allowed(motor_barrier))

local bollard = transform_node({ barrier = "bollard", maxwidth = "1.2", motorcar = "no" })
check("a narrow bollard tagged motorcar=no also reaches tagged_access 0",
  bollard.tagged_access == 0, bollard.tagged_access)

-- A restrictive bicycle tag is a real refusal and survives, tagged_access and
-- all: arming a cost dial is not a reason to widen access.
local closed_barrier = transform_node({ barrier = "cycle_barrier", bicycle = "no" })
check("a cycle barrier tagged bicycle=no keeps the refusal",
  closed_barrier.tagged_access == 1 and not bike_allowed(closed_barrier),
  closed_barrier.tagged_access)

-- vehicle=no is not cleared, and never needed to be: it is absent from
-- upstream's tagged_access test, so the dial was armed already.
local vehicle_barrier = transform_node({ barrier = "cycle_barrier", vehicle = "no" })
check("a cycle barrier tagged vehicle=no was never what held the dial off",
  vehicle_barrier.tagged_access == 0, vehicle_barrier.tagged_access)
check("and its refusal survives", not bike_allowed(vehicle_barrier))

-- ---------------------------------------------------------------------------
-- A violation is loud and leaves the element where it was.
--
-- error() inside an entry point does not halt a build: Transform catches it and
-- returns an empty tag map, so the element is silently stripped and dropped -
-- the opposite of what both guards claimed to do.
-- ---------------------------------------------------------------------------

local remap = require("routemaker_remap")

local logged = {}
local real_stderr = io.stderr
io.stderr = { write = function(_, line) logged[#logged + 1] = line end }

local real_remap_way = remap.remap_way
remap.remap_way = function() return { highway = "motorway", cycleway = "track" } end
local before = #remap.violations
local forbidden_ok, forbidden_filter, forbidden_out =
  pcall(ways_proc, { highway = "residential", name = "Ordinary Street" }, 2)
remap.remap_way = real_remap_way

check("a forbidden write does not raise", forbidden_ok, forbidden_filter)
check("the way is kept rather than blanked", forbidden_filter == 0, forbidden_filter)
check("the way keeps the class it arrived with",
  forbidden_out and forbidden_out.highway == "residential", forbidden_out and forbidden_out.highway)
check("the rest of the tags survive", forbidden_out and forbidden_out.name == "Ordinary Street")
check("the permitted part of the change still applies", forbidden_out.cycleway == "track")
check("the violation is recorded", #remap.violations == before + 1)
check("the element carries the sentinel", forbidden_out[remap.VIOLATION_TAG] ~= nil,
  forbidden_out[remap.VIOLATION_TAG])
check("and a line goes to the build log under the searched prefix",
  #logged == 1 and logged[1]:find(remap.VIOLATION_LOG_PREFIX, 1, true) == 1, logged[1])

-- The border guard, which is the one whose error() deleted the node it exists
-- to protect.
logged = {}
local real_remap_node = remap.remap_node
remap.remap_node = function() return { bicycle = "no" } end
before = #remap.violations
local border_ok, _, border_out =
  pcall(nodes_proc, { barrier = "border_control", name = "State Line" }, 2)
remap.remap_node = real_remap_node

check("a denying border change does not raise", border_ok)
check("the border node is not blanked", border_out and border_out.name == "State Line")
check("upstream still sees a border control", border_out.border_control == "true")
check("the denying change is refused rather than applied", border_out.bicycle == nil,
  border_out.bicycle)
check("bicycle access at the border survives", bike_allowed(border_out))
check("the violation is recorded and logged", #remap.violations == before + 1 and #logged == 1)

-- And the node the guard must not catch, which is what the second half of its
-- condition is for: a border control this remap wrote nothing to. OSM tags a
-- genuinely closed crossing `access=no`, so the merged tags deny bicycle access
-- on their own - and denying it is upstream's reading, not a change of this
-- project's making. Testing `denies_bicycle_at_border` alone cannot see the
-- difference: it answers true here either way. Drop `next(changes) ~= nil` and
-- every closed border crossing in the extract raises a violation, tags the node
-- with the sentinel and puts a line under the searched prefix into the build
-- log, which the validation stage fails the rebuild on.
logged = {}
before = #remap.violations
local closed_border_ok, _, closed_border_out =
  pcall(nodes_proc, { barrier = "border_control", access = "no", name = "Closed Crossing" }, 3)

check("a closed border crossing does not raise", closed_border_ok)
check("upstream's own closure is not this remap's violation",
  #remap.violations == before, #remap.violations - before)
check("and nothing reaches the build log for it", #logged == 0, logged[1])
check("the node carries no violation sentinel",
  closed_border_out and closed_border_out[remap.VIOLATION_TAG] == nil,
  closed_border_out and closed_border_out[remap.VIOLATION_TAG])
check("and passes through to upstream as the border control it is",
  closed_border_out and closed_border_out.border_control == "true",
  closed_border_out and closed_border_out.border_control)

io.stderr = real_stderr

-- ---------------------------------------------------------------------------
-- Every value this remap can emit onto a bicycle key is one upstream reads.
-- Read out of the vendored table rather than remembered: a value outside it
-- maps to nil, which drops the override instead of granting it.
-- ---------------------------------------------------------------------------
check("the vendored upstream exposes its bicycle table", type(bicycle) == "table")
for value in pairs(remap.EMITTABLE_BICYCLE) do
  check("upstream's bicycle table carries '" .. value .. "'", bicycle[value] ~= nil)
end
check("customers is ranked but never emitted",
  remap.ACCESS_RANK.customers ~= nil and remap.EMITTABLE_BICYCLE.customers == nil
    and bicycle["customers"] == nil)

local customers_only = remap.remap_conditional_access(
  { bicycle = "no", ["bicycle:conditional"] = "customers @ (Mo-Su 08:00-20:00)" })
check("a conditional that only upstream cannot express writes nothing",
  next(customers_only) == nil)

-- Loading twice would capture this file's own entry points as "upstream".
local twice_ok, twice_err = pcall(dofile, "lua/graph.lua")
check("a second load is refused rather than left to recurse",
  not twice_ok and tostring(twice_err):find("loaded twice", 1, true) ~= nil, twice_err)

io.write(string.format("%d checks, %d failures\n", checks, failures))
os.exit(failures == 0 and 0 or 1)
