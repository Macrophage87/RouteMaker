"""The app's icon where a link is shared (the owner, 2026-10-20: "Is there a way to have the icon
when shared?"; core.share_preview.site_page, the edges' link-fetcher rules).

A link fetcher asking for / gets a page of preview tags naming the app with its card
(frontend/public/icons/share-card.png); a browser gets the app. Every address in the tags comes
from the request's own host, so no host name is in the repository. The fetcher test is the same
pattern in three places (share_preview.FETCHER_RE, the Caddyfile, the beta's nginx map), and on
the beta exactly the preview's paths are outside the password.
"""

from __future__ import annotations

import base64
import re
import struct
import zlib
from pathlib import Path

import pytest
from django.test import Client

from core import preview_icon, share_preview

REPO = Path(__file__).resolve().parents[1]
CADDYFILE = (REPO / "Caddyfile").read_text()
NGINX = (REPO / "deploy" / "beta" / "nginx-routemaker.conf.template").read_text()
CARD = REPO / "frontend" / "public" / "icons" / "share-card.png"

db = pytest.mark.django_db(transaction=True)

FETCHERS = (
    "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
    "facebookexternalhit/1.1 Facebot Twitterbot/1.0",
    "Mozilla/5.0 (Linux; Android 14) GoogleMessages",
    "WhatsApp/2.23.20.0",
    "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
    "TelegramBot (like TwitterBot)",
)
BROWSER = "Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/130.0 Mobile Safari/537.36"


@pytest.fixture(autouse=True)
def _hosts(settings) -> None:
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "beta.example.org", "elsewhere.example"]


def fetch(path: str, ua: str, **extra):
    return Client(HTTP_HOST="beta.example.org").get(
        path, HTTP_USER_AGENT=ua, HTTP_X_FORWARDED_PROTO="https", secure=True, **extra
    )


@db
@pytest.mark.parametrize("ua", FETCHERS)
def test_a_fetcher_gets_the_apps_name_description_and_card(ua: str) -> None:
    response = fetch("/link-preview", ua)
    assert response.status_code == 200
    body = response.content.decode()
    tags = dict(re.findall(r'<meta (?:property|name)="([^"]+)" content="([^"]*)"', body))
    assert tags["og:title"] == tags["twitter:title"] == "RouteMaker"
    assert tags["og:description"] == share_preview.SITE_DESCRIPTION
    assert (
        tags["og:image"] == tags["twitter:image"] == "https://beta.example.org/icons/share-card.png"
    )
    assert tags["og:url"] == "https://beta.example.org/"
    assert (tags["og:image:width"], tags["og:image:height"]) == ("1200", "630")
    assert tags["twitter:card"] == "summary_large_image"
    assert tags["og:image:alt"]
    assert '<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">' in body
    # Googlebot gets this page at /: the favicons Google's favicon service takes.
    assert '<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48">' in body
    assert response["Cache-Control"] == "no-store"
    assert "User-Agent" in response["Vary"]


@db
def test_the_addresses_follow_the_requests_host() -> None:
    body = Client(HTTP_HOST="elsewhere.example").get(
        "/link-preview", HTTP_USER_AGENT=FETCHERS[0], secure=True
    )
    assert b"https://elsewhere.example/icons/share-card.png" in body.content


@db
@pytest.mark.parametrize("extra", [{}, {"HTTP_SEC_FETCH_MODE": "navigate"}])
def test_a_browser_is_sent_to_the_app(extra) -> None:
    ua = BROWSER if not extra else FETCHERS[0]
    response = fetch("/link-preview", ua, **extra)
    assert response.status_code == 302 and response["Location"] == "/"


def test_the_card_is_a_1200_by_630_png_and_the_icon_module_is_whole() -> None:
    head = CARD.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", head[16:24]) == (1200, 630)
    rgba = zlib.decompress(base64.b64decode("".join(preview_icon.DATA)))
    assert len(rgba) == preview_icon.SIZE**2 * 4


def test_a_shared_routes_image_draws_the_icon_beside_the_name() -> None:
    line = [(-77.03 + i * 0.001, 38.9 + i * 0.001) for i in range(30)]
    png = share_preview.render_png(share_preview.drawn_route(line, [], None), "1.0 mi (1.6 km)")
    raw = zlib.decompress(png[png.index(b"IDAT") + 4 : png.index(b"IEND") - 8])
    width = share_preview.WIDTH
    size = preview_icon.SIZE
    x0 = width - 40 - share_preview.text_width(share_preview.BRAND) - 14 - size
    y = share_preview.MAP_H + share_preview.BAND // 2
    row = raw[y * (width * 3 + 1) + 1 : (y + 1) * (width * 3 + 1)]
    blue = [row[x * 3 : x * 3 + 3] for x in range(x0, x0 + size)]
    # the icon's own blue (#0003f8) across most of its middle row
    assert sum(1 for p in blue if p[2] > 200 and p[0] < 60 and p[1] < 60) > size // 3


