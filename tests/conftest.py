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
    """A live/staging schema pair, torn down afterwards however the test ends.

    Named from settings rather than written out here, so that a run with
    ROUTEMAKER_LIVE_SCHEMA set does not reach into another run's schemas. Two
    concurrent runs used to drop each other's tables mid-test and leave failures
    that read as code defects rather than as contention: a stale database whose
    next run errors with "relation django_content_type does not exist" is not
    obviously a concurrency problem to whoever hits it.

    The fixture yields the names for that reason. Tests that still write "live"
    and "staging" as literals - most of tests/test_schema_swap.py - work on a
    default run and fail loudly rather than silently on a renamed one, which is
    the safe direction but is not the same as being isolated.
    """
    from django.conf import settings

    from pipeline.schema import create_segment_schema, drop_segment_schema

    live = settings.SEGMENT_SCHEMA_LIVE
    staging = settings.SEGMENT_SCHEMA_STAGING
    names = (live, staging, settings.SEGMENT_SCHEMA_RETIRED)

    for name in names:
        drop_segment_schema(name)
    create_segment_schema(live)
    create_segment_schema(staging)
    yield live, staging
    for name in names:
        drop_segment_schema(name)
