"""Featured routes posts (core.route_posts; the owner, 2026-10-19 and 2026-10-24: "each blog post as
a shareable website where the seen thumbnail is the map").

A post is written in the admin by an instance admin, from one of their saved routes, which is
copied then (owned by no account, kept permanently, no weight). Its page has, in this order, the
title, the row of figures, the map, the four buttons, the elevation and stress charts, the
description, who it is for and the highlighted sections; its link preview's picture is the map an
admin's browser sent, else the route's line drawing. Drafts are admins' only, withdrawn posts say
so, and seasonal posts lead the list in season and wait in a fold out of it.
"""

from __future__ import annotations

import importlib
import json
import re
import struct
from datetime import date
from decimal import Decimal
from itertools import count
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from core import route_posts
from core.models import (
    AuditLogEntry,
    MyGo,
    RoutePost,
    RoutePostSection,
    SavedRoute,
    Session,
    SharedRoute,
    User,
)

REPO = Path(__file__).resolve().parents[1]
db = pytest.mark.django_db(transaction=True)
_ids = count(98000)

START = (-77.0365, 38.8977)
LINE = [[START[0] + i * 0.0004, START[1] + i * 0.0003, 10.0 + i] for i in range(60)]
ANSWER = {
    "geometry": {"type": "LineString", "coordinates": [p[:2] for p in LINE]},
    "distance_m": 3218.7,
    "duration_s": 840.0,
    "climb_m": 59.0,
    "descent_m": 0.0,
    "preset": "group-ride",
    "stress_m": {"1": 2000.0, "2": 1218.7},
    "dials": {"stress": 50, "hills": 0, "system_weight_kg": 92.0},
    "effort_m": 3400.0,
    "candidates": [{"distance_m": 1}],
}
INPUTS = {
    "hash": f"#p={START[0]},{START[1]};{LINE[-1][0]},{LINE[-1][1]}&preset=group-ride",
    "points": [list(START), LINE[-1][:2]],
    "preset": "group-ride",
    "dials": {"stress": 50},
}


def make_user(**fields) -> User:
    return User.objects.create(discord_user_id=next(_ids), **fields)


def signed_in(user: User) -> Client:
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    now = timezone.now()
    Session.objects.create(
        session_key=client.session.session_key,
        user=user,
        issued_epoch=user.session_epoch,
        created_at=now,
        last_seen_at=now,
    )
    return client


def saved_route(user: User, **changes) -> SavedRoute:
    fields = {
        "name": "Mall loop",
        "source": "plan",
        "line": LINE,
        "distance_m": 3218.7,
        "inputs": INPUTS,
        "answer": ANSWER,
    }
    return SavedRoute.objects.create(user=user, **{**fields, **changes})


def make_post(author: User | None = None, **changes) -> RoutePost:
    author = author or make_user(is_instance_admin=True)
    fields = {
        "slug": "mall-loop",
        "title": "A loop round the Mall",
        "abstract": "Flat and calm.\n\nGood in the morning.",
        "audience": "New riders & families.",
        "status": RoutePost.Status.PUBLISHED,
        "author": author,
        "published_at": timezone.now(),
    }
    post = RoutePost(**{**fields, **changes})
    route_posts.freeze(post, saved_route(author))
    post.save()
    return post


# ---- Seasons ----


def season(start: str, end: str) -> RoutePost:
    return RoutePost(season_start=start, season_end=end)


def test_a_season_window_and_one_that_wraps_past_new_year() -> None:
    blossoms = season("03-20", "04-15")
    assert route_posts.in_season(blossoms, date(2027, 4, 1))
    assert not route_posts.in_season(blossoms, date(2027, 4, 16))
    lights = season("12-01", "01-06")
    assert route_posts.in_season(lights, date(2026, 12, 25))
    assert route_posts.in_season(lights, date(2027, 1, 6))
    assert not route_posts.in_season(lights, date(2027, 2, 1))
    assert route_posts.in_season(season("", ""), date(2027, 1, 1)) is None
    assert route_posts.season_words(blossoms) == "Best 20 Mar to 15 Apr"


