"""The privacy policy (Google Play asks for a privacy policy's web address for the Android app).

One public page, GET /privacy, in the delete-account page's frame (`account_deletion._page`), and
linked from it and from Settings > Account. It says, most important first, what the site and the
phone app (mobile/) collect, keep and send, and to whom. Every claim is the code's; where each one
comes from:

- Location: Ride mode's positions stay on the device (frontend/src/RideMode.tsx, "Privacy"); the
  app's GPS runs only from Start ride to End ride, never with background-location permission
  (mobile/README.md, "Privacy"; mobile/test/config.test.mjs); a route request carries points in
  its body, and the logs keep no query (docs/DEVELOPMENT.md, "Logs and the rider's position").
- Group and Mass Ride: core.ride_presence (20 m grid, memory only, 2 minutes; alerts 10 minutes)
  and frontend/src/RideGroup.tsx (only while sharing and the page is in front, near the route).
- Discord sign-in: core.discord_oauth (identify scope, no token kept) and core.models.User (the
  Discord id and dates only); the bot's role cache: core.membership.
- What an account keeps: core.models MyGo, AccountSettings (frontend/src/lib/accountSettings.ts,
  weight included), Report311Log, SavedRoute and SavedRouteVersion, AssistantKey (a digest), and
  ConnectorGrant and ConnectorDraft (core.connector).
- Shared links: core.shared_routes (keeping, no weight, owner only) and core.share_preview (Home
  left out of the preview).
- Suggestions: core.suggestions, core.junction_suggestions, core.mass_hazards (the spot dropped,
  the account for the admin only), core.suggestion_post (the Discord poll names nobody),
  core.signed_out_suggestions (a salted daily hash, 24 hours); 311: core.report_log and core.dc311.
- What the browser and the server contact: the Content-Security-Policy (Caddyfile, `connect-src
  'self'`), core.street_photo, core.gbfs, core.wmata_live, core.closure_sources, core.dc311.
- Logs, limits and backups: docker/api-entrypoint.sh (the access log's format), core.ratelimit,
  config.procrastinate (BACKUP_KEEP, BACKUP_EXCLUDED_TABLES); sessions: core.revocation.

Change the page when the code changes what it collects. It names no host: every address is a path
on the site itself.
"""

from __future__ import annotations

from html import escape

from django.views.decorators.http import require_GET

from . import account_deletion

PATH = account_deletion.PRIVACY_PATH
TITLE = "RouteMaker privacy policy"
CONTACT = "Questions, or a request about your data: ask the site's owner on Discord."
NO_ADS = "No ads, no analytics, no tracking, and nothing about you is sold or shared for marketing."


def _p(text: str) -> str:
    return f"<p>{escape(text)}</p>"


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


SUMMARY = _ul(
    [
        NO_ADS,
        "You can use RouteMaker without an account. Your location is used to plan and guide your "
        "ride, on your phone or computer; the server does not store it.",
        "Signing in with Discord keeps your Discord account number, not your name or e-mail, and "
        "what you choose to save.",
    ]
) + (
    f'<p>You can delete your account at any time: <a href="{account_deletion.PATH}">'
    "Delete your account</a>.</p>"
)

