"""Featured routes: blog-style posts around one exact route (the owner, 2026-10-19: "a blog-style
posting tool that would allow sharing some curated routes"; the design is in the project's
plans/route-posts-architecture.md; built for v0.12.1).

Each post is a page of its own, `/routes/<slug>`, laid out as the owner asked on 2026-10-24
("Basically I'd like each blog post as a shareable website where the seen thumbnail is the map"):

1. the title (and the season, when the post has one);
2. one row of figures: distance, climb, descent, riding time and ride type;
3. the map of the route;
4. one row of four buttons: Open in RouteMaker, Download GPX, Send to Garmin and Send to Wahoo;
5. the elevation and traffic stress profiles;
6. the description of the ride, who it is for, and the highlighted sections; a section given a
   stretch (From mile, To mile) has a small map of it (the owner, 2026-10-24: "Show a minimap of
   each of the sections highlighted"), with the stretch in words for readers without the map.

The page is made here, whole, so it reads without JavaScript and a link fetcher sees its tags
(no fetcher test as /s/ needs: the page is the same for both). `/post.js` (frontend/src/post/)
then swaps the picture for a live map, draws Plan's own charts from the route's frozen answer,
and makes Send to Garmin and Send to Wahoo work as the app's own buttons do (GpxPanel.tsx). With
no script the two Send buttons stay off and say why.

The link preview's picture is the map (`thumbnail`): on the page, an instance admin presses
"Use this map as the link picture" and their browser draws the post's map at 1200 by 630 and
sends it here (`thumbnail_upload`), credits drawn in. Until then the route's line drawing
(core.share_preview) stands in.

Posts are written in the admin (core.admin RoutePostAdmin), by instance admins only. Picking a
saved route copies it (`freeze`) into a SharedRoute kept permanently and owned by no account,
with the figures read then, so the post never changes under a map rebuild or an edit of the saved
route. Two checks refuse a route there (`route_problem`): one with no planned answer (an opened
GPX file not planned again has no stress figures for the charts), and one that starts, ends or
stops in the author's Home circle (core.share_preview), since posts are public.

States: draft (admins only, marked as a draft), published (listed and linked), unlisted (link
only) and withdrawn (410, one plain line). Every save and every new picture is in the audit log.
Seasons (the owner, 2026-10-19): a post with one is badged and first in the list while in
season, and in a closed "Out of season" fold otherwise; its link always works. Nothing of the
reader is read or kept: the list is the same for everyone.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import secrets
from datetime import date
from html import escape

from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.html import json_script
from django.views.decorators.http import require_http_methods, require_safe

from . import ratelimit, share_preview, shared_routes

BRAND = share_preview.BRAND
INDEX_TITLE = "Featured routes"
INDEX_INTRO = "Rides we like around Washington, DC and Baltimore, each with its exact route."
NONE_YET = "No featured routes yet."
OUT_OF_SEASON = "Out of season"
WITHDRAWN = "This post was withdrawn."
NOT_FOUND = "There is no featured route at this address."
DRAFT_NOTE = "Draft: only admins can see this page."
UNLISTED_NOTE = "Unlisted: only people with the link can find this page."
NO_SCRIPT_SEND = "Send to Garmin and Send to Wahoo need JavaScript. Download GPX works without it."

OPEN_LABEL = "Open in RouteMaker"
GPX_LABEL = "Download GPX"
GARMIN_LABEL = "Send to Garmin"
WAHOO_LABEL = "Send to Wahoo"
THUMBNAIL_LABEL = "Use this map as the link picture"

# The thumbnail as the page's script sends it: a JPEG of the preview's size, at most this big.
THUMBNAIL_MAX_BYTES = 1024 * 1024
THUMBNAIL_TYPE = "image/jpeg"
THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT = share_preview.WIDTH, share_preview.HEIGHT

SEASON_RE = re.compile(r"(\d\d)-(\d\d)")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# The app's own Content-Security-Policy (Caddyfile @frontend), since this page loads its script.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' "
    "data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; child-src 'self' "
    "blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
)

# The buttons' icons, as frontend/src/lib/iconPaths.ts draws them ("routes", "download"), and a
# bike computer for the two Send buttons (tests/test_route_posts.py holds the first two equal).
ICONS = {
    "routes": '<circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/>'
    '<path d="M6 17V10a4 4 0 0 1 4-4h6M18 7v7a4 4 0 0 1-4 4H8"/>',
    "download": '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>',
    "device": '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M9 6h6v7H9z"/>'
    '<path d="M10 17h4"/>',
}


# ---- Seasons ----


def season_day(value: str) -> tuple[int, int] | None:
    """ "03-20" as (3, 20), or None when it is not a day of the year (29 February is one)."""
    match = SEASON_RE.fullmatch(value or "")
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    try:
        date(2000, month, day)
    except ValueError:
        return None
    return month, day


def has_season(post) -> bool:
    return season_day(post.season_start) is not None and season_day(post.season_end) is not None


def in_season(post, today: date) -> bool | None:
    """Whether today falls in the post's window (which may wrap past New Year); None without one."""
    if not has_season(post):
        return None
    start, end, now = (
        season_day(post.season_start),
        season_day(post.season_end),
        (today.month, today.day),
    )
    return start <= now <= end if start <= end else now >= start or now <= end


