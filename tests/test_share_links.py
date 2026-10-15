"""Short map links followed for shared locations (v0.7.0; POST /api/share/resolve)."""

from __future__ import annotations

import json

import pytest

from core import share_links

GOOGLE_FULL = "https://www.google.com/maps/place/Lincoln+Memorial/@38.8892686,-77.050176,17z"


def hops(*chain: str | None):
    """A redirect chain: each call answers the next Location; the URLs asked are kept."""
    asked: list[str] = []
    answers = list(chain)

    def location(url: str, timeout: float) -> str | None:
        asked.append(url)
        assert timeout <= share_links.TIMEOUT_S
        return answers.pop(0) if answers else None

    location.asked = asked  # type: ignore[attr-defined]
    return location


@pytest.mark.parametrize(
    "url, short",
    [
        ("https://maps.app.goo.gl/AbC123", True),
        ("https://goo.gl/maps/AbC123", True),
        ("https://maps.apple/p/AbC123", True),
        ("https://goo.gl/other", False),
        ("http://maps.app.goo.gl/AbC123", False),
        ("https://maps.app.goo.gl/", False),
        ("https://user@maps.app.goo.gl/AbC123", False),
        ("https://evil.example/maps.app.goo.gl", False),
        (GOOGLE_FULL, False),
    ],
)
def test_what_counts_as_a_short_link(url, short):
    assert share_links.is_short_link(url) is short


def test_a_short_link_is_followed_to_the_map_link():
    location = hops(GOOGLE_FULL)
    assert share_links.resolve("https://maps.app.goo.gl/AbC123", location) == GOOGLE_FULL
    assert location.asked == ["https://maps.app.goo.gl/AbC123"]


def test_a_relative_redirect_and_two_hops():
    location = hops("/maps/AbC", GOOGLE_FULL)
    # goo.gl/maps/x -> goo.gl/maps/AbC (still short) -> the full link
    assert share_links.resolve("https://goo.gl/maps/x", location) == GOOGLE_FULL
    assert location.asked == ["https://goo.gl/maps/x", "https://goo.gl/maps/AbC"]


@pytest.mark.parametrize(
    "chain",
    [
        ("https://evil.example/phish",),
        ("http://www.google.com/maps/@38.9,-77,15z",),
        (None,),
        ("/x",) * 6,
    ],
)
def test_a_link_that_leaves_the_map_sites_or_goes_nowhere_is_unresolved(chain):
    with pytest.raises(share_links.Unresolved):
        share_links.resolve("https://maps.app.goo.gl/AbC123", hops(*chain))


def test_only_short_links_are_followed():
    location = hops(GOOGLE_FULL)
    with pytest.raises(share_links.NotAShortLink):
        share_links.resolve("https://example.com/AbC", location)
    assert location.asked == []


# --- The endpoint ---------------------------------------------------------------------------


def post(client, payload, **extra):
    return client.post(
        "/api/share/resolve", data=json.dumps(payload), content_type="application/json", **extra
    )


def test_the_endpoint_follows_a_short_link(client, db, monkeypatch):
    # The network stand-in: resolve's default way to ask.
    monkeypatch.setattr(share_links.resolve, "__defaults__", (hops(GOOGLE_FULL),))
    response = post(client, {"url": "https://maps.app.goo.gl/AbC123"})
    assert response.status_code == 200 and response.json() == {"url": GOOGLE_FULL}
    assert response["Cache-Control"] == "no-store"


def test_the_endpoint_refuses_other_links_and_says_why(client, db, monkeypatch):
    response = post(client, {"url": "https://example.com/x"})
    assert response.status_code == 400 and "short map link" in response.json()["error"]
    monkeypatch.setattr(share_links.resolve, "__defaults__", (hops(None),))
    response = post(client, {"url": "https://maps.app.goo.gl/AbC123"})
    assert response.status_code == 502


def test_the_endpoint_takes_json_only(client, db):
    response = client.post("/api/share/resolve", data="url=x", content_type="text/plain")
    assert response.status_code == 400
