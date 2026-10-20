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
-- Against `REVIEWER_PENALTY_FLOOR` the check above is self-referential: it
-- holds for whatever the floor is set to, including a floor loosened past the
-- threshold Valhalla actually refuses at. So the threshold itself is named, and
-- so is the surface a maximum penalty on a paved way lands on.
check("Road's minimum ridable surface is compacted", M.MIN_RIDABLE.Road == 4)
check("which is the rank `compacted` holds", M.SURFACE_ORDER.compacted == 4)
check("and the cap is that threshold", M.REVIEWER_PENALTY_FLOOR == M.MIN_RIDABLE.Road)
check("so the worst a reviewer can make a paved way is compacted",
  capped.surface == "compacted")

check("surface downgrade never improves a surface",
  M.SURFACE_ORDER[M.valhalla_surface(M.bounded_surface("gravel", "paved_smooth"))]
    >= M.SURFACE_ORDER.gravel)

-- FOLLOWUP-VALHALLA-36-LEFTOVERS, item 1: the penalty lands as a tag the
-- parser reads as the class meant (it reads `surface` by substring, so
-- `paved_rough` itself read as paved_smooth), and the way's own surface is read
-- the parser's way too.
for name, tag in pairs(M.SURFACE_TAG) do
  check("the tag written for " .. name .. " reads as " .. name,
    M.valhalla_surface(tag) == name, tag)
end
check("every class but impassable has a tag", (function()
  for name in pairs(M.SURFACE_ORDER) do
    if name ~= "impassable" and M.SURFACE_TAG[name] == nil then return false end
  end
  return true
end)())
check("the class names alone are not tags the parser reads as meant",
  M.valhalla_surface("paved_rough") == "paved_smooth" and M.valhalla_surface("path") == nil)
check("a paved_rough penalty on asphalt lands as cobblestone",
  M.bounded_surface("asphalt", "paved_rough") == "cobblestone")
check("a paved penalty on asphalt lands as paving stones",
  M.bounded_surface("asphalt", "paved") == "paving_stones")
check("a ground path is dirt, and a penalty does not lift it to compacted",
  M.bounded_surface("ground", "gravel") == "ground")
check("a grass path keeps its own surface",
  M.bounded_surface("grass", "compacted") == "grass")
check("an untagged way with a penalty that changes nothing gets no surface",
  M.bounded_surface(nil, "paved_smooth") == nil)
check("an untagged way with a penalty is capped at compacted",
  M.bounded_surface(nil, "path") == "compacted")
check("the parser's order: unpaved is gravel before paved matches",
  M.valhalla_surface("unpaved") == "gravel" and M.valhalla_surface("Asphalt") == "paved_smooth")
check("an untagged way's remap writes no surface for a no-op penalty",
  M.remap_way({ highway = "residential" }, { reviewer_surface_penalty = "paved_smooth" }).surface
    == nil)

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
-- And the tie itself, which is the half of the threshold the pair above cannot
-- see: the comparison is `<`, so a gap of exactly the threshold is the wide
-- side. A metre and a half is stated as the gap a loaded cargo bike clears, so
-- a bollard leaving exactly that is not furniture to charge for.
check("a gap of exactly the threshold is on the wide side of it",
  M.remap_node({ barrier = "bollard", maxwidth = "1.5" }).barrier == nil,
  M.remap_node({ barrier = "bollard", maxwidth = "1.5" }).barrier)

-- The conjunction that selects the branch at all. `maxwidth` appears on plenty
-- of nodes that are not bollards - height and width restrictions on gates,
-- lift gates and tunnel portals - and reading the two conditions as an
-- alternative converts every one of them into a gate, which both moves the
-- barrier type Valhalla reads and clears the access tags beside it.
check("a narrow node that is not a bollard is not converted",
  M.remap_node({ maxwidth = "1.2" }).barrier == nil,
  M.remap_node({ maxwidth = "1.2" }).barrier)
check("and a lift gate keeps the barrier type it was tagged with",
  next(M.remap_node({ barrier = "lift_gate", maxwidth = "1.2" })) == nil)

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

