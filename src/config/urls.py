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

from core import auth_views, health
from core.admin import site

urlpatterns = [
    path(settings.ADMIN_PATH, site.urls),
    path("healthz", health.healthz, name="healthz"),
    path("auth/login", auth_views.login_start, name="login"),
    path("auth/callback", auth_views.login_callback, name="login-callback"),
    path("auth/logout", auth_views.logout_view, name="logout"),
]
