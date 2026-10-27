"""Android App Links: GET /.well-known/assetlinks.json, so a tapped link to the site opens the app.

Android opens a link to a site in an app only when the site names that app here: its application id
and the SHA-256 fingerprint of the key Play signs it with (mobile/README.md, "Links open in the
app"). Both come from the deployment's environment, so no owner's app id is committed:

- ANDROID_APP_ID: the store app's id (the ROUTEMAKER_APP_ID secret the app is built with).
- ANDROID_CERT_SHA256: the fingerprint from Play Console, Test and release > App integrity > App
  signing key certificate; more than one (the upload key too, for a sideloaded store build)
  separated by commas.

Either unset, the file is a 404 and links open in the browser as before. The answer is the same for
everyone and holds nothing about a rider.
"""

import re

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_safe

# Play Console shows a fingerprint as 32 hex pairs joined by colons.
_FINGERPRINT = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){31}$")
# An Android application id: two or more dot-separated names, each starting with a letter.
_APP_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")


def statements() -> list[dict]:
    """The Digital Asset Links statements, or [] when the app is not configured."""
    app_id = settings.ANDROID_APP_ID
    if app_id and not _APP_ID.match(app_id):
        return []
    prints = [p.strip().upper() for p in settings.ANDROID_CERT_SHA256.split(",") if p.strip()]
    if not app_id or not prints or not all(_FINGERPRINT.match(p) for p in prints):
        return []
    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": app_id,
                "sha256_cert_fingerprints": prints,
            },
        }
    ]


@require_safe
def assetlinks(request):
    """GET or HEAD: the statements Android checks when the app is installed."""
    found = statements()
    if not found:
        raise Http404
    response = JsonResponse(found, safe=False)
    # Android fetches it at install and now and then after; a day is plenty.
    response["Cache-Control"] = "public, max-age=86400"
    return response
