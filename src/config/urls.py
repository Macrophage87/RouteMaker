"""URL configuration.

The admin mounts under a configured path rather than /admin/. The path is not
what protects it; the disabled login form, the derived staff resolution and the
per-object checks are. It is absent from the OpenAPI schema and the frontend
bundle so it is not advertised either.
"""

from django.conf import settings
from django.urls import path

from core.admin import site

urlpatterns = [
    path(settings.ADMIN_PATH, site.urls),
]