def season_words(post) -> str:
    """ "Best 20 Mar to 15 Apr", or "" without a season."""
    if not has_season(post):
        return ""
    (m1, d1), (m2, d2) = season_day(post.season_start), season_day(post.season_end)
    return f"Best {d1} {MONTHS[m1 - 1]} to {d2} {MONTHS[m2 - 1]}"


# ---- Picking the route ----


def route_problem(saved, author) -> str | None:
    """Why a saved route cannot be a post's route, or None."""
    if saved is None:
        return "Pick one of your saved routes."
    if not isinstance(saved.answer, dict) or not saved.answer.get("geometry"):
        return "Plan this route in RouteMaker and save it again: a post needs its stress figures."
    line = saved.line or []
    if len(line) < 2:
        return "This saved route has no line."
    zone = author_zone(author)
    points = share_preview.route_points(saved)
    if zone is not None and share_preview.at_home(line, points, zone):
        return "This route starts, ends or stops at your Home. Posts are public, so pick another."
    return None


def author_zone(author):
    """The author's Home circle (core.share_preview), or None."""
    from .models import MyGo

    if author is None:
        return None
    go = MyGo.objects.filter(user_id=author.pk).first()
    if go is None or go.home_lat is None or go.home_lon is None:
        return None
    return share_preview.home_zone((go.home_lon, go.home_lat), share_preview.zone_jitter(author.pk))


def stats_of(answer: dict, preset: str, planned_on: date) -> dict:
    """The figures the page shows, read once from the route as published."""

    def number(key):
        value = answer.get(key)
        return float(value) if isinstance(value, int | float) else None

    return {
        "distance_m": number("distance_m"),
        "climb_m": number("climb_m"),
        "descent_m": number("descent_m"),
        "duration_s": number("duration_s"),
        "preset": preset,
        "planned_on": planned_on.isoformat(),
    }


def freeze(post, saved) -> None:
    """Copy the saved route into a SharedRoute of the post's own and read its figures (not saved
    here). The copy is kept permanently and owned by no account."""
    from .models import SharedRoute

    now = timezone.now()
    answer = shared_routes.public_answer(saved.answer)
    inputs = dict(saved.inputs or {})
    # The rider's weight never leaves their account (shared_routes.public_answer does the same for
    # the answer): an older saved route's dials may still carry it.
    if isinstance(inputs.get("dials"), dict):
        inputs["dials"] = {k: v for k, v in inputs["dials"].items() if "weight" not in k.lower()}
    row = SharedRoute.objects.create(
        id=secrets.token_hex(16),
        name=post.title[:120],
        source=saved.source,
        line=saved.line,
        distance_m=saved.distance_m,
        inputs=inputs,
        answer=answer,
        gpx="",
        created_at=now,
        last_opened_at=now,
        keep="forever",
        owner=None,
        preview_image=True,
    )
    post.route = row
    preset = str(inputs.get("preset") or answer.get("preset") or "")
    planned = saved.updated_at or timezone.now()
    post.stats = stats_of(answer, preset, timezone.localdate(planned))
    # A new route is a new map: the old link picture no longer shows it.
    post.thumbnail, post.thumbnail_key = None, ""
    first = saved.line[0]
    post.start_lon, post.start_lat = float(first[0]), float(first[1])