@pytest.mark.parametrize("value", ["3-20", "13-01", "02-30", "aa-bb", ""])
def test_a_season_day_is_a_real_month_and_day(value: str) -> None:
    assert route_posts.season_day(value) is None
    assert route_posts.season_day("02-29") == (2, 29)


# ---- Picking the route ----


@db
def test_the_route_is_copied_owned_by_no_one_kept_for_good_and_without_weight() -> None:
    post = make_post()
    row = post.route
    assert row.owner_id is None and row.keep == "forever" and row.preview_image
    assert row.line == LINE and row.inputs == INPUTS
    assert row.answer["dials"]["system_weight_kg"] is None and row.answer["effort_m"] is None
    assert row.answer["candidates"] is None
    assert post.stats["distance_m"] == 3218.7 and post.stats["preset"] == "group-ride"
    assert (post.start_lon, post.start_lat) == (LINE[0][0], LINE[0][1])


@db
def test_a_route_with_no_planned_answer_or_from_home_is_refused() -> None:
    author = make_user(is_instance_admin=True)
    assert "Plan this route" in route_posts.route_problem(saved_route(author, answer=None), author)
    assert route_posts.route_problem(saved_route(author), author) is None
    MyGo.objects.create(user=author, home_lat=START[1], home_lon=START[0])
    assert "Home" in route_posts.route_problem(saved_route(author), author)


# ---- The page ----


@db
def test_the_page_is_laid_out_as_the_owner_asked() -> None:
    post = make_post()
    RoutePostSection.objects.create(post=post, position=2, heading="Coffee", body="At the end.")
    RoutePostSection.objects.create(post=post, position=1, heading="The Mall", body="Wide paths.")
    response = Client().get("/routes/mall-loop")
    assert response.status_code == 200
    body = response.content.decode()
    order = [
        "<h1>A loop round the Mall</h1>",
        'class="figures"',
        'id="post-map"',
        route_posts.OPEN_LABEL,
        route_posts.GPX_LABEL,
        route_posts.GARMIN_LABEL,
        route_posts.WAHOO_LABEL,
        'id="post-charts"',
        "About this ride",
        "Who it's for",
        "The Mall",
        "Coffee",
    ]
    places = [body.index(part) for part in order]
    assert places == sorted(places)
    assert "<p>Flat and calm.</p><p>Good in the morning.</p>" in body
    assert "New riders &amp; families." in body
    figures = dict(re.findall(r"<dt>([^<]+)</dt><dd>([^<]+)</dd>", body))
    assert figures == {
        "Distance": "2.0 mi (3.2 km)",
        "Climb": "194 ft (59 m)",
        "Descent": "0 ft (0 m)",
        "Riding time": "14 min",
        "Ride type": "Group Ride",
    }
    assert f'href="/s/{post.route_id}#p=' in body and f"&amp;route={post.route_id}" in body
    assert 'href="/routes/mall-loop/route.gpx" download' in body
    assert '<script type="module" src="/post.js"></script>' in body
    assert response["Content-Security-Policy"].startswith("default-src 'self'; script-src 'self'")
    assert 'system_weight_kg": 92' not in body