-- The same table as `TestWidthParsing` in tests/test_stress.py, case for case.
-- Two parsers read these same OSM tags off the same extract - this one for a
-- bollard's `maxwidth`, the Python one for `shoulder:*:width` and
-- `cycleway:*:width` - and round 5 found them disagreeing on four of these
-- forms, in the dangerous direction both ways: `"8 feet"` was 8.0 metres on the
-- Python side, a twenty-six-foot shoulder that rates a road low-stress on a tag
-- that says nothing of the kind, while `"2.4m"`, `"1,5"` and `5'6"` were
-- unreadable there and read correctly here. Neither table is allowed to move
-- without the other.
local FOOT = 0.3048
for _, case in ipairs({
  { "3'", 3 * FOOT }, { "8'", 8 * FOOT },
  { "3 ft", 3 * FOOT }, { "8ft", 8 * FOOT },
  { "3feet", 3 * FOOT }, { "8 feet", 8 * FOOT },
  { [[5'6"]], 5 * FOOT + 6 * FOOT / 12 }, { "5'6", 5 * FOOT + 6 * FOOT / 12 },
  { "1.2", 1.2 }, { "2.4", 2.4 }, { "2 m", 2.0 }, { "2.4 m", 2.4 }, { "2.4m", 2.4 },
  { "1,2", 1.2 }, { "1,5", 1.5 },
}) do
  check("width " .. case[1] .. " reads the same as it does in Python",
    close(M.parse_width_m(case[1]), case[2]))
end
for _, value in ipairs({ "wide", "ft", "1,5,2", "~2", "8 metres", "-2" }) do
  check("width " .. value .. " is unreadable on both sides",
    M.parse_width_m(value) == nil)
end
check("and so is an absent one", M.parse_width_m(nil) == nil and M.parse_width_m("") == nil)

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

-- `bicycle=no` is not the only way to deny it. PLAN:72 says the Lua mapping is
-- verified not to deny bicycle access at those nodes, and a blanket `access=no`
-- denies it to everyone - so the guard reads both keys, on the merged tags.
check("a blanket access=no at a border node is a denial too",
  M.denies_bicycle_at_border(border, { access = "no" }))
check("and an access=no the node arrived with counts, since the merge keeps it",
  M.denies_bicycle_at_border({ barrier = "border_control", access = "no" }, {}))
check("a write that does not clear it leaves it denied",
  M.denies_bicycle_at_border(
    { barrier = "border_control", access = "no" },
    { barrier = "gate" }))
check("but clearing it lifts the denial",
  not M.denies_bicycle_at_border(
    { barrier = "border_control", access = "no" },
    { access = M.REMOVE }))
check("a permissive access value is no denial at all",
  not M.denies_bicycle_at_border({ barrier = "border_control", access = "yes" }, {}))

-- Bridge legality is expressed through access, which is what it actually is.
check("bridge legality sets bicycle access",
  M.remap_way({ highway = "trunk" }, { bridge_bicycle_legal = false }).bicycle == "no")
check("and the legal half writes yes",
  M.remap_way({ highway = "secondary", bridge = "yes" },
              { bridge_bicycle_legal = true }).bicycle == "yes")
check("a row with no opinion writes nothing",
  M.remap_way({ highway = "secondary", bridge = "yes" }, {}).bicycle == nil)

-- The `yes` half widens access, so it carries the guard the cycleway write
-- carries - and a different one, because the two answer to different
-- authorities. A legality row IS a reviewed correction to OSM's own `bicycle`
-- tagging on that bridge, so it overrides `bicycle=no`; it is not a claim that
-- a way its owner has closed is open to the public, so it never overrides an
-- `access` or `vehicle` restriction, and never lands on a motorway.
check("the fixture may override an explicit bicycle=no on the roadway",
  M.remap_way({ highway = "secondary", bridge = "yes", bicycle = "no" },
              { bridge_bicycle_legal = true }).bicycle == "yes")
check("and a directional one",
  M.remap_way({ highway = "secondary", bridge = "yes", ["bicycle:forward"] = "no" },
              { bridge_bicycle_legal = true }).bicycle == "yes")

for _, case in ipairs({
  { highway = "service", bridge = "yes", access = "no" },
  { highway = "service", bridge = "yes", access = "private" },
  { highway = "service", bridge = "yes", access = "customers" },
  { highway = "service", bridge = "yes", access = "destination" },
  { highway = "service", bridge = "yes", vehicle = "no" },
  { highway = "motorway", bridge = "yes" },
  { highway = "motorway_link", bridge = "yes", bicycle = "no" },
}) do
  local label = (case.access and ("access=" .. case.access))
    or (case.vehicle and ("vehicle=" .. case.vehicle))
    or ("highway=" .. case.highway)
  check(label .. " is never widened to bicycle=yes",
    M.remap_way(case, { bridge_bicycle_legal = true }).bicycle == nil)
  -- And the narrowing half still applies there, because it only narrows.
  check(label .. " still takes a barring row",
    M.remap_way(case, { bridge_bicycle_legal = false }).bicycle == "no")
end

check("a permissively tagged bridge still takes the grant",
  M.remap_way({ highway = "unclassified", bridge = "yes", access = "permissive" },
              { bridge_bicycle_legal = true }).bicycle == "yes")
check("trunk is not motor-only here - US-1 and New York Avenue are trunk and bike-legal",
  M.remap_way({ highway = "trunk", bridge = "yes" },
              { bridge_bicycle_legal = true }).bicycle == "yes")

-- `electric_bicycle` says nothing to this file, and the grant is not declined
-- for it.
--
-- The protection it used to provide is real: the e-bike variant is built by
-- writing `bicycle=no` onto every way tagged `electric_bicycle=no`, in the
-- extract, before this transform ever sees it, so a bridge whose roadway the
-- fixture calls legal arrives carrying a `bicycle=no` indistinguishable from
-- OSM's own and the grant put it back to `yes` - undoing the variant on exactly
-- the ways this file may widen.
--
-- It is in the wrong layer here and it was wider than the thing it protected.
-- One Lua script serves all three extracts, so a guard in this file cannot tell
-- which variant is being parsed: it declined the legality row on the standard
-- and no-trail extracts too, where nothing had written `bicycle=no` and the row
-- applies. And it declined on `private`, `destination` and `customers` as well,
-- values no variant writes, so narrowing it to `== "no"` left both suites
-- green. `variants.inject_tags` knows the variant and suppresses the
-- bridge-legality tag on an `electric_bicycle=no` way for the EBIKE variant
-- alone, which is where the protection lives now; these cases assert that this
-- file no longer takes the row away from the two variants entitled to it.
check("a way barred to e-bikes still takes its legality row here",
  M.remap_way({ highway = "secondary", bridge = "yes", bicycle = "no",
                electric_bicycle = "no" },
              { bridge_bicycle_legal = true }).bicycle == "yes")
check("and the barring half of the row still applies there",
  M.remap_way({ highway = "secondary", bridge = "yes", electric_bicycle = "no" },
              { bridge_bicycle_legal = false }).bicycle == "no")
check("the key is not read at all, whatever its value",
  M.bridge_may_be_granted({ highway = "secondary", bridge = "yes",
                            electric_bicycle = "no" })
    and M.bridge_may_be_granted({ highway = "secondary", bridge = "yes",
                                  electric_bicycle = "designated" }))
check("and an untagged way is granted as before",
  M.bridge_may_be_granted({ highway = "secondary", bridge = "yes" }))
-- The guards that remain are the way's own access statement and the motor-only
-- class, and they are unmoved by the key going away.
check("an access restriction still declines the grant even with e-bikes permitted",
  not M.bridge_may_be_granted({ highway = "secondary", bridge = "yes",
                                access = "no", electric_bicycle = "designated" }))

-- ---------------------------------------------------------------------------
-- The lit write, which is the derived value with no Lua-side test at all.
--
-- The Python producer of `rm:lit` was pinned and this consumer was not: with
-- `derived.lit ~= nil` inverted to `== nil`, and with either of the two
-- and/or operators swapped, all three Lua suites stayed green. Valhalla reads
-- `lit` on a way, so the difference is the night-riding signal on every way the
-- reference data lights or declares unlit.
-- ---------------------------------------------------------------------------
local lit_yes = M.remap_way({ highway = "residential" }, { lit = true })
check("a lit way is written lit=yes", lit_yes.lit == "yes", tostring(lit_yes.lit))
check("and as the string Valhalla reads, not a boolean",
  type(lit_yes.lit) == "string", type(lit_yes.lit))

local lit_no = M.remap_way({ highway = "residential" }, { lit = false })
check("a way declared unlit is written lit=no", lit_no.lit == "no", tostring(lit_no.lit))
check("also as a string", type(lit_no.lit) == "string", type(lit_no.lit))

-- `false` and `nil` are the two readings that must not collapse into one: no
-- opinion leaves OSM's own `lit` tagging standing, while `false` overwrites it.
local lit_absent = M.remap_way({ highway = "residential", lit = "yes" }, {})
check("a way with no lit opinion keeps its own tagging",
  lit_absent.lit == nil, tostring(lit_absent.lit))

-- Directional conditional access, for the parkway reversal. Valhalla's Lua
-- transform reads bicycle:forward and bicycle:backward and no *:conditional key
-- (its C++ parser reads them as timed restrictions; see M.remap_conditional_access
-- in the remap) - so, by its static tags, a road signed
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

-- The mass-ride-only bar (`variants.bar_mass_ride_only_roadway`, owner rule of
-- 2026-09-26) sets every conditional key present to a bare "no" on the standard
-- and e-bike extracts, and relies on this: a bare "no" over a base of "no"
-- opens nothing in either direction.
do
  local barred = M.remap_conditional_access({
    bicycle = "no",
    ["bicycle:conditional"] = "no",
    ["bicycle:forward:conditional"] = "no",
    ["bicycle:backward:conditional"] = "no",
  })
  check("a bare no conditional over a barred way opens neither direction",
    barred["bicycle:forward"] == nil and barred["bicycle:backward"] == nil)
end

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

-- "Less restrictive" is strict. A branch at the base's own rank grants nothing
-- the way does not already grant, so writing it turns a time-limited sign into
-- a permanent tag for no gain - and on a way with no base tag at all the
-- comparison is against fully permissive, where a tie is every `designated @`
-- and `yes @` conditional in the extract being written as unconditional.
check("a conditional at the base's own rank is not a relaxation",
  M.least_restrictive("destination", "destination @ (Mo-Fr 07:00-19:00)") == nil)
check("nor is a same-rank value under another name",
  M.least_restrictive("yes", "designated @ (Sa,Su)") == nil)
check("an absent base counts as permissive, so designated ties with it",
  M.least_restrictive(nil, "designated @ (Sa,Su 07:00-19:00)") == nil)
check("and nothing is written onto a way with no base tag",
  next(M.remap_conditional_access(
    { highway = "residential", ["bicycle:conditional"] = "designated @ (Sa,Su)" })) == nil)
check("a genuinely less restrictive branch still opens",
  M.least_restrictive("destination", "yes @ (Sa,Su)") == "yes")

-- On a one-way the undirected conditional speaks for the traffic's direction
-- only, unless the way itself grants the reverse (Pulaski Highway, contraflow
-- review r1).
local PULASKI_CONDITIONAL = "yes @ (Sa-Su dawn-dusk; PH dawn-dusk)"
local function pulaski(extra)
  local tags = { highway = "trunk", bicycle = "no", ["bicycle:conditional"] = PULASKI_CONDITIONAL }
  for k, v in pairs(extra) do tags[k] = v end
  return M.remap_conditional_access(tags)
end
for _, shape in ipairs({
  { oneway = "yes" }, { oneway = "true" }, { oneway = "1" }, { oneway = "-1" },
  { junction = "roundabout" }, { junction = "circular" },
}) do
  local out = pulaski(shape)
  local name = shape.oneway and ("oneway=" .. shape.oneway) or ("junction=" .. shape.junction)
  check("a one-way's undirected conditional opens with the traffic (" .. name .. ")",
    out["bicycle:forward"] == "yes")
  check("and not against it (" .. name .. ")", out["bicycle:backward"] == nil)
end
for _, shape in ipairs({ {}, { oneway = "no" }, { oneway = "reversible" }, { oneway = "alternating" } }) do
  check("a two-way way's undirected conditional still opens both directions ("
      .. tostring(shape.oneway) .. ")",
    pulaski(shape)["bicycle:backward"] == "yes" and pulaski(shape)["bicycle:forward"] == "yes")
end
for _, grant in ipairs({
  { ["oneway:bicycle"] = "no" }, { ["oneway:bicycle"] = "false" }, { ["oneway:bicycle"] = "0" },
  { ["oneway:bicycle"] = "-1" },
  { cycleway = "opposite" }, { ["cycleway:left"] = "opposite_lane" },
  { ["cycleway:right"] = "opposite_track" }, { ["cycleway:both"] = "opposite_lane" },
  { ["vehicle:backward"] = "yes" }, { ["vehicle:backward"] = "designated" },
  { ["vehicle:backward"] = "permissive" },
}) do
  local key, value = next(grant)
  local tags = { oneway = "yes" }
  tags[key] = value
  check("a one-way granting contraflow (" .. key .. "=" .. value .. ") keeps the reverse",
    pulaski(tags)["bicycle:backward"] == "yes")
end
check("a bicycle:backward grant speaks for the reverse",
  M.speaks_for_reverse({ oneway = "yes", ["bicycle:backward"] = "permissive" }))
check("a bicycle:backward restriction does not",
  not M.speaks_for_reverse({ oneway = "yes", ["bicycle:backward"] = "no" }))
check("nor oneway:bicycle=yes",
  not M.speaks_for_reverse({ oneway = "yes", ["oneway:bicycle"] = "yes" }))
check("nor a with-flow lane", not M.speaks_for_reverse({ oneway = "yes", ["cycleway:right"] = "lane" }))
check("nor a vehicle:backward=no", not M.speaks_for_reverse({ oneway = "yes", ["vehicle:backward"] = "no" }))
check("a directional backward conditional on a one-way is the mapper's own word for the reverse",
  M.remap_conditional_access({
    oneway = "yes", bicycle = "no", ["bicycle:backward:conditional"] = "yes @ (Sa,Su)",
  })["bicycle:backward"] == "yes")
check("and the undirected one still decides the with-flow side beside it",
  M.remap_conditional_access({
    oneway = "yes", bicycle = "no", ["bicycle:backward:conditional"] = "no",
    ["bicycle:conditional"] = "yes @ (Sa,Su)",
  })["bicycle:forward"] == "yes")
check("the closure's bare no over the backward conditional still opens nothing against",
  M.remap_conditional_access({
    oneway = "yes", bicycle = "no", ["bicycle:backward:conditional"] = "no",
    ["bicycle:conditional"] = "yes @ (Sa,Su)", ["oneway:bicycle"] = "yes",
  })["bicycle:backward"] == nil)

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
  local road = { highway = "residential" }
  road[key] = value
  check("and earns no cycleway write",
    M.remap_way(road, { stress_tier = 1, facility = "path" }).cycleway == nil, key)
end

-- The one cycleway write left is a road closed to motor traffic, which the
-- facility class calls a path (`routemaker.facility`).
check("an unrestricted car-free road gets its write",
  M.remap_way({ highway = "residential", motor_vehicle = "no" }, { facility = "path" }).cycleway
    == "track")
check("and so does one whose bicycle tag reopens it",
  M.remap_way({ highway = "tertiary", access = "no", bicycle = "yes" }, { facility = "path" })
    .cycleway == "track")

-- Superseded 2026-09-27: stress no longer reaches the graph as a cycleway
-- write at any tier. It reaches it as the use_sidepath penalty, on tiers 3 and
-- 4 and nowhere else; every tier is checked, because `>= 3` narrowed to `== 4`
-- or widened to `>= 2` moves only a tier a two-case test never looks at.
for tier = 1, 4 do
  local out = M.remap_way({ highway = "residential" }, { stress_tier = tier })
  check("stress tier " .. tier .. " writes no cycleway", out.cycleway == nil)
  check("stress tier " .. tier .. " is penalised only at 3 and 4",
    (out.bicycle == "use_sidepath") == (tier >= 3), tostring(out.bicycle))
end
check("no tier at all writes nothing",
  next(M.remap_way({ highway = "residential" }, {})) == nil)
check("the penalty never lands on a trail-class way",
  M.remap_way({ highway = "cycleway" }, { stress_tier = 4, is_trail_class = true }).bicycle == nil)
check("nor over a refusal",
  M.remap_way({ highway = "primary", bicycle = "no" }, { stress_tier = 4 }).bicycle == nil)
check("nor over dismount",
  M.remap_way({ highway = "primary", bicycle = "dismount" }, { stress_tier = 4 }).bicycle == nil)
check("nor onto a way whose access restricts it",
  M.remap_way({ highway = "primary", access = "private" }, { stress_tier = 4 }).bicycle == nil)
check("nor onto an untagged motorway",
  M.remap_way({ highway = "motorway" }, { stress_tier = 4 }).bicycle == nil)
check("it replaces an explicit yes",
  M.remap_way({ highway = "primary", bicycle = "yes" }, { stress_tier = 3 }).bicycle
    == "use_sidepath")
check("and a bridge legality of false still bars the roadway",
  M.remap_way({ highway = "primary" }, { stress_tier = 4, bridge_bicycle_legal = false }).bicycle
    == "no")
check("while a legality of true is penalised like any tier-4 roadway",
  M.remap_way({ highway = "primary", bicycle = "no" }, { stress_tier = 4, bridge_bicycle_legal = true })
    .bicycle == "use_sidepath")
check("the penalised tiers are 3 and 4", M.STRESS_PENALTY_TIER == 3)

-- ---------------------------------------------------------------------------
-- A way that already declares a cycleway on any side keeps what it was tagged.
--
-- The guard read the bare `cycleway` key alone, so the three side forms went
-- straight through it: `cycleway:both=no` is a mapper who surveyed the street
-- and found no facility, and the write asserted a separated track over that
-- survey; `cycleway:left=lane` is a painted lane on one side, and the write
-- replaced the mapper's own value with `track`, which is both an invention and
-- a loss. A side key is not an exotic spelling - it is what a mapper writes the
-- moment a street has a facility on one side only, which is most of the
-- District's network.
--
-- The key list is the same one Python's `tags.cycleway_values` reads, and it is
-- presence that blocks the write rather than value, exactly as the bare-key
-- guard always worked: the question is whether anybody has already said
-- something about a cycleway here, not what they said.
for _, key in ipairs({ "cycleway", "cycleway:both", "cycleway:left", "cycleway:right" }) do
  for _, value in ipairs({ "no", "lane", "track", "separate" }) do
    local tags = { highway = "residential" }
    tags[key] = value
    tags.motor_vehicle = "no"
    check(key .. "=" .. value .. " blocks the write",
      M.remap_way(tags, { facility = "path" }).cycleway == nil, key .. "=" .. value)
    tags.motor_vehicle = nil
    check(key .. "=" .. value .. " is seen by declares_cycleway", M.declares_cycleway(tags))
  end
end
check("the key list is exactly the four forms", #M.CYCLEWAY_KEYS == 4)
-- And nothing wider: a width key is not a facility value and a sidewalk is not
-- a cycleway, so neither may block a write the way deserves.
check("a cycleway width alone does not block the write",
  M.remap_way({ highway = "residential", ["cycleway:left:width"] = "2.0", sidewalk = "both",
                motor_vehicle = "no" }, { facility = "path" }).cycleway == "track")
check("and declares_cycleway says so",
  not M.declares_cycleway({ highway = "residential", ["cycleway:left:width"] = "2.0" }))

-- The side precedence, case by case: the side key over `:both` over the bare
-- key, one answer per side. The same cases Python's side record is held to.
local precedence_cases = {
  { { cycleway = "track", ["cycleway:right"] = "no" }, "track", "no" },
  { { cycleway = "track", ["cycleway:both"] = "lane" }, "lane", "lane" },
  { { ["cycleway:both"] = "lane", ["cycleway:left"] = "track" }, "track", "lane" },
  { { cycleway = "no", ["cycleway:left"] = "lane" }, "lane", "no" },
  { { ["cycleway:right"] = "lane" }, nil, "lane" },
  { { cycleway = "" }, nil, nil },
  { {}, nil, nil },
}
for index, case in ipairs(precedence_cases) do
  local tags, left, right = case[1], case[2], case[3]
  check("precedence case " .. index .. " left",
    M.cycleway_on_side(tags, "left") == left)
  check("precedence case " .. index .. " right",
    M.cycleway_on_side(tags, "right") == right)
  check("precedence case " .. index .. " guard",
    M.declares_cycleway(tags) == (left ~= nil or right ~= nil))
end

-- ---------------------------------------------------------------------------
-- The barrier conversion, and what it may and may not clear.
-- ---------------------------------------------------------------------------

check("a motor-vehicle-only tag is cleared so gate_cost can apply",
  M.remap_node({ barrier = "cycle_barrier", motor_vehicle = "no" }).motor_vehicle == M.REMOVE)
check("so is one on a converted bollard",
  M.remap_node({ barrier = "bollard", maxwidth = "1.0", hgv = "no" }).hgv == M.REMOVE)
check("nothing is cleared on a barrier that was not converted",
  M.remap_node({ barrier = "bollard", motor_vehicle = "no" }).motor_vehicle == nil)
-- `bicycle` is the member of BICYCLE_ACCESS_KEYS the checks above exercise, and
-- it was the only one: the list could be cut to { "bicycle" } with the suite
-- green. Both of the others are ordinary tagging on the barriers this converts -
-- a trail bollard or cycle barrier carrying `access=yes` or `foot=yes` - and
-- either one left in place holds tagged_access at 1, which multiplies gate_cost
-- to nothing and makes the Cargo preset's dial inert on exactly the nodes it
-- exists for.
check("a permissive access tag on a converted barrier is marked for removal too",
  M.remap_node({ barrier = "cycle_barrier", access = "yes" }).access == M.REMOVE)
check("and a permissive foot tag",
  M.remap_node({ barrier = "cycle_barrier", foot = "yes" }).foot == M.REMOVE)
check("every permissive value counts, not just yes",
  M.remap_node({ barrier = "cycle_barrier", access = "permissive" }).access == M.REMOVE
    and M.remap_node({ barrier = "cycle_barrier", foot = "designated" }).foot == M.REMOVE)
check("and the same on a converted bollard",
  M.remap_node({ barrier = "bollard", maxwidth = "1.0", access = "yes" }).access == M.REMOVE)
check("nothing is cleared on a bollard that was not converted",
  M.remap_node({ barrier = "bollard", access = "yes" }).access == nil)
check("a restrictive bicycle tag is never cleared",
  M.remap_node({ barrier = "cycle_barrier", bicycle = "no" }).bicycle == nil)
check("nor a restrictive foot tag",
  M.remap_node({ barrier = "cycle_barrier", foot = "no" }).foot == nil)
check("nor is vehicle=no, which bars bicycles under OSM semantics",
  M.remap_node({ barrier = "cycle_barrier", vehicle = "no" }).vehicle == nil)
check("nor is a restrictive access tag",
  M.remap_node({ barrier = "cycle_barrier", access = "private" }).access == nil)

-- ---------------------------------------------------------------------------
-- The stress penalty is a cost on a way already open to bicycles, never a
-- grant over a refusal. (These cases were the retired ordinary-ride
-- penalty's, which wrote the same tag; they hold for the tier that replaced it.)
-- ---------------------------------------------------------------------------

local P = M.STRESS_PENALTY_BICYCLE
local pen = { stress_tier = 4 }
check("the penalty is upstream's sidepath-preferred value", P == "use_sidepath")
for _, value in ipairs({ "yes", "designated", "permissive" }) do
  check("the penalty replaces bicycle=" .. value,
    M.remap_way({ highway = "secondary", bicycle = value }, pen).bicycle == P)
end
check("and lands on an untagged, unrestricted road",
  M.remap_way({ highway = "secondary" }, pen).bicycle == P)
for label, tags in pairs({
  ["bicycle=no"] = { highway = "secondary", bicycle = "no" },
  ["bicycle=private"] = { highway = "secondary", bicycle = "private" },
  ["access=no"] = { highway = "secondary", access = "no" },
  ["vehicle=no"] = { highway = "secondary", vehicle = "no" },
  ["bicycle:forward=no"] = { highway = "secondary", ["bicycle:forward"] = "no" },
}) do
  check("the penalty never opens a way that refuses a bicycle (" .. label .. ")",
    M.remap_way(tags, pen).bicycle == nil)
end
-- Nor one whose road class refuses it: untagged, these are closed to a bicycle
-- by upstream's highway table, and `use_sidepath` would open them.
for _, class in ipairs({ "motorway", "motorway_link", "footway", "pedestrian", "bridleway",
                         "busway", "bus_guideway", "corridor", "elevator", "platform" }) do
  check("the penalty never opens an untagged highway=" .. class,
    M.remap_way({ highway = class }, pen).bicycle == nil)
end
for class in pairs(M.MOTOR_ONLY_HIGHWAY) do
  check("no motor-only class admits a bicycle by default (" .. class .. ")",
    not M.BICYCLE_BY_DEFAULT_HIGHWAY[class])
end
check("nor a construction site without a class",
  M.remap_way({ highway = "construction" }, pen).bicycle == nil)
for _, class in ipairs({ "residential", "trunk", "cycleway", "path", "track" }) do
  check("and it still lands on an untagged highway=" .. class,
    M.remap_way({ highway = class }, pen).bicycle == P)
end
-- And leaves a bicycle value that says more than "may ride" alone.
for _, value in ipairs({ "dismount", "destination", "discouraged", "use_sidepath" }) do
  check("the penalty leaves bicycle=" .. value .. " alone",
    M.remap_way({ highway = "secondary", bicycle = value }, pen).bicycle == nil)
end
check("a fixture legality of false wins over the penalty",
  M.remap_way({ highway = "secondary", bicycle = "yes" },
              { stress_tier = 4, bridge_bicycle_legal = false }).bicycle == "no")
check("a fixture legality of true is granted and then penalised",
  M.remap_way({ highway = "secondary", bicycle = "no" },
              { stress_tier = 4, bridge_bicycle_legal = true }).bicycle == P)
check("no tier, no change",
  M.remap_way({ highway = "secondary", bicycle = "yes" }, {}).bicycle == nil)
check("a derived ordinary_ride_penalty is read by nothing any more",
  M.remap_way({ highway = "secondary", bicycle = "yes" },
              { ordinary_ride_penalty = true }).bicycle == nil)

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

-- ---------------------------------------------------------------------------
-- Facility (the owner's order, 2026-09-27): off-road path > protected >>
-- painted lane > ordinary street, sharrows nothing; and nothing at all on the
-- no-trail variant Mass Ride routes on.
-- ---------------------------------------------------------------------------

local function fac(tags, facility, extra)
  local derived = { facility = facility }
  for k, v in pairs(extra or {}) do derived[k] = v end
  return M.remap_way(tags, derived)
end

check("an off-road footpath is segregated",
  fac({ highway = "path" }, "path").segregated == "yes")
check("a separately mapped protected lane is left as upstream prices it",
  next(fac({ highway = "cycleway" }, "protected")) == nil)
check("a mapper's own segregated tag stands",
  fac({ highway = "path", segregated = "no" }, "path").segregated == nil)
check("no cycleway key is ever written on a trail-class way",
  fac({ highway = "footway", bicycle = "designated" }, "path").cycleway == nil
    and fac({ highway = "cycleway" }, "protected").cycleway == nil)
check("a trail-class way with no facility is left alone",
  next(fac({ highway = "footway" }, "none")) == nil)

check("a painted lane is moved to upstream's shared class",
  fac({ highway = "tertiary", ["cycleway:right"] = "lane" }, "lane")["cycleway:right"] == "shared_lane")
check("a buffered lane too",
  fac({ highway = "tertiary", cycleway = "buffered_lane" }, "lane").cycleway == "shared_lane")
check("a physically separated painted lane is a track",
  fac({ highway = "tertiary", ["cycleway:both"] = "lane" }, "protected")["cycleway:both"] == "track")
check("a track stays a track",
  fac({ highway = "primary", ["cycleway:left"] = "track" }, "protected")["cycleway:left"] == nil)
check("a sharrow counts as nothing",
  fac({ highway = "residential", cycleway = "shared_lane" }, "none").cycleway == M.REMOVE)
check("a bus lane shared with bicycles counts as nothing",
  fac({ highway = "secondary", ["cycleway:both"] = "share_busway" }, "none")["cycleway:both"] == M.REMOVE)
check("contraflow is never touched",
  fac({ highway = "residential", oneway = "yes", ["cycleway:left"] = "opposite_lane" }, "lane")
    ["cycleway:left"] == nil)
check("separate and no are never touched",
  next(fac({ highway = "primary", ["cycleway:right"] = "separate", ["cycleway:left"] = "no" }, "none"))
    == nil)
-- Upstream opens a way to bicycles when both sides carry a lane of any class,
-- over bicycle=no; moving or removing a value there could close the way.
check("no lane is moved where the bicycle tag refuses",
  next(fac({ highway = "secondary", bicycle = "no", ["cycleway:both"] = "shared_lane" }, "none")) == nil)
check("nor where access restricts the way",
  next(fac({ highway = "residential", access = "private", cycleway = "lane" }, "lane")) == nil)
check("nor on a class closed to bicycles by default",
  next(fac({ highway = "motorway", cycleway = "shared_lane" }, "none")) == nil)

check("the no-trail variant takes every lane off the roadway",
  fac({ highway = "tertiary", ["cycleway:right"] = "track", ["cycleway:left"] = "lane" }, nil,
      { facility_neutral = true })["cycleway:right"] == M.REMOVE)
check("and the painted one too",
  fac({ highway = "tertiary", ["cycleway:both"] = "lane" }, nil, { facility_neutral = true })
    ["cycleway:both"] == M.REMOVE)
check("but never contraflow",
  fac({ highway = "residential", oneway = "yes", cycleway = "opposite_track" }, nil,
      { facility_neutral = true }).cycleway == nil)
check("and it writes no path signal even when handed a class",
  next(fac({ highway = "residential", motor_vehicle = "no" }, "path", { facility_neutral = true }))
    == nil)

-- cycleway:both spelled out as the two sides upstream prices.
local split = M.remap_way({ highway = "primary", ["cycleway:both"] = "track" }, { facility = "protected" })
check("cycleway:both=track is copied to both sides",
  split["cycleway:left"] == "track" and split["cycleway:right"] == "track")
local painted = M.remap_way({ highway = "tertiary", ["cycleway:both"] = "lane" }, { facility = "lane" })
check("a painted both-sides lane is copied after the facility rewrite",
  painted["cycleway:left"] == "shared_lane" and painted["cycleway:right"] == "shared_lane")
local sided = M.remap_way({ highway = "tertiary", ["cycleway:both"] = "lane", ["cycleway:left"] = "no" },
  { facility = "none" })
check("a side the mapper spoke for is left alone",
  sided["cycleway:left"] == nil and sided["cycleway:right"] == "shared_lane")
check("a sharrow on both sides is not copied",
  M.remap_way({ highway = "residential", ["cycleway:both"] = "shared_lane" }, { facility = "none" })
    ["cycleway:right"] == nil)
check("contraflow is never copied",
  M.remap_way({ highway = "residential", oneway = "yes", ["cycleway:both"] = "opposite_lane" },
    { facility = "lane" })["cycleway:left"] == nil)
check("separate is never copied",
  M.remap_way({ highway = "primary", ["cycleway:both"] = "separate" }, { facility = "none" })
    ["cycleway:left"] == nil)
check("nor onto the no-trail variant",
  M.remap_way({ highway = "tertiary", ["cycleway:both"] = "track" }, { facility_neutral = true })
    ["cycleway:right"] == nil)
check("nor onto a trail-class way",
  M.remap_way({ highway = "cycleway", ["cycleway:both"] = "lane" }, { facility = "path" })
    ["cycleway:left"] == nil)
check("nor where the bicycle tag refuses",
  M.remap_way({ highway = "secondary", bicycle = "no", ["cycleway:both"] = "lane" }, {})
    ["cycleway:left"] == nil)
check("and it runs without a facility class",
  M.remap_way({ highway = "tertiary", ["cycleway:both"] = "track" }, {})["cycleway:left"] == "track")

-- A car-free road's sharrow counts for nothing; the road is a track.
local closed_sharrow = M.remap_way({ highway = "tertiary", bicycle = "designated", cycleway = "shared_lane" },
  { facility = "path" })
check("a car-free road with a sharrow is a track", closed_sharrow.cycleway == "track")
local closed_side = M.remap_way({ highway = "tertiary", ["cycleway:right"] = "shared_lane",
  motor_vehicle = "no" }, { facility = "path" })
check("a side sharrow is removed and the road is a track",
  closed_side["cycleway:right"] == M.REMOVE and closed_side.cycleway == "track")
check("a car-free road with a real lane keeps it and gets no track",
  M.remap_way({ highway = "tertiary", cycleway = "lane", motor_vehicle = "no" }, { facility = "path" })
    .cycleway == nil)
check("nor over a refusal",
  next(M.remap_way({ highway = "tertiary", bicycle = "no", cycleway = "shared_lane" }, { facility = "path" }))
    == nil)

-- "Legal but avoid" (tier 5): the stress penalty and the alley use, and
-- nothing about motor vehicles (only tier-5 ways pay; local-access ways stay).
local avoid = M.remap_way({ highway = "trunk", expressway = "yes", maxspeed = "55 mph" }, { stress_tier = 5 })
check("tier 5 carries the stress penalty", avoid.bicycle == "use_sidepath")
check("and the alley use", avoid.service == "alley")
check("and writes nothing about motor vehicles", avoid.motor_vehicle == nil)
for tier = 1, 4 do
  check("tier " .. tier .. " gets no alley use",
    M.remap_way({ highway = "trunk" }, { stress_tier = tier }).service == nil)
end
check("never on a trail-class way",
  M.remap_way({ highway = "cycleway" }, { stress_tier = 5, is_trail_class = true }).service == nil)
check("never over a way's own service value",
  M.remap_way({ highway = "primary", service = "busway" }, { stress_tier = 5 }).service == nil)
check("never on a service road",
  M.remap_way({ highway = "service" }, { stress_tier = 5 }).service == nil)
check("nor where a bicycle may not ride",
  M.remap_way({ highway = "primary", bicycle = "no" }, { stress_tier = 5 }).service == nil)
check("nor where a bridge legality of false bars the roadway",
  M.remap_way({ highway = "primary" }, { stress_tier = 5, bridge_bicycle_legal = false }).service == nil)
check("nor on an untagged motorway",
  M.remap_way({ highway = "motorway" }, { stress_tier = 5 }).service == nil)
check("a roadway OSM already tags use_sidepath is marked (the Douglass bridge)",
  M.remap_way({ highway = "primary", bicycle = "use_sidepath", foot = "no" }, { stress_tier = 5 })
    .service == "alley")
-- Review RL-1: OSM's own use_sidepath on a road with no side path mapped is rated on its
-- own merits, so below the penalty's tier it is plain access, and from it the penalty.
check("OSM's use_sidepath never opens a motorway",
  M.remap_way({ highway = "motorway", bicycle = "use_sidepath" }, { stress_tier = 4 }).bicycle
    == "no")
check("nor a motorroad",
  M.remap_way({ highway = "trunk", motorroad = "yes", bicycle = "use_sidepath" },
    { stress_tier = 4 }).bicycle == "no")
check("nor a private road",
  M.remap_way({ highway = "service", access = "private", bicycle = "use_sidepath" },
    { stress_tier = 1 }).bicycle == "no")
check("nor a vehicle=no road",
  M.remap_way({ highway = "residential", vehicle = "no", bicycle = "use_sidepath" },
    { stress_tier = 1 }).bicycle == "no")
check("an open road with it is not closed",
  M.remap_way({ highway = "primary", bicycle = "use_sidepath" }, { stress_tier = 5 }).bicycle
    == nil)
check("OSM's use_sidepath below tier 3 is plain access",
  M.remap_way({ highway = "secondary", bicycle = "use_sidepath" }, { stress_tier = 2 }).bicycle
    == "yes")
check("OSM's use_sidepath at tier 3 is left as the penalty",
  M.remap_way({ highway = "secondary", bicycle = "use_sidepath" }, { stress_tier = 3 }).bicycle
    == nil)
check("OSM's use_sidepath at Avoid is left as the penalty",
  M.remap_way({ highway = "secondary", bicycle = "use_sidepath" }, { stress_tier = 5 }).bicycle
    == nil)
check("OSM's own alleys become service roads, so they do not pay the tier-5 charge",
  M.remap_way({ highway = "service", service = "alley" }, {}).service == M.REMOVE)
check("at every tier",
  M.remap_way({ highway = "service", service = "alley" }, { stress_tier = 2 }).service == M.REMOVE)
check("and other service values are left alone",
  M.remap_way({ highway = "service", service = "driveway" }, {}).service == nil)
check("a local-access street is not touched",
  next(M.remap_way({ highway = "residential", access = "destination" }, { stress_tier = 1 })) == nil)

-- Graded: LTS 4 and up take the graph's top speed and lane count (the owner,
-- 2026-09-28: "I'd probably want LTS 4 to be twice the stress level of LTS 3
-- at least.").
local SP, LF, LB = "maxspeed:practical", "lanes:forward", "lanes:backward"
local function graded(out) return out[SP] == "140" and out[LF] == "15" and out[LB] == "15" end
local function ungraded(out) return out[SP] == nil and out[LF] == nil and out[LB] == nil end
check("tier 3: the penalty, not graded",
  ungraded(M.remap_way({ highway = "secondary" }, { stress_tier = 3 })))
check("tier 4: graded", graded(M.remap_way({ highway = "secondary" }, { stress_tier = 4 })))
check("tier 5: graded too", graded(M.remap_way({ highway = "trunk" }, { stress_tier = 5 })))
check("tier 5 over OSM's own use_sidepath (Douglass)",
  graded(M.remap_way({ highway = "primary", bicycle = "use_sidepath", foot = "no" }, { stress_tier = 5 })))
check("over a way's own lanes and practical speed",
  graded(M.remap_way({ highway = "secondary", lanes = "4", ["maxspeed:practical"] = "30" }, { stress_tier = 4 })))
check("not on the no-trail variant",
  ungraded(M.remap_way({ highway = "secondary" }, { stress_tier = 4, facility_neutral = true })))
check("not on a trail-class way",
  ungraded(M.remap_way({ highway = "cycleway" }, { stress_tier = 4, is_trail_class = true })))
check("not where a bicycle may not ride",
  ungraded(M.remap_way({ highway = "secondary", bicycle = "no" }, { stress_tier = 4 })))
check("not where the penalty may not land (dismount)",
  ungraded(M.remap_way({ highway = "secondary", bicycle = "dismount" }, { stress_tier = 4 })))
check("no tier, not graded", ungraded(M.remap_way({ highway = "secondary" }, {})))

-- Mutation review r1, LU6 and LU20: the guards that keep a comfort write
-- from opening or closing a way.
check("a car-free way of a class not open to bicycles by default gets no track",
  fac({ highway = "construction", motor_vehicle = "no" }, "path").cycleway == nil
    and fac({ highway = "busway", motor_vehicle = "no" }, "path").cycleway == nil)
check("while one that is gets it",
  fac({ highway = "residential", motor_vehicle = "no" }, "path").cycleway == "track")
check("the no-trail variant takes no lane off a way the lanes open over bicycle=no",
  fac({ highway = "residential", bicycle = "no", ["cycleway:both"] = "lane" }, nil,
      { facility_neutral = true })["cycleway:both"] == nil)
check("a trail-class way is never graded, even one a mapper tagged use_sidepath (LU3)",
  ungraded(M.remap_way({ highway = "cycleway", bicycle = "use_sidepath" },
    { stress_tier = 4, is_trail_class = true })))
check("nor off one whose access is restricted",
  fac({ highway = "residential", access = "private", cycleway = "track" }, nil,
      { facility_neutral = true }).cycleway == nil)

-- OWNER-DECISIONS 110: an OSM alley is priced like LTS 3 (the stress
-- penalty), not graded, and does not pay the tier-5 entry charge.
local alley = M.remap_way({ highway = "service", service = "alley" }, { stress_tier = 1 })
check("an alley pays the LTS 3 penalty", alley.bicycle == "use_sidepath")
check("an alley is not graded", ungraded(alley))
check("an alley loses the alley use (no tier-5 entry charge)", alley.service == M.REMOVE)
check("a driveway does not pay the alley penalty",
  M.remap_way({ highway = "service", service = "driveway" }, { stress_tier = 1 }).bicycle == nil)
check("only a service road is an alley: service=alley on a track is not",
  M.remap_way({ highway = "track", service = "alley" }, { stress_tier = 1 }).bicycle == nil)
check("an alley a bicycle may not ride stays closed",
  M.remap_way({ highway = "service", service = "alley", bicycle = "no" }, { stress_tier = 1 }).bicycle == nil)

-- A parking aisle, driveway or drive-through open to bicycles by its own tags
-- loses upstream's destination-only use (M.bicycle_link_service).
for _, service in ipairs({ "parking_aisle", "driveway", "drive-through" }) do
  for _, grant in ipairs({ "yes", "designated", "permissive" }) do
    check(service .. " with bicycle=" .. grant .. " becomes a plain service road",
      M.remap_way({ highway = "service", service = service, bicycle = grant }, { stress_tier = 1 }).service
        == M.REMOVE)
  end
end
check("an aisle with no bicycle tag keeps its use",
  M.remap_way({ highway = "service", service = "parking_aisle" }, { stress_tier = 1 }).service == nil)
check("an aisle with bicycle=destination keeps its use",
  M.remap_way({ highway = "service", service = "parking_aisle", bicycle = "destination" }, {}).service == nil)
for _, restriction in ipairs({ { access = "private" }, { access = "customers" }, { vehicle = "private" },
    { access = "destination" } }) do
  local tags = { highway = "service", service = "parking_aisle", bicycle = "yes" }
  local key, value = next(restriction)
  tags[key] = value
  check("an aisle with " .. key .. "=" .. value .. " keeps its use", M.remap_way(tags, {}).service == nil)
end
check("an aisle with access=yes is still a link",
  M.remap_way({ highway = "service", service = "parking_aisle", bicycle = "yes", access = "yes" }, {}).service
    == M.REMOVE)
check("a parking aisle off a service highway is not touched",
  M.remap_way({ highway = "track", service = "parking_aisle", bicycle = "yes" }, {}).service == nil)
check("a tier-5 road still gets the entry charge",
  M.remap_way({ highway = "primary" }, { stress_tier = 5 }).service == M.AVOID_SERVICE)

-- OWNER-DECISIONS 111: singletrack is closed to every current ride type.
check("singletrack is bicycle=no",
  M.remap_way({ highway = "path", ["mtb:scale"] = "2" },
    { no_bicycle = "singletrack", is_trail_class = true, stress_tier = 1 }).bicycle == "no")
check("an unmarked dirt path is not",
  M.remap_way({ highway = "path", surface = "dirt" }, { is_trail_class = true, stress_tier = 1 }).bicycle == nil)

-- rm:no_bicycle closes each direction too, so no directional grant upstream
-- reads ahead of plain `bicycle` can reopen one (M.close_both_directions).
local cct = {
  highway = "path", bicycle = "yes", foot = "yes", surface = "dirt", ["mtb:scale"] = "2",
  ["bicycle:forward"] = "yes", oneway = "yes", ["oneway:bicycle"] = "no", cycleway = "opposite",
}
local closed_cct = M.remap_way(cct, { no_bicycle = "singletrack", is_trail_class = true, stress_tier = 1, facility = "path" })
check("closed singletrack closes the forward direction", closed_cct["bicycle:forward"] == "no",
  tostring(closed_cct["bicycle:forward"]))
check("and the backward direction", closed_cct["bicycle:backward"] == "no",
  tostring(closed_cct["bicycle:backward"]))
local closed_cbd = M.remap_way({ highway = "footway", footway = "sidewalk", ["bicycle:backward"] = "yes" },
  { no_bicycle = "cbd_sidewalk", is_trail_class = true })
check("so does a CBD sidewalk", closed_cbd["bicycle:forward"] == "no" and closed_cbd["bicycle:backward"] == "no")
local open_cct = M.remap_way(cct, { is_trail_class = true, stress_tier = 1, facility = "path" })
check("without the mark no direction is written",
  open_cct["bicycle:forward"] == nil and open_cct["bicycle:backward"] == nil)
check("the remap leaves the ratings to graph.lua, which reads upstream's verdict",
  closed_cct["mtb:scale"] == nil)

-- M.strip_ratings_if_closed, on tables shaped like upstream's output.
local function stripped(kv) M.strip_ratings_if_closed(kv); return kv end
local rated = function(fwd, bwd)
  return { bike_forward = fwd, bike_backward = bwd, ["mtb:scale"] = "2", ["mtb:scale:imba"] = "1",
    ["mtb:scale:uphill"] = "1", ["mtb:description"] = "rocky", mtb = "yes", surface = "dirt" }
end
local both_closed = stripped(rated("false", "false"))
for _, key in ipairs({ "mtb:scale", "mtb:scale:imba", "mtb:scale:uphill", "mtb:description" }) do
  check("closed both ways loses " .. key, both_closed[key] == nil)
end
check("but keeps bare mtb, which reopens nothing", both_closed.mtb == "yes")
check("and every other key", both_closed.surface == "dirt" and both_closed.bike_forward == "false")
check("forward closed alone is closed", stripped(rated("false", "true"))["mtb:scale"] == nil)
check("backward closed alone is closed", stripped(rated("true", "false"))["mtb:scale"] == nil)
local function one_way(fwd, bwd, reverse)
  local kv = rated(fwd, bwd)
  kv.oneway = "true"
  kv.oneway_reverse = reverse and "true" or "false"
  return stripped(kv)
end
check("a one-way open its own way keeps its ratings (the parser keeps its reverse closed)",
  one_way("true", "false")["mtb:scale"] == "2" and one_way("true", "false")["mtb:description"] == "rocky")
check("and so does oneway=-1, which upstream has already swapped",
  one_way("false", "true", true)["mtb:scale"] == "2")
check("a one-way closed its own way is stripped", one_way("false", "false")["mtb:scale"] == nil)
check("so is oneway=-1 closed its own way", one_way("true", "false", true)["mtb:scale"] == nil)
check("and a forward-only closure on a way that is not one-way",
  stripped(rated("false", "true"))["mtb:scale"] == nil)
check("a direction upstream left unset is closed, as the parser reads it",
  stripped(rated(nil, "true"))["mtb:scale"] == nil)
local open_both = stripped(rated("true", "true"))
check("open both ways keeps every rating", open_both["mtb:scale"] == "2" and open_both["mtb:scale:imba"] == "1"
  and open_both["mtb:scale:uphill"] == "1" and open_both["mtb:description"] == "rocky")
check("reports what it did",
  M.strip_ratings_if_closed(rated("false", "false")) == true
    and M.strip_ratings_if_closed({ bike_forward = "false", bike_backward = "false" }) == false
    and M.strip_ratings_if_closed(rated("true", "true")) == false)

-- OWNER-DECISIONS 104: a CBD sidewalk is barred to bicycles, and nothing else is.
check("a CBD sidewalk is bicycle=no",
  M.remap_way({ highway = "footway", footway = "sidewalk", bicycle = "yes" },
    { no_bicycle = "cbd_sidewalk", is_trail_class = true }).bicycle == "no")
check("without the mark a sidewalk keeps its bicycle tag",
  M.remap_way({ highway = "footway", footway = "sidewalk", bicycle = "yes" },
    { is_trail_class = true }).bicycle == nil)

-- The contraflow closure's `bicycle:backward=none` (pipeline.variants
-- .close_contraflow) is not a restriction on a one-way, and is one anywhere else.
for _, oneway in ipairs({ "yes", "true", "1", "-1" }) do
  check("a closed reverse direction leaves a oneway=" .. oneway .. " unrestricted",
    M.access_is_unrestricted({ oneway = oneway, ["bicycle:backward"] = "none" }))
end
check("and a roundabout",
  M.access_is_unrestricted({ junction = "roundabout", ["bicycle:backward"] = "none" }))
check("and a circular junction",
  M.access_is_unrestricted({ junction = "circular", ["bicycle:backward"] = "none" }))
check("not on a two-way way",
  not M.access_is_unrestricted({ ["bicycle:backward"] = "none" }))
check("nor on a reversible one",
  not M.access_is_unrestricted({ oneway = "reversible", ["bicycle:backward"] = "none" }))
check("a bicycle:backward=no is still a restriction on a one-way",
  not M.access_is_unrestricted({ oneway = "yes", ["bicycle:backward"] = "no" }))
check("and none on another key is still one",
  not M.access_is_unrestricted({ oneway = "yes", ["bicycle:forward"] = "none" }))
check("and the exception does not excuse another key's restriction",
  not M.access_is_unrestricted({ oneway = "yes", ["bicycle:backward"] = "none", access = "private" }))

-- OWNER-DECISIONS 291(4): the Zoo's destination-only spur.
local spur = M.remap_way({ highway = "footway", footway = "sidewalk", bicycle = "no" },
  { destination_only = true, is_trail_class = true })
check("a destination-only way is opened to bicycles", spur.bicycle == "destination")
check("and is destination-only for access", spur.access == "destination")
check("a stricter access tag is kept on it",
  M.remap_way({ highway = "service", access = "private" },
    { destination_only = true }).access == nil)
check("an unmarked footway is not opened",
  M.remap_way({ highway = "footway" }, { is_trail_class = true }).bicycle == nil)

-- A sidewalk ridden as a last resort (routemaker.sidewalks, 2026-10-20).
local ridden = M.remap_way({ highway = "footway", footway = "sidewalk" },
  { sidewalk = true, is_trail_class = true, stress_tier = 3 })
check("a ridden sidewalk is opened with the stress penalty",
  ridden.bicycle == "use_sidepath")
check("and priced at the sidewalk speed", ridden["maxspeed:practical"] == M.SIDEWALK_SPEED)
check("and given no road's graded lanes", ridden["lanes:forward"] == nil)
check("a ridden sidewalk never overrules a bicycle tag",
  M.remap_way({ highway = "footway", bicycle = "no" },
    { sidewalk = true, is_trail_class = true }).bicycle == nil)
check("nor a closure reason (a CBD sidewalk)",
  M.remap_way({ highway = "footway", footway = "sidewalk" },
    { sidewalk = true, is_trail_class = true, no_bicycle = "cbd_sidewalk" }).bicycle == "no")

-- A paved way is not a mountain-bike trail: its rating, which Valhalla's parser
-- prices as dirt, comes off (the Rock Creek Trail in Montgomery County, way
-- 851669430 among others, as the 2026-10-03 extract tags it).
local rock_creek = {
  highway = "cycleway", name = "Rock Creek Trail", surface = "paved", smoothness = "good",
  bicycle = "designated", foot = "designated", motor_vehicle = "no", segregated = "no",
  ["mtb:scale"] = "0", sac_scale = "hiking", trail_visibility = "excellent",
}
local paved_out = M.remap_way(rock_creek, { is_trail_class = true })
check("a paved trail's mtb:scale is removed", paved_out["mtb:scale"] == M.REMOVE)
check("and sac_scale is left alone", paved_out.sac_scale == nil)
check("and no access key is written", paved_out.bicycle == nil and paved_out.access == nil
  and paved_out["bicycle:forward"] == nil and paved_out["bicycle:backward"] == nil
  and paved_out.foot == nil)
check("nor the surface", paved_out.surface == nil)
check("mtb:scale:imba on asphalt is removed too",
  M.remap_way({ highway = "path", surface = "asphalt", ["mtb:scale:imba"] = "1" },
    { is_trail_class = true })["mtb:scale:imba"] == M.REMOVE)
check("and on concrete:plates",
  M.remap_way({ highway = "path", surface = "concrete:plates", ["mtb:scale"] = "2" },
    { is_trail_class = true })["mtb:scale"] == M.REMOVE)

-- Every hard surface is paved (OWNER-DECISIONS 440): a wooden bridge on the Rock
-- Creek Trail (way 156659889: cycleway, wood, bridge=yes, mtb:scale=0) loses its
-- rating, and its deck reaches the graph as a surface Valhalla prices paved.
local wood_bridge = M.remap_way({ highway = "cycleway", surface = "wood", bridge = "yes",
  bicycle = "designated", ["mtb:scale"] = "0" }, { is_trail_class = true })
check("a wooden trail bridge's mtb:scale is removed", wood_bridge["mtb:scale"] == M.REMOVE)
check("and its deck is priced paved", wood_bridge.surface == "paving_stones",
  tostring(wood_bridge.surface))
check("and no access key is written", wood_bridge.bicycle == nil
  and wood_bridge["bicycle:forward"] == nil and wood_bridge["bicycle:backward"] == nil)
for _, surface in ipairs({ "wood", "boardwalk", "brick", "bricks" }) do
  check(surface .. " reaches the graph as paving stones",
    M.remap_way({ highway = "footway", surface = surface }, { is_trail_class = true }).surface
      == "paving_stones")
end
for _, surface in ipairs({ "metal", "sett", "cobblestone", "unhewn_cobblestone", "tartan",
    "rubber", "concrete:plates", "paving_stones:lanes", "asphalt", "gravel", "dirt" }) do
  check(surface .. " keeps its own surface in the graph",
    M.remap_way({ highway = "footway", surface = surface }, { is_trail_class = true }).surface == nil)
end
for _, surface in ipairs({ "metal", "metal_grid", "brick", "bricks", "sett", "tartan", "rubber",
    "cobblestone", "unhewn_cobblestone", "paving_stones:lanes", "asphalt:lanes", "boardwalk" }) do
  check(surface .. " is paved", M.is_paved({ surface = surface }))
end
for _, surface in ipairs({ "unpaved", "gravel", "compacted", "dirt", "ground", "woodchips",
    "grass_paver", "asphalt;unpaved", "" }) do
  check(surface .. " is not paved", not M.is_paved({ surface = surface }))
end
check("no surface is not paved", not M.is_paved({}))
-- A rated wooden MTB feature (The Boss Trail's "Rollercoaster Wooden Feature",
-- way 808882074: cycleway, wood, bridge=yes, mtb:scale=3) is singletrack, so it
-- is closed both ways whatever losing its rating does.
local feature = M.remap_way({ highway = "cycleway", surface = "wood", bridge = "yes",
  bicycle = "yes", ["mtb:scale"] = "3" }, { is_trail_class = true, no_bicycle = true })
check("a rated wooden MTB feature stays closed both ways",
  feature["bicycle:forward"] == "no" and feature["bicycle:backward"] == "no")
-- A reviewer surface penalty still wins over the deck's price.
local penalised_deck = M.remap_way({ highway = "footway", surface = "wood" },
  { is_trail_class = true, reviewer_surface_penalty = "compacted" })
-- The deck's own `wood` is the parser's compacted already, so the penalty puts
-- it back over the deck's paving_stones price.
check("a reviewer penalty on a wooden deck wins",
  M.valhalla_surface(penalised_deck.surface) == "compacted", tostring(penalised_deck.surface))
check("a dirt trail keeps its rating",
  M.remap_way({ highway = "path", surface = "dirt", ["mtb:scale"] = "2" },
    { is_trail_class = true })["mtb:scale"] == nil)
check("and so does a trail with no surface tag",
  M.remap_way({ highway = "path", ["mtb:scale"] = "1" },
    { is_trail_class = true })["mtb:scale"] == nil)
check("gravel is not paved",
  M.remap_way({ highway = "path", surface = "gravel", ["mtb:scale"] = "0" },
    { is_trail_class = true })["mtb:scale"] == nil)
check("mtb:scale:uphill and mtb:description stay",
  (function()
    local o = M.remap_way({ highway = "path", surface = "asphalt", ["mtb:scale:uphill"] = "1",
      ["mtb:description"] = "x" }, { is_trail_class = true })
    return o["mtb:scale:uphill"] == nil and o["mtb:description"] == nil
  end)())
check("a closed paved singletrack-rated way stays closed",
  (function()
    local o = M.remap_way({ highway = "path", surface = "asphalt", ["mtb:scale"] = "3" },
      { is_trail_class = true, no_bicycle = "park_path" })
    return o["mtb:scale"] == M.REMOVE and o.bicycle == "no"
  end)())

-- ---------------------------------------------------------------------------
-- Half steps (441i-441l, 461a; `rm:stress_half`): each borrows the marks of the
-- levels around it at an intermediate value, and never opens a way.
-- ---------------------------------------------------------------------------

do
  local o = M.remap_way({ highway = "secondary" }, { stress_tier = 3, stress_half = true })
  check("3.5 keeps LTS 3's penalty", o.bicycle == M.STRESS_PENALTY_BICYCLE)
  check("3.5 adds the intermediate practical speed", o["maxspeed:practical"] == M.HALF_GRADED_SPEED)
  local fast = M.remap_way({ highway = "trunk", maxspeed = "65 mph" }, { stress_tier = 3, stress_half = true })
  check("3.5 never lowers a road's own speed: 65 mph keeps 105 km/h", fast["maxspeed:practical"] == "105")
  local slow = M.remap_way({ highway = "secondary", maxspeed = "25 mph" }, { stress_tier = 3, stress_half = true })
  check("3.5 raises a 25 mph road to 90 km/h", slow["maxspeed:practical"] == "90")
  check("speed_kph reads km/h, mph and nothing else", M.speed_kph("50") == 50 and M.speed_kph("35 mph") == 56
    and M.speed_kph("walk") == nil and M.speed_kph(nil) == nil)
  -- Review RL-5: the rebuild writes a bare `maxspeed=45` as `45 mph`
  -- (`pipeline.variants.with_speed_units`), which reads as 72 km/h, not 45.
  check("speed_kph reads the rebuild's explicit mph", M.speed_kph("45 mph") == 72)
  local rewritten = M.remap_way({ highway = "trunk", maxspeed = "60 mph" }, { stress_tier = 3, stress_half = true })
  check("3.5's speed mark reads the rewritten mph: 60 mph keeps 97 km/h",
    rewritten["maxspeed:practical"] == "97")
  check("3.5 adds the intermediate lane count both ways",
    o["lanes:forward"] == M.HALF_GRADED_LANES and o["lanes:backward"] == M.HALF_GRADED_LANES)
  check("3.5's marks sit between the road's and LTS 4's",
    tonumber(M.HALF_GRADED_SPEED) < tonumber(M.GRADED_SPEED)
      and tonumber(M.HALF_GRADED_LANES) < tonumber(M.GRADED_LANES))
  check("3.5 never writes a forbidden key", not writes_forbidden(o))

  local three = M.remap_way({ highway = "secondary" }, { stress_tier = 3 })
  check("a whole LTS 3 gets no half-step marks",
    three["maxspeed:practical"] == nil and three["lanes:forward"] == nil)

  local two = M.remap_way({ highway = "residential" }, { stress_tier = 2, stress_half = true })
  check("2.5 gets no LTS 3 penalty", two.bicycle == nil)
  check("2.5 gets the lower lane count and no speed",
    two["lanes:forward"] == M.HALF_LOW_LANES and two["lanes:backward"] == M.HALF_LOW_LANES
      and two["maxspeed:practical"] == nil)

  local one = M.remap_way({ highway = "residential" }, { stress_tier = 1, stress_half = true })
  check("1.5 adds nothing", one["lanes:forward"] == nil and one.bicycle == nil)

  local four = M.remap_way({ highway = "primary" }, { stress_tier = 4, stress_half = true })
  check("4.5 is priced as LTS 4", four["maxspeed:practical"] == M.GRADED_SPEED
    and four["lanes:forward"] == M.GRADED_LANES and four.bicycle == M.STRESS_PENALTY_BICYCLE)
  check("4.5 is never Avoid: no alley mark", four.service == nil)

  check("2.5 never marks a way closed to a bicycle",
    M.remap_way({ highway = "residential", bicycle = "no" }, { stress_tier = 2, stress_half = true })["lanes:forward"] == nil)
  check("2.5 never marks a road class closed to a bicycle",
    M.remap_way({ highway = "motorway" }, { stress_tier = 2, stress_half = true })["lanes:forward"] == nil)
  check("3.5 never marks a way the penalty cannot land on",
    M.remap_way({ highway = "secondary", access = "private" }, { stress_tier = 3, stress_half = true })["maxspeed:practical"] == nil)
  check("a half step on a trail-class way adds nothing",
    M.remap_way({ highway = "cycleway" }, { stress_tier = 3, stress_half = true, is_trail_class = true })["lanes:forward"] == nil)
  check("a half step on a facility-neutral way adds nothing",
    M.remap_way({ highway = "secondary" }, { stress_tier = 3, stress_half = true, facility_neutral = true })["maxspeed:practical"] == nil)
end

-- DDOT's Pavement Condition Index (DC-PCI, `rm:pci`): the band is the street's
-- smoothness reading, over OSM's.
do
  local poor = M.remap_way({ highway = "residential", surface = "asphalt", smoothness = "excellent" },
    { pci = "poor" })
  check("a poor PCI street is priced as the compacted class", poor.surface == "compacted")
  check("and OSM's smoothness no longer speaks for it", poor.smoothness == M.REMOVE)
  check("a poor street stays ridable on every bicycle type",
    M.SURFACE_ORDER[poor.surface] <= M.MAX_PENALISED_ROUGHNESS)
  local fair = M.remap_way({ highway = "tertiary" }, { pci = "fair" })
  check("a fair PCI street with no surface tag is priced paved but rough",
    fair.surface == "cobblestone")
  local good = M.remap_way({ highway = "residential", surface = "asphalt", smoothness = "bad" },
    { pci = "good" })
  check("a good PCI street keeps its surface", good.surface == nil)
  check("and loses OSM's worse smoothness", good.smoothness == M.REMOVE)
  local gravel = M.remap_way({ highway = "residential", surface = "gravel" }, { pci = "fair" })
  check("PCI never makes an unpaved surface look better", gravel.surface == nil)
  local trail = M.remap_way({ highway = "cycleway", surface = "asphalt" },
    { pci = "poor", is_trail_class = true })
  check("PCI never reaches a trail", trail.surface == nil and trail.smoothness == nil)
  local closed = M.remap_way({ highway = "residential", smoothness = "impassable" }, { pci = "good" })
  check("an impassable way stays closed", closed.smoothness == nil)
  check("PCI never rewrites highway class", not writes_forbidden(poor))
end

-- FOLLOWUP-SIGNAL-DERIVE: a signalised trail crossing reaches the parser's
-- signal flag, which it reads from `highway=traffic_signals` alone.
do
  local function signal(tags) return M.remap_node(tags).highway == "traffic_signals" end
  check("a crossing node tagged crossing=traffic_signals becomes a signal",
    signal({ highway = "crossing", crossing = "traffic_signals" }))
  check("so does one tagged crossing:signals=yes",
    signal({ highway = "crossing", crossing = "marked", ["crossing:signals"] = "yes" }))
  check("crossing:signals=yes with no crossing value is a signal",
    signal({ highway = "crossing", ["crossing:signals"] = "yes" }))
  check("and the node keeps its crossing scheme",
    M.remap_node({ highway = "crossing", ["crossing:signals"] = "yes" }).crossing == "traffic_signals")
  check("a crossing that already names its scheme is not rewritten",
    M.remap_node({ highway = "crossing", crossing = "traffic_signals" }).crossing == nil)
  check("a node the rebuild marked becomes a signal",
    signal({ ["rm:crossing_signal"] = "yes" }))
  check("so does a marked crossing node with no control of its own",
    signal({ highway = "crossing", ["rm:crossing_signal"] = "yes" }))
  check("an uncontrolled crossing is not a signal",
    not signal({ highway = "crossing", crossing = "uncontrolled" }))
  check("a flashing beacon is not a signal",
    not signal({ highway = "crossing", crossing = "uncontrolled", flashing_lights = "button" }))
  check("a node that says uncontrolled overrides the way's mark",
    not signal({ highway = "crossing", crossing = "uncontrolled", ["rm:crossing_signal"] = "yes" }))
  check("so does an unmarked one",
    not signal({ crossing = "unmarked", ["rm:crossing_signal"] = "yes" }))
  check("crossing:signals=no overrides crossing=traffic_signals",
    not signal({ highway = "crossing", crossing = "traffic_signals", ["crossing:signals"] = "no" }))
  check("crossing:signals=yes on an uncontrolled crossing is a contradiction, read as none",
    not signal({ highway = "crossing", crossing = "uncontrolled", ["crossing:signals"] = "yes" }))
  check("a stop sign stays a stop sign",
    not signal({ highway = "stop", ["rm:crossing_signal"] = "yes" }))
  check("a give-way sign stays one",
    not signal({ highway = "give_way", crossing = "traffic_signals" }))
  check("a crossing whose bicycle=no upstream reopens keeps its class",
    not signal({ highway = "crossing", crossing = "traffic_signals", bicycle = "no" }))
  local agency = M.AGENCY_SIGNAL_MARK
  check("a junction an agency lists as a signal becomes one",
    signal({ [agency] = "yes" }))
  check("the agency's signal overrides an uncontrolled crosswalk (a HAWK)",
    signal({ highway = "crossing", crossing = "uncontrolled", [agency] = "yes" }))
  check("and an unmarked one",
    signal({ highway = "crossing", crossing = "unmarked", [agency] = "yes" }))
  check("and a stop sign mapped on the junction",
    signal({ highway = "stop", [agency] = "yes" }))
  check("and a give-way sign",
    signal({ highway = "give_way", [agency] = "yes" }))
  check("but not a crossing whose bicycle=no upstream reopens",
    not signal({ highway = "crossing", bicycle = "no", [agency] = "yes" }))
  check("nor any other node class",
    not signal({ highway = "motorway_junction", [agency] = "yes" }))
  check("a crossing with no signal tag is untouched",
    next(M.remap_node({ highway = "crossing", crossing = "marked" })) == nil)
  check("a bare node with no mark is untouched", next(M.remap_node({ name = "x" })) == nil)
  check("the one class write a node may make is the signal",
    M.NODE_WRITES_ALLOWED.highway == "traffic_signals" and M.FORBIDDEN_KEYS.highway)
end

-- v0.10.0's known hazards (`rm:hazard`): priced as LTS 4, never a change of access.
do
  local street = { highway = "residential", maxspeed = "25 mph" }
  local plain = M.remap_way(street, { stress_tier = 1 })
  local cobbled = M.remap_way(street, { stress_tier = 1, hazard = true })
  local four = M.remap_way(street, { stress_tier = 4 })
  check("a hazard LTS 1 street takes the stress penalty",
    cobbled.bicycle == M.STRESS_PENALTY_BICYCLE and plain.bicycle == nil)
  check("and LTS 4's graded marks", cobbled["maxspeed:practical"] == M.GRADED_SPEED
    and cobbled["lanes:forward"] == four["lanes:forward"])
  check("a hazard 2.5 is priced as LTS 4, not its half step",
    M.remap_way(street, { stress_tier = 2, stress_half = true, hazard = true })["lanes:forward"]
      == M.GRADED_LANES)
  check("a hazard never opens a closed road",
    M.remap_way({ highway = "residential", access = "no" }, { stress_tier = 1, hazard = true }).bicycle
      ~= M.STRESS_PENALTY_BICYCLE)
  check("a hazard on a path changes nothing",
    M.remap_way({ highway = "cycleway" }, { stress_tier = 1, hazard = true, is_trail_class = true })
      .bicycle == nil)
  check("an Avoid road keeps its own marks",
    M.remap_way({ highway = "primary" }, { stress_tier = 5, hazard = true }).service == M.AVOID_SERVICE)
  local derived = { stress_tier = 2, hazard = true }
  M.hazard_priced(derived)
  check("the derived table passed in is not changed", derived.stress_tier == 2)
  check("a hazard never rewrites road class or speed", not writes_forbidden(cobbled))
  check("a hazard LTS 3 street is priced as LTS 4",
    M.remap_way(street, { stress_tier = 3, hazard = true })["lanes:forward"] == M.GRADED_LANES)
  local alley = { highway = "service", service = "alley" }
  local hazard_alley = M.remap_way(alley, { stress_tier = 2, hazard = true })
  local plain_alley = M.remap_way(alley, { stress_tier = 2 })
  check("a hazard alley keeps its alley use and adds the graded marks",
    hazard_alley.service == plain_alley.service and hazard_alley["lanes:forward"] == M.GRADED_LANES)
  check("Mass Ride's no-trail variant gets no graded marks for a hazard",
    M.remap_way(street, { stress_tier = 1, hazard = true, facility_neutral = true })["lanes:forward"]
      ~= M.GRADED_LANES)
end

io.write(string.format("%d checks, %d failures\n", checks, failures))
os.exit(failures == 0 and 0 or 1)