# ---- Words ----


def _paragraphs(text: str) -> str:
    """Plain text as paragraphs: a blank line starts a new one, a single line break stays."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n"))]
    return "".join(
        "<p>" + "<br>".join(escape(line) for line in b.split("\n")) + "</p>" for b in blocks if b
    )


def _duration(seconds: float) -> str:
    """As the app says it (frontend/src/lib/format.ts formatDuration)."""
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def ride_name(post) -> str:
    return share_preview.RIDE_NAMES.get(str(post.stats.get("preset") or ""), "Bike ride")


def figures(post) -> list[tuple[str, str]]:
    """The row of figures as (name, value)."""
    stats = post.stats or {}
    out = []
    if stats.get("distance_m"):
        out.append(("Distance", share_preview.format_distance(stats["distance_m"])))
    if stats.get("climb_m") is not None:
        out.append(("Climb", share_preview.format_climb(stats["climb_m"])))
    if stats.get("descent_m") is not None:
        out.append(("Descent", share_preview.format_climb(stats["descent_m"])))
    if stats.get("duration_s"):
        out.append(("Riding time", _duration(stats["duration_s"])))
    out.append(("Ride type", ride_name(post)))
    return out


def summary_line(post) -> str:
    """One line for the list and the preview: distance and climb."""
    stats = post.stats or {}
    parts = []
    if stats.get("distance_m"):
        parts.append(share_preview.format_distance(stats["distance_m"]))
    if stats.get("climb_m"):
        parts.append(f"{share_preview.format_climb(stats['climb_m'])} climb")
    return " · ".join(parts)


def _icon(name: str) -> str:
    return (
        '<svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" focusable="false">{ICONS[name]}</svg>'
    )


def _date(day) -> str:
    return f"{MONTHS[day.month - 1]} {day.day}, {day.year}"


# ---- Who may see what ----


def is_admin(request) -> bool:
    user = getattr(request, "user", None)
    return bool(
        user is not None
        and user.is_authenticated
        and getattr(user, "is_active", False)
        and getattr(user, "is_instance_admin", False)
    )


def visible(post, request) -> bool:
    from .models import RoutePost

    if post.route_id is None:
        return False
    if post.status in (RoutePost.Status.PUBLISHED, RoutePost.Status.UNLISTED):
        return True
    return post.status == RoutePost.Status.DRAFT and is_admin(request)


def listed(today: date):
    """The published posts, in season first, then by weight and date; and those out of season."""
    from .models import RoutePost

    posts = list(RoutePost.objects.filter(status=RoutePost.Status.PUBLISHED, route__isnull=False))
    shown = [p for p in posts if in_season(p, today) is not False]
    shown.sort(key=lambda p: not in_season(p, today))  # stable: the model's order otherwise
    return shown, [p for p in posts if in_season(p, today) is False]


# ---- The page's frame ----

STYLE = (
    ":root{color-scheme:light dark;--ink:#1f2933;--muted:#52606d;--bg:#fff;--card:#f5f7f4;"
    "--rule:#d6dcd4;--accent:#1d4ed8;--accent-ink:#fff;--badge:#fef3c7;--badge-ink:#713f12}"
    "@media (prefers-color-scheme:dark){:root{--ink:#e6e9ec;--muted:#aab4bf;--bg:#1b1e24;"
    "--card:#1c2025;--rule:#323942;--accent:#8ab4ff;--accent-ink:#0b1733;--badge:#3f3210;"
    "--badge-ink:#fde68a}}"
    "*{box-sizing:border-box}"
    "body{margin:0;font:17px/1.55 'Atkinson Hyperlegible',system-ui,sans-serif;color:var(--ink);"
    "background:var(--bg)}"
    "a{color:var(--accent)}"
    ".site{display:flex;gap:1rem;align-items:center;padding:.6rem 1rem;border-bottom:1px solid "
    "var(--rule)}.site a{font-weight:700;text-decoration:none}"
    "main{max-width:46rem;margin:0 auto;padding:1rem 1rem 3rem}"
    "h1{font-size:1.75rem;line-height:1.2;margin:.5rem 0}"
    "h2{font-size:1.25rem;margin:2rem 0 .5rem}h3{font-size:1.1rem;margin:1.25rem 0 .25rem}"
    ".note{padding:.5rem .75rem;border-radius:6px;background:var(--badge);color:var(--badge-ink);"
    "font-weight:700}"
    ".badge{display:inline-block;padding:.1rem .55rem;border-radius:999px;background:var(--badge);"
    "color:var(--badge-ink);font-weight:700;font-size:.9rem}"
    ".season{margin:.25rem 0;color:var(--muted)}"
    ".figures{display:flex;flex-wrap:wrap;gap:.25rem 1.25rem;margin:.75rem 0;padding:0}"
    ".figures div{display:flex;flex-direction:column}.figures dt{font-size:.85rem;"
    "color:var(--muted)}.figures dd{margin:0;font-weight:700}"
    ".post-map{margin:1rem 0;border-radius:8px;overflow:hidden;background:var(--card);"
    "aspect-ratio:1200/630;position:relative}"
    ".post-map img{display:block;width:100%;height:100%;object-fit:cover}"
    ".post-map .map{position:absolute;inset:0}"
    ".post-actions{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem;margin:1rem 0}"
    "@media (max-width:30rem){.post-actions{grid-template-columns:repeat(2,1fr)}}"
    ".action{display:flex;flex-direction:column;align-items:center;justify-content:center;"
    "gap:.25rem;min-height:4.25rem;padding:.5rem;border:2px solid var(--accent);border-radius:8px;"
    "background:var(--bg);color:var(--accent);font:inherit;font-size:.95rem;font-weight:700;"
    "text-align:center;text-decoration:none;cursor:pointer}"
    ".action.primary{background:var(--accent);color:var(--accent-ink)}"
    ".action:disabled{opacity:.55;cursor:not-allowed}"
    ".said{min-height:1.5em;margin:.25rem 0}"
    ".chart-text{color:var(--muted)}"
    ".highlight{border-left:4px solid var(--accent);padding:.1rem 0 .1rem 1rem;margin:1rem 0}"
    ".section-map{margin:.5rem 0}.section-map figcaption{color:var(--muted);font-size:.95rem}"
    ".minimap{position:relative;width:100%;aspect-ratio:16/9;border-radius:8px;overflow:hidden;background:var(--card);"
    "margin-bottom:.25rem}"
    ".byline{color:var(--muted);font-size:.95rem;margin-top:2rem}"
    ".admin{margin-top:2rem;padding:1rem;border:1px dashed var(--rule);border-radius:8px}"
    ".admin button{font:inherit;padding:.5rem 1rem;min-height:44px;border-radius:6px;"
    "border:2px solid var(--accent);background:var(--bg);color:var(--accent);cursor:pointer}"
    ".cards{list-style:none;padding:0;margin:0;display:grid;gap:1rem}"
    ".card a{display:grid;grid-template-columns:8rem 1fr;gap:.75rem;text-decoration:none;"
    "color:inherit;padding:.5rem;border:1px solid var(--rule);border-radius:8px}"
    ".card img{width:8rem;aspect-ratio:1200/630;object-fit:cover;border-radius:6px}"
    ".card h2{margin:0;font-size:1.1rem;color:var(--accent)}.card p{margin:.2rem 0}"
    "details summary{cursor:pointer;font-weight:700;margin:2rem 0 1rem}"
    ".visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);"
    "white-space:nowrap}"
)


def _frame(page_title: str, body: str, *, head: str = "", script: bool = False) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(page_title)}</title>{head}{share_preview.ICON_LINKS}"
        f"<style>{STYLE}</style></head><body>"
        '<header class="site"><a href="/">RouteMaker</a>'
        f'<a href="/routes/">{INDEX_TITLE}</a></header>'
        f"<main>{body}</main>"
        + ('<script type="module" src="/post.js"></script>' if script else "")
        + "</body></html>"
    )


def _respond(html: str, status: int = 200, *, cache: str = "no-cache") -> HttpResponse:
    response = HttpResponse(html, status=status, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = cache
    response["Content-Security-Policy"] = CSP
    response["Referrer-Policy"] = "same-origin"
    response["X-Content-Type-Options"] = "nosniff"
    response["Vary"] = "Cookie"
    return response


def _plain(status: int, words: str) -> HttpResponse:
    body = f"<h1>{escape(INDEX_TITLE)}</h1><p>{escape(words)}</p>"
    response = _respond(_frame(INDEX_TITLE, body), status, cache="no-store")
    response["X-Robots-Tag"] = "noindex"
    return response


def image_path(post) -> str:
    """The link picture: the map once an admin made it, else the route's line drawing."""
    if post.thumbnail_key:
        return f"/routes/{post.slug}/thumbnail.jpg?v={post.thumbnail_key}"
    return f"/s/{post.route_id}/preview.png"