def test_a_sections_stretch_is_cut_from_the_line_at_its_miles_on_the_routes_own_distance() -> None:
    # 2.0 mi of route over a line of 59 equal steps: mile 0.5 to 1.0 is the line's second quarter.
    stretch = route_posts.section_line(LINE, 2 * 1609.344, 0.5, 1.0)
    assert stretch[0] == pytest.approx([LINE[0][0] + 59 * 0.0004 / 4, LINE[0][1] + 59 * 0.0003 / 4])
    assert stretch[-1] == pytest.approx(
        [LINE[0][0] + 59 * 0.0004 / 2, LINE[0][1] + 59 * 0.0003 / 2]
    )
    assert all(len(p) == 2 for p in stretch) and len(stretch) > 10
    # Past the end it stops at the finish; wholly past it, or backwards, there is none.
    assert route_posts.section_line(LINE, 2 * 1609.344, 1.5, 9.0)[-1] == pytest.approx(LINE[-1][:2])
    assert route_posts.section_line(LINE, 2 * 1609.344, 3.0, 4.0) == []
    assert route_posts.section_line(LINE, 2 * 1609.344, 1.0, 0.5) == []
    assert route_posts.section_line(LINE, 2 * 1609.344, None, None) == []


@db
def test_a_section_with_a_stretch_has_a_small_map_of_it_and_says_where_it_is() -> None:
    post = make_post()
    for position, (heading, start, end) in enumerate(
        [
            ("First", "0.5", "1.0"),
            ("No map", None, None),
            ("Off the end", "3", "4"),
            ("Last", "1.5", "9"),
        ]
    ):
        RoutePostSection.objects.create(
            post=post,
            position=position,
            heading=heading,
            body="Wide paths.",
            start_mi=start and Decimal(start),
            end_mi=end and Decimal(end),
        )
    body = Client().get("/routes/mall-loop").content.decode()
    assert body.count('class="section-map"') == 2
    assert (
        '<h3>First</h3><figure class="section-map" data-section="0">'
        "<figcaption>Mile 0.5 to 1.0 (km 0.8 to 1.6)</figcaption></figure><p>Wide paths.</p>"
    ) in body
    # A stretch past the finish is said, as it is drawn, to end there.
    assert (
        '<h3>Last</h3><figure class="section-map" data-section="1">'
        "<figcaption>Mile 1.5 to 2.0 (km 2.4 to 3.2)</figcaption></figure>"
    ) in body
    assert "<h3>No map</h3><p>" in body and "<h3>Off the end</h3><p>" in body
    data = json.loads(re.search(r'id="post-data"[^>]*>(.*?)</script>', body).group(1))
    lines = data["sections"]
    assert len(lines) == 2
    assert lines[0][0] == pytest.approx(route_posts.section_line(LINE, 3218.7, 0.5, 1.0)[0])
    assert lines[1][-1] == pytest.approx(LINE[-1][:2])
    with pytest.raises(ValidationError):
        RoutePostSection(post=post, heading="Half", start_mi=Decimal("1")).full_clean()
    with pytest.raises(ValidationError):
        RoutePostSection(
            post=post, heading="Back", start_mi=Decimal("2"), end_mi=Decimal("1")
        ).full_clean()


@db
def test_the_link_preview_is_the_map_once_an_admin_made_it() -> None:
    post = make_post()
    tags = dict(
        re.findall(
            r'<meta (?:property|name)="([^"]+)" content="([^"]*)"',
            Client().get("/routes/mall-loop", secure=True).content.decode(),
        )
    )
    assert tags["og:title"] == "A loop round the Mall"
    assert tags["og:image"].endswith(f"/s/{post.route_id}/preview.png")
    assert tags["twitter:card"] == "summary_large_image"
    post.thumbnail, post.thumbnail_key = jpeg(1200, 630), "abc123"
    post.save()
    body = Client().get("/routes/mall-loop").content.decode()
    assert 'og:image" content="http://testserver/routes/mall-loop/thumbnail.jpg?v=abc123"' in body
    assert Client().get("/routes/mall-loop/thumbnail.jpg")["Content-Type"] == "image/jpeg"


