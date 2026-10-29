"""The privacy policy (core.privacy_policy; Google Play's privacy-policy link): one public page,
GET /privacy, in the delete-account page's frame, linked from it and from Settings > About.

The page is the same for everyone, names no host, and leads with what matters most.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

import pytest
from django.test import override_settings
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
        assert body.index(escape(privacy_policy.WHERE_YOU_ARE)) < first_section
        assert body.index(f'<time datetime="{privacy_policy.LAST_UPDATED[0]}">') < first_section
        assert "Last updated: <time" in body

    def test_every_section_is_a_heading_in_order(self, client) -> None:
        _, body, _ = get(client)
        headings = re.findall(r"<h2>([^<]+)</h2>", body)
        assert headings == [escape(h) for h, _ in privacy_policy.SECTIONS]
        needed = ["Your location", "Group and Mass Ride sharing", "If you sign in with Discord",
                  "If you connect Garmin", "If you connect Wahoo", "Shared links",
                  "Suggestions and reports",
                  "Who else is contacted", "Cookies and your device", "Server logs",
                  "Where your data is kept", "How long data is kept", "Deleting your account",
                  "Contact"]  # fmt: skip
        assert [h for h in headings if h in needed] == needed

    def test_it_is_the_same_signed_in(self, client) -> None:
        _, signed_out, _ = get(client)
        mine, _user, _csrf = signed_in()
        status, body, _ = get(mine)
        assert status == 200 and body == signed_out

    def test_only_get_and_head(self, client) -> None:
        assert client.head(privacy_policy.PATH, **addr()).status_code == 200
        assert client.post(privacy_policy.PATH, **addr()).status_code in (403, 405)

    def test_it_has_the_deletion_page_s_frame_and_no_link_to_itself(self, client) -> None:
        _, body, _ = get(client)
        assert '<html lang="en">' in body and "<main>" in body
        assert 'name="viewport"' in body and "prefers-color-scheme:dark" in body
        assert f'href="{privacy_policy.PATH}"' not in body
        assert '<a href="/">Back to RouteMaker</a>' in body

    @override_settings(PRIVACY_CONTACT="")
    def test_it_names_no_host_and_no_e_mail(self, client) -> None:
        _, body, _ = get(client)
        assert not re.search(r"https?://", body)
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", body)
        source = (ROOT / "src/core/privacy_policy.py").read_text()
        assert not re.search(r"https?://", source)

    @override_settings(PRIVACY_CONTACT="privacy@example.org")
    def test_a_configured_e_mail_is_the_contact_and_the_only_one(self, client) -> None:
        _, body, _ = get(client)
        assert '<a href="mailto:privacy@example.org">privacy@example.org</a>' in body
        assert escape(privacy_policy.CONTACT) not in body
        others = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", body)) - {"privacy@example.org"}
        assert not others and not re.search(r"https?://", body)

    @override_settings(PRIVACY_CONTACT="https://example.org/contact")
    def test_a_configured_web_address_is_a_link(self, client) -> None:
        _, body, _ = get(client)
        assert '<a href="https://example.org/contact">https://example.org/contact</a>' in body
        assert re.findall(r"https?://[^\s\"<]+", body) == ["https://example.org/contact"] * 2

    @override_settings(PRIVACY_CONTACT='<script>"x"</script>')
    def test_a_configured_contact_is_escaped(self, client) -> None:
        _, body, _ = get(client)
        assert "<script>" not in body and "&lt;script&gt;" in body

    @override_settings(PRIVACY_HOSTING="")
    def test_unset_hosting_says_the_owner_runs_it(self, client) -> None:
        _, body, _ = get(client)
        hosted = body[body.index("<h2>Where your data is kept</h2>") :]
        hosted = hosted[: hosted.index("<h2>", 4)]
        assert escape(privacy_policy.HOSTING) in hosted
        assert escape(privacy_policy.HOSTING_LEAD) not in body

    @override_settings(PRIVACY_HOSTING="Amazon Web Services (AWS)")
    def test_a_configured_host_is_named(self, client) -> None:
        _, body, _ = get(client)
        named = escape(
            privacy_policy.HOSTING_LEAD + "Amazon Web Services (AWS)" + privacy_policy.HOSTING_TAIL
        )
        assert named in body and escape(privacy_policy.HOSTING) not in body

    @override_settings(PRIVACY_HOSTING='<b onclick="x">Host</b>')
    def test_a_configured_host_is_escaped(self, client) -> None:
        _, body, _ = get(client)
        assert "<b onclick" not in body and "&lt;b onclick=" in body

    def test_garmin_s_requirements_are_answered(self, client) -> None:
        """Garmin's developer program asks the policy to say how Garmin data is used, who stores
        it, that it is not sold, whether AI touches it, and how to delete it or withdraw."""
        _, body, _ = get(client)
        garmin = body[body.index("<h2>If you connect Garmin</h2>") :]
        garmin = garmin[: garmin.index("<h2>", 4)]
        text = re.sub(r"<[^>]+>", " ", garmin).replace("&#x27;", "'").replace("’", "'")
        for claim in (
            "your choice, in Settings",
            "encrypted",
            "only to send the courses you choose",
            "never reads your activities, health data",
            privacy_policy.GARMIN_NO_AI,
            "deletes the token and tells Garmin",
            "Deleting your account does the same",
            "nothing else to see, correct or export",
        ):
            assert claim in text, claim

    def test_wahoo_s_requirements_are_answered(self, client) -> None:
        """Wahoo's API agreement asks for a privacy policy saying how its data is handled and that
        a rider's data is deleted on request; the section says what the code keeps and removes."""
        _, body, _ = get(client)
        section = body[body.index("<h2>If you connect Wahoo</h2>") :]
        section = section[: section.index("<h2>", 4)]
        text = re.sub(r"<[^>]+>", " ", section).replace("&#x27;", "'").replace("’", "'")
        for claim in (
            "your choice, in Settings",
            "encrypted",
            "only to send the routes you choose",
            "never reads your rides, workouts, plans",
            privacy_policy.WAHOO_NO_AI,
            "withdraws its access at Wahoo",
            "routes already sent stay in your Wahoo app",
            "up to 100 routes",
            "nothing else to see, correct or export",
        ):
            assert claim in text, claim

    @override_settings(PRIVACY_CONTACT="")
    def test_the_claims_the_code_backs(self, client) -> None:
        _, body, _ = get(client)
        text = re.sub(r"<[^>]+>", " ", body).replace("&#x27;", "'").replace("&quot;", '"')
        for claim in (
            "never on disk or in a log",  # core.ride_presence
            "2 minutes",  # ride_presence.DOT_TTL_S
            "Nothing about a ride is kept longer",  # ride_presence.KEEP_S
            "Discord account number",  # core.models.User: discord_user_id only
            "Riding with RouteMaker",  # the app's foreground-service notification
            "keeps going with the screen locked",  # the app's foreground service, Start to End
            "bikeshare docks",  # POST /api/bikeshare/stations takes a point
            "including the internet address, for a short time",  # error logs
            "A note that an account was deleted, and when",  # account_deletion.KEPT
            "never asks for location all the time",  # no ACCESS_BACKGROUND_LOCATION
            "a year after it was last opened",  # shared_routes.KEEP
            "24 hours",  # signed_out_suggestions: SignedOutSend
            "about 30 hours",  # ratelimit.RETENTION and the sweep
            "the last seven kept",  # procrastinate.BACKUP_KEEP
            "leaves them within a week",  # procrastinate.BACKUP_MAX_AGE
            "with the next one that succeeds",  # retention.prune_backups keeps the newest
            "before an update are kept on the server for at most a week",  # prune_snapshots
            "one a night, encrypted",  # procrastinate.perform_backup, through age
            "30 days unused, or after 90 days",  # revocation's idle and absolute lifetimes
            "Sign out everywhere",  # auth_views.logout_everywhere_view
            "Two cookies",  # the session and CSRF cookies
            privacy_policy.CONTACT,
        ):
            assert escape(claim) in body or claim in text, claim

    def test_the_numbers_are_the_code_s(self) -> None:
        from datetime import timedelta

        from config import procrastinate
        from core import ratelimit, revocation, ride_presence, shared_routes

        assert ride_presence.DOT_TTL_S == 120 and ride_presence.ALERT_TTL_S == 120
        assert ride_presence.KEEP_S == 120 and ride_presence.PATH_TTL_S == 120
        # Every ride is sealed: the server rounds nothing, and refuses plain numbers.
        assert not hasattr(ride_presence, "GRID_M") and not hasattr(ride_presence, "rounded")
        assert procrastinate.BACKUP_KEEP == 7
        assert procrastinate.BACKUP_MAX_AGE < timedelta(days=7)
        assert {"app_session", "django_session", "rate_limit_window", "cached_membership"} <= set(
            procrastinate.BACKUP_EXCLUDED_TABLES
        )
        assert revocation.IDLE_SESSION_LIFETIME == timedelta(days=30)
        assert revocation.ABSOLUTE_SESSION_LIFETIME == timedelta(days=90)
        assert ratelimit.RETENTION <= timedelta(hours=30)
        assert shared_routes.KEEP == timedelta(days=365)

    def test_the_encryption_is_spelled_out_behind_its_summary(self, client) -> None:
        # Stephen 2026-10-29: the full technical specification, since nothing is secret but the key.
        _, body, _ = get(client)
        ride = body[body.index("<h2>Group and Mass Ride sharing</h2>") :]
        ride = ride[: ride.index("<h2>", 5)]
        assert f"<details><summary>{escape(privacy_policy.RIDE_CRYPTO_SUMMARY)}</summary>" in ride
        for item in privacy_policy.RIDE_CRYPTO:
            assert escape(item) in ride

    def test_every_ride_link_carries_a_key_ride_posts_too(self, client) -> None:
        from core import ride_presence, route_posts

        _, body, _ = get(client)
        ride = body[body.index("<h2>Group and Mass Ride sharing</h2>") :]
        ride = ride[: ride.index("<h2>", 5)]
        text = re.sub(r"<[^>]+>", " ", ride).replace("&#x27;", "'").replace("’", "'")
        assert "Every ride link carries a key" in text
        assert "anyone who can read the post can see the dots and alerts of that ride" in text
        assert "not encrypted this way" not in text and "rounded" not in text
        # The server's own ride links (a ride post's) carry a key as the phone's do.
        assert len(route_posts.new_ride_key()) == 22
        assert route_posts.RIDE_LINK_TYPES == ("mass-ride", "group-ride")
        assert ride_presence.PLAIN_REFUSED

    def test_the_encryption_details_are_the_code_s(self) -> None:
        from core import route_posts

        seal = (ROOT / "frontend/src/lib/rideSeal.ts").read_text()
        group = (ROOT / "frontend/src/lib/rideGroup.ts").read_text()
        text = " ".join(privacy_policy.RIDE_CRYPTO)
        # A new key is 16 bytes, 22 characters (the owner, 2026-10-29), as the server makes a ride
        # post's; an older link's 43 still opens.
        assert route_posts.RIDE_KEY_BYTES == 16 and "16 random bytes" in text
        assert "export const SECRET_BYTES = 16;" in seal and "const OLD_SECRET_BYTES = 32;" in seal
        assert "22 base64url characters" in text and "43 characters, still works" in text
        assert "lead=, the first 16 bytes of the SHA-256" in text and "32 hex digits" in text
        assert "const NONCE_BYTES = 12;" in seal and "12-byte nonce" in text
        assert 'enc.encode("routemaker ride seal v1")' in seal and "routemaker ride seal v1" in text
        assert 'info: enc.encode("ride id") }, base, 256)' in seal and "256 bits" in text
        assert 'info: enc.encode("ride key")' in seal
        assert '{ name: "AES-GCM", length: 256 },\n    false,' in seal and "non-extractable" in text
        assert "number> = { dot: 128, alert: 512, path: 4096 }" in seal
        assert "128 bytes (a dot), 512 bytes (an alert) or 4,096 bytes (a path)" in text
        assert "additionalData: aad(seal, kind)" in seal and "`${kind}|${seal.ride}`" in seal
        assert 'export const SECRET_PARAM = "k";' in seal and "k=" in text
        assert "Every ride link carries one" in text
        # Phones send their position as measured: no grid or rounding is claimed.
        assert "20 m" not in text and "grid" not in text and "round" not in text
        assert "new Uint8Array(16)" in group and "16 random bytes" in text


class TestLinks:
    def test_the_deletion_page_links_here(self, client, db) -> None:
        body = client.get(account_deletion.PATH, **addr()).content.decode()
        assert f'<a href="{privacy_policy.PATH}">Privacy policy</a>' in body

    def test_settings_links_here(self) -> None:
        sign_in = (ROOT / "frontend/src/lib/signIn.ts").read_text()
        assert f'PRIVACY_PAGE = "{privacy_policy.PATH}"' in sign_in
        sheets = (ROOT / "frontend/src/app/Sheets.tsx").read_text()
        about = sheets[sheets.index('<h3 id="settings-about-heading">') :]
        about = about[: about.index("</section>")]
        assert "<a href={PRIVACY_PAGE}" in about and "Privacy policy" in about
        assert "PRIVACY_PAGE}" not in sheets[: sheets.index('<h3 id="settings-about-heading">')]

    def test_the_url_is_routed(self) -> None:
        from django.urls import resolve

        assert resolve(privacy_policy.PATH).func is privacy_policy.page