def _tags(request, post) -> str:
    url = request.build_absolute_uri(f"/routes/{post.slug}")
    image = request.build_absolute_uri(image_path(post))
    words = post.abstract.strip().split("\n")[0][:200] or summary_line(post)
    image_type = THUMBNAIL_TYPE if post.thumbnail_key else "image/png"
    alt = f"Map of the route, {summary_line(post)}."
    props = [
        ("og:type", "article"),
        ("og:site_name", BRAND),
        ("og:title", post.title),
        ("og:description", words),
        ("og:url", url),
        ("og:image", image),
        ("og:image:type", image_type),
        ("og:image:width", str(THUMBNAIL_WIDTH)),
        ("og:image:height", str(THUMBNAIL_HEIGHT)),
        ("og:image:alt", alt),
    ]
    names = [
        ("description", words),
        ("twitter:card", "summary_large_image"),
        ("twitter:title", post.title),
        ("twitter:description", words),
        ("twitter:image", image),
        ("twitter:image:alt", alt),
    ]
    robots = "" if post.status == "published" else '<meta name="robots" content="noindex">'
    return (
        "".join(f'<meta property="{k}" content="{escape(v)}">' for k, v in props)
        + "".join(f'<meta name="{k}" content="{escape(v)}">' for k, v in names)
        + f'<link rel="canonical" href="{escape(url)}">{robots}'
    )


