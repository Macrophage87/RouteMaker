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
| `plan_route` | Plans through 2 to 25 points (places, station names or `[lon, lat]`), on any ride type with any of its settings, as a loop if asked; reports distance, time, climbing and the share on each traffic-stress level (and the bikeshare or transit plan on those ride types); checks the distance from Metro; can add stations as via points where it strays. Also lists what the route rides: its roads in order with miles, LTS and any scenic designation (Montgomery County Rustic Roads, scenic byways, the East Coast Greenway, US Bicycle Routes), where it rides LTS 3 and up (leaving out a bit of 0.1 mi or less at a start or end at a Metro station, the sidewalk the elevator stands on, rated as its road), its very-high-stress junctions, and small detours (where it leaves a road and comes back to it). On a Bike + transit or Bikeshare + transit trip those figures are the first ride's; `summary.transit.later_rides` gives each ride after it (miles, LTS shares and busy stretches) and `ridden_mi` all of them together. A via point reached by an out-and-back is moved to where the spur leaves the road (`trim_spurs`, on by default). With `intervals` (on and off minutes, sets, pace) it checks the route for interval training: where efforts can run with no stop, signal, busy crossing, sharp turn, descent or LTS 4 road, how many sets fit in one session (each rest about the asked minutes, laps on a loop), and clear climbs for up-and-back repeats. With `best_order` (alleycat or errand checkpoints) it keeps the start and finish and rides the points between in the quickest order: the shortest few orders by straight line are planned and the quickest kept. `closures` lists the closures it goes through or round (what, until when, where on the route, source and link), and `closure_warning` says when it rides through one, naming any stop or via point reached on a closed stretch; `check_before_you_go` lists the park notices for the ride's time (an NPS alert, or a deer-management closure in Rock Creek Park or a Montgomery park), which are warnings and never routed round. `potential_closures` lists the permits and planned work along the route (DDOT permits, DDOT ProTrack+, DC Water, WSSC Water) that may close the road or bike lane in their window, with their miles, source and link; they are not routed round either. A place name is searched near the route's other points; one that matches places far apart and none near the route is asked back. Among the matches near the route, a town or neighbourhood named just what was typed before the comma comes first ("Leesburg, VA" is the town, not Leesburg Pike or a clinic nearer the route), then a match named just that, then one in the town typed after the comma (routing hunt 4, G4-1). For optimizing: the summary gives unpaved miles and the minutes spent waiting at signals and stop signs; `legs` gives miles, minutes, climb and busy miles between stops (food, water and overnight stops on a long ride); `steep_grades` and `road_hazards` (cobbles, rails) say where. `pace_mph` times the route at the rider's own speed (on Run, the running pace, 4 to 10 mph); `alternatives` also answers the other routes the site's search found at the same settings, each its own draft that keeps its line when revised; `avoid` leaves out a line of road; `follow` plans along a line the rider has (an encoded polyline) instead of through points. |
| `open_link` | Picks up a route from a RouteMaker link you paste: the page's address after you changed the route in the app, one of your saved routes opened in the app, or a shared route's link. |
| `revise_route` | Changes a draft (add, move or remove points; any ride type or setting; roads to `avoid`, by name, by mile range or as a line; not on a line you asked it to follow, which is ridden as it is, while an alternative's draft is then planned through its points) and plans it again as a new draft; the old one stays to go back to. `changed_from_previous` gives each figure before and after (miles, minutes, climb, LTS 3+ and 4+ miles, unpaved miles, junctions, junction waits), so the assistant can tell whether a change helped and stop when the gains are small. |
| `route_notes` | Puts notes on a draft's route: a caution (a dangerous intersection) or a point of interest, each at a spot (a point, a place to look up, or a mile along) in a few words. Give the whole list each time; `[]` clears it. A note within 60 m (our default) is a cue on the app's cue sheets, phone images and courses, and said in Ride; one up to 400 m off is put on the route. Kept in the link and on a new draft. |
| `route_segments` | Reads a draft stretch by stretch: miles, road, LTS, facility, surface, average and steepest grade, climb, one-way and minutes; every higher and very-high stress junction with its reason; steep grades and hazards. Paged for long rides (`from_mi`, `to_mi`, `next_from_mi`). |
| `ride_conditions` | Light and weather for riding a draft at a time: dark or light at the start and the finish (civil dawn and dusk), the arrival time, and within 48 hours the National Weather Service alerts along the route and where rain is first forecast, through the site's own weather check (points rounded, nothing kept). |
| `my_routes` | Site connector only: lists your saved routes with their tags and whether each is fixed (archived ones with `archived`, narrowed by `tag` or `search`), or opens one by name or id as a draft to revise or read ("my commute"); a fixed route with closures on its line comes with the suggestion to plan it again around them. It never changes My routes, though opening one counts as opening it (a full account offers the route unopened longest). A connection allowed before it existed cannot read them until you connect again. |
| `reach` | Where a rider can be in 15, 30, 45 and 60 minutes (isochrones) from one to five points, by any bike ride type, Walk or Run, from the points or to them, with each ring's area and the Metro stations, bike racks, places to eat and places to see inside; unless `calm` is false, the same rings at Low-stress beside them. Several points combine as any, all (a meeting spot) or each. Its link opens the rings in the app. |
| `compare_places` | Ranks 2 to 6 places to start from (a home, a hotel, an office) by the riding minutes to 1 to 3 places the rider goes, at the rider's traffic setting and at Low-stress (left out where the setting is already Low-stress or calmer), against any minute limits; places left when the call's time runs out are listed, not ranked. Bike ride types only. |
| `save_route` | Keeps a draft, only when you say so: in your My routes on the site's own connector, with `tags` if given, or as a GPX file on your own computer. On the site, `replaces` (a saved route's id) archives that route once this one is saved, for a new route that supersedes it. `fixed` true keeps it as a fixed route: its exact line, never re-routed in a ride, with Update route offered only when a closure is on its line; left out, it is saved by its via points (our default). A full account (200 routes, nothing archived) is refused with the route unopened longest, for the assistant to offer archiving it. |
| `my_drafts` | Lists the drafts planned through this app and not saved, newest first (the archived ones with `archived`). |
| `archive_draft` | Archives a draft and every revision of its route: it leaves the app's Load route and `my_drafts`, and still goes a week after it was made; `archived` false restores it. For a draft that only tested or checked RouteMaker. `plan_route`, `plan_metro_loop` and `open_link` take `test: true` to make the draft archived from the start, and a revision of an archived draft stays archived. It never touches My routes. |
| `organize_route` | Site connector only, when you say so: tags a saved route (`tags`, `add_tags`, `remove_tags`) or archives or restores it (`archived`). Archived routes leave Load route's list (Archived lists them) and are the first to go, longest archived first, when the account is full. It never renames or deletes. A connection allowed before it existed cannot use it until you connect again. |
| `gpx_route` | A draft as a GPX track: a `.gpx` file on your own computer, or a download link on the site. |
| `route_picture` | Site connector only, when you ask for a picture: the draft's map and graphs (on a Mass Ride its flow and corkers too) as one PNG, and a link that opens it, to share, while the draft is kept. |
| `cue_cards` | Site connector only, when you ask for turn cues as images: the draft's cues as phone-sized PNGs (Plan's "Cue sheet image" export), each row the miles, an arrow, the turn and the road, stops by number and name, Part 1 of N on a long route, and a link that opens each while the draft is kept. Stop names you give are kept on a new draft. |
| `draft_route_post` | Site connector, instance admins only: writes a Featured routes post as a draft (title, about, who it's for, season, highlighted sections with their miles) around a draft route or a line to follow, for an admin to publish in the admin. Sending the same slug again with `replace` rewrites the draft. |
| `plan_metro_loop` | Builds a loop of about the target length around DC (or another centre) through waypoints at or just beyond Metro stations, rescales it once towards the target, and repairs stretches past the Metro limit. |

`plan_route` also answers `why` on bike rides up to 25 mi in straight lines (our default,
unmeasured): the route against the most direct one between the same points (the Fast ride
type's, planned once more), in our own ratings: how many miles and minutes longer, how many
fewer busy miles (LTS 3 and up), and up to three busy roads it leaves with what it rides instead
("leaves Georgia Avenue (LTS 4) for the Metropolitan Branch Trail"; a road counts when it has
at least 0.25 mi at LTS 3 and up, our default, unmeasured). It is left out on a loop, a
followed line, Fast, Mass Ride and the transit, bikeshare, walk and run trips, and when the call
has no time left for one more plan.

### Ready-made asks (prompts)

An assistant app that lists MCP prompts offers four starters a person can pick: **Plan a
commute** (start, end, when you leave), **Family trail ride** (start, an end or none for a ride
back, about how far), **Loop of N miles** (start, miles, whether to stay near Metro) and **Bike
plus Metro** (start, end, when you leave). Each becomes one ask that names the tools and settings
that fit, and asks for a short answer. The server's instructions carry a short playbook beside
them: which ride type for which ask, and what to say after a plan.

### Calls sent together

Assistants often send several calls at once. Each rider has one place search running at a time
on the site, so a lookup (place search, and the scenic road, climb, closure, reach and riding
time searches) that finds the site busy waits and tries again: each pause the Retry-After, at
most 1 s, and at most 4 s for all of one call's lookups (our defaults, unmeasured; a waiting call
holds its web worker). Past that, or when the site asks for a longer wait, the answer says
`retry_after_s` and that nothing is wrong with the request.

### The route view: a map and graphs in the chat

In an assistant app that shows MCP Apps (the `io.modelcontextprotocol/ui` extension; Claude does),
`plan_route`, `revise_route`, `open_link`, `plan_metro_loop` and `route_notes` show the draft under the answer:
the route on a map coloured by traffic stress, with its start, stops, finish, stressful junctions
and closures; a stress ribbon (trail and bike lane rails on its edges) over the elevation profile,
on one mile axis, with a readout where you point or tap (or move with the arrow keys); and
buttons to open the route in the app, download its GPX, or ask the assistant to save it (saving
stays on your word, as before). Other assistants get the same text answer as before.

The page is `mcp/route_view.html`, served as `ui://routemaker/route-view.html`. What it draws
travels in the tool result's `_meta` (`routemaker/route-view`), which the extension keeps out of
the model's context, so the answer the model reads is unchanged. On the site the base map behind
the line comes from `route_view_map`, a tool only the view calls (visibility `app`): a picture of
the app's own base map for the box the view asks for, drawn in memory and never kept
(`src/core/route_view_map.py`). It answers only with a key that travels in the view's `_meta`, so
an assistant without MCP Apps lists it but its model cannot use it. Each view's base map is one
connector call, counted in the same hourly limit as planning. On your own computer there is no
base map, so the line is drawn on a plain background.

On a Mass Ride the view is read by flow and corkers, not traffic stress: the line takes the
app's flow bands, there is no stress ribbon, and the graphs are the elevation, the riders a
minute the road carries (with the ride size's need as a dashed line), the corkers held at once
along the route (the app's corker load, with "about N for the ride": the most held at once times
2, as corkers leapfrog ahead riding about twice the group's pace) and the junctions that need
corkers, on the map and in a row under the graphs. Ask to leave junctions out ("don't cork the
LTS 3 roads", "skip Kennedy Street") and the assistant sets `corking` on `plan_route` or
`revise_route` (`from_lts`, `skip` by street or mile): the count, the chart and the
`mass_capacity.corkers` answer add up only the junctions kept, list the others as not corked,
and keep the count for every junction beside it. The route itself and the app's link are
unchanged (the app still counts every junction). Corker marks a few pixels apart are drawn as one with their corkers
added up (our default), and each flow step wide enough carries its band's word, so the bands
are not told by colour alone.

To share it, ask for a picture: `route_picture` (on the site only, and only when asked) sends the
map and graphs as one PNG image, and a link that opens it while the draft is kept; the view
has a Picture button for the same link. The picture is drawn when it is asked for or the link is
opened (a few a minute from one address, our default), in memory, and never kept (`src/core/route_picture.py`). The link sits under `/mcp/gpx/`
(with `.png` on the end and its own digest), so the access logs already take its token out.

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

On Mountain Bike the summary's `mtb` lines (and each alternative's) say what the app's trail
notes say: trail harder than the rider's hardest level with no way round, busy road, the
mountain-bike map being down, the trail and singletrack miles (or that no trail was found), and
miles easier or harder than the preferred level. Mountain-bike trails are "mountain-bike trail"
in the summary's facilities and `trail` in `roads` and `route_segments`, not ordinary street.
`target_miles` is the longest the ride may be; where only a calmer route past it was found, the
summary's `over_target` says by how much.

Every planned route is a draft: it comes back with a link, kept for a week, that opens that
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
whole words; the one nearest the route's other points), in `find_place` as in `plan_route`. A
station `find_place` finds is shown at its bike way in (`lon_lat` and `bike_entrance`, nearest
`near`), where `plan_route` goes, not its platform point. In `compare_places` each place is taken
by the destinations (a station's way in nearest the first, a name searched near them), not by the
other places. And the answer's `points_taken_as` lists the other points of the same place the search found as `nearby_matches`.

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
the draft can still fix where it strays from Metro or move its points. Drafts are kept on the site for a week
(7 days, our default), listed in the app's Load route with Save until then (`my_drafts` lists
them to the assistant), and only the app that planned one can use it. There is no GPX file on the server: `gpx_route` gives a
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
  stand-in planner), `tests/test_mcp_connector_guidance.py` (calls sent together, the prompts and
  `why`), `tests/test_mcp_route_view.py` (the route view) and
  `tests/test_connector.py` (the site's connector, saving and posts).