SECTIONS: list[tuple[str, str]] = [
    (
        "Your location",
        _p(
            "RouteMaker uses your location only when you ask: Use my location, Ride mode, and "
            "sharing your dot on a Group or Mass Ride."
        )
        + _p(
            "In the Android app, the GPS runs only from Start ride to End ride, while the app is "
            "running, including with the screen locked; the notification “Riding with "
            "RouteMaker” shows while it does. The app never asks for location all the time."
        )
        + _p(
            "Your positions stay on your device. One is sent to the server only as part of "
            "something you use: planning or re-planning a route from where you are, naming "
            "a place, finding the nearest water or restroom, finding which 311 website covers a "
            "problem you log, and Group or Mass Ride sharing. The server answers and does not "
            "store it; the one position kept is that of a problem you log for 311 (below)."
        )
        + _p(
            "A route’s link holds its points, so a route planned from your location carries "
            "it to whoever you send the link to; RouteMaker says so before you share."
        ),
    ),
    (
        "Group and Mass Ride sharing",
        _ul(
            [
                "Off until you choose to show yourself as a dot, and only while RouteMaker is on "
                "screen and you are within a quarter mile (400 m) of the route.",
                "Your position is rounded to about 66 ft (20 m), kept only in the server’s "
                "memory, never on disk or in a log, and dropped 2 minutes after it was sent.",
                "Other riders on the same ride see an unnamed dot. No account or name is sent: "
                "your phone makes a new random code for each ride.",
                "An alert you send keeps your rounded spot for 10 minutes, or until you clear it.",
            ]
        ),
    ),
    (
        "If you sign in with Discord",
        _p(
            "RouteMaker asks Discord only for your identity. It keeps your Discord account "
            "number and when your account was made, and each sign-in records when it was last "
            "used. Not your name, e-mail, picture or servers. Discord’s sign-in tokens are "
            "thrown away, not kept."
        )
        + _p(
            "If the site’s owner connects a Discord server, its bot keeps which of that "
            "server’s roles you have, as numbers, to decide what you may do on the site."
        )
        + _p("With your account, RouteMaker keeps what you save, private to you:")
        + _ul(
            [
                "Saved routes: the line, its start, end and stops, ride type and settings, name "
                "and date, and earlier versions. They are checked against new road closures so My "
                "routes can warn you.",
                "Settings: favorite ride types, ride type and dials, map layers, and your rider "
                "and bike weight.",
                "My Go: the view the app opens in, your ride type, and Home (one point and its "
                "label).",
                "Your 311 log (below).",
                "An AI assistant key, kept only as a one-way code, and the assistant apps you "
                "connected, with the routes they drafted for a week.",
            ]
        )
        + _p(
            "Only your weight’s total, rounded to whole kilograms, goes with a route "
            "request; it is never in a link, a shared route or a log. Signed out, all of these "
            "stay on your device instead."
        ),
    ),
    (
        "Shared links",
        _p(
            "Share keeps the route under a random link. Anyone with the link can open it. Shared "
            "signed in, the link records your account, so only you can turn it off; shared signed "
            "out, it records nothing of you. Your weight is taken out. When a route starts, ends "
            "or stops at your Home, the preview a chat app shows leaves out the part near it."
        )
        + _p(
            "A link is kept a year after it was last opened, unless you choose to keep it "
            "permanently or until a date. A link you turn off loses its route and only says it "
            "was turned off."
        ),
    ),
    (
        "Suggestions and reports",
        _ul(
            [
                "A suggestion for a road or junction, or a Mass Ride hazard, keeps the road, your "
                "level and your reason. The spot you tapped is not kept. Signed in, your account "
                "is kept with it for the site’s admin only.",
                "The admin may post a suggestion as a poll on Discord. The poll names nobody.",
                "Signed out, a suggestion keeps no account. To limit sends, your device is counted "
                "by a one-way code made from your internet address and the day, deleted after 24 "
                "hours. E-mail addresses and phone numbers are taken out of what you type.",
                "The 311 log keeps each problem you log: what it is, the road’s name, its GPS "
                "position, the time and your note. It stays on your device, and with your account "
                "when signed in. RouteMaker shows which city or county 311 website takes it; you "
                "send it yourself.",
                "In Washington, DC, where the site has DC 311’s key, a problem logged in Ride "
                "mode is also sent to DC 311 by the server: the problem, the point on your route "
                "and the report’s words, nothing about you.",
            ]
        ),
    ),
    (
        "Who else is contacted",
        _p(
            "Your browser and the app talk only to this site: the map, place search and routing "
            "run on the site’s own servers. The exceptions are Discord’s pages when you "
            "sign in, links you choose to open, such as a street photo on Mapillary or a 311 "
            "website, and, in the Android app, a course you send to Garmin Connect."
        )
        + _p("The site’s server contacts, with nothing about you:")
        + _ul(
            [
                "Mapillary, for a street photo: a small box around a point on the road, never "
                "your position.",
                "WMATA, for live trains, buses and elevator outages.",
                "The bikeshare operator’s public feeds, for docks and bikes.",
                "The National Park Service and DC’s road-closure notices, for closures.",
                "DC 311, as above.",
                "Discord, to finish your sign-in and for the bot.",
            ]
        )
        + _p(
            "If you connect an AI assistant app, the routes it plans go to that app and its "
            "maker, under their own privacy policy. It can plan routes and add them to My routes; "
            "it cannot read your saved routes."
        ),
    ),
    (
        "Cookies and your device",
        _p(
            "Two cookies, both needed for the site to work: one keeps you signed in, one protects "
            "forms. No advertising or tracking cookies. A sign-in ends after 30 days unused, or "
            "after 90 days."
        )
        + _p(
            "Your browser or the app keeps your settings, Home, weight, offline routes and 311 log "
            "until you clear its storage. The Android app also keeps the site address you typed. "
            "It has no analytics or crash reporting, and its data is left out of phone backups."
        ),
    ),
    (
        "Server logs",
        _p(
            "The access logs keep the time, the page asked for without its query, the result, its "
            "size, how long it took and the browser’s name. No internet address, and no "
            "request body, so no route points or positions. Map tile requests show which area was "
            "viewed. The logs are capped in size, so old lines are overwritten. When a request "
            "fails, an error log may keep more of it."
        )
        + _p(
            "Request limits count a one-way code made from your internet address, deleted within "
            "about 30 hours."
        ),
    ),
    (
        "How long data is kept",
        _ul(
            [
                "What you save with your account: until you delete it, or the account.",
                "Group and Mass Ride positions: 2 minutes; alerts: 10 minutes.",
                "Shared links: as above.",
                "Database backups: one a night, the last seven kept, so deleted data can stay in "
                "them for up to a week. Sign-ins, request limits and the Discord role list are "
                "left out of them.",
                "Suggestions already decided stay as the map’s history, with nothing linking "
                "them to you once your account is deleted.",
            ]
        ),
    ),
    (
        "Deleting your account",
        f'<p><a href="{account_deletion.PATH}">Delete your account</a> on the web, or in the app '
        "under Settings, Account, Delete account. It says what is deleted and what is kept, and "
        "asks once.</p>",
    ),
    ("Contact", _p(CONTACT)),
]


def body() -> str:
    return SUMMARY + "".join(f"<h2>{escape(h)}</h2>{content}" for h, content in SECTIONS)


@require_GET
def page(request):
    """GET: the policy, the same for everyone, signed in or not."""
    return account_deletion._page(body(), title=TITLE, privacy=False)