def open_link(post) -> str:
    """The app with the post's exact route (core.shared_routes.link_of, on this site)."""
    return shared_routes.link_of(post.route, "")


def _point_at(a, b, fraction: float) -> list[float]:
    return [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction]


def section_line(line, distance_m, start_mi, end_mi) -> list[list[float]]:
    """The part of the route's line from `start_mi` to `end_mi` along it, as [lon, lat] points,
    cut where those miles fall. Miles are counted on the route's own distance (the figures row),
    the line's length scaled to it, so the mileages an author reads off the app's charts land
    where the charts put them. Empty when the stretch is off the end of the route or the line
    has no length."""
    points = [p for p in line if len(p) >= 2]
    if len(points) < 2 or start_mi is None or end_mi is None:
        return []
    steps = [share_preview._haversine(a, b) for a, b in itertools.pairwise(points)]
    length = sum(steps)
    if length <= 0:
        return []
    scale = (distance_m or length) / length
    start = float(start_mi) * share_preview.METRES_PER_MILE / scale
    end = min(float(end_mi) * share_preview.METRES_PER_MILE / scale, length)
    if not 0 <= start < end:
        return []
    out: list[list[float]] = []
    walked = 0.0
    for (a, b), step in zip(itertools.pairwise(points), steps, strict=True):
        if walked + step >= start and walked <= end and step > 0:
            if not out:
                out.append(_point_at(a, b, max(0.0, start - walked) / step))
            if walked + step >= end:
                out.append(_point_at(a, b, (end - walked) / step))
                break
            out.append([b[0], b[1]])
        walked += step
    return out if len(out) >= 2 else []


def stretch_words(section) -> str:
    """Where a section's stretch is: "Mile 33.4 to 33.8 (km 53.8 to 54.4)"."""
    start, end = float(section.start_mi), float(section.end_mi)
    km = share_preview.METRES_PER_MILE / 1000
    return f"Mile {start:.1f} to {end:.1f} (km {start * km:.1f} to {end * km:.1f})"