@db
def test_drafts_are_for_admins_withdrawn_posts_say_so_and_unlisted_ones_are_not_indexed() -> None:
    admin = make_user(is_instance_admin=True)
    post = make_post(admin, status=RoutePost.Status.DRAFT)
    assert Client().get("/routes/mall-loop").status_code == 404
    assert Client().get("/routes/mall-loop/route.gpx").status_code == 404
    page = signed_in(admin).get("/routes/mall-loop")
    assert page.status_code == 200 and route_posts.DRAFT_NOTE.encode() in page.content
    assert route_posts.THUMBNAIL_LABEL.encode() in page.content
    assert page["Cache-Control"] == "no-store"
    rider = signed_in(make_user()).get("/routes/mall-loop")
    assert rider.status_code == 404
    post.status = RoutePost.Status.UNLISTED
    post.save()
    page = Client().get("/routes/mall-loop")
    assert page.status_code == 200 and page["X-Robots-Tag"] == "noindex"
    assert route_posts.THUMBNAIL_LABEL.encode() not in page.content
    post.status = RoutePost.Status.WITHDRAWN
    post.save()
    page = Client().get("/routes/mall-loop")
    assert page.status_code == 410 and route_posts.WITHDRAWN.encode() in page.content


@db
def test_the_gpx_is_the_exact_line_with_its_credits() -> None:
    make_post()
    response = Client().get("/routes/mall-loop/route.gpx")
    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="mall-loop.gpx"'
    text = response.content.decode()
    assert text.count("<trkpt ") == len(LINE)
    assert f'<trkpt lat="{LINE[0][1]:.6f}" lon="{LINE[0][0]:.6f}"><ele>10.0</ele></trkpt>' in text
    assert '<copyright author="OpenStreetMap contributors">' in text
    from defusedxml import ElementTree

    ElementTree.fromstring(text.encode())


# ---- The link picture ----


def jpeg(width: int, height: int) -> bytes:
    """The smallest frame header a JPEG reader takes the size from."""
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0\x00\x04ab" + sof + b"\xff\xd9"


@db
def test_only_an_admin_with_the_csrf_token_sends_the_link_picture() -> None:
    admin = make_user(is_instance_admin=True)
    post = make_post(admin)
    picture = jpeg(1200, 630)
    path = "/routes/mall-loop/thumbnail"
    rider = signed_in(make_user())
    rider_token = "a" * 32
    rider.cookies["csrftoken"] = rider_token
    refused = rider.post(path, picture, content_type="image/jpeg", HTTP_X_CSRFTOKEN=rider_token)
    assert refused.status_code == 404
    client = signed_in(admin)
    assert client.post(path, picture, content_type="image/jpeg").status_code == 403
    client.get("/routes/mall-loop")
    token = client.cookies["csrftoken"].value
    send = lambda body, kind="image/jpeg": client.post(  # noqa: E731
        path, body, content_type=kind, HTTP_X_CSRFTOKEN=token
    )
    assert send(jpeg(800, 600)).status_code == 400
    assert send(picture, "image/png").status_code == 400
    assert send(b"not a picture").status_code == 400
    assert send(picture).status_code == 204
    post.refresh_from_db()
    assert bytes(post.thumbnail) == picture and len(post.thumbnail_key) == 16
    rows = AuditLogEntry.objects.filter(action="route_post.thumbnail")
    assert {r.outcome for r in rows} == {"refused", "allowed"}


def test_a_jpegs_size_is_read_from_its_frame_header() -> None:
    assert route_posts.jpeg_size(jpeg(1200, 630)) == (1200, 630)
    assert route_posts.jpeg_size(b"\x89PNG\r\n") is None


# ---- The list ----


