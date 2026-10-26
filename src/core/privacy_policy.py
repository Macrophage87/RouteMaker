"""The privacy policy (Google Play asks for a privacy policy's web address for the Android app).

One public page, GET /privacy, in the delete-account page's frame (`account_deletion._page`), and
linked from it and from Settings > About. It says, most important first, what the site and the
phone app (mobile/) collect, keep and send, and to whom. Every claim is the code's; where each one
comes from:

- Location: Ride mode's positions stay on the device (frontend/src/RideMode.tsx, "Privacy"); the
  app uses location only while on screen when asked, or during a ride, never with
  background-location permission (mobile/README.md, "Privacy"; mobile/test/config.test.mjs); a
  route request carries points in its body, and the logs keep no query (docs/DEVELOPMENT.md,
  "Logs and the rider's position").
- Group and Mass Ride: core.ride_presence (20 m grid, memory only; dots, alerts and a leader's
  path 2 minutes, nothing longer)
  and frontend/src/RideGroup.tsx (only while sharing and the page is in front, near the route).
- Discord sign-in: core.discord_oauth (identify scope, no token kept) and core.models.User (the
  Discord id and dates only); the bot's role cache: core.membership.
- What an account keeps: core.models MyGo, AccountSettings (frontend/src/lib/accountSettings.ts,
  weight included), Report311Log, SavedRoute and SavedRouteVersion, and
  ConnectorGrant and ConnectorDraft (core.connector).
- Shared links: core.shared_routes (keeping, no weight, owner only) and core.share_preview (Home
  left out of the preview).
- Suggestions: core.suggestions, core.junction_suggestions, core.mass_hazards (the spot dropped,
  the account for the admin only), core.suggestion_post (the Discord poll names nobody),
  core.signed_out_suggestions (a salted daily hash, 24 hours); 311: core.report_log and core.dc311.
- What the browser and the server contact: the Content-Security-Policy (Caddyfile, `connect-src
  'self'`), core.street_photo, core.gbfs, core.wmata_live, core.closure_sources, core.dc311,
  core.weather (points rounded to 0.01 degree, answers 2 minutes in memory).
- Logs, limits and backups: docker/api-entrypoint.sh (the access log's format), core.ratelimit,
  config.procrastinate (BACKUP_KEEP, BACKUP_EXCLUDED_TABLES); sessions: core.revocation.
- Garmin: core.garmin (the encrypted token, offered only with core.garmin.COURSES_WIRED),
  core.garmin_views (connect, Disconnect, Garmin's deregistration notice), core.garmin_courses
  (the course sent, and GarminLink.courses, which course each saved route was sent as). Garmin's
  developer program reviews this page before an app may connect riders.
- Wahoo: core.wahoo (the encrypted token, offered where the Wahoo keys are set),
  core.wahoo_views (connect, Disconnect, removing the routes sent when the account is deleted),
  core.wahoo_routes (the route sent, and WahooLink.routes, the Wahoo routes sent). Wahoo's API
  agreement asks for a privacy policy and for deletion on request.
- Hosting: settings.PRIVACY_HOSTING, the deployment's own (Garmin asks that every party storing
  riders' data be named).

Change the page when the code changes what it collects. It names no host: every address is a path
on the site itself.
"""

from __future__ import annotations

from html import escape

from django.conf import settings
from django.views.decorators.http import require_safe

from . import account_deletion

