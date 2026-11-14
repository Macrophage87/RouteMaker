"""Google and Apple sign-in beside Discord's, and linking them to one account (Stephen 2026-11-13:
"Yes, and allow account linking"). The providers are never called: `exchange_subject` and Discord's
`exchange_code` are replaced, as tests/test_auth_views.py does for Discord.
"""

from __future__ import annotations

import base64
import json
import time

import pytest
from django.urls import reverse

from core import oidc_login
from core.auth_views import STATE_SESSION_KEY
from core.models import SignInIdentity, User
from core.sign_in_views import PENDING_KEY

db = pytest.mark.django_db
WEBVIEW_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A; wv) AppleWebKit/537.36 Chrome/129.0"
    " Mobile Safari/537.36"
)


@pytest.fixture
def keys(settings):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    settings.DISCORD_CLIENT_ID, settings.DISCORD_CLIENT_SECRET = "d-id", "d-secret"
    settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET = "g-id", "g-secret"
    settings.GOOGLE_REDIRECT_URI = "https://routes.example.org/auth/google/callback"
    settings.APPLE_CLIENT_ID, settings.APPLE_TEAM_ID, settings.APPLE_KEY_ID = (
        "org.example.web",
        "TEAM1",
        "KEY1",
    )
    settings.APPLE_PRIVATE_KEY = pem.decode()
    settings.APPLE_REDIRECT_URI = "https://routes.example.org/auth/apple/callback"
    return settings


def token(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


def provider_login(
    client, monkeypatch, provider: str, subject: str, *, link: bool = False, **headers
):
    start = client.get(f"/auth/{provider}/start" + ("?link=1" if link else ""), **headers)
    assert start.status_code == 302, start.content
    state = client.session[PENDING_KEY]["state"]
    monkeypatch.setattr("core.sign_in_views.exchange_subject", lambda _p, _c: subject)
    return client.get(f"/auth/{provider}/callback", {"state": state, "code": "abc"})


def response_redirects_to_discord(response) -> bool:
    return response.status_code == 302 and response["Location"].startswith("/auth/login")


def discord_login(client, monkeypatch, discord_id: int, *, link: bool = False):
    client.get(reverse("login") + ("?link=1" if link else "?pick=discord"))
    state = client.session[STATE_SESSION_KEY]["state"]
    monkeypatch.setattr(
        "core.auth_views.exchange_code", lambda _code: (discord_id, "identify"), raising=False
    )
    return client.get(reverse("login-callback"), {"state": state, "code": "abc"})


# ---- The protocol half
# ----------------------------------------------------------------------------------


def test_an_id_token_is_read_only_from_its_issuer_for_this_app_and_unexpired() -> None:
    now = time.time()
    good = {"iss": "https://accounts.google.com", "aud": "g-id", "exp": now + 60, "sub": "1081"}
    assert oidc_login.subject_from_id_token(oidc_login.GOOGLE, token(good), "g-id") == "1081"
    for bad in (
        {**good, "iss": "https://evil.example"},
        {**good, "aud": "someone-else"},
        {**good, "exp": now - 1},
        {k: v for k, v in good.items() if k != "sub"},
    ):
        with pytest.raises(oidc_login.ExchangeFailed):
            oidc_login.subject_from_id_token(oidc_login.GOOGLE, token(bad), "g-id")
    with pytest.raises(oidc_login.ExchangeFailed):
        oidc_login.subject_from_id_token(oidc_login.GOOGLE, "not-a-token", "g-id")


def test_the_authorize_urls_ask_for_an_account_number_and_nothing_else() -> None:
    google = oidc_login.authorize_url(oidc_login.GOOGLE, "g-id", "https://x/cb", "st")
    assert "scope=openid&" in google + "&" and "email" not in google and "profile" not in google
    apple = oidc_login.authorize_url(oidc_login.APPLE, "a-id", "https://x/cb", "st")
    assert "scope" not in apple and "response_mode=query" in apple


def test_apples_client_secret_is_an_es256_jwt_its_key_verifies(keys) -> None:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    jwt = oidc_login.apple_client_secret(
        "TEAM1", "org.example.web", "KEY1", keys.APPLE_PRIVATE_KEY, now=1000
    )
    head, body, sig = jwt.split(".")
    pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    assert json.loads(pad(head)) == {"alg": "ES256", "kid": "KEY1"}
    claims = json.loads(pad(body))
    assert (
        claims["iss"] == "TEAM1"
        and claims["sub"] == "org.example.web"
        and claims["aud"] == "https://appleid.apple.com"
    )
    raw = pad(sig)
    public = serialization.load_pem_private_key(keys.APPLE_PRIVATE_KEY.encode(), None).public_key()
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))


# ---- The choice
# ---------------------------------------------------------------------------------------


