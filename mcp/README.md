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
| `find_place` | Searches RouteMaker's place search for a place, address or street, around a point if given (`near`). |
| `metro_stations` | Lists the 98 Metrorail stations, or those near a point, with miles and bearing. |
| `scenic_roads_near` | Lists the rustic roads, scenic byways, East Coast Greenway and US Bicycle Routes near a point, with miles, stress mix and a point on each to put a via point on. |
| `climbs_near` | Lists the categorised climbs near a point (name, miles, gain, grade, surface, foot, summit and points up it). With `on_minutes` it keeps the climbs long enough for one effort, steepest first, and plans up the first few to check that an effort fits with no stop, signal, busy crossing or sharp turn: hill repeats for intervals, up for the effort and down to recover. |
| `closures_near` | Lists the closures and construction in force now near a point, nearest first, one row per closure: what is closed, until when, how far away, its miles, the source (Maryland SHA, NPS, MPD or a RouteMaker reviewer) and its link. DDOT permits only with `include_permits`. |
| `plan_route` | Plans through 2 to 25 points (places, station names or `[lon, lat]`), on any ride type with any of its settings, as a loop if asked; reports distance, time, climbing and the share on each traffic-stress level (and the bikeshare or transit plan on those ride types); checks the distance from Metro; can add stations as via points where it strays. Also lists what the route rides: its roads in order with miles, LTS and any scenic designation (Montgomery County Rustic Roads, scenic byways, the East Coast Greenway, US Bicycle Routes), where it rides LTS 3 and up, its very-high-stress junctions, and small detours (where it leaves a road and comes back to it). A via point reached by an out-and-back is moved to where the spur leaves the road (`trim_spurs`, on by default). With `intervals` (on and off minutes, sets, pace) it checks the route for interval training: where efforts can run with no stop, signal, busy crossing, sharp turn, descent or LTS 4 road, how many sets fit in one session (each rest about the asked minutes, laps on a loop), and clear climbs for up-and-back repeats. With `best_order` (alleycat or errand checkpoints) it keeps the start and finish and rides the points between in the quickest order: the shortest few orders by straight line are planned and the quickest kept. `closures` lists the closures it goes through or round (what, until when, where on the route, source and link), and `closure_warning` says when it rides through one, naming any stop or via point reached on a closed stretch; `check_before_you_go` lists the park notices for the ride's time (an NPS alert, or a deer-management closure in Rock Creek Park or a Montgomery park), which are warnings and never routed round. `potential_closures` lists the permits and planned work along the route (DDOT permits, DDOT ProTrack+, DC Water, WSSC Water) that may close the road or bike lane in their window, with their miles, source and link; they are not routed round either. A place name is searched near the route's other points; one that matches places far apart and none near the route is asked back. For optimizing: the summary gives unpaved miles and the minutes spent waiting at signals and stop signs; `legs` gives miles, minutes, climb and busy miles between stops (food, water and overnight stops on a long ride); `steep_grades` and `road_hazards` (cobbles, rails) say where. `pace_mph` times the route at the rider's own speed (on Run, the running pace, 4 to 10 mph); `alternatives` also answers the other routes the site's search found at the same settings, each its own draft that keeps its line when revised; `avoid` leaves out a line of road; `follow` plans along a line the rider has (an encoded polyline) instead of through points. |
| `open_link` | Picks up a route from a RouteMaker link you paste: the page's address after you changed the route in the app, one of your saved routes opened in the app, or a shared route's link. |
| `revise_route` | Changes a draft (add, move or remove points; any ride type or setting; roads to `avoid`, by name, by mile range or as a line) and plans it again as a new draft; the old one stays to go back to. `changed_from_previous` gives each figure before and after (miles, minutes, climb, LTS 3+ and 4+ miles, unpaved miles, junctions, junction waits), so the assistant can tell whether a change helped and stop when the gains are small. |
| `route_segments` | Reads a draft stretch by stretch: miles, road, LTS, facility, surface, average and steepest grade, climb, one-way and minutes; every higher and very-high stress junction with its reason; steep grades and hazards. Paged for long rides (`from_mi`, `to_mi`, `next_from_mi`). |
| `ride_conditions` | Light and weather for riding a draft at a time: dark or light at the start and the finish (civil dawn and dusk), the arrival time, and within 48 hours the National Weather Service alerts along the route and where rain is first forecast, through the site's own weather check (points rounded, nothing kept). |
| `my_routes` | Site connector only: lists your saved routes with their tags (archived ones with `archived`, narrowed by `tag` or `search`), or opens one by name or id as a draft to revise or read ("my commute"). It never changes My routes, though opening one counts as opening it (a full account offers the route unopened longest). A connection allowed before it existed cannot read them until you connect again. |
| `reach` | Where a rider can be in 15, 30, 45 and 60 minutes (isochrones) from one to five points, by any bike ride type, Walk or Run, from the points or to them, with each ring's area and the Metro stations, bike racks, places to eat and places to see inside; unless `calm` is false, the same rings at Low-stress beside them. Several points combine as any, all (a meeting spot) or each. Its link opens the rings in the app. |
| `compare_places` | Ranks 2 to 6 places to start from (a home, a hotel, an office) by the riding minutes to 1 to 3 places the rider goes, at the rider's traffic setting and at Low-stress (left out where the setting is already Low-stress or calmer), against any minute limits; places left when the call's time runs out are listed, not ranked. Bike ride types only. |
| `save_route` | Keeps a draft, only when you say so: in your My routes on the site's own connector, with `tags` if given, or as a GPX file on your own computer. On the site, `replaces` (a saved route's id) archives that route once this one is saved, for a new route that supersedes it. A full account (200 routes, nothing archived) is refused with the route unopened longest, for the assistant to offer archiving it. |
| `organize_route` | Site connector only, when you say so: tags a saved route (`tags`, `add_tags`, `remove_tags`) or archives or restores it (`archived`). Archived routes leave Load route's list (Archived lists them) and are the first to go, longest archived first, when the account is full. It never renames or deletes. A connection allowed before it existed cannot use it until you connect again. |
| `gpx_route` | A draft as a GPX track: a `.gpx` file on your own computer, or a download link on the site. |
| `draft_route_post` | Site connector, instance admins only: writes a Featured routes post as a draft (title, about, who it's for, season, highlighted sections with their miles) around a draft route or a line to follow, for an admin to publish in the admin. Sending the same slug again with `replace` rewrites the draft. |
| `plan_metro_loop` | Builds a loop of about the target length around DC (or another centre) through waypoints at or just beyond Metro stations, rescales it once towards the target, and repairs stretches past the Metro limit. |

The assistant picks the ride type and settings that fit what you ask: every ride type the app
has (bikeshare and bike plus transit included) and every setting (traffic stress, hills, ride
time, trails, target distance, rider weight, riding speed, cargo load and assist, trail
levels, Easy MTB trails, the bikeshare bike and ending, departure time).

`easy_mtb` (Default and Trailmaxxing only, off unless asked) is the app's "Easy MTB trails"
switch: the route may also ride mountain-bike trails rated 0 or 1 on `mtb:scale` or
`mtb:scale:imba`, or unrated (mostly grass and dirt), on the off-road graph as Gravel does, and
is steered off trails rated 2 or harder. The summary's `easy_mtb` says where the route still
rides a harder one (no way round was found), or that the off-road router was not running and
the route kept to the usual trails. It travels in the link (`easymtb=1`) and a saved route;
`open_link` reads it back, and drops it on a ride type that does not offer it, as the app does.

Every planned route is a draft: it comes back with a link, kept for a day, that opens that
exact route in the app, like a link from the app's Share, so the map, Start ride and the app's own GPX are the
route the assistant described. Nothing is saved to My routes. Drafts last while the assistant's session does. On the site's connector
(below), `save_route` puts one in My routes, where it opens like any route you saved yourself; on
your own computer it writes a GPX file. Either way you can also open the link and press Save in
the app.

It plans through the site's own API (`POST /api/route`), so a route is exactly what the app would
plan. It changes nothing on the site except adding the routes you ask it to save. Metro distances
are straight-line, from DC Open Data's station file (CC BY 4.0) that the map also uses. A route to
or through a station goes to its bike entrance (its elevator where one is listed), from the
entrance files beside the station file: of a station's elevators, the one nearest the route's
point before it (for a start, the point after), as the map takes it, so a Silver Line station in
the toll road's median is gone to on the rider's side.

A name said with "Metro" or "station" ("Vienna Metro"), or a station's whole name that can be
nothing else ("Union Station", "Navy Yard-Ballpark"), is that station. A bare name that is also a
station's ("Navy Yard", "Vienna", "Rockville") is searched, and is the station only where the
search finds it there; "Mount Vernon", "Arlington" and road names such as "Braddock Road" are the
places the search finds. A park, refuge or campus found by the search goes to a way in the same
search found (its visitor centre, entrance, parking, trailhead or boat launch, named for it by
whole words; the one nearest the route's other points), in `find_place` as in `plan_route`, and
the answer's
`points_taken_as` lists the other points of the same place the search found as `nearby_matches`.

## Use it in Claude on the web and on your phone

The site runs the same server itself, at `/mcp` on its own address, so Claude on claude.ai and
in the Claude phone apps can use it with nothing installed.

1. In Claude, open **Settings > Connectors > Add custom connector**.
2. Name it RouteMaker, and give the site's address followed by `/mcp`, for example
   `https://routes.example.org/mcp`.
3. Choose **Connect**. RouteMaker's sign-in opens: sign in with Discord as usual (on the beta,
   with its password first), and choose **Allow**. Claude can then plan routes, add the ones
   you ask it to save to your My routes, and read your saved routes when you ask it to plan from
   one. It cannot change or delete your saved routes or change anything else.

On the site, each call answers within one web request (up to a minute), so a long loop is
planned once per request: the answer says when it stopped early, and asking Claude to revise
the draft can still fix where it strays from Metro or move its points. Drafts are kept on the site for a day
(24 hours), long enough to plan in the evening and save or download the next morning, and only
the app that planned one can use it. There is no GPX file on the server: `gpx_route` gives a
download link instead, which works while the draft is kept (on the beta, behind its password).
The draft's link goes with the draft and then says the exact line is no longer kept. Disconnecting
the app in Settings, or signing out everywhere, drops its drafts at once, and their links and GPX
links stop working.

### Featured routes posts, for instance admins

Signed in as an instance admin, the connector also offers `draft_route_post`, so you can ask
Claude to write a Featured routes post and send it straight to the site. The post always lands
as a **draft**: only admins see its page (`/routes/<slug>`), and publishing is still your press
of Status > Published in the admin, where you can also change anything first. The route is either
a draft Claude planned (or opened from a link) or a line to follow, such as a ride's GPX track,
planned the way the app plans an opened file. The same checks as the admin apply: the route needs
its planned figures, and one that starts, ends or stops in your Home circle is refused. Sending
the same slug again with `replace` rewrites that draft (without it, a draft already at that slug,
such as one you started in the admin, is left alone); once a post has left draft, the connector cannot change
it. Disconnecting the app in Settings ends it.

## Set it up on your own computer

Most riders want the connector above: it signs you in and saves to My routes. Running the
server yourself suits a local stack or another assistant app; it plans the same routes and keeps
them as GPX files, but it does not sign in, so it cannot save to My routes (open a route's link
and press Save in the app instead). The save-only key it once used is retired (2026-10-25).

You need Python 3.11 or later and this repository checked out. Nothing to install: it uses the
standard library only. Add the server to your assistant with these settings:

- `ROUTEMAKER_BASE_URL`: the address you open RouteMaker at, for example `http://localhost` for a
  local stack. Route links are built from it, so `http://localhost` links open only on that
  computer; use the site's public address to open them on your phone.
- `ROUTEMAKER_ROUTES_DIR` (optional): where GPX files go; default `~/RouteMaker-routes`.
- `ROUTEMAKER_BASIC_AUTH` (optional): `user:password` for a site behind a password. It is sent
  only to an `https://` address, or to plain `http://` on this computer (`localhost`); with any other
  `http://` address the tools refuse to start.

If the address answers with something other than RouteMaker (a sign-in or Wi-Fi portal page, or the
wrong site), each tool says so and names `ROUTEMAKER_BASE_URL` to check.

### Claude Desktop on Windows, with the checkout in WSL

Settings > Developer > Edit Config opens `claude_desktop_config.json`. Add (with your own WSL
distribution, path and address). `WSLENV` passes the settings from Windows into WSL:

```json
{
  "mcpServers": {
    "routemaker": {
      "command": "wsl",
      "args": ["-d", "Ubuntu", "--", "python3", "/home/you/src/RouteMaker/mcp/routemaker_mcp.py"],
      "env": {
        "ROUTEMAKER_BASE_URL": "http://localhost",
        "WSLENV": "ROUTEMAKER_BASE_URL"
      }
    }
  }
}
```

For a site behind a password, add `"ROUTEMAKER_BASIC_AUTH": "user:password"` to `env`
and `:ROUTEMAKER_BASIC_AUTH` to the end of `WSLENV`: a setting `WSLENV` does not name never
reaches WSL.

Restart Claude Desktop. RouteMaker's tools appear under the tools button in a new chat.

### Claude Code

```sh
claude mcp add routemaker \
  -e ROUTEMAKER_BASE_URL=http://localhost \
  -- python3 /path/to/RouteMaker/mcp/routemaker_mcp.py
```

A long loop can take a few minutes to plan (each plan of a long ride can take up to a minute,
and `plan_metro_loop` makes up to four by default). If the client gives up first, raise its tool
timeout (Claude Code: `MCP_TOOL_TIMEOUT=600000`; other clients have their own setting) or ask for
fewer plans (`max_plans`). A call the client gives up on stops at its next step and keeps
nothing.

### Other assistants

Any MCP client that runs local (stdio) servers works the same way: the command is `python3`, the
argument is the path to `routemaker_mcp.py`, and the settings above are environment variables.

## Notes

- The planner covers DC to Baltimore. Points outside it are refused.
- Stress: 70 is the app's Default; 80 keeps to low-stress ways unless avoiding them takes much
  longer, and is what `plan_metro_loop` uses unless asked; above 80 the calm detour search runs,
  which is slower on a long ride.
- A route planned for the first time in the app may differ a little from the one saved here if
  live closures or the map change in between: the saved route keeps the line exactly as planned.
- Tests: `tests/test_mcp_server.py` (the protocol, the Metro check, the loop builder against a
  stand-in planner) and `tests/test_connector.py` (the site's connector, saving and posts).