@db
def test_the_list_puts_posts_in_season_first_and_the_rest_in_a_fold(monkeypatch) -> None:
    author = make_user(is_instance_admin=True)
    make_post(author, slug="all-year", sort_weight=5)
    make_post(
        author,
        slug="blossoms",
        season_label="Cherry blossoms",
        season_start="03-20",
        season_end="04-15",
    )
    make_post(
        author,
        slug="lights",
        season_label="Holiday lights",
        season_start="12-01",
        season_end="01-06",
    )
    make_post(author, slug="hidden", status=RoutePost.Status.UNLISTED)
    monkeypatch.setattr(timezone, "localdate", lambda *a: date(2027, 4, 1))
    body = Client().get("/routes/").content.decode()
    fold = body.index(route_posts.OUT_OF_SEASON)
    assert body.index("/routes/blossoms") < body.index("/routes/all-year") < fold
    assert body.index("/routes/lights") > fold
    assert "/routes/hidden" not in body
    assert '<span class="badge">Cherry blossoms</span>' in body


@db
def test_an_empty_list_says_so() -> None:
    assert route_posts.NONE_YET.encode() in Client().get("/routes/").content


# ---- The admin ----


@db
def test_an_instance_admin_writes_a_post_from_their_saved_route_in_the_admin() -> None:
    admin = make_user(is_instance_admin=True)
    saved = saved_route(admin)
    other = saved_route(make_user())
    client = signed_in(admin)
    url = f"/{settings.ADMIN_PATH}core/routepost/add/"
    page = client.get(url)
    assert page.status_code == 200
    token = client.cookies["csrftoken"].value
    fields = {
        "csrfmiddlewaretoken": token,
        "title": "Mall loop",
        "slug": "mall-loop",
        "status": "published",
        "abstract": "Flat.",
        "audience": "",
        "byline": "RouteMaker",
        "season_label": "",
        "season_start": "03-20",
        "season_end": "",
        "sort_weight": "0",
        "sections-TOTAL_FORMS": "1",
        "sections-INITIAL_FORMS": "0",
        "sections-MIN_NUM_FORMS": "0",
        "sections-MAX_NUM_FORMS": "1000",
        "sections-0-position": "1",
        "sections-0-heading": "The Mall",
        "sections-0-body": "Wide paths.",
    }
    refused = client.post(url, {**fields, "saved_route": str(other.pk)})
    assert refused.status_code == 200 and not RoutePost.objects.exists()
    refused = client.post(url, {**fields, "saved_route": str(saved.pk)})
    assert b"Give both days, or neither." in refused.content
    done = client.post(url, {**fields, "saved_route": str(saved.pk), "season_start": ""})
    assert done.status_code == 302
    post = RoutePost.objects.get()
    assert post.author == admin and post.route.line == LINE and post.published_at
    assert post.sections.get().heading == "The Mall"
    assert Client().get("/routes/mall-loop").status_code == 200
    # Another admin edits it: their list lacks the author's saved route, and the post keeps it.
    second = signed_in(make_user(is_instance_admin=True))
    shown = second.get(f"/{settings.ADMIN_PATH}core/routepost/{post.pk}/change/")
    assert shown.status_code == 200, shown.content[:300]
    edit = {
        **fields,
        "csrfmiddlewaretoken": second.cookies["csrftoken"].value,
        "season_start": "",
        "title": "Mall loop, fixed",
        "saved_route": "",
        "sections-TOTAL_FORMS": "0",
    }
    kept_route = post.route_id
    assert (
        second.post(f"/{settings.ADMIN_PATH}core/routepost/{post.pk}/change/", edit).status_code
        == 302
    )
    post.refresh_from_db()
    assert post.title == "Mall loop, fixed" and post.route_id == kept_route
    assert post.saved_route_id == saved.pk
    # A section's stretch must start on the route, or it would get no map.
    past = {
        **edit,
        "sections-TOTAL_FORMS": "1",
        "sections-0-start_mi": "5",
        "sections-0-end_mi": "6",
    }
    refused = second.post(f"/{settings.ADMIN_PATH}core/routepost/{post.pk}/change/", past)
    assert refused.status_code == 200 and b"The route is 2.0 mi long." in refused.content


