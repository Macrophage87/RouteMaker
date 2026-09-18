"""The admin map widget makes no request off this deployment.

The finding this file answers was executed rather than reasoned about: an
instance admin opening `core/jurisdiction/add/` loaded
`https://cdn.jsdelivr.net/npm/ol@v7.2.2/dist/ol.js` - a third party's script, in
an authenticated admin session, with no subresource integrity and no
content-security-policy behind it - and the page then emitted
`new ol.source.OSM()`, which is `tile.openstreetmap.org`. PLAN.md:15 ends "Do
not use the public OpenStreetMap tile servers" and PLAN.md:52 names this very
widget as one "configured against the self-hosted basemap rather than its
default, which would otherwise call the public OpenStreetMap tile servers this
plan rules out".

Two halves, asserted separately because they fail separately.

The *host* assertions below are the ones that would have caught it. They do not
grep for `jsdelivr`, or for any other host somebody has thought of: they pull
every `src=`, every `href=`, every CSS `url(` and every absolute URL out of the
rendered body and refuse any of them that names a host other than the one the
request was made to. A new CDN, a font, a tile server, an analytics beacon -
each fails the same way, without this file being edited.

The *widget* assertions are what keeps the fix from being "delete the map".
Dropping `GISModelAdmin` from `JurisdictionAdmin` removes the CDN and the tile
source at once and leaves 2731 tests passing, which is exactly the mutation the
reviewer found surviving - and it also removes the reason PLAN.md:52 chose
Django, which is that jurisdiction polygons "are edited by drawing on a map in
the admin rather than in a second bespoke editor". So the map widget is pinned,
and the polygon is posted through it and read back off the database.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

db = pytest.mark.django_db(transaction=True)

REPO = Path(__file__).resolve().parents[1]
VENDORED = REPO / "src" / "core" / "static" / "core" / "ol"

# The one host a rendered page may name besides its own. These are XML
# namespaces on the inline `<svg>` the admin's icons live in - identifiers, not
# addresses: nothing dereferences them and no request is made for them.
XML_NAMESPACE_HOSTS = frozenset({"www.w3.org"})

# Absolute URLs, wherever they appear - in an attribute, in a stylesheet, in a
# script literal.
ABSOLUTE_URL = re.compile(r"https?://[^\s\"'<>()\\]+")

# `src="..."`, `href='...'` and `url(...)`, including the relative ones, which
# is what makes a protocol-relative `//cdn.example/ol.js` visible: it has no
# scheme, so ABSOLUTE_URL above would never see it.
MARKUP_REFERENCE = re.compile(
    r"""(?:\bsrc\s*=\s*|\bhref\s*=\s*|\burl\()\s*["']?([^"'()\s>]+)""",
    re.IGNORECASE,
)


def foreign_hosts(body: str, own_host: str) -> set[str]:
    """Every host the page names that is neither its own nor an XML namespace."""
    candidates = set(ABSOLUTE_URL.findall(body)) | set(MARKUP_REFERENCE.findall(body))
    hosts = set()
    for candidate in candidates:
        # `//host/path` has no scheme and urlparse needs one to find the netloc.
        parsed = urlparse(candidate if "//" in candidate else f"///{candidate}")
        host = parsed.netloc.rsplit("@", 1)[-1].split(":", 1)[0]
        if host and host != own_host and host not in XML_NAMESPACE_HOSTS:
            hosts.add(host)
    return hosts


def sign_in(client, monkeypatch, user):
    """Sign in over HTTP, through the real Discord flow.

    Not `force_login`: this deployment's sessions exist only once `issue_session`
    has written the `core.Session` row the epoch middleware requires, so a forced
    login is signed straight back out on the next request.
    """
    from django.urls import reverse

    from core.auth_views import STATE_SESSION_KEY

    monkeypatch.setattr(
        "core.auth_views.exchange_code",
        lambda code: (user.discord_user_id, "identify"),
        raising=False,
    )
    client.get(reverse("login"))
    state = client.session[STATE_SESSION_KEY]["state"]
    response = client.get(reverse("login-callback"), {"state": state, "code": "abc"})
    assert response.status_code == 302, "the login itself must work before anything else does"
    return client


SQUARE = "MULTIPOLYGON (((-77.05 38.9, -77.05 38.95, -77.0 38.95, -77.0 38.9, -77.05 38.9)))"


@pytest.fixture
def jurisdiction(db):
    from django.contrib.gis.geos import GEOSGeometry

    from core.models import Jurisdiction

    return Jurisdiction.objects.create(
        layer="state",
        name="Test Jurisdiction",
        state="DC",
        geometry=GEOSGeometry(SQUARE, srid=4326),
    )


@pytest.fixture
def as_instance_admin(client, monkeypatch, db):
    user = get_user_model().objects.create(discord_user_id=9700, is_instance_admin=True)
    return sign_in(client, monkeypatch, user)


def page(client, url: str) -> str:
    response = client.get(url)
    assert response.status_code == 200, f"{url} answered {response.status_code}"
    return response.content.decode()


def add_url() -> str:
    from django.urls import reverse

    return reverse("routemaker_admin:core_jurisdiction_add")


def change_url(obj) -> str:
    from django.urls import reverse

    return reverse("routemaker_admin:core_jurisdiction_change", args=[obj.pk])


# --- The library, and where it comes from ----------------------------------------------


def django_pinned_openlayers_version() -> str:
    """The OpenLayers version `OpenLayersWidget` expects, read off Django.

    Read rather than written down, because the vendored copy is only correct
    while it matches whatever the installed Django's widget JavaScript was built
    against. `MapWidget` is Django's file and uses whatever OpenLayers API that
    release had; pinning our own number here would let a Django upgrade move
    that API out from under a directory nothing was checking.
    """
    from django.contrib.gis.forms.widgets import OpenLayersWidget

    references = list(OpenLayersWidget.Media.js) + list(OpenLayersWidget.Media.css["all"])
    versions = {
        match.group(1)
        for reference in references
        if (match := re.search(r"ol@v?(\d+\.\d+\.\d+)", reference))
    }
    assert len(versions) == 1, f"Django names more than one OpenLayers version: {versions}"
    return versions.pop()


def test_the_vendored_version_is_the_one_django_asks_for() -> None:
    """Anchored to the `Version` block's own first word, not to the file.

    `version in source` was true of prose: the number appears in the release
    URL, in the sentence about jsdelivr and in the "keep this in step" note, so
    a SOURCE whose *declaration* said 8.0.0 while the release URL still said
    7.2.2 passed - which is precisely the state a half-finished upgrade leaves
    the file in, and precisely what this test exists to catch.
    """
    version = django_pinned_openlayers_version()
    source = (VENDORED / "SOURCE").read_text()
    declared = re.search(r"^Version\n[ \t]+(\S+)", source, re.MULTILINE)
    assert declared, "SOURCE has no `Version` block declaring one"
    assert declared.group(1) == version, (
        f"Django 5's OpenLayersWidget is built against OpenLayers {version} and "
        f"core/static/core/ol/SOURCE declares {declared.group(1)}"
    )
    assert f"openlayers/releases/download/v{version}/" in source, (
        "SOURCE must name the release the files were taken from, at that version"
    )


def test_the_source_file_records_the_hash_of_every_file_beside_it() -> None:
    """A vendored dependency with no provenance is a blob. The point of the
    hashes is that the next person can re-download the release and check that
    what is in the tree is what was published, without trusting this commit."""
    source = (VENDORED / "SOURCE").read_text()
    vendored = sorted(p for p in VENDORED.iterdir() if p.name != "SOURCE")
    assert [p.name for p in vendored] == ["LICENSE.md", "ol.css", "ol.js"]
    for path in vendored:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest in source, f"SOURCE does not record the sha256 of {path.name}"


def test_the_vendored_files_are_served_by_the_staticfiles_app() -> None:
    """Which is what makes `collectstatic` land them in the volume Caddy
    serves. A file sitting in the tree that the finders cannot see is a 404 on
    every admin map page."""
    from django.contrib.staticfiles import finders

    from core.widgets import OL_CSS, OL_JS

    for reference in (OL_JS, OL_CSS):
        assert finders.find(reference), f"{reference} is not findable by collectstatic"


def test_the_widgets_media_replaces_djangos_rather_than_extending_it() -> None:
    """`MediaDefiningClass` merges a subclass's `Media` into its parents' unless
    `extend = False`, so a subclass that simply declared the vendored files would
    ship them *alongside* the two jsdelivr URLs and the page would still fetch
    and run a third party's script. This is that one line, asserted."""
    from core.widgets import SelfHostedOpenLayersWidget

    rendered = str(SelfHostedOpenLayersWidget().media)
    assert "/static/core/ol/ol.js" in rendered
    assert "/static/core/ol/ol.css" in rendered
    assert "cdn.jsdelivr.net" not in rendered
    assert not ABSOLUTE_URL.findall(rendered), f"the widget's media names a host: {rendered}"


# --- The rendered page ------------------------------------------------------------------


@db
class TestNeitherAdminMapPageLeavesThisDeployment:
    """Both forms, over the test client, signed in as an instance admin."""

    def urls(self, jurisdiction) -> dict[str, str]:
        return {"add": add_url(), "change": change_url(jurisdiction)}

    @pytest.mark.parametrize("which", ["add", "change"])
    def test_the_body_names_no_host_but_its_own(
        self, as_instance_admin, jurisdiction, which
    ) -> None:
        """The assertion that does not need to know what a CDN is called."""
        body = page(as_instance_admin, self.urls(jurisdiction)[which])
        assert foreign_hosts(body, "testserver") == set()

    @pytest.mark.parametrize("which", ["add", "change"])
    def test_no_public_tile_source_is_emitted(self, as_instance_admin, jurisdiction, which) -> None:
        """`ol.source.OSM` is `tile.openstreetmap.org` with no URL written
        anywhere, which is why the host sweep above cannot see it and this is a
        separate assertion."""
        body = page(as_instance_admin, self.urls(jurisdiction)[which])
        assert "ol.source.OSM" not in body
        assert "openstreetmap" not in body.lower()

    @pytest.mark.parametrize("which", ["add", "change"])
    def test_the_vendored_openlayers_is_what_the_page_loads(
        self, as_instance_admin, jurisdiction, which
    ) -> None:
        """The path the page actually asks for, and the file behind it."""
        from django.contrib.staticfiles import finders

        from core.widgets import OL_JS

        body = page(as_instance_admin, self.urls(jurisdiction)[which])
        expected = f"{settings.STATIC_URL}{OL_JS}"
        assert expected in body, f"the page does not reference {expected}"
        assert "cdn.jsdelivr.net" not in body
        on_disk = finders.find(OL_JS)
        assert on_disk and Path(on_disk).is_file() and Path(on_disk).stat().st_size > 100_000

    @pytest.mark.parametrize("which", ["add", "change"])
    def test_with_no_basemap_configured_there_is_no_tile_source_at_all(
        self, as_instance_admin, jurisdiction, which
    ) -> None:
        """The shipped configuration. Phase 1 has no self-hosted basemap, so the
        widget draws the polygon over a plain background and requests nothing."""
        assert settings.ADMIN_BASEMAP_TILE_URL == "", "this deployment ships no default basemap"
        body = page(as_instance_admin, self.urls(jurisdiction)[which])
        assert "ol.source.XYZ" not in body
        assert "ol.layer.Tile" not in body
        # And the layer is present rather than absent, which is the whole of the
        # empty branch. `var base_layer = null` passes every negative assertion
        # above and is the worst possible value: Django's own OLMapWidget.js
        # builds `new ol.source.OSM()` when `options.base_layer` is falsy, so a
        # page with no layer at all is a page that fetches tile.openstreetmap.org
        # - the one thing PLAN.md:15 rules out - from inside the vendored ol.js.
        assert "var base_layer = new ol.layer.Vector" in body, (
            "the empty branch must build an empty vector layer; a falsy base_layer "
            "makes Django's MapWidget fall back to ol.source.OSM"
        )
        assert "new ol.source.Vector()" in body

    @pytest.mark.parametrize("which", ["add", "change"])
    def test_a_configured_basemap_becomes_one_xyz_source_and_nothing_else(
        self, as_instance_admin, jurisdiction, which, settings
    ) -> None:
        """The operator's escape hatch: their own renderer, or a tile server
        they chose. One layer, from one URL, and still never `ol.source.OSM`.

        `settings` here is pytest-django's fixture, which shadows the module's
        own import of `django.conf.settings` for the body of this test and
        restores the value afterwards.
        """
        url = "https://tiles.example.test/basemap/{z}/{x}/{y}.png"
        settings.ADMIN_BASEMAP_TILE_URL = url

        body = page(as_instance_admin, self.urls(jurisdiction)[which])
        assert "ol.source.XYZ" in body
        assert body.count("ol.source.XYZ") == 1
        assert url in body, "the configured template is not what the page emits"
        assert "ol.source.OSM" not in body
        # The configured host, and nothing that arrived with it.
        assert foreign_hosts(body, "testserver") == {"tiles.example.test"}
        # And it is a JavaScript *string literal*, not a bare token. Without the
        # quotes `json.dumps` puts round it, `{url: https://.../{z}/{x}/{y}.png}`
        # is a syntax error and the widget does not initialise at all.
        assert f'url: "{url}"' in body, "the URL is interpolated into script unquoted"

    @pytest.mark.parametrize("configured", ["   ", "\t", "\n  ", " \t\n "])
    def test_a_whitespace_only_setting_is_not_a_configured_basemap(
        self, as_instance_admin, jurisdiction, settings, configured
    ) -> None:
        """A trailing newline in an env file is not an operator's choice.

        `.env` files pick up spaces and newlines, and `"  "` is truthy. Without
        the `.strip()` in `basemap_tile_url` the widget takes a run of spaces
        for a tile template and emits `new ol.source.XYZ({url: "  "})`, which is
        a layer requesting the admin page's own directory once per tile.
        """
        from core.widgets import basemap_tile_url

        settings.ADMIN_BASEMAP_TILE_URL = configured
        assert basemap_tile_url() == "", "whitespace is not a configured basemap"

        body = page(as_instance_admin, self.urls(jurisdiction)["add"])
        assert "ol.source.XYZ" not in body
        assert "var base_layer = new ol.layer.Vector" in body


# --- The widget is still a map ----------------------------------------------------------


def test_jurisdiction_admin_still_declares_a_map_widget() -> None:
    """The reviewer's surviving mutation was deleting `GISModelAdmin` from the
    class, which takes the CDN and the tile source with it and leaves nothing
    to draw a polygon on. Both halves are pinned: the base that provides
    `formfield_for_dbfield`, and the widget it is told to use."""
    from django.contrib.gis.admin import GISModelAdmin

    from core.admin import JurisdictionAdmin
    from core.widgets import SelfHostedOpenLayersWidget

    assert GISModelAdmin in JurisdictionAdmin.__mro__, (
        "without GISModelAdmin the geometry is a WKT textarea, and PLAN:52's "
        "reason for choosing Django is gone"
    )
    assert JurisdictionAdmin.gis_widget is SelfHostedOpenLayersWidget


@db
def test_the_geometry_field_reaches_the_map_widget_on_the_real_form() -> None:
    """Declared is not the same as used: `gis_widget` is read by
    `GeoModelAdminMixin.formfield_for_dbfield`, so this asks the ModelAdmin for
    the form it would render and looks at what the geometry field got."""
    from core.admin import JurisdictionAdmin, site
    from core.models import Jurisdiction
    from core.widgets import SelfHostedOpenLayersWidget

    class Request:
        GET: dict = {}
        META: dict = {}

        def __init__(self):
            self.user = get_user_model()(discord_user_id=9701, is_instance_admin=True)

    form = JurisdictionAdmin(Jurisdiction, site).get_form(Request())()
    assert isinstance(form.fields["geometry"].widget, SelfHostedOpenLayersWidget)


@db
def test_a_polygon_drawn_on_the_map_still_saves(client, monkeypatch) -> None:
    """The map has to keep editing, not merely keep rendering.

    The widget serializes to GeoJSON in the map's own SRID, which is what the
    browser posts; this posts the same thing the browser would and reads the row
    back, so a widget that rendered but could not round-trip a geometry fails
    here rather than in production.
    """
    from django.contrib.gis.geos import GEOSGeometry

    from core.models import Jurisdiction
    from core.widgets import SelfHostedOpenLayersWidget

    drawn = GEOSGeometry(SQUARE, srid=4326)
    drawn.transform(SelfHostedOpenLayersWidget.map_srid)

    user = get_user_model().objects.create(discord_user_id=9702, is_instance_admin=True)
    signed_in = sign_in(client, monkeypatch, user)
    response = signed_in.post(
        add_url(),
        {"layer": "state", "name": "Drawn By Hand", "state": "VA", "geometry": drawn.json},
    )

    assert response.status_code == 302, (
        response.context["errors"] if getattr(response, "context", None) else response.status_code
    )
    saved = Jurisdiction.objects.get(name="Drawn By Hand")
    assert saved.geometry.srid == 4326
    assert saved.geometry.intersects(GEOSGeometry(SQUARE, srid=4326))


# --- The one value that reaches a <script> block ----------------------------------------


class TestTheTileUrlIsEscapedWhereItIsInterpolated:
    """`js_string_literal` is the only thing between a settings value and a
    `<script>` body, and every part of it survived mutation: replacing the whole
    function with `mark_safe(value)` left the suite green, and so did dropping
    the `<` escape on its own.

    The tile URL is an operator's setting rather than user input, so this is not
    a live cross-site-scripting hole; it is the escaping that keeps it from
    becoming one when a URL arrives from somewhere else, and an escape nothing
    asserts is an escape that gets deleted in a refactor. The five characters
    are the ones `django.utils.html.json_script` neutralises, for the same
    reasons: `<` and `>` end the script element early, `&` is HTML-decoded
    inside some contexts, and U+2028 and U+2029 are JavaScript line terminators
    that end a string literal without a newline anyone can see.
    """

    def literal(self, value: str) -> str:
        from core.widgets import js_string_literal

        return str(js_string_literal(value))

    def test_a_plain_url_is_a_quoted_json_string(self) -> None:
        """The shape, not just the content: `mark_safe(value)` returns the bare
        characters, which the template interpolates into `{url: ...}` as a
        syntax error rather than a string."""
        import json

        url = "https://tiles.example.test/{z}/{x}/{y}.png"
        literal = self.literal(url)
        assert literal == json.dumps(url)
        assert literal.startswith('"') and literal.endswith('"')
        assert json.loads(literal) == url, "the literal must round-trip to the value"

    def test_the_result_is_marked_safe(self) -> None:
        """Because autoescaping would turn the quotes into `&quot;`. The mark is
        load-bearing and is the reason the escaping has to be complete here."""
        from django.utils.safestring import SafeString

        from core.widgets import js_string_literal

        assert isinstance(js_string_literal("https://example.test/"), SafeString)

    @pytest.mark.parametrize(
        ("character", "escaped"),
        [
            ("<", "\\u003C"),
            (">", "\\u003E"),
            ("&", "\\u0026"),
            ("\u2028", "\\u2028"),
            ("\u2029", "\\u2029"),
        ],
    )
    def test_each_character_is_neutralised(self, character: str, escaped: str) -> None:
        literal = self.literal(f"https://tiles.example.test/a{character}b")
        assert character not in literal, f"{character!r} reaches the script body unescaped"
        assert escaped in literal, f"{character!r} is not escaped as {escaped}"

    def test_the_literal_is_ascii_whatever_it_was_handed(self) -> None:
        """Which is the property behind the last two rows of the escape table.

        U+2028 and U+2029 are neutralised today by `json.dumps`'s
        `ensure_ascii=True` rather than by the table - deleting those two rows
        changes no byte, and `core/widgets.py` records that. The assertion that
        can still be made is the one that covers them and every other line
        terminator, byte order mark and bidirectional override at once: whatever
        reaches a `<script>` body from here is ASCII. Passing
        `ensure_ascii=False` fails here even for a character nobody listed.
        """
        literal = self.literal("https://tiles.example.test/\u2028\u2029\ufeff\u202e/{z}.png")
        assert literal.isascii(), f"a non-ASCII character reaches the script body: {literal!r}"

    def test_a_closing_script_tag_cannot_close_the_script(self) -> None:
        """The payload the escaping exists for, end to end through the function.

        `</script>` inside a JavaScript string literal ends the element in every
        HTML parser regardless of the quotes round it, so this is the one case
        where correct JSON is still unsafe markup.
        """
        import json

        payload = "https://tiles.example.test/</script><script>alert(1)</script>/{z}.png"
        literal = self.literal(payload)
        assert "</script>" not in literal
        assert "<" not in literal and ">" not in literal
        assert "\\u003C/script\\u003E" in literal
        assert json.loads(literal) == payload, "neutralised, not mangled"


@db
def test_the_rendered_page_escapes_the_configured_url_rather_than_the_setting(
    as_instance_admin, jurisdiction, settings
) -> None:
    """The template has to use the escaped context value, not the raw one.

    Asserted through the page because that is where the two can come apart:
    `basemap_tile_url` and `basemap_tile_url_js` are both in the context, and
    `{{ basemap_tile_url }}` renders without a syntax error in the ordinary
    case - it would simply be autoescaped, unquoted and broken only for values
    nobody tests with.
    """
    settings.ADMIN_BASEMAP_TILE_URL = "https://tiles.example.test/</script>/{z}/{x}/{y}.png"

    body = page(as_instance_admin, add_url())
    assert "\\u003C/script\\u003E" in body, "the URL is not escaped where it is interpolated"
    assert "tiles.example.test/</script>" not in body
    assert "&quot;" not in body.split("<script>")[-1], "the literal was HTML-escaped instead"
