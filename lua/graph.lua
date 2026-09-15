-- The tag-transform script Valhalla loads, named by `mjolnir.graph_lua_name`.
--
-- This file is the entry point and deliberately thin. It defers to Valhalla's
-- own graph.lua for the whole standard transform and applies this project's
-- remap on top, so a Valhalla upgrade is a re-vendor of their file rather than a
-- merge of our changes into it.
--
-- The upstream script is vendored at a pinned version into `vendor/graph.lua`
-- by the build rather than read out of the image at runtime, so the tags a tile
-- build produces are a function of this repository and not of whichever image
-- tag happened to be pulled.
--
-- Failing loudly here matters more than usual. If Valhalla cannot load a script
-- named by this key it falls back to its compiled-in transform and says nothing,
-- and every derived tag is silently dropped: routing then looks a little off
-- rather than broken, which is the hardest kind of failure to attribute.

local here = (debug.getinfo(1, "S").source:match("@(.*/)") or "./")
package.path = here .. "?.lua;" .. here .. "vendor/?.lua;" .. package.path

local ok, upstream = pcall(require, "graph_upstream")
if not ok then
  error(
    "RouteMaker: vendored Valhalla graph.lua not found at vendor/graph_upstream.lua. "
      .. "Run the vendor step for the pinned Valhalla version before building tiles; "
      .. "without it Valhalla would fall back to its built-in transform and drop "
      .. "every derived tag without reporting an error. Cause: " .. tostring(upstream)
  )
end

local remap = require("routemaker_remap")

-- Derived values are injected into the extract as `rm:*` tags, namespaced so
-- they cannot collide with real OSM keys.
local function derived_from(kv)
  local derived = {}
  if kv["rm:stress_tier"] then derived.stress_tier = tonumber(kv["rm:stress_tier"]) end
  if kv["rm:reviewer_surface"] then derived.reviewer_surface_penalty = kv["rm:reviewer_surface"] end
  if kv["rm:bridge_bicycle"] then derived.bridge_bicycle_legal = kv["rm:bridge_bicycle"] == "yes" end
  if kv["rm:lit"] then derived.lit = kv["rm:lit"] == "yes" end
  return derived
end

function way_function(kv, nodes, relations, result)
  local changes = remap.remap_way(kv, derived_from(kv))
  for key, value in pairs(changes) do
    if remap.FORBIDDEN_KEYS[key] then
      error("RouteMaker: the remap attempted to write '" .. key .. "', which is never permitted")
    end
    kv[key] = value
  end
  return upstream.way_function(kv, nodes, relations, result)
end

function node_function(kv, result)
  for key, value in pairs(remap.remap_node(kv)) do
    kv[key] = value
  end
  if remap.denies_bicycle_at_border(kv, {}) then
    error("RouteMaker: a border-control node would deny bicycle access, which would make every state crossing unroutable")
  end
  return upstream.node_function(kv, result)
end

return { way_function = way_function, node_function = node_function }