def _stretches(post) -> list[tuple[object, list[list[float]]]]:
    """Each section with the line of its stretch (empty without one)."""
    distance = (post.stats or {}).get("distance_m")
    return [
        (s, section_line(post.route.line or [], distance, s.start_mi, s.end_mi))
        for s in post.sections.all()
    ]


def page_data(request, post) -> dict:
    """What the page's script reads: the exact line, the frozen answer and the plan's points."""
    route = post.route
    data = {
        "slug": post.slug,
        "title": post.title,
        "line": route.line,
        "answer": route.answer,
        "points": share_preview.route_points(route),
        "sections": [
            {"heading": s.heading, "line": stretch} for s, stretch in _stretches(post) if stretch
        ],
        "admin": is_admin(request),
    }
    if data["admin"]:
        data["csrf"] = get_token(request)
    return data


def _chart_text(post) -> str:
    """With no script: the figures the charts would show, in words."""
    stats = post.stats or {}
    words = summary_line(post) or "The route's figures"
    descent = stats.get("descent_m")
    if descent:
        words += f" · {share_preview.format_climb(descent)} descent"
    return f'<p class="chart-text">{escape(words)}. The charts need JavaScript.</p>'


def post_html(request, post) -> str:
    from .models import RoutePost

    notes = ""
    if post.status == RoutePost.Status.DRAFT:
        notes = f'<p class="note">{escape(DRAFT_NOTE)}</p>'
    elif post.status == RoutePost.Status.UNLISTED:
        notes = f'<p class="note">{escape(UNLISTED_NOTE)}</p>'
    season = ""
    if has_season(post):
        badge = (
            f'<span class="badge">{escape(post.season_label)}</span> '
            if post.season_label and in_season(post, timezone.localdate())
            else ""
        )
        label = f"{post.season_label}: " if post.season_label else ""
        season = f'<p class="season">{badge}{escape(label + season_words(post))}</p>'
    row = "".join(
        f"<div><dt>{escape(name)}</dt><dd>{escape(value)}</dd></div>"
        for name, value in figures(post)
    )
    image = escape(image_path(post))
    map_alt = escape(f"Map of the route, {summary_line(post)}.")
    actions = (
        f'<a class="action primary" href="{escape(open_link(post))}">{_icon("routes")}'
        f"{OPEN_LABEL}</a>"
        f'<a class="action" href="/routes/{escape(post.slug)}/route.gpx" download>'
        f"{_icon('download')}{GPX_LABEL}</a>"
        f'<button type="button" class="action" data-send="garmin" disabled>{_icon("device")}'
        f"{GARMIN_LABEL}</button>"
        f'<button type="button" class="action" data-send="wahoo" disabled>{_icon("device")}'
        f"{WAHOO_LABEL}</button>"
    )
    # The page's script finds each stretch's line by its place among the sections that have one.
    numbers = itertools.count()

    def highlight(s, stretch) -> str:
        minimap = (
            f'<figure class="section-map" data-section="{next(numbers)}">'
            f"<figcaption>{escape(stretch_words(s))}</figcaption></figure>"
            if stretch
            else ""
        )
        return (
            f'<section class="highlight"><h3>{escape(s.heading)}</h3>{minimap}'
            f"{_paragraphs(s.body)}</section>"
        )

    sections = "".join(highlight(s, stretch) for s, stretch in _stretches(post))
    planned = (post.stats or {}).get("planned_on")
    byline = [f"By {post.byline}" if post.byline else ""]
    if post.published_at:
        byline.append(f"Published {_date(timezone.localdate(post.published_at))}")
    if planned:
        byline.append(f"Planned on the map of {_date(date.fromisoformat(planned))}")
    admin = ""
    if is_admin(request):
        admin = (
            '<section class="admin" aria-labelledby="admin-h"><h2 id="admin-h">For admins</h2>'
            "<p>The link picture is the map as it shows above, at the size chat apps use.</p>"
            f'<button type="button" id="make-thumbnail" disabled>{THUMBNAIL_LABEL}</button>'
            '<p class="said" id="thumbnail-said" role="status"></p></section>'
        )
    body = (
        f"<article>{notes}<h1>{escape(post.title)}</h1>{season}"
        f'<dl class="figures">{row}</dl>'
        f'<figure class="post-map" id="post-map"><img src="{image}" alt="{map_alt}" '
        f'width="{THUMBNAIL_WIDTH}" height="{THUMBNAIL_HEIGHT}"></figure>'
        f'<div class="post-actions" role="group" aria-label="Use this route">{actions}</div>'
        f'<p class="said" id="send-said" role="status">'
        f"<noscript>{escape(NO_SCRIPT_SEND)}</noscript></p>"
        '<section id="post-charts" aria-labelledby="charts-h">'
        f'<h2 id="charts-h">Elevation and traffic stress</h2>{_chart_text(post)}</section>'
        f'<section aria-labelledby="about-h"><h2 id="about-h">About this ride</h2>'
        f"{_paragraphs(post.abstract)}</section>"
        + (
            f'<section aria-labelledby="who-h"><h2 id="who-h">Who it\'s for</h2>'
            f"{_paragraphs(post.audience)}</section>"
            if post.audience.strip()
            else ""
        )
        + (
            f'<section aria-labelledby="highlights-h"><h2 id="highlights-h">Highlights</h2>'
            f"{sections}</section>"
            if sections
            else ""
        )
        + f'<p class="byline">{escape(" · ".join(b for b in byline if b))}</p>'
        f"{admin}</article>" + json_script(page_data(request, post), "post-data")
    )
    return _frame(f"{post.title} · {BRAND}", body, head=_tags(request, post), script=True)