PATH = account_deletion.PRIVACY_PATH
TITLE = "RouteMaker privacy policy"
# Change with the text: the date a rider reads as when this page last said something new.
LAST_UPDATED = ("2026-10-26", "October 26, 2026")
# Unless the deployment sets PRIVACY_CONTACT (an e-mail address or a web address).
CONTACT = "Questions, or a request about your data: ask the site's owner on Discord."
CONTACT_LEAD = "Questions, or a request about your data: "
NO_ADS = "No ads, no analytics, no tracking, and nothing about you is sold or shared for marketing."
# Unless the deployment sets PRIVACY_HOSTING (the hosting provider's name).
HOSTING = (
    "The site's owner runs the server and its database, at home or with a hosting company, which "
    "stores the data only to run the site."
)
HOSTING_LEAD = "The server and its database run at "
HOSTING_TAIL = ", which stores the data only to run the site. No other company stores your data."
GARMIN_NO_AI = "Nothing from Garmin is sold, shared, given to AI services, or used to train AI."
WAHOO_NO_AI = "Nothing from Wahoo is sold, shared, given to AI services, or used to train AI."
WHERE_YOU_ARE = (
    "Your location is used on your phone or computer to plan and guide your ride. The server "
    "keeps no record of where you are, only places you choose to save or share (Home, favorite "
    "places, saved and shared routes, a 311 problem’s spot) and, while you share on a Group or "
    "Mass Ride, your rounded dot for 2 minutes and an alert’s spot for 2 minutes."
)


def _p(text: str) -> str:
    return f"<p>{escape(text)}</p>"


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


SUMMARY = (
    f'<p>Last updated: <time datetime="{LAST_UPDATED[0]}">{LAST_UPDATED[1]}</time>.</p>'
    + _ul(
        [
            NO_ADS,
            "You can use RouteMaker without an account.",
            WHERE_YOU_ARE,
            "Signing in with Discord keeps your Discord account number, not your name or e-mail, "
            "and what you choose to save.",
        ]
    )
    + (
        f'<p>You can delete your account at any time: <a href="{account_deletion.PATH}">'
        "Delete your account</a>.</p>"
    )
)

