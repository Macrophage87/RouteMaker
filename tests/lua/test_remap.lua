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

-- The border node must stay passable.
local border = { barrier = "border_control" }
check("border control node denies no bicycle access",
  not M.denies_bicycle_at_border(border, M.remap_node(border)))
check("a mapping that denied access would be caught",
  M.denies_bicycle_at_border(border, { bicycle = "no" }))

-- Bridge legality is expressed through access, which is what it actually is.
check("bridge legality sets bicycle access",
  M.remap_way({ highway = "trunk" }, { bridge_bicycle_legal = false }).bicycle == "no")

io.write(string.format("%d checks, %d failures\n", checks, failures))
os.exit(failures == 0 and 0 or 1)
