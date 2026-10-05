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

from core import auth_views, health, mass_tiles, stress_tiles
from core.admin import site
from core.api import api

urlpatterns = [
    path(settings.ADMIN_PATH, site.urls),
    path("healthz", health.healthz, name="healthz"),
    path("api/", api.urls),
    path("tiles/stress/<int:z>/<int:x>/<int:y>.pbf", stress_tiles.stress_tile, name="stress-tile"),
    # The Mass Ride map's capacity tiles (OWNER-DECISIONS 415, 417, 418; core.mass_tiles).
    path("tiles/mass/<int:z>/<int:x>/<int:y>.pbf", mass_tiles.mass_tile, name="mass-tile"),
    path("auth/login", auth_views.login_start, name="login"),
    path("auth/callback", auth_views.login_callback, name="login-callback"),
    path("auth/logout", auth_views.logout_view, name="logout"),
]