SECTIONS: list[tuple[str, str]] = [
    (
        "Your location",
        _p(
            "RouteMaker uses your location only when you ask: Use my location, Ride mode, and "
            "sharing your dot on a Group or Mass Ride."
        )
        + _p(
            "In the Android app, location is used while the app is on screen when you ask for "
            "it; from Start ride to End ride it also keeps going with the screen locked, with the "
            "“Riding with RouteMaker” notification showing. The app never asks for "
            "location all the time."
        )
        + _p(
            "Your positions stay on your device. One is sent to the server only as part of "
            "something you use: planning or re-planning a route from where you are, naming "
            "a place, finding the nearest water, restroom, food, repair or bikeshare docks, "
            "a Detour search, checking the weather along your route or, in Roam, where you are "
            "(every 5 minutes), finding which 311 website covers a problem you log, and Group or "
            "Mass Ride sharing. The server answers "
            "and does not store it, except places you choose to save or share and ride sharing "
            "(below)."
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
                "An alert you send keeps your rounded spot for 2 minutes, or until you clear it.",
                "Share ride and Broadcast make you the ride leader, shown as a dot from the start "
                "of your ride. While you ride a shared ride, you and anyone on it who chooses to "
                "be shown are shown on or off the route, so riders who get separated can find "
                "each other; once the ride ends, the quarter-mile rule is back.",
                "As leader, your phone also sends the route you are riding and the path you have "
                "ridden (rounded the same way, without its first 650 ft (200 m), as rides often "
                "start at home) about every 2 minutes; the server keeps each only in memory and "
                "drops it after 2 minutes. Only those with your link see it. The link itself, "
                "like any shared route, shows where the route starts.",
                "Speak, in an alert's Other box, uses your browser's speech recognition: the "
                "browser's maker (Google for Chrome, Apple for Safari) turns the recording into "
                "text. The words go only into the box until you tap Send.",
            ]
        ),
    ),
    (
        "If you sign in with Discord",
        _ul(
            [
                "RouteMaker asks Discord only for your identity.",
                "It keeps your Discord account number and when your account was made; each "
                "sign-in records when it was last used.",
                "Not your name, e-mail, picture or servers.",
                "Discord’s sign-in tokens are thrown away, not kept.",
            ]
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
                "Favorites: the places you save, Work among them (each one point and its name).",
                "Your 311 log (below).",
                "The assistant apps you connected, with the routes they drafted for a week.",
            ]
        )
        + _p(
            "Only your weight’s total, rounded to whole kilograms, goes with a route "
            "request; it is never in a link, a shared route or a log. Signed out, all of these "
            "stay on your device instead."
        ),
    ),
    (
        "If you connect Garmin",
        _p("Connecting a Garmin account is your choice, in Settings. It works like this:")
        + _ul(
            [
                "Send to Garmin then adds the course to your Garmin Connect account directly, "
                "without opening the Garmin Connect app.",
                "RouteMaker keeps only Garmin’s sign-in token for your account, encrypted, "
                "your Garmin account number, which Garmin course each saved route was sent as (so "
                "sending it again updates that course), and when you connected and last sent a "
                "course. It uses them only to send the courses you choose.",
                "Other than your account number, it never reads your activities, health data or "
                "anything else from Garmin.",
                GARMIN_NO_AI,
                "Settings shows whether you are connected. Disconnect there at any time: "
                "RouteMaker deletes the token and tells Garmin. Deleting your account does the "
                "same. Disconnect in Garmin Connect instead, and RouteMaker deletes it when Garmin "
                "says so.",
                "That connection is all RouteMaker keeps from Garmin, so there is nothing else to "
                "see, correct or export. To fix it, disconnect and connect again.",
            ]
        ),
    ),
    (
        "If you connect Wahoo",
        _p("Connecting a Wahoo account is your choice, in Settings. It works like this:")
        + _ul(
            [
                "Send to Wahoo then adds the route to your Wahoo app directly, with its turn "
                "cues, and the app sends it to your ELEMNT.",
                "RouteMaker keeps only Wahoo’s sign-in token for your account, encrypted, your "
                "Wahoo account number, which Wahoo routes it sent (so sending a saved route again "
                "updates it, and deleting your account removes them), and when you connected and "
                "last sent a route. It uses them only to send the routes you choose.",
                "Other than your account number, it never reads your rides, workouts, plans or "
                "anything else from Wahoo.",
                WAHOO_NO_AI,
                "Settings shows whether you are connected. Disconnect there at any time: "
                "RouteMaker deletes the token and withdraws its access at Wahoo. The routes "
                "already sent stay in your Wahoo app. Deleting your account does the same and "
                "also deletes from Wahoo up to 100 routes RouteMaker sent through that "
                "connection; any it could not reach stay in your Wahoo app, to delete there.",
                "That connection is all RouteMaker keeps from Wahoo, so there is nothing else to "
                "see, correct or export. To fix it, disconnect and connect again.",
            ]
        ),
    ),
    (
        "Shared links",
        _ul(
            [
                "Share keeps the route under a random link. Anyone with the link can open it.",
                "Shared signed in, the link records your account, so only you can turn it off. "
                "Shared signed out, it records nothing of you.",
                "Your weight is taken out.",
                "When a route starts, ends or stops at your Home, the preview a chat app shows "
                "leaves out the part near it.",
                "A link is kept a year after it was last opened, unless you choose to keep it "
                "permanently or until a date.",
                "A link you turn off loses its route and only says it was turned off.",
            ]
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
            "sign in, Garmin’s or Wahoo’s pages when you connect them, links you choose to "
            "open, such as a street photo on Mapillary or a 311 website, and a course file you "
            "hand to Garmin Connect."
        )
        + _p("The site’s server contacts, with nothing about you:")
        + _ul(
            [
                "Mapillary, for a street photo: a small box around a point on the road, never "
                "your position.",
                "WMATA, for live trains, buses and elevator outages.",
                "The National Weather Service and Open-Meteo, for weather alerts and rain along "
                "your route: points on it rounded to about 0.7 mi (1.1 km), never your exact "
                "position. The answers are kept 2 minutes, by the rounded point only.",
                "The bikeshare operator’s public feeds, for docks and bikes.",
                "The National Park Service and DC’s road-closure notices, for closures.",
                "DC 311, as above.",
                "Discord, to finish your sign-in and for the bot.",
            ]
        )
        + _p("Where you connect Garmin, the server also contacts Garmin:")
        + _ul(
            [
                "Your Garmin sign-in token: to finish connecting, to keep you connected, and to "
                "end the connection when you disconnect.",
                "A course you choose to send: the route’s line with its heights, its name, "
                "distance, climb and descent, and the kind of ride.",
            ]
        )
        + _p(
            "Where you connect Wahoo, the server also contacts Wahoo, with your Wahoo sign-in "
            "token and a route you choose to send: its course file with turn cues, its name, "
            "start, distance, climb and descent."
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
            "until you clear its storage. The Android app also keeps the site address. It has no "
            "analytics or crash reporting, and its data is left out of phone backups."
        ),
    ),
    (
        "Server logs",
        _ul(
            [
                "The access logs keep the time, the page asked for without its query, the result, "
                "its size, how long it took and the browser’s name.",
                "No internet address, and no request body, so no route points or positions.",
                "Map tile requests show which area was viewed.",
                "The app’s own logs are capped in size, so old lines are overwritten.",
                "When a request fails, an error log may keep more of it, including the internet "
                "address, for a short time.",
                "Request limits count a one-way code made from your internet address, deleted "
                "within about 30 hours.",
            ]
        ),
    ),
    # The hosting provider is the deployment's (`hosting`), filled in at request time.
    ("Where your data is kept", ""),
    (
        "How long data is kept",
        _ul(
            [
                "What you save with your account: until you delete it, or the account.",
                "Group and Mass Ride positions, alerts and a leader's path: 2 minutes. Nothing "
                "about a ride is kept longer.",
                "Shared links: as above.",
                "Database backups: one a night, the last seven kept, so deleted data can stay in "
                "them for up to a week. Sign-ins, request limits, the Discord role list and Garmin "
                "and Wahoo connections are left out of them.",
                "Suggestions already decided stay as the map’s history, with nothing linking "
                "them to you once your account is deleted.",
                "A note that an account was deleted, and when, under an account number.",
            ]
        ),
    ),
    (
        "Deleting your account",
        f'<p><a href="{account_deletion.PATH}">Delete your account</a> on the web, or in the app '
        "under Settings, Account, Delete account. It says what is deleted and what is kept, and "
        "asks once.</p>",
    ),
    # The contact is the deployment's (`contact`), filled in at request time.
    ("Contact", ""),
]


