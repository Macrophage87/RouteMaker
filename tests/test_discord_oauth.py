from __future__ import annotations

import http.client
from datetime import UTC, datetime, timedelta

import pytest

from core.discord_oauth import (
    SCOPES,
    STATE_LIFETIME,
    LoginRequest,
    OAuthStateError,
    begin_login,
    scopes_are_minimal,
    verify_state,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def test_only_the_identify_scope_is_requested() -> None:
    """`guilds` would list every server the person is in - more than planning a
    bike ride requires them to disclose. Membership comes from the bot instead."""
    url, _ = begin_login("client", "https://example.test/cb", NOW)
    assert "scope=identify" in url
    assert "guilds" not in url
    assert SCOPES == ("identify",)


def test_state_is_required_and_must_match() -> None:
    _, request = begin_login("client", "https://example.test/cb", NOW)
    assert verify_state(request, request.state, NOW) is request
    with pytest.raises(OAuthStateError, match="state mismatch"):
        verify_state(request, "forged", NOW)
    # A non-ASCII state is a mismatch too, not compare_digest's TypeError (sec-app-4).
    with pytest.raises(OAuthStateError, match="state mismatch"):
        verify_state(request, "f\u00f6rged", NOW)


def test_callback_without_a_login_in_progress_is_refused() -> None:
    with pytest.raises(OAuthStateError, match="no login was in progress"):
        verify_state(None, "anything", NOW)


def test_expired_state_is_refused() -> None:
    stale = LoginRequest(state="abc", issued_at=NOW - STATE_LIFETIME - timedelta(seconds=1))
    with pytest.raises(OAuthStateError, match="expired"):
        verify_state(stale, "abc", NOW)


def test_state_is_unguessable() -> None:
    _, first = begin_login("client", "https://example.test/cb", NOW)
    _, second = begin_login("client", "https://example.test/cb", NOW)
    assert first.state != second.state
    # The exact length `secrets.token_urlsafe(32)` produces, not a floor: a
    # floor of 32 is satisfied by token_urlsafe(24), which is eight bytes less
    # entropy in the value that binds an authorize URL to one browser session.
    assert len(first.state) == 43
    assert len(second.state) == 43


def test_excess_granted_scope_is_refused_not_ignored() -> None:
    """More than identify means the URL was tampered with or the application
    configuration drifted."""
    assert scopes_are_minimal("identify")
    assert not scopes_are_minimal("identify guilds")
    assert not scopes_are_minimal("identify email")


class _Reply:
    """One of Discord's answers to the exchange: a body, or a read that fails part way."""

    def __init__(self, body: str = "", fails: Exception | None = None) -> None:
        self.body = body
        self.fails = fails

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self, *_args) -> bytes:
        if self.fails is not None:
            raise self.fails
        return self.body.encode()


def _discord_answers(monkeypatch, *answers) -> None:
    """urlopen replaced: each call takes the next answer, raising it where it is an exception."""
    queue = list(answers)

    def urlopen(*_args, **_kwargs):
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr("core.auth_views.urllib.request.urlopen", urlopen)


TOKEN = '{"access_token": "t", "scope": "identify"}'


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param([TimeoutError("timed out")], id="token reply slower than the timeout"),
        pytest.param([http.client.RemoteDisconnected("closed")], id="token reply dropped"),
        pytest.param([_Reply(fails=TimeoutError("timed out"))], id="token body slow"),
        pytest.param([_Reply(fails=http.client.IncompleteRead(b"{"))], id="token body cut off"),
        pytest.param([_Reply(TOKEN), TimeoutError("timed out")], id="profile reply slow"),
        pytest.param([_Reply(TOKEN), ConnectionResetError()], id="profile reply reset"),
        pytest.param([_Reply(TOKEN), _Reply('{"id": "4')], id="profile body not JSON"),
        pytest.param(
            [_Reply(TOKEN), http.client.BadStatusLine("")], id="profile reply with no status"
        ),
    ],
)
def test_a_slow_dropped_or_cut_off_discord_reply_is_a_failed_sign_in(monkeypatch, answers) -> None:
    """The callback answers LoginRefused with its sign-in failure page; anything else is a 500."""
    from core.auth_views import LoginRefused, exchange_code

    _discord_answers(monkeypatch, *answers)
    with pytest.raises(LoginRefused):
        exchange_code("abc")


def test_a_whole_discord_reply_still_signs_in(monkeypatch) -> None:
    from core.auth_views import exchange_code

    _discord_answers(monkeypatch, _Reply(TOKEN), _Reply('{"id": "4321"}'))
    assert exchange_code("abc") == (4321, "identify")
