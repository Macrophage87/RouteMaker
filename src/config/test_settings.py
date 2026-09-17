"""The production settings, with the one secret the suite has to supply itself.

`config.settings` refuses to import without `KEY_ENCRYPTION_KEY`: it is what
keys every ban tombstone, and a default in the settings module would be a
published key that turns every tombstone in a dump back into a Discord id. That
refusal is the point, so the suite does not get an exemption from it - it gets
this module, which supplies a test value in the open and then imports the real
settings unchanged.

It lives here rather than in `tests/conftest.py` because pytest-django sets
Django up while it loads the initial conftests, before any conftest body has
run, so an environment default written there arrives too late to be read.

Nothing else is overridden. A test settings module that quietly relaxed a
security setting would make the assertions in tests/test_settings_security.py
assertions about itself.
"""

from __future__ import annotations

import os

os.environ.setdefault("KEY_ENCRYPTION_KEY", "test-key-encryption-key")

from config.settings import *  # noqa: E402,F403