@db
def test_with_only_discord_set_up_the_choice_goes_straight_to_it(client, settings) -> None:
    settings.DISCORD_CLIENT_ID, settings.DISCORD_CLIENT_SECRET = "d-id", "d-secret"
    response = client.get("/auth/sign-in?next=/delete-account")
    assert response["Location"] == "/auth/login?next=%2Fdelete-account&pick=discord"
    assert client.get("/api/me").json()["sign_in_choices"] == ["discord"]


@db
def test_with_all_three_the_choice_lists_them_but_not_google_in_the_android_app(
    client, keys
) -> None:
    body = client.get("/auth/sign-in").content.decode()
    for name in ("Discord", "Google", "Apple"):
        assert f"Sign in with {name}" in body
    in_app = client.get("/auth/sign-in", HTTP_USER_AGENT=WEBVIEW_UA).content.decode()
    # The app opens other sites in the phone's browser, away from the sign-in in progress.
    assert response_redirects_to_discord(client.get("/auth/sign-in", HTTP_USER_AGENT=WEBVIEW_UA))
    assert "Sign in with Google" not in in_app
    assert client.get("/api/me").json()["sign_in_choices"] == ["discord", "google", "apple"]


@db
def test_the_apps_sign_in_link_opens_the_choice_once_there_is_one(client, keys) -> None:
    response = client.get("/auth/login?next=/x")
    assert response.status_code == 302 and response["Location"] == "/auth/sign-in?next=%2Fx"
    picked = client.get("/auth/login?pick=discord")
    assert picked["Location"].startswith("https://discord.com/oauth2/authorize?")


@db
def test_a_provider_without_keys_is_not_started(client, settings) -> None:
    settings.GOOGLE_CLIENT_ID = ""
    assert client.get("/auth/google/start").status_code == 503


# ---- Signing in
# ---------------------------------------------------------------------------------------


@db
def test_google_signs_in_to_one_account_and_keeps_only_a_keyed_subject(
    client, keys, monkeypatch
) -> None:
    response = provider_login(client, monkeypatch, "google", "108177")
    assert response.status_code == 302 and response["Location"] == "/"
    assert client.get("/api/me").json()["signed_in"] is True
    user = User.objects.get()
    assert user.discord_user_id is None and str(user) == f"account:{user.pk}"
    stored = SignInIdentity.objects.get()
    assert (
        stored.provider == "google"
        and "108177" not in stored.subject_key
        and len(stored.subject_key) == 64
    )
    client.post("/auth/logout")
    provider_login(client, monkeypatch, "google", "108177")
    assert User.objects.count() == 1


@db
def test_a_callback_with_another_state_signs_nobody_in(client, keys, monkeypatch) -> None:
    client.get("/auth/apple/start")
    monkeypatch.setattr("core.sign_in_views.exchange_subject", lambda _p, _c: "x")
    assert client.get("/auth/apple/callback", {"state": "forged", "code": "abc"}).status_code == 400
    assert not User.objects.exists()


@db
def test_a_banned_account_cannot_sign_in_with_a_linked_provider(client, keys, monkeypatch) -> None:
    provider_login(client, monkeypatch, "apple", "000123.abc")
    User.objects.update(is_banned=True)
    client.logout()
    assert provider_login(client, monkeypatch, "apple", "000123.abc").status_code == 403


# ---- Linking
# ------------------------------------------------------------------------------------------


@db
def test_a_discord_account_links_google_and_apple_and_each_reaches_it(
    client, keys, monkeypatch
) -> None:
    discord_login(client, monkeypatch, 4242)
    assert (
        provider_login(client, monkeypatch, "google", "g-sub", link=True)["Location"]
        == "/auth/sign-ins"
    )
    assert (
        provider_login(client, monkeypatch, "apple", "a-sub", link=True)["Location"]
        == "/auth/sign-ins"
    )
    page = client.get("/auth/sign-ins").content.decode()
    assert page.count(": linked") == 3 and page.count(">Unlink<") == 3
    client.post("/auth/logout")
    provider_login(client, monkeypatch, "apple", "a-sub")
    assert User.objects.count() == 1


@db
def test_a_google_account_links_discord(client, keys, monkeypatch) -> None:
    provider_login(client, monkeypatch, "google", "g-sub")
    assert discord_login(client, monkeypatch, 777, link=True)["Location"] == "/auth/sign-ins"
    assert User.objects.get().discord_user_id == 777


@db
def test_a_sign_in_on_another_account_is_not_taken_over(client, keys, monkeypatch) -> None:
    provider_login(client, monkeypatch, "google", "theirs")
    client.post("/auth/logout")
    discord_login(client, monkeypatch, 4242)
    assert provider_login(client, monkeypatch, "google", "theirs", link=True).status_code == 409
    assert discord_login(client, monkeypatch, 4242, link=True).status_code == 302
    other = User.objects.create(discord_user_id=9999)
    assert discord_login(client, monkeypatch, other.discord_user_id, link=True).status_code == 409