# ---- Views ----


def _post(slug: str):
    from .models import RoutePost

    return RoutePost.objects.select_related("route").filter(slug=slug).first()


@require_safe
@ratelimit.rate_limited(ratelimit.SHARE_PREVIEWS)
def index(request):
    """GET /routes/: the published posts."""
    shown, later = listed(timezone.localdate())

    def card(post) -> str:
        today = timezone.localdate()
        badge = (
            f'<span class="badge">{escape(post.season_label)}</span> '
            if post.season_label and in_season(post, today)
            else ""
        )
        return (
            f'<li class="card"><a href="/routes/{escape(post.slug)}">'
            f'<img src="{escape(image_path(post))}" alt="" loading="lazy" '
            f'width="{THUMBNAIL_WIDTH}" height="{THUMBNAIL_HEIGHT}">'
            f"<div><h2>{escape(post.title)}</h2><p>{badge}{escape(summary_line(post))}</p>"
            f"<p>{escape(ride_name(post))}</p></div></a></li>"
        )

    body = f"<h1>{INDEX_TITLE}</h1><p>{escape(INDEX_INTRO)}</p>"
    if shown:
        body += '<ul class="cards">' + "".join(card(p) for p in shown) + "</ul>"
    elif not later:
        body += f"<p>{escape(NONE_YET)}</p>"
    if later:
        body += (
            f"<details><summary>{OUT_OF_SEASON} ({len(later)})</summary>"
            '<ul class="cards">' + "".join(card(p) for p in later) + "</ul></details>"
        )
    head = (
        f'<meta name="description" content="{escape(INDEX_INTRO)}">'
        f'<meta property="og:title" content="{INDEX_TITLE}">'
        f'<meta property="og:site_name" content="{BRAND}">'
        f'<meta property="og:description" content="{escape(INDEX_INTRO)}">'
    )
    return _respond(_frame(f"{INDEX_TITLE} · {BRAND}", body, head=head))


@require_safe
@ratelimit.rate_limited(ratelimit.SHARE_PREVIEWS)
def page(request, slug: str):
    """GET /routes/<slug>: the post."""
    from .models import RoutePost

    post = _post(slug)
    if post is not None and post.status == RoutePost.Status.WITHDRAWN:
        return _plain(410, WITHDRAWN)
    if post is None or not visible(post, request):
        return _plain(404, NOT_FOUND)
    # A draft is an admin's own view: never kept by a cache.
    cache = "no-store" if post.status == RoutePost.Status.DRAFT or is_admin(request) else "no-cache"
    response = _respond(post_html(request, post), cache=cache)
    if post.status != RoutePost.Status.PUBLISHED:
        response["X-Robots-Tag"] = "noindex"
    return response


