"""A rider's feedback, sent from inside the app with no Discord account (backlog 2026-11-12,
"Ready for a dozen testers"; the owner, 2026-11-12: text only, through the server, nothing kept).

POST /api/feedback takes the rider's words and the same place-free details the crash screen builds
(frontend/src/lib/feedback.ts: version, browser, ride type, language, Go or Plan) and posts them
to the owner's Discord bug-reports forum through a webhook, as a new post. Nothing is written to
the database or a log: the words exist on this server only for the length of the request. No
screenshot is taken (a picture can show where someone is).

Off unless the deployment sets FEEDBACK_WEBHOOK_URL (the forum's webhook: the channel's settings,
Integrations, Webhooks); GET /api/feedback says whether it is on, so the app shows the entry only
where it works. The address is a secret and is never printed.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

TEXT_MIN = 3
TEXT_MAX = 2000
# Each detail is a short label, never free text: anything else is dropped.
DETAIL_KEYS = ("version", "browser", "ride_type", "language", "mode", "app")
DETAIL_MAX = 80
TIMEOUT_S = 15
# Discord: a message is at most 2000 characters, a forum post's title at most 100.
CONTENT_MAX = 2000
TITLE_MAX = 90


class NotSent(Exception):
    """Discord did not take it; the rider is told to try again later."""


def enabled() -> bool:
    return bool(getattr(settings, "FEEDBACK_WEBHOOK_URL", ""))


def clean_details(details: object) -> dict[str, str]:
    if not isinstance(details, dict):
        return {}
    kept = {}
    for key in DETAIL_KEYS:
        value = details.get(key)
        if isinstance(value, str) and value.strip():
            kept[key] = " ".join(value.split())[:DETAIL_MAX]
    return kept


def message(text: str, details: dict[str, str]) -> dict:
    """The webhook's body: a new forum post titled with the words' start, mentions off."""
    words = text.strip()
    title = " ".join(words.split())
    title = title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1] + "…"
    line = " · ".join(f"{key.replace('_', ' ')}: {value}" for key, value in details.items())
    footer = f"\n\n-# Sent from the app. {line}" if line else "\n\n-# Sent from the app."
    content = words[: CONTENT_MAX - len(footer)] + footer
    return {
        "content": content,
        "thread_name": f"Feedback: {title}",
        "allowed_mentions": {"parse": []},
        "username": "RouteMaker feedback",
    }


def _post(body: dict) -> int:
    request = urllib.request.Request(
        settings.FEEDBACK_WEBHOOK_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "RouteMaker feedback"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as answer:  # noqa: S310
            return answer.status
    except urllib.error.HTTPError as error:
        return error.code


def send(text: str, details: dict[str, str]) -> None:
    body = message(text, details)
    try:
        status = _post(body)
        if status == 400:
            # Not a forum (a plain channel's webhook refuses a thread name): one post instead.
            body.pop("thread_name")
            status = _post(body)
    except (urllib.error.URLError, TimeoutError, OSError) as failed:
        # The reason only: never the words, never the address.
        logger.warning("feedback: Discord could not be reached (%s)", type(failed).__name__)
        raise NotSent from None
    if not 200 <= status < 300:
        logger.warning("feedback: Discord answered HTTP %s", status)
        raise NotSent
