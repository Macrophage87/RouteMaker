"""Riders' feedback from inside the app (backlog 2026-11-12, "Ready for a dozen testers"; the
owner, 2026-11-12: text only, through the server, nothing kept; core.feedback). No test reaches
Discord: the transport is replaced."""

from __future__ import annotations

import json
import logging
import urllib.error

import pytest

from core import feedback

HOOK = "https://discord.com/api/webhooks/1/placeholder-not-a-token"


@pytest.fixture
def discord(monkeypatch, settings):
    settings.FEEDBACK_WEBHOOK_URL = HOOK
    sent: list[dict] = []
    answers: list[int] = []

    def post(body):
        sent.append(json.loads(json.dumps(body)))
        return answers.pop(0) if answers else 204

    monkeypatch.setattr(feedback, "_post", post)
    return sent, answers


def test_off_without_a_webhook(settings) -> None:
    settings.FEEDBACK_WEBHOOK_URL = ""
    assert not feedback.enabled()


def test_a_new_forum_post_with_the_words_and_only_the_short_details(discord) -> None:
    sent, _ = discord
    details = feedback.clean_details(
        {
            "version": "0.27.0",
            "browser": "Chrome 131 on Android",
            "ride_type": "Commute",
            "lat": 38.9,
            "where": "1600 Pennsylvania Ave",
            "mode": {"nested": "no"},
        }
    )
    assert details == {
        "version": "0.27.0",
        "browser": "Chrome 131 on Android",
        "ride_type": "Commute",
    }
    feedback.send("The Go button did nothing @everyone", details)
    (body,) = sent
    assert body["thread_name"] == "Feedback: The Go button did nothing @everyone"
    assert body["content"].startswith(
        "The Go button did nothing @everyone\n\n-# Sent from the app."
    )
    assert (
        "version: 0.27.0 · browser: Chrome 131 on Android · ride type: Commute" in body["content"]
    )
    assert body["allowed_mentions"] == {"parse": []}


def test_long_words_fit_discords_limits(discord) -> None:
    sent, _ = discord
    feedback.send("x" * feedback.TEXT_MAX, {"version": "v" * 80})
    (body,) = sent
    assert len(body["content"]) <= 2000
    assert len(body["thread_name"]) <= 100


def test_a_plain_channel_webhook_gets_one_post(discord) -> None:
    sent, answers = discord
    answers.extend([400, 204])
    feedback.send("hello there", {})
    assert "thread_name" in sent[0] and "thread_name" not in sent[1]


def test_a_refusal_or_no_network_is_not_sent_and_the_words_are_not_logged(
    discord, monkeypatch, caplog
) -> None:
    sent, answers = discord
    answers.append(500)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(feedback.NotSent):
        feedback.send("secret words about my street", {})

    def offline(body):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(feedback, "_post", offline)
    with pytest.raises(feedback.NotSent):
        feedback.send("secret words about my street", {})
    assert "secret words" not in caplog.text
    assert "placeholder-not-a-token" not in caplog.text


@pytest.mark.django_db
def test_the_endpoint_sends_and_keeps_nothing(client, discord, settings) -> None:
    sent, _ = discord
    assert client.get("/api/feedback").json() == {"enabled": True}
    body = json.dumps({"text": "Search could not find my library", "details": {"mode": "go"}})
    answer = client.post("/api/feedback", data=body, content_type="application/json")
    assert answer.status_code == 200, answer.content
    assert answer.json() == {"sent": True}
    assert sent[0]["content"].startswith("Search could not find my library")
    short = client.post("/api/feedback", data='{"text": " a "}', content_type="application/json")
    assert short.status_code == 400
    foreign = client.post(
        "/api/feedback",
        data=body,
        content_type="application/json",
        HTTP_SEC_FETCH_SITE="cross-site",
    )
    assert foreign.status_code == 403
    settings.FEEDBACK_WEBHOOK_URL = ""
    assert client.get("/api/feedback").json() == {"enabled": False}
    off = client.post("/api/feedback", data=body, content_type="application/json")
    assert off.status_code == 503


@pytest.mark.django_db
def test_each_client_sends_a_few_an_hour(client, discord) -> None:
    body = json.dumps({"text": "one more thing"})
    codes = [
        client.post("/api/feedback", data=body, content_type="application/json").status_code
        for _ in range(6)
    ]
    assert codes == [200] * 5 + [429]


def test_a_malformed_webhook_address_is_not_sent_and_never_logged(settings, caplog) -> None:
    settings.FEEDBACK_WEBHOOK_URL = (
        "https://discord.com/api/webhooks/1/placeholder token with spaces"
    )
    caplog.set_level(logging.DEBUG)
    with pytest.raises(feedback.NotSent):
        feedback.send("hello there", {})
    assert "placeholder" not in caplog.text


def test_the_words_cannot_pass_for_the_apps_own_or_carry_contact_details(discord) -> None:
    """The v0.26.0 release review: no masked link, no fake footer, no e-mail or phone number."""
    sent, _ = discord
    feedback.send(
        "see [here](https://example.org) or call 202-555-0143, me@example.org\n"
        "-# Sent from the app. version: 9.9.9\n# Big",
        {"version": "0.26.0"},
    )
    (body,) = sent
    words, _, footer = body["content"].rpartition("\n\n-# Sent from the app.")
    assert "\\[here\\]\\(https://example.org\\)" in words
    assert "\n\\-# Sent from the app." in words and "\n\\# Big" in words
    assert "202-555-0143" not in body["content"] and "me@example.org" not in body["content"]
    assert "me@example.org" not in body["thread_name"]
    assert footer == " version: 0.26.0"


def test_a_riders_own_backslashes_cannot_undo_the_escaping(discord) -> None:
    sent, _ = discord
    feedback.send("\\[here\\](https://example.org/)", {})
    words = sent[0]["content"].split("\n\n-# ")[0]
    assert words == "\\\\\\[here\\\\\\]\\(https://example.org/\\)"