def _fetcher_patterns() -> tuple[str, str, str]:
    python = share_preview.FETCHER_RE.pattern
    caddy = re.search(r"header_regexp User-Agent `\(\?i\)(.+)`", CADDYFILE).group(1)
    nginx = re.search(r'"~\*\^\[\^\|\]\*\\\|\.\*\((.+)\)" 1;', NGINX).group(1)
    return python, caddy, nginx


def test_the_three_fetcher_patterns_are_the_same() -> None:
    python, caddy, nginx = _fetcher_patterns()
    assert python == caddy == nginx
    assert "googlemessages" in python and "facebookexternalhit" in python


def test_the_edges_hand_a_fetchers_slash_to_the_preview_and_never_a_navigation() -> None:
    block = re.search(r"@link_fetcher \{(.*?)\n\t\}", CADDYFILE, re.S).group(1)
    assert re.search(r"^\s*path /$", block, re.M)
    assert re.search(r"^\s*not header Sec-Fetch-Mode navigate$", block, re.M)
    handle = re.search(r"handle @link_fetcher \{(.*?)\n\t\}", CADDYFILE, re.S).group(1)
    assert "rewrite * /link-preview" in handle and "reverse_proxy api:8000" in handle
    # before the front end's handle, which would otherwise serve index.html
    assert CADDYFILE.index("handle @link_fetcher") < CADDYFILE.index("handle @frontend")

    assert '"~*^navigate\\|" 0;' in NGINX
    assert NGINX.index('"~*^navigate\\|" 0;') < NGINX.index('"~*^[^|]*\\|.*(')
    root = re.search(r"location = / \{(.*?)\n    \}", NGINX, re.S).group(1)
    assert re.search(r"if \(\$rmbeta_link_fetcher\) \{\s*rewrite \^ /link-preview last;", root)


def test_on_the_beta_only_the_previews_paths_skip_the_password() -> None:
    covered = re.compile(r"^/s/[^/]+(/preview\.png)?$")
    assert "location ~ ^/s/[^/]+(/preview\\.png)?$ {" in NGINX
    for path in ("/s/abc123", "/s/abc123/preview.png"):
        assert covered.fullmatch(path)
    for path in ("/s/", "/s/a/b", "/s/a/preview.png/x", "/api/shared-routes", "/link-preview/x"):
        assert not covered.fullmatch(path)
    for loc in (
        "location ~ ^/s/[^/]+(/preview\\.png)?$ {",
        "location = /link-preview {",
        "location ^~ /icons/ {",
        "location ~ ^/favicon\\.(svg|ico)$ {",
    ):
        body = NGINX[NGINX.index(loc) :].split("\n    }", 1)[0]
        assert "auth_basic off;" in body, loc
    for loc in ("location ~ ^/s/", "location = /link-preview {"):
        body = NGINX[NGINX.index(loc) :].split("\n    }", 1)[0]
        assert "proxy_pass http://rmbeta_api;" in body
        assert "proxy_set_header Host $host;" in body
        assert "proxy_set_header X-Forwarded-Proto $scheme;" in body


def test_no_host_name_is_written_into_the_preview() -> None:
    source = (REPO / "src" / "core" / "share_preview.py").read_text()
    assert "routemakerdc" not in source.lower()
    assert not re.search(r"https?://[a-z]", share_preview.SITE_CARD + share_preview.ICON_LINKS)


def test_the_favicon_ico_is_the_favicon_at_16_32_and_48_px() -> None:
    """scripts/make_app_icons.py's PNG frames, which Google's favicon service and old browsers
    read; frontend/index.html links it beside the SVG."""
    data = (REPO / "frontend" / "public" / "favicon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, 3)
    sizes = []
    for n in range(count):
        width, height, _, _, _, _, length, offset = struct.unpack(
            "<BBBBHHII", data[6 + 16 * n : 22 + 16 * n]
        )
        frame = data[offset : offset + length]
        assert frame[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", frame[16:24]) == (width, height)
        sizes.append(width)
    assert sizes == [16, 32, 48]
    index = (REPO / "frontend" / "index.html").read_text()
    assert '<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48" />' in index
