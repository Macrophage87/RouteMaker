from __future__ import annotations

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
