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
| `save_route` | Keeps a draft, only when you say so: in your My routes on the site's own connector, or as a GPX file on your own computer. |
| `gpx_route` | A draft as a GPX track: a `.gpx` file on your own computer, or a download link on the site. |
| `draft_route_post` | Site connector, instance admins only: writes a Featured routes post as a draft (title, about, who it's for, season, highlighted sections with their miles) around a draft route or a line to follow, for an admin to publish in the admin. Sending the same slug again with `replace` rewrites the draft. |
| `plan_metro_loop` | Builds a loop of about the target length around DC (or another centre) through waypoints at or just beyond Metro stations, rescales it once towards the target, and repairs stretches past the Metro limit. |

The assistant picks the ride type and settings that fit what you ask: every ride type the app
has (bikeshare and bike plus transit included) and every setting (traffic stress, hills, ride
time, gravel, trails, target distance, rider weight, cargo load and assist, trail levels, the
bikeshare bike and ending, departure time).

Every planned route is a draft: it comes back with a link, kept for a week, that opens that
exact route in the app, like a link from the app's Share, so the map, Start ride and the app's own GPX are the
route the assistant described. Nothing is saved to My routes. Drafts last while the assistant's session does. On the site's connector
(below), `save_route` puts one in My routes, where it opens like any route you saved yourself; on
your own computer it writes a GPX file. Either way you can also open the link and press Save in
the app.

It plans through the site's own API (`POST /api/route`), so a route is exactly what the app would
plan. It changes nothing on the site except adding the routes you ask it to save. Metro distances
are straight-line, from DC Open Data's station file (CC BY 4.0) that the map also uses.

## Use it in Claude on the web and on your phone

The site runs the same server itself, at `/mcp` on its own address, so Claude on claude.ai and
in the Claude phone apps can use it with nothing installed.

1. In Claude, open **Settings > Connectors > Add custom connector**.
2. Name it RouteMaker, and give the site's address followed by `/mcp`, for example
   `https://routes.example.org/mcp`.
3. Choose **Connect**. RouteMaker's sign-in opens: sign in with Discord as usual (on the beta,
   with its password first), and choose **Allow**. Claude can then plan routes and add the ones
   you ask it to save to your My routes. It cannot read your saved routes or change anything
   else.

On the site, each call answers within one web request (up to a minute), so a long loop is
planned once per request: the answer says when it stopped early, and asking Claude to revise
the draft can still fix where it strays from Metro or move its points. Drafts are kept on the site for a week. There is no GPX
file on the server: `gpx_route` gives a download link instead, which works while the draft is kept
(on the beta, behind its password).

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
- `ROUTEMAKER_BASIC_AUTH` (optional): `user:password` for a site behind a password.

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