@db
def test_a_new_route_drops_the_old_picture_and_no_weight_comes_with_the_plan() -> None:
    author = make_user(is_instance_admin=True)
    post = make_post(author, thumbnail=jpeg(1200, 630), thumbnail_key="abc")
    assert post.thumbnail is None and post.thumbnail_key == ""
    heavy = saved_route(author, inputs={**INPUTS, "dials": {"stress": 50, "systemWeightKg": 90}})
    route_posts.freeze(post, heavy)
    assert post.route.inputs["dials"] == {"stress": 50}


@db
def test_a_drafts_picture_is_never_kept_by_a_shared_cache() -> None:
    admin = make_user(is_instance_admin=True)
    post = make_post(admin, status=RoutePost.Status.DRAFT)
    RoutePost.objects.filter(pk=post.pk).update(thumbnail=jpeg(1200, 630), thumbnail_key="k")
    client = signed_in(admin)
    assert client.get("/routes/mall-loop/thumbnail.jpg")["Cache-Control"] == "private, no-store"
    RoutePost.objects.filter(pk=post.pk).update(status=RoutePost.Status.WITHDRAWN)
    for path in ("/routes/mall-loop/thumbnail.jpg", "/routes/mall-loop/route.gpx"):
        assert Client().get(path).status_code == 404


@db
def test_open_in_routemaker_opens_the_route_kept_before_with_no_plan_link() -> None:
    # The owner, 2026-10-25: "It just opens RouteMaker". An assistant's followed line was kept
    # with no plan link and no file; the app takes neither (frontend/src/lib/sharedRoutes.ts
    # isRoute) and opened empty. The migration mends the posts' routes kept so.
    from django.apps import apps

    post = make_post(status=RoutePost.Status.DRAFT, published_at=None)
    SharedRoute.objects.filter(pk=post.route_id).update(
        source="gpx", inputs={"points": [LINE[0], LINE[-1]], "preset": "trailmaxxing"}, gpx=""
    )
    plain = make_post(slug="mall-loop-2")
    kept = SharedRoute.objects.get(pk=plain.route_id)
    step = importlib.import_module("core.migrations.0047_route_post_openable_routes")
    step.mend(apps, None)
    row = SharedRoute.objects.get(pk=post.route_id)
    ends = ";".join(f"{p[0]:.5f},{p[1]:.5f}" for p in (LINE[0], LINE[-1]))
    assert row.inputs["hash"] == f"p={ends}&preset=trailmaxxing"
    assert row.gpx == route_posts.line_gpx(post.title, LINE)
    # A route that opened already is left as it was.
    again = SharedRoute.objects.get(pk=plain.route_id)
    assert (again.inputs, again.gpx) == (kept.inputs, kept.gpx) and again.gpx == ""


@db
def test_a_rider_cannot_reach_the_posts_admin() -> None:
    client = signed_in(make_user())
    assert client.get(f"/{settings.ADMIN_PATH}core/routepost/").status_code == 404


# ---- What the page relies on ----


def test_the_buttons_icons_are_the_apps() -> None:
    source = (REPO / "frontend" / "src" / "lib" / "iconPaths.ts").read_text()
    for name in ("routes", "download"):
        drawn = re.search(rf'^  "{name}": "(.+)",$', source, re.M).group(1).replace('\\"', '"')
        assert drawn == route_posts.ICONS[name]


def test_the_edges_serve_the_posts_script_and_the_build_writes_it() -> None:
    caddy = (REPO / "Caddyfile").read_text()
    nginx = (REPO / "deploy" / "beta" / "nginx-routemaker.conf.template").read_text()
    vite = (REPO / "frontend" / "vite.config.ts").read_text()
    assert re.search(r"@frontend path [^\n]* /post\.js\n", caddy)
    assert 'header /post.js Cache-Control "no-cache"' in caddy
    assert re.search(r"location = /post\.js \{[^}]*no-cache", nginx)
    assert 'chunk.name === "post" ? "post.js"' in vite
