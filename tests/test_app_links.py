"""Android App Links (core.app_links): GET /.well-known/assetlinks.json names the store app and the
key Play signs it with, from the environment, so a tapped link to the site opens the phone app.
"""

from __future__ import annotations

import pytest
from django.test import override_settings
from test_accounts import addr

db = pytest.mark.django_db(transaction=True)
PATH = "/.well-known/assetlinks.json"
PRINT = ":".join(["AB"] * 32)


@db
def test_it_names_the_app_and_its_signing_keys(client) -> None:
    other = ":".join(["0c"] * 32)
    both = f"{PRINT}, {other}"
    with override_settings(ANDROID_APP_ID="org.example.app", ANDROID_CERT_SHA256=both):
        r = client.get(PATH, **addr())
    assert r.status_code == 200
    assert r["Content-Type"] == "application/json"
    assert r.json() == [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "org.example.app",
                # Upper case, as Android compares them.
                "sha256_cert_fingerprints": [PRINT, other.upper()],
            },
        }
    ]
    # Public, and the same for everyone.
    assert "public" in r["Cache-Control"]
    assert "Set-Cookie" not in r


@db
@pytest.mark.parametrize(
    ("app_id", "prints"),
    [
        ("", PRINT),
        ("org.example.app", ""),
        # Not a SHA-256 fingerprint (a SHA-1 one, a typo): no file rather than one Android refuses.
        ("org.example.app", ":".join(["AB"] * 20)),
        ("org.example.app", PRINT + "Z"),
    ],
)
def test_without_a_whole_setting_there_is_no_file(client, app_id, prints) -> None:
    with override_settings(ANDROID_APP_ID=app_id, ANDROID_CERT_SHA256=prints):
        assert client.get(PATH, **addr()).status_code == 404


@db
def test_it_is_read_only(client) -> None:
    with override_settings(ANDROID_APP_ID="org.example.app", ANDROID_CERT_SHA256=PRINT):
        assert client.post(PATH, **addr()).status_code == 405
