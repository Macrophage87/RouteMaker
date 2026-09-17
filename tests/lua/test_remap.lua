-- Run with: ROUTEMAKER_LUA_DIR=lua luajit tests/lua/test_remap.lua
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
check("a bollard leaving a gap wide enough to ride through is left alone",
  M.remap_node({ barrier = "bollard", maxwidth = "3.0" }).barrier == nil)
check("the narrow-gap threshold is the one the dial was reasoned about at",
  M.NARROW_GAP_M == 1.5)
check("a gap just under it converts and one just over it does not",
  M.remap_node({ barrier = "bollard", maxwidth = "1.49" }).barrier == "gate"
    and M.remap_node({ barrier = "bollard", maxwidth = "1.51" }).barrier == nil)

-- maxwidth is not always metres written with a full stop, and the forms it is
-- not written in used to be read as a *different number* rather than refused:
-- `tonumber((value:gsub("[^%d%.]", "")))` turned `3'` into three metres and
-- `1,5` into fifteen, so a bollard the Cargo preset should be charged for read
-- as a gap wide enough to ignore.
local function close(a, b) return a and math.abs(a - b) < 1e-9 end
check("a width in feet is converted rather than read as metres",
  close(M.parse_width_m("3'"), 3 * 0.3048))
check("feet and inches are read together",
  close(M.parse_width_m([[5'6"]]), 5 * 0.3048 + 6 * 0.3048 / 12))
check("a spelled-out foot unit is read too",
  close(M.parse_width_m("3 ft"), 3 * 0.3048) and close(M.parse_width_m("3feet"), 3 * 0.3048))
check("a comma decimal separator is read as a decimal point",
  close(M.parse_width_m("1,2"), 1.2) and close(M.parse_width_m("1,5"), 1.5))
check("plain metres still read, with or without the unit",
  close(M.parse_width_m("1.2"), 1.2) and close(M.parse_width_m("2 m"), 2))
check("a value that cannot be read is refused rather than guessed at",
  M.parse_width_m("wide") == nil and M.parse_width_m("1,5,2") == nil
    and M.parse_width_m("~2") == nil and M.parse_width_m(nil) == nil)

check("a three-foot bollard gap is narrow and becomes a gate",
  M.remap_node({ barrier = "bollard", maxwidth = "3'" }).barrier == "gate")
check("a comma-decimal 1,2 m gap is narrow and becomes a gate",
  M.remap_node({ barrier = "bollard", maxwidth = "1,2" }).barrier == "gate")
check("a six-foot gap is wide and is left alone",
  M.remap_node({ barrier = "bollard", maxwidth = [[6']] }).barrier == nil)
-- Refusing fails toward not charging: the rider's route is no more expensive
-- than Valhalla already makes it, rather than detoured around a barrier this
-- remap cannot show is there.
check("an unreadable width leaves the bollard as upstream reads it",
  M.remap_node({ barrier = "bollard", maxwidth = "narrow" }).barrier == nil)

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

-- An earlier version wrote `rm:access_conditional_<side>` here "so phase 3 can
-- report when the restriction is in force", and the entry point stripped it
-- three lines later, before anything could read it. Nothing consumed it and
-- nothing ever would have.
local recorded = M.remap_conditional_access({ ["bicycle:conditional"] = "no @ (Mo-Fr 07:00-09:30)" })
check("no namespaced key is written that the entry point strips unread",
  recorded["rm:access_conditional_forward"] == nil
    and recorded["rm:access_conditional_backward"] == nil)

-- The wiki's precedence: a directional conditional wins over the undirected one
-- for its own direction, and the undirected one still covers the other. Pinned
-- with the two disagreeing, because with only one of them present the order of
-- the fallback cannot be seen and reversing it left the suite green.
local mixed = M.remap_conditional_access({
  bicycle = "no",
  ["bicycle:conditional"] = "destination @ (Mo-Su)",
  ["bicycle:forward:conditional"] = "yes @ (Sa,Su)",
})
check("a directional conditional outranks the undirected one for its direction",
  only(mixed, "bicycle:forward") == "yes")
check("and the undirected one still covers the other direction",
  only(mixed, "bicycle:backward") == "destination")

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

-- Only values upstream's bicycle table carries may be emitted. `customers` is
-- ranked, because it can be the base value a conditional is compared against,
-- and never written: upstream maps it to nil, which drops the override rather
-- than granting it. The membership of the table itself is asserted against the
-- vendored file in test_graph_entry.lua.
check("customers is ranked", M.ACCESS_RANK.customers ~= nil)
check("customers is not emittable", M.EMITTABLE_BICYCLE.customers == nil)
check("a conditional granting only customers changes nothing",
  M.least_restrictive("no", "customers @ (Mo-Su 08:00-20:00)") == nil)
check("a conditional granting customers and yes still opens on yes",
  M.least_restrictive("no", "customers @ (Mo-Fr); yes @ (Sa,Su)") == "yes")

-- ---------------------------------------------------------------------------
-- Access restrictions the cycleway write must not talk over.
-- ---------------------------------------------------------------------------

check("an untagged way is unrestricted", M.access_is_unrestricted({ highway = "residential" }))
check("access=yes is unrestricted", M.access_is_unrestricted({ access = "yes" }))
check("access=permissive is unrestricted", M.access_is_unrestricted({ access = "permissive" }))

for _, case in ipairs({
  { access = "no" }, { access = "private" }, { access = "agricultural" },
  { access = "forestry" }, { access = "discouraged" }, { access = "destination" },
  { access = "customers" }, { access = "emergency" }, { access = "psv" },
  { vehicle = "no" }, { bicycle = "no" }, { bicycle = "dismount" },
  { ["bicycle:forward"] = "no" }, { ["bicycle:backward"] = "no" },
}) do
  local key, value = next(case)
  check(key .. "=" .. value .. " is a restriction", not M.access_is_unrestricted(case))
  check("and earns no cycleway write",
    M.remap_way(case, { stress_tier = 1 }).cycleway == nil)
end

check("an unrestricted low-stress way still gets its write",
  M.remap_way({ highway = "residential" }, { stress_tier = 1 }).cycleway == "track")
check("and so does a permissively tagged one",
  M.remap_way({ highway = "track", access = "permissive" }, { stress_tier = 1 }).cycleway
    == "track")

-- ---------------------------------------------------------------------------
-- The barrier conversion, and what it may and may not clear.
-- ---------------------------------------------------------------------------

check("a motor-vehicle-only tag is cleared so gate_cost can apply",
  M.remap_node({ barrier = "cycle_barrier", motor_vehicle = "no" }).motor_vehicle == M.REMOVE)
check("so is one on a converted bollard",
  M.remap_node({ barrier = "bollard", maxwidth = "1.0", hgv = "no" }).hgv == M.REMOVE)
check("nothing is cleared on a barrier that was not converted",
  M.remap_node({ barrier = "bollard", motor_vehicle = "no" }).motor_vehicle == nil)
check("a restrictive bicycle tag is never cleared",
  M.remap_node({ barrier = "cycle_barrier", bicycle = "no" }).bicycle == nil)
check("nor is vehicle=no, which bars bicycles under OSM semantics",
  M.remap_node({ barrier = "cycle_barrier", vehicle = "no" }).vehicle == nil)
check("nor is a restrictive access tag",
  M.remap_node({ barrier = "cycle_barrier", access = "private" }).access == nil)

-- ---------------------------------------------------------------------------
-- Violations are recorded rather than raised. error() inside the transform
-- returns an empty tag map and deletes the element; see lua/graph.lua.
-- ---------------------------------------------------------------------------

local before = #M.violations
local kv = { highway = "residential" }
local real_stderr = io.stderr
local logged = {}
io.stderr = { write = function(_, line) logged[#logged + 1] = line end }
M.record_violation(kv, "a test violation")
io.stderr = real_stderr

check("recording a violation does not raise", true)
check("the violation is appended", #M.violations == before + 1)
check("the element is marked", kv[M.VIOLATION_TAG] == "a test violation")
check("the element keeps its tags", kv.highway == "residential")
check("the line carries the prefix the build log is searched for",
  #logged == 1 and logged[1]:find(M.VIOLATION_LOG_PREFIX, 1, true) == 1)
check("the sentinel is outside the stripped namespace", M.VIOLATION_TAG:sub(1, 3) ~= "rm:")

io.write(string.format("%d checks, %d failures\n", checks, failures))
os.exit(failures == 0 and 0 or 1)
