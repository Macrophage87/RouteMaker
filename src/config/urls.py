"""URL configuration.

The admin mounts under a configured path rather than /admin/. The path is not
what protects it; the disabled login form, the derived staff resolution and the
per-object checks are. It is absent from the OpenAPI schema and the frontend
bundle so it is not advertised either.
"""

from django.conf import settings
from django.urls import path

from core import auth_views
from core.admin import site

urlpatterns = [
    path(settings.ADMIN_PATH, site.urls),
    path("auth/login", auth_views.login_start, name="login"),
    path("auth/callback", auth_views.login_callback, name="login-callback"),
    path("auth/logout", auth_views.logout_view, name="logout"),
]
