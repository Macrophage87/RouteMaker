# Vendored Valhalla Lua

`graph_upstream.lua` is Valhalla's own `lua/graph.lua`, byte-identical to the
tag at `VERSION`, fetched by `scripts/vendor_valhalla_lua.sh`.

It is checked in rather than fetched at build time for two reasons. The tags a
tile build produces become a function of this repository instead of whichever
image tag happened to be pulled; and the entry-point contract can be tested
against the real file. The earlier test stubbed a module-shaped upstream, which
hid the fact that upstream defines globals and returns nothing — the exact
mismatch the test existed to catch.

Do not edit it. RouteMaker's own transform lives in `lua/graph.lua` and
`lua/routemaker_remap.lua`, which wrap this file rather than patching it, so an
upgrade is a re-vendor and not a merge.

Valhalla is MIT licensed, Copyright (c) 2018 Valhalla contributors, Copyright
(c) 2015-2017 Mapillary AB, Mapzen. See
https://github.com/valhalla/valhalla/blob/3.5.1/COPYING.