def gpx_text(post) -> str:
    """The route as a GPX 1.1 track with its credits (frontend/src/lib/gpx.ts writeGpx)."""
    name = escape(post.title, quote=True)
    points = []
    for p in post.route.line:
        ele = p[2] if len(p) > 2 and isinstance(p[2], int | float) else None
        at = f'lat="{float(p[1]):.6f}" lon="{float(p[0]):.6f}"'
        points.append(
            f"      <trkpt {at}><ele>{float(ele):.1f}</ele></trkpt>"
            if ele is not None
            else f"      <trkpt {at}/>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="RouteMaker">\n'
        "  <metadata>\n"
        f"    <name>{name}</name>\n"
        "    <desc>Route data: © OpenStreetMap contributors, ODbL.</desc>\n"
        '    <copyright author="OpenStreetMap contributors">\n'
        "      <license>https://opendatacommons.org/licenses/odbl/1-0/</license>\n"
        "    </copyright>\n"
        '    <link href="https://www.openstreetmap.org/copyright">\n'
        "      <text>© OpenStreetMap contributors</text>\n"
        "    </link>\n"
        "  </metadata>\n"
        "  <trk>\n"
        f"    <name>{name}</name>\n"
        "    <type>cycling</type>\n"
        "    <trkseg>\n" + "\n".join(points) + "\n    </trkseg>\n"
        "  </trk>\n"
        "</gpx>\n"
    )


@require_safe
@ratelimit.rate_limited(ratelimit.SHARE_PREVIEWS)
def gpx(request, slug: str):
    """GET /routes/<slug>/route.gpx: the exact route as a file."""
    post = _post(slug)
    if post is None or not visible(post, request):
        return HttpResponse(status=404)
    response = HttpResponse(gpx_text(post), content_type="application/gpx+xml")
    filename = re.sub(r"[^a-z0-9]+", "-", post.slug.lower()).strip("-") or "route"
    response["Content-Disposition"] = f'attachment; filename="{filename}.gpx"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-cache"
    return response


@require_safe
@ratelimit.rate_limited(ratelimit.SHARE_PREVIEWS)
def thumbnail(request, slug: str):
    """GET /routes/<slug>/thumbnail.jpg: the link picture an admin made."""
    post = _post(slug)
    if post is None or not visible(post, request) or not post.thumbnail:
        return HttpResponse(status=404)
    response = HttpResponse(bytes(post.thumbnail), content_type=THUMBNAIL_TYPE)
    # Public once anyone may see the post; a draft's picture is the admin's alone.
    shown = post.status in ("published", "unlisted")
    response["Cache-Control"] = "public, max-age=3600" if shown else "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """A baseline or progressive JPEG's (width, height), read from its frame header; else None."""
    if not data.startswith(b"\xff\xd8"):
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return width, height
        i += 2 + length
    return None


@require_http_methods(["POST"])
@ratelimit.rate_limited(ratelimit.SHARE_PREVIEWS)
def thumbnail_upload(request, slug: str):
    """POST /routes/<slug>/thumbnail: an instance admin's browser sends the post's map as the
    link picture (a 1200 by 630 JPEG). CSRF-checked like every form."""
    from .audit import record
    from .models import RoutePost

    if not is_admin(request):
        return HttpResponse(status=404)
    post = _post(slug)
    if post is None or post.route_id is None:
        return HttpResponse(status=404)
    data = request.body
    size = jpeg_size(data) if len(data) <= THUMBNAIL_MAX_BYTES else None
    if request.content_type != THUMBNAIL_TYPE or size != (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT):
        record(
            request.user, "route_post.thumbnail", "RoutePost", post.pk, "refused", "not a picture"
        )
        return HttpResponse(
            "Send the map as a 1200 by 630 JPEG.", status=400, content_type="text/plain"
        )
    key = hashlib.sha256(data).hexdigest()[:16]
    RoutePost.objects.filter(pk=post.pk).update(thumbnail=data, thumbnail_key=key)
    record(request.user, "route_post.thumbnail", "RoutePost", post.pk, "allowed")
    response = HttpResponse(status=204)
    response["Cache-Control"] = "no-store"
    return response
