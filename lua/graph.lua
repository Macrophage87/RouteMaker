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

-- Loading twice in one interpreter would capture this file's own entry points as
-- "upstream" below and recurse until the stack gave out, because `require`
-- returns its cached result without re-running the vendored chunk.
if _ROUTEMAKER_GRAPH_LOADED then
  error("RouteMaker: graph.lua was loaded twice into one Lua state")
end
_ROUTEMAKER_GRAPH_LOADED = true

local ok, err = pcall(require, "graph_upstream")
if not ok then
  error(
    "RouteMaker: vendored Valhalla graph.lua not found at " .. ROOT .. "/vendor/graph_upstream.lua. "
      .. "Run scripts/vendor_valhalla_lua.sh for the pinned version before building tiles. "
      .. "Cause: " .. tostring(err)
  )
end

-- Valhalla's graph.lua installs its entry points as *globals* and ends without
-- returning a module, so `require` hands back the boolean `true`, not a table.
-- An earlier version of this file held that return value as `upstream` and
-- called `upstream.ways_proc`, which raises "attempt to index a boolean value"
-- on the first way of every tile build. Capture the globals the chunk installed
-- instead, before this file overwrites them below.
local up_ways, up_nodes, up_rels = ways_proc, nodes_proc, rels_proc
if type(up_ways) ~= "function" or type(up_nodes) ~= "function" or type(up_rels) ~= "function" then
  error(
    "RouteMaker: the vendored Valhalla graph.lua did not define the *_proc globals. "
      .. "Re-vendor it with scripts/vendor_valhalla_lua.sh; upstream's entry-point "
      .. "contract has changed and this wrapper needs updating with it."
  )
end

-- `rel_members_proc` is upstream's fourth entry point and nothing here modifies
-- relation membership, so it is deliberately left as upstream installed it
-- rather than wrapped. Overwriting the other three does not disturb it.

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

-- Neither guard below calls error(), and that is the whole of their design.
--
-- `LuaTagTransform::Transform` runs each entry point under lua_pcall and, on
-- failure, returns an *empty* tag map. A raised error therefore does not refuse
-- an element or stop a build: it strips the element of every tag and drops it
-- out of the graph, silently, while the build reports success. Both guards here
-- were written as error() and both therefore did the opposite of what they say.
-- The border guard is the clearest case - it exists so that a state crossing
-- stays passable, and what it actually did was delete the crossing node.
--
-- So a violation refuses the *change*, keeps the element, says so on stderr
-- under a prefix the build-log check greps for, and marks the element with a
-- sentinel tag that Valhalla does not read and so cannot act on. The pipeline's
-- validation stage asserts that no line under that prefix appears in the parse
-- log; the Lua suites assert the same thing through remap.violations.

-- A change whose value is the remap's REMOVE sentinel deletes the tag. Applied
-- here rather than in the remap because a Lua table cannot hold a nil value, so
-- "remove this key" cannot be expressed in the table the remap returns.
local function apply(kv, changes)
  for key, value in pairs(changes) do
    if remap.FORBIDDEN_KEYS[key] then
      -- `highway` and `maxspeed` set hierarchy level, shortcut building, the
      -- road-class factor, A* pruning and whether Odin emits a maneuver at all.
      -- The write is dropped and the way keeps the class it arrived with.
      remap.record_violation(
        kv,
        "the remap attempted to write '" .. key .. "', which is never permitted"
      )
    elseif value == remap.REMOVE then
      kv[key] = nil
    else
      kv[key] = value
    end
  end
end

function ways_proc(kv, nokeys)
  apply(kv, remap.remap_way(kv, derived_from(kv)))
  strip_namespace(kv)
  return up_ways(kv, nokeys)
end

function nodes_proc(kv, nokeys)
  local changes = remap.remap_node(kv)
  -- Only this remap's own writes are checked. Upstream OSM carries genuinely
  -- closed border crossings tagged access=no, and refusing a whole tile build on
  -- one of those would be a bug, not a guard.
  --
  -- The node keeps every tag it arrived with and none of the remap's changes:
  -- upstream's own reading of a border-control node is the one this project
  -- would rather have than a half-applied change set.
  if remap.denies_bicycle_at_border(kv, changes) and next(changes) ~= nil then
    remap.record_violation(kv, "the remap would deny bicycle access at a border-control node")
  else
    apply(kv, changes)
  end
  strip_namespace(kv)
  return up_nodes(kv, nokeys)
end

function rels_proc(kv, nokeys)
  -- Nothing derived applies to relations; pass straight through so the global
  -- exists, which LuaTagTransform requires.
  return up_rels(kv, nokeys)
end
