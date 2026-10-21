"""The privacy policy (core.privacy_policy; Google Play's privacy-policy link): one public page,
GET /privacy, in the delete-account page's frame, linked from it and from Settings > Account.

The page is the same for everyone, names no host, and leads with what matters most.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

import pytest
from test_accounts import addr, signed_in

from core import account_deletion, privacy_policy

db = pytest.mark.django_db(transaction=True)
ROOT = Path(__file__).resolve().parents[1]


def get(client) -> tuple[int, str, object]:
    r = client.get(privacy_policy.PATH, **addr())
    return r.status_code, r.content.decode(), r


@db
class TestPage:
    def test_it_is_public_and_says_what_matters_first(self, client) -> None:
        status, body, r = get(client)
        assert status == 200 and r["Content-Type"].startswith("text/html")
        assert f"<h1>{escape(privacy_policy.TITLE)}</h1>" in body
        # Inverted pyramid: no ads and the deletion link come before the first section.
        first_section = body.index("<h2>")
        assert body.index(escape(privacy_policy.NO_ADS)) < first_section
        assert body.index(f'href="{account_deletion.PATH}"') < first_section

    def test_every_section_is_a_heading_in_order(self, client) -> None:
        _, body, _ = get(client)
        headings = re.findall(r"<h2>([^<]+)</h2>", body)
        assert headings == [escape(h) for h, _ in privacy_policy.SECTIONS]
        needed = ["Your location", "Group and Mass Ride sharing", "If you sign in with Discord",
                  "Shared links", "Suggestions and reports", "Who else is contacted",
                  "Cookies and your device", "Server logs", "How long data is kept",
                  "Deleting your account", "Contact"]  # fmt: skip
        assert [h for h in headings if h in needed] == needed

    def test_it_is_the_same_signed_in(self, client) -> None:
        _, signed_out, _ = get(client)
        mine, _user, _csrf = signed_in()
        status, body, _ = get(mine)
        assert status == 200 and body == signed_out

    def test_only_get(self, client) -> None:
        assert client.post(privacy_policy.PATH, **addr()).status_code in (403, 405)

    def test_it_has_the_deletion_page_s_frame_and_no_link_to_itself(self, client) -> None:
        _, body, _ = get(client)
        assert '<html lang="en">' in body and "<main>" in body
        assert 'name="viewport"' in body and "prefers-color-scheme:dark" in body
        assert f'href="{privacy_policy.PATH}"' not in body
        assert '<a href="/">Back to RouteMaker</a>' in body

    def test_it_names_no_host_and_no_e_mail(self, client) -> None:
        _, body, _ = get(client)
        assert not re.search(r"https?://", body)
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", body)
        source = (ROOT / "src/core/privacy_policy.py").read_text()
        assert not re.search(r"https?://", source)

    def test_the_claims_the_code_backs(self, client) -> None:
        _, body, _ = get(client)
        text = re.sub(r"<[^>]+>", " ", body).replace("&#x27;", "'").replace("&quot;", '"')
        for claim in (
            "never on disk or in a log",  # core.ride_presence
            "2 minutes",  # ride_presence.DOT_TTL_S
            "10 minutes",  # ride_presence.ALERT_TTL_S
            "Discord account number",  # core.models.User: discord_user_id only
            "Riding with RouteMaker",  # the app's foreground-service notification
            "never asks for location all the time",  # no ACCESS_BACKGROUND_LOCATION
            "a year after it was last opened",  # shared_routes.KEEP
            "24 hours",  # signed_out_suggestions: SignedOutSend
            "about 30 hours",  # ratelimit.RETENTION and the sweep
            "the last seven kept",  # procrastinate.BACKUP_KEEP
            "30 days unused, or after 90 days",  # revocation's idle and absolute lifetimes
            "Two cookies",  # the session and CSRF cookies
            privacy_policy.CONTACT,
        ):
            assert escape(claim) in body or claim in text, claim

    def test_the_numbers_are_the_code_s(self) -> None:
        from datetime import timedelta

        from config import procrastinate
        from core import ratelimit, revocation, ride_presence, shared_routes

        assert ride_presence.DOT_TTL_S == 120 and ride_presence.ALERT_TTL_S == 600
        assert ride_presence.GRID_M == 20.0
        assert procrastinate.BACKUP_KEEP == 7
        assert {"app_session", "django_session", "rate_limit_window", "cached_membership"} <= set(
            procrastinate.BACKUP_EXCLUDED_TABLES
        )
        assert revocation.IDLE_SESSION_LIFETIME == timedelta(days=30)
        assert revocation.ABSOLUTE_SESSION_LIFETIME == timedelta(days=90)
        assert ratelimit.RETENTION <= timedelta(hours=30)
        assert shared_routes.KEEP == timedelta(days=365)


class TestLinks:
    def test_the_deletion_page_links_here(self, client, db) -> None:
        body = client.get(account_deletion.PATH, **addr()).content.decode()
        assert f'<a href="{privacy_policy.PATH}">Privacy policy</a>' in body

    def test_settings_links_here(self) -> None:
        sign_in = (ROOT / "frontend/src/lib/signIn.ts").read_text()
        assert f'PRIVACY_PAGE = "{privacy_policy.PATH}"' in sign_in
        sheets = (ROOT / "frontend/src/app/Sheets.tsx").read_text()
        assert "<a href={PRIVACY_PAGE}>Privacy policy</a>" in sheets

    def test_the_url_is_routed(self) -> None:
        from django.urls import resolve

        assert resolve(privacy_policy.PATH).func is privacy_policy.page
