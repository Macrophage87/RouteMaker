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

-- The gate is `stress_tier == 1` and nothing else. LTS1 is the only tier that
-- claims the separation a `cycleway=track` write asserts; LTS2 and LTS3 are
-- roads a confident adult rides in traffic, and writing a separated track onto
-- them hands upstream's accommodation factor to roads that have no provision at
-- all. Every tier is checked because `== 1` widened to `<= 2` or `<= 3` moves
-- only the tiers a two-case test never looks at.
for tier = 1, 4 do
  check("stress tier " .. tier .. " writes a cycleway only at 1",
    (M.remap_way({ highway = "residential" }, { stress_tier = tier }).cycleway == "track")
      == (tier == 1))
end
check("no tier at all writes nothing",
  M.remap_way({ highway = "residential" }, {}).cycleway == nil)
check("and so does a permissively tagged one",
  M.remap_way({ highway = "track", access = "permissive" }, { stress_tier = 1 }).cycleway
    == "track")

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
    check(key .. "=" .. value .. " blocks the write",
      M.remap_way(tags, { stress_tier = 1 }).cycleway == nil, key .. "=" .. value)
    check(key .. "=" .. value .. " is seen by declares_cycleway", M.declares_cycleway(tags))
  end
end
check("the key list is exactly the four forms", #M.CYCLEWAY_KEYS == 4)
-- And nothing wider: a width key is not a facility value and a sidewalk is not
-- a cycleway, so neither may block a write the way deserves.
check("a cycleway width alone does not block the write",
  M.remap_way({ highway = "residential", ["cycleway:left:width"] = "2.0", sidewalk = "both" },
              { stress_tier = 1 }).cycleway == "track")
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