@db
def test_unlink_keeps_at_least_one_sign_in(client, keys, monkeypatch) -> None:
    discord_login(client, monkeypatch, 4242)
    page = client.get("/auth/sign-ins").content.decode()
    assert ">Unlink<" not in page and "Link Google" in page
    assert client.post("/auth/unlink", {"provider": "discord"}).status_code == 409
    provider_login(client, monkeypatch, "google", "g-sub", link=True)
    user = User.objects.get()
    # The Android app signs in with Discord alone: the page says so before Discord is unlinked.
    assert "Android app signs in with Discord only" in client.get("/auth/sign-ins").content.decode()
    assert client.post("/auth/unlink", {"provider": "discord"})["Location"] == "/auth/sign-ins"
    user.refresh_from_db()
    assert user.discord_user_id is None
    assert client.post("/auth/unlink", {"provider": "google"}).status_code == 409


@db
def test_signed_out_the_sign_in_methods_page_sends_to_sign_in(client, keys) -> None:
    response = client.get("/auth/sign-ins")
    assert response.status_code == 302 and response["Location"].startswith("/auth/sign-in?next=")


@db
def test_deleting_the_account_deletes_its_sign_ins(client, keys, monkeypatch) -> None:
    from core.account_deletion import delete_account

    provider_login(client, monkeypatch, "google", "g-sub")
    delete_account(User.objects.get())
    assert not SignInIdentity.objects.exists()


@db
def test_apple_signs_in_too(client, keys, monkeypatch) -> None:
    start = client.get("/auth/apple/start")
    assert start["Location"].startswith("https://appleid.apple.com/auth/authorize?")
    assert provider_login(client, monkeypatch, "apple", "000999.x").status_code == 302
    assert SignInIdentity.objects.get().provider == "apple"


@db
def test_signed_in_a_plain_sign_in_does_not_switch_accounts(client, keys, monkeypatch) -> None:
    discord_login(client, monkeypatch, 4242)
    response = client.get("/auth/google/start?next=/x")
    assert response.status_code == 302 and response["Location"] == "/x"
    assert PENDING_KEY not in client.session


@db
def test_a_link_finished_by_another_account_is_refused(client, keys, monkeypatch) -> None:
    discord_login(client, monkeypatch, 4242)
    client.get("/auth/google/start?link=1")
    pending = client.session[PENDING_KEY]
    other = User.objects.create(discord_user_id=5)
    session = client.session
    session["_auth_user_id"] = str(other.pk)
    session.save()
    monkeypatch.setattr("core.sign_in_views.exchange_subject", lambda _p, _c: "g")
    response = client.get("/auth/google/callback", {"state": pending["state"], "code": "c"})
    assert response.status_code in (302, 400)
    assert not SignInIdentity.objects.exists()


@db
def test_unlinking_discord_drops_its_cached_standing(client, keys, monkeypatch) -> None:
    from core.models import CachedMembership, ConfiguredGuild

    discord_login(client, monkeypatch, 4242)
    provider_login(client, monkeypatch, "google", "g-sub", link=True)
    guild = ConfiguredGuild.objects.create(guild_id=1, name="Club")
    from django.utils import timezone

    CachedMembership.objects.create(
        discord_user_id=4242, guild=guild, last_confirmed=timezone.now()
    )
    client.post("/auth/unlink", {"provider": "discord"})
    assert not CachedMembership.objects.exists()


@db
def test_a_sign_in_whose_keys_were_removed_does_not_count_as_the_one_kept(
    client, keys, monkeypatch
) -> None:
    discord_login(client, monkeypatch, 4242)
    provider_login(client, monkeypatch, "google", "g-sub", link=True)
    keys.GOOGLE_CLIENT_SECRET = ""
    assert client.post("/auth/unlink", {"provider": "discord"}).status_code == 409


@db
def test_unlink_needs_the_csrf_token(keys, monkeypatch) -> None:
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    discord_login(client, monkeypatch, 4242)
    provider_login(client, monkeypatch, "google", "g-sub", link=True)
    assert client.post("/auth/unlink", {"provider": "google"}).status_code == 403
    assert SignInIdentity.objects.exists()


@db
def test_a_banned_discord_account_cannot_be_linked(client, keys, monkeypatch) -> None:
    from django.conf import settings

    from core.models import BanTombstone
    from core.revocation import tombstone

    provider_login(client, monkeypatch, "google", "g-sub")
    BanTombstone.objects.create(tombstone=tombstone(31337, settings.TOMBSTONE_KEY))
    assert discord_login(client, monkeypatch, 31337, link=True).status_code == 403
    assert User.objects.get().discord_user_id is None
