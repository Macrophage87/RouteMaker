# RouteMaker MCP server

Lets an AI assistant plan routes with RouteMaker's routing engine, check them against Metro, and
save them to your My routes. It speaks the Model Context Protocol (MCP), an open standard, so it
works with any assistant app that can run a local MCP server: Claude Desktop, Claude Code, and
others.

Ask things like:

> Make me a 100 mile route that goes around DC using low stress roads and doesn't stray more than
> 5 miles from a Metro station.

Then look at it (the answer has a link that opens it in the app), and either tell the assistant
what to change ("go by the Capital Crescent Trail instead", "make it calmer") or change it in the
app yourself and paste the page's address back. When it is right, say "save it as Metro
century".

## What it can do

| Tool | What it does |
| --- | --- |
| `find_place` | Searches RouteMaker's place search for a place, address or street. |
| `metro_stations` | Lists the 98 Metrorail stations, or those near a point, with miles and bearing. |
| `plan_route` | Plans through 2 to 25 points (places, station names or `[lon, lat]`), on any ride type with any of its settings, as a loop if asked; reports distance, time, climbing and the share on each traffic-stress level (and the bikeshare or transit plan on those ride types); checks the distance from Metro; can add stations as via points where it strays. |
| `open_link` | Picks up a route from a RouteMaker link you paste: the page's address after you changed the route in the app, one of your saved routes opened in the app, or a shared route's link. |
| `revise_route` | Changes a draft (add, move or remove points; any ride type or setting) and plans it again as a new draft; the old one stays to go back to. |
| `save_route` | Keeps a draft, only when you say so: in your My routes on the site, and/or as a GPX file. |
| `plan_metro_loop` | Builds a loop of about the target length around DC (or another centre) through waypoints at or just beyond Metro stations, rescales it once towards the target, and repairs stretches past the Metro limit. |

The assistant picks the ride type and settings that fit what you ask: every ride type the app
has (bikeshare and bike plus transit included) and every setting (traffic stress, hills, ride
time, gravel, trails, target distance, rider weight, cargo load and assist, trail levels, the
bikeshare bike and ending, departure time).

Every planned route is a draft: it comes back with a link that opens it in the app, and
nothing is saved. Drafts last while the assistant's session does. `save_route` (with a key,
below) puts one in My routes, where it opens like any route you saved yourself; you can also
open the link and press Save in the app.

It plans through the site's own API (`POST /api/route`), so a route is exactly what the app would
plan. It changes nothing on the site except adding the routes you ask it to save. Metro distances
are straight-line, from DC Open Data's station file (CC BY 4.0) that the map also uses.

## Set it up

You need Python 3.11 or later and this repository checked out. Nothing to install: it uses the
standard library only.

1. **Make a key (only to save routes).** On the site, sign in, open Settings, and under Account
   choose **AI assistant key > Make a key**. Copy it: it is shown once. The key can only add
   routes to your My routes. It cannot sign in, read your routes or change anything else, and
   you can remove or replace it there at any time.
2. **Add the server to your assistant** with these settings:
   - `ROUTEMAKER_BASE_URL`: the address you open RouteMaker at, for example `http://localhost`
     for a local stack.
   - `ROUTEMAKER_SAVE_KEY`: the key from step 1 (leave it out to plan without saving).
   - `ROUTEMAKER_ROUTES_DIR` (optional): where GPX files go; default `~/RouteMaker-routes`.
   - `ROUTEMAKER_BASIC_AUTH` (optional): `user:password` for a site behind a password, such as
     a beta. The key travels in its own header, so both work together.

### Claude Desktop on Windows, with the checkout in WSL

Settings > Developer > Edit Config opens `claude_desktop_config.json`. Add (with your own WSL
distribution, path, address and key). `WSLENV` passes the settings from Windows into WSL, and
keeps the key off the command line:

```json
{
  "mcpServers": {
    "routemaker": {
      "command": "wsl",
      "args": ["-d", "Ubuntu", "--", "python3", "/home/you/src/RouteMaker/mcp/routemaker_mcp.py"],
      "env": {
        "ROUTEMAKER_BASE_URL": "http://localhost",
        "ROUTEMAKER_SAVE_KEY": "rmk_your_key_here",
        "WSLENV": "ROUTEMAKER_BASE_URL:ROUTEMAKER_SAVE_KEY"
      }
    }
  }
}
```

Restart Claude Desktop. RouteMaker's tools appear under the tools button in a new chat.

### Claude Code

```sh
claude mcp add routemaker \
  -e ROUTEMAKER_BASE_URL=http://localhost \
  -e ROUTEMAKER_SAVE_KEY=rmk_your_key_here \
  -- python3 /path/to/RouteMaker/mcp/routemaker_mcp.py
```

A long loop can take a few minutes to plan (each plan of a long ride can take up to a minute,
and `plan_metro_loop` makes up to three by default). If the client gives up first, raise its tool
timeout (Claude Code: `MCP_TOOL_TIMEOUT=600000`; other clients have their own setting) or ask for
fewer plans (`max_plans`). A call the client gives up on stops at its next step and saves
nothing, unless the save was already under way.

### Other assistants

Any MCP client that runs local (stdio) servers works the same way: the command is `python3`, the
argument is the path to `routemaker_mcp.py`, and the three settings above are environment
variables.

## Notes

- The planner covers DC to Baltimore. Points outside it are refused.
- Stress: 70 is the app's Default; 80 keeps to low-stress ways unless avoiding them takes much
  longer, and is what `plan_metro_loop` uses unless asked; above 80 the calm detour search runs,
  which is slower on a long ride.
- A route planned for the first time in the app may differ a little from the one saved here if
  live closures or the map change in between: the saved route keeps the line exactly as planned.
- Tests: `tests/test_mcp_server.py` (the protocol, the Metro check, the loop builder against a
  stand-in planner, and a save end to end) and `tests/test_assistant_key.py` (the key).
