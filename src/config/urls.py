"""URL configuration.

The admin mounts under a configured path rather than /admin/. The path is not
what protects it; the disabled login form, the derived staff resolution and the
per-object checks are. It is absent from the OpenAPI schema and the frontend
bundle so it is not advertised either.

`/healthz` is the one deliberate exception to all of that: a fixed, public,
unauthenticated path, because a container healthcheck runs before any session
exists and pointing it at the admin prefix would publish that prefix to
`compose.yaml`, the process table and the orchestrator's logs. It is safe to
expose because it is worth nothing to find - see `core.health`, which holds the
reasoning for the two-word body and the single query.
"""

from django.conf import settings
from django.urls import path

from core import (
    account_deletion,
    app_links,
    auth_views,
    connector,
    garmin_views,
    health,
    mass_tiles,
    privacy_policy,
    route_posts,
    share_preview,
    stress_tiles,
    wahoo_views,
)
from core.admin import site
from core.api import api

urlpatterns = [
    path(settings.ADMIN_PATH, site.urls),
    path("healthz", health.healthz, name="healthz"),
    path("api/", api.urls),
    path("tiles/stress/<int:z>/<int:x>/<int:y>.pbf", stress_tiles.stress_tile, name="stress-tile"),
    # The Mass Ride map's capacity tiles (OWNER-DECISIONS 415, 417, 418; core.mass_tiles).
    path("tiles/mass/<int:z>/<int:x>/<int:y>.pbf", mass_tiles.mass_tile, name="mass-tile"),
    # A shared route's link and its preview (core.share_preview).
    path("s/<str:route_id>", share_preview.share_page, name="share-page"),
    path("s/<str:route_id>/preview.png", share_preview.share_image, name="share-image"),
    # The app's own address as a link fetcher sees it (the edge sends a fetcher's GET / here).
    path("link-preview", share_preview.site_page, name="link-preview"),
    path("auth/login", auth_views.login_start, name="login"),
    path("auth/callback", auth_views.login_callback, name="login-callback"),
    path("auth/logout", auth_views.logout_view, name="logout"),
    path("auth/logout-everywhere", auth_views.logout_everywhere_view, name="logout-everywhere"),
    # Connecting a rider's Garmin account, for Send to Garmin (core.garmin_views).
    path("auth/garmin/start", garmin_views.connect_start, name="garmin-start"),
    path("auth/garmin/callback", garmin_views.connect_callback, name="garmin-callback"),
    path("garmin/deregistrations", garmin_views.deregistrations, name="garmin-deregistrations"),
    # Connecting a rider's Wahoo account, for Send to Wahoo (core.wahoo_views).
    path("auth/wahoo/start", wahoo_views.connect_start, name="wahoo-start"),
    path("auth/wahoo/callback", wahoo_views.connect_callback, name="wahoo-callback"),
    # The site's own MCP connector and its sign-in (core.connector; v0.10.0).
    path("mcp", connector.mcp_endpoint, name="mcp"),
    path("mcp/gpx/<str:token>", connector.draft_gpx, name="mcp-gpx"),
    path(".well-known/oauth-protected-resource", connector.protected_resource),
    path(".well-known/oauth-protected-resource/mcp", connector.protected_resource),
    path(".well-known/oauth-authorization-server", connector.authorization_server),
    # Android App Links: a tapped link to the site opens the phone app (core.app_links).
    path(".well-known/assetlinks.json", app_links.assetlinks, name="assetlinks"),
    path("oauth/register", connector.register, name="oauth-register"),
    path("oauth/authorize", connector.authorize, name="oauth-authorize"),
    path("oauth/token", connector.token, name="oauth-token"),
    # Deleting an account, from Settings or from the web without the app (core.account_deletion).
    path("delete-account", account_deletion.page, name="delete-account"),
    # The privacy policy, public, for Google Play's listing and Settings (core.privacy_policy).
    path("privacy", privacy_policy.page, name="privacy"),
    # Featured routes: blog-style posts around one exact route (core.route_posts; v0.12.1).
    path("routes/", route_posts.index, name="route-posts"),
    path("routes/<slug:slug>", route_posts.page, name="route-post"),
    path("routes/<slug:slug>/route.gpx", route_posts.gpx, name="route-post-gpx"),
    path("routes/<slug:slug>/thumbnail.jpg", route_posts.thumbnail, name="route-post-thumbnail"),
    path("routes/<slug:slug>/thumbnail", route_posts.thumbnail_upload, name="route-post-picture"),
    path("routes/<slug:slug>/photos", route_posts.photo_upload, name="route-post-photos"),
    path("routes/<slug:slug>/photos/<str:key>.jpg", route_posts.photo, name="route-post-photo"),
]
