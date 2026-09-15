-- The tag-transform script Valhalla loads, named by `mjolnir.graph_lua_name`.
--
-- Valhalla's LuaTagTransform checks for three globals by name at construction -
-- `ways_proc`, `nodes_proc`, `rels_proc` - and throws if any is missing. An
-- earlier version of this file defined `way_function` and `node_function`, which
-- are OSRM's profile entry points, so Valhalla would have refused to load it.
-- The calling convention differs too: Valhalla pushes (table, key count) and
-- pops four return values for ways and two for nodes and relations.
--
-- This file is the entry point and stays thin. It defers to Valhalla's own
-- transform for everything standard and applies this project's remap on top, so
-- an upgrade is a re-vendor of their file rather than a merge of ours into it.
--
-- Failing loudly here matters more than usual: if Valhalla cannot load a script
-- named by this key it falls back to its compiled-in transform and says nothing,
-- so every derived tag is dropped and routing looks slightly off rather than
-- broken.

-- Valhalla loads this with luaL_dostring rather than luaL_dofile, so the chunk
-- has no path and debug.getinfo cannot locate it. The directory is injected by
-- the build instead, and defaulting to the mount point keeps a hand-run working.
local ROOT = os.getenv("ROUTEMAKER_LUA_DIR") or "/conf/lua"
package.path = ROOT .. "/?.lua;" .. ROOT .. "/vendor/?.lua;" .. package.path

local ok, upstream = pcall(require, "graph_upstream")
if not ok then
  error(
    "RouteMaker: vendored Valhalla graph.lua not found at " .. ROOT .. "/vendor/graph_upstream.lua. "
      .. "Run scripts/vendor_valhalla_lua.sh for the pinned version before building tiles. "
      .. "Cause: " .. tostring(upstream)
  )
end

local remap = require("routemaker_remap")

-- Derived values arrive as `rm:*` tags, namespaced so they cannot collide with
-- real OSM keys, and are stripped before the transform returns.
local function derived_from(kv)
  local derived = {}
  if kv["rm:stress_tier"] then derived.stress_tier = tonumber(kv["rm:stress_tier"]) end
  if kv["rm:reviewer_surface"] then derived.reviewer_surface_penalty = kv["rm:reviewer_surface"] end
  if kv["rm:bridge_bicycle"] then derived.bridge_bicycle_legal = kv["rm:bridge_bicycle"] == "yes" end
  if kv["rm:lit"] then derived.lit = kv["rm:lit"] == "yes" end
  if kv["rm:trail_class"] then derived.is_trail_class = kv["rm:trail_class"] == "yes" end
  return derived
end

local function strip_namespace(kv)
  for key in pairs(kv) do
    if key:sub(1, 3) == "rm:" then kv[key] = nil end
  end
end

function ways_proc(kv, nokeys)
  local changes = remap.remap_way(kv, derived_from(kv))
  for key, value in pairs(changes) do
    if remap.FORBIDDEN_KEYS[key] then
      error("RouteMaker: the remap attempted to write '" .. key .. "', which is never permitted")
    end
    kv[key] = value
  end
  strip_namespace(kv)
  return upstream.ways_proc(kv, nokeys)
end

function nodes_proc(kv, nokeys)
  local changes = remap.remap_node(kv)
  -- Only this remap's own writes are checked. Upstream OSM carries genuinely
  -- closed border crossings tagged access=no, and halting a whole tile build on
  -- one of those would be a bug, not a guard.
  if remap.denies_bicycle_at_border(kv, changes) and next(changes) ~= nil then
    error("RouteMaker: the remap would deny bicycle access at a border-control node")
  end
  for key, value in pairs(changes) do
    kv[key] = value
  end
  strip_namespace(kv)
  return upstream.nodes_proc(kv, nokeys)
end

function rels_proc(kv, nokeys)
  -- Nothing derived applies to relations; pass straight through so the global
  -- exists, which LuaTagTransform requires.
  return upstream.rels_proc(kv, nokeys)
end
