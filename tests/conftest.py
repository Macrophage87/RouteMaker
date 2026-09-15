"""Test configuration.

Database tests run against a real PostgreSQL with PostGIS rather than a
stand-in, because the things most worth testing here - the schema swap's locking
and rename ordering, spatial predicates, unmanaged-model DDL - do not exist in a
substitute engine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def pytest_configure() -> None:
    import django

    django.setup()


@pytest.fixture
def segment_schemas():
    """A live/staging schema pair, torn down afterwards however the test ends."""
    from pipeline.schema import create_segment_schema, drop_segment_schema

    for name in ("live", "staging", "live_old"):
        drop_segment_schema(name)
    create_segment_schema("live")
    create_segment_schema("staging")
    yield "live", "staging"
    for name in ("live", "staging", "live_old"):
        drop_segment_schema(name)
