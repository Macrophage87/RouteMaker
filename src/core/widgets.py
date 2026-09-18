"""The admin's map widget, with no request that leaves this deployment.

GeoDjango's default is `OSMWidget`, and what it renders is two problems at
once. Its `Media` names `https://cdn.jsdelivr.net/npm/ol@v7.2.2/dist/ol.js`
and the matching stylesheet - a third party executing script in an
instance admin's authenticated admin session, with no subresource integrity and
no content-security-policy behind it - and its template emits
`new ol.source.OSM()`, which is `tile.openstreetmap.org`. PLAN.md:15 ends with
"Do not use the public OpenStreetMap tile servers", and PLAN.md:52 names this
very widget as one "configured against the self-hosted basemap rather than its
default, which would otherwise call the public OpenStreetMap tile servers this
plan rules out".

So two changes, and they are separable on purpose.

The library is vendored. `src/core/static/core/ol/` holds the OpenLayers build
the Django version in use pins, taken from the project's own GitHub release and
recorded in the `SOURCE` file beside it; `collectstatic` lands it in the same
volume Caddy serves as the rest of the admin's assets. Nothing about that
depends on the basemap question - it is simply where the script comes from.

The basemap is the honest part. Phase 1 has no self-hosted basemap: the PMTiles
extract and the renderer are unbuilt. The widget therefore draws the geometry
over a plain background by default and requests no tiles at all, which is enough
to edit a jurisdiction polygon - the draw and modify controls are OpenLayers'
own and need no imagery under them. A deployment that does have tiles, whether
its own renderer or an operator-chosen server, sets `ADMIN_BASEMAP_TILE_URL` and
gets an XYZ layer under the polygon. There is no default value, and the empty
setting is not a degraded mode to be fixed later by pointing it somewhere
public: it is the shipped configuration.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.gis.forms.widgets import OpenLayersWidget
from django.utils.safestring import SafeString, mark_safe

#: Vendored, from `core/static/core/ol/`. The version is not repeated here as a
#: string: `SOURCE` records it, and what actually has to agree is this directory
#: and whatever `OpenLayersWidget` expects, which is asserted in
#: tests/test_admin_map_widget.py rather than restated.
OL_JS = "core/ol/ol.js"
OL_CSS = "core/ol/ol.css"

# What `json.dumps` leaves alone and a `<script>` block does not. The tile URL
# is an operator's setting rather than user input, but a value interpolated into
# script is escaped where it is interpolated or it is escaped nowhere; these are
# the same five characters `django.utils.html.json_script` neutralises.
_SCRIPT_ESCAPES = {
    ord(">"): "\\u003E",
    ord("<"): "\\u003C",
    ord("&"): "\\u0026",
    0x2028: "\\u2028",
    0x2029: "\\u2029",
}


def js_string_literal(value: str) -> SafeString:
    """`value` as a JavaScript string literal, safe inside a `<script>` block.

    Marked safe because the escaping here is stricter than the template
    engine's: autoescaping would turn the quotes `json.dumps` emits into
    `&quot;` and produce a syntax error, so the alternative to doing it here is
    `|safe` on an unescaped value.
    """
    return mark_safe(json.dumps(value).translate(_SCRIPT_ESCAPES))


def basemap_tile_url() -> str:
    """The configured XYZ tile template, or the empty string.

    Read per render rather than captured at import, so `override_settings` in a
    test and a restart-free settings change behave the same way.
    """
    return (getattr(settings, "ADMIN_BASEMAP_TILE_URL", "") or "").strip()


class SelfHostedOpenLayersWidget(OpenLayersWidget):
    """`OpenLayersWidget` with the CDN and the OSM source taken out.

    Extends `OpenLayersWidget` rather than `OSMWidget` because `OSMWidget` is
    the OSM tile source: its whole contribution over its parent is a template
    block that reads `new ol.source.OSM()` and three default-centre attributes.

    `extend = False` on `Media` is the load-bearing line. Django's
    `MediaDefiningClass` *merges* a subclass's `Media` into its parents' by
    default, so a subclass that simply declares the vendored files would ship
    them **alongside** the two jsdelivr URLs it is replacing, and the admin page
    would still fetch and execute a third party's script.
    """

    template_name = "gis/routemaker_openlayers.html"

    class Media:
        # Not a merge. See the class docstring.
        extend = False
        css = {"all": (OL_CSS, "gis/css/ol3.css")}
        js = (OL_JS, "gis/js/OLMapWidget.js")

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        # `BaseGeometryWidget.get_context` merges its own names into the *top*
        # level of the context rather than under "widget", and the template
        # reads `{{ id }}` and `{{ name }}` from there, so these go beside them.
        url = basemap_tile_url()
        context["basemap_tile_url"] = url
        context["basemap_tile_url_js"] = js_string_literal(url) if url else ""
        return context


__all__ = ["SelfHostedOpenLayersWidget", "basemap_tile_url", "js_string_literal"]
