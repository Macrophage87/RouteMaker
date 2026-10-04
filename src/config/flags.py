"""Reading on/off switches from the environment, kept out of settings.py so they can be
tested without reloading the settings module (a reload replaces `DATABASES` with a fresh
dict that pytest-django has not adjusted, so config.test_settings then differs from
config.settings: tests/test_settings_security.py)."""

from __future__ import annotations


def env_true(value: str | None) -> bool:
    """Whether a switch's value means on: 1 or true, any case, spaces ignored."""
    return (value or "").strip().lower() in {"1", "true"}