def contact() -> str:
    """The Contact section: settings.PRIVACY_CONTACT as a link (an e-mail address or a web
    address) or as text, or, unset, the Discord wording."""
    value = (getattr(settings, "PRIVACY_CONTACT", "") or "").strip()
    if not value:
        return _p(CONTACT)
    if value.partition(":")[0] in ("https", "http"):
        shown = f'<a href="{escape(value)}">{escape(value)}</a>'
    elif "@" in value and " " not in value:
        shown = f'<a href="mailto:{escape(value)}">{escape(value)}</a>'
    else:
        shown = escape(value)
    return f"<p>{escape(CONTACT_LEAD)}{shown}.</p>"


def hosting() -> str:
    """The Where your data is kept section: settings.PRIVACY_HOSTING named as the host, or, unset,
    the owner-run wording."""
    value = (getattr(settings, "PRIVACY_HOSTING", "") or "").strip()
    if not value:
        return _p(HOSTING)
    return _p(f"{HOSTING_LEAD}{value}{HOSTING_TAIL}")


# The sections whose text is the deployment's, made at request time.
FILLED = {"Contact": contact, "Where your data is kept": hosting}


def body() -> str:
    return SUMMARY + "".join(
        f"<h2>{escape(h)}</h2>{FILLED[h]() if h in FILLED else content}" for h, content in SECTIONS
    )


@require_safe
def page(request):
    """GET or HEAD: the policy, the same for everyone, signed in or not."""
    return account_deletion._page(body(), title=TITLE, privacy=False)
