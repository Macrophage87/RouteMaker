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
# `config.test_settings` is the production settings plus the one secret they
# refuse to import without; see its docstring for why that default cannot live
# in this file.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")


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


@pytest.fixture(autouse=True)
def _weekend_router_state(monkeypatch):
    """core.routing remembers a failed weekend router for a minute; no test
    inherits another's memory of one. And it plans a weekend ride on the
    weekend graph only once a weekend build has been promoted (a settings
    row), which a test database has none of: route tests take it as promoted,
    and `weekend_rows_read` gives a test the real check."""
    try:
        from core import routing
    except Exception:  # noqa: BLE001 - modules that never load Django
        yield
        return
    _REAL_WEEKEND_CHECK.setdefault("check", routing._weekend_is_promoted)
    monkeypatch.setattr(routing, "_weekend_is_promoted", lambda: True)
    routing._weekend_failed_at = None
    yield
    routing._weekend_failed_at = None


_REAL_WEEKEND_CHECK: dict = {}


# The production list, read before any test patches it (pinned in test_states).
try:
    from pipeline import states as _states

    REAL_REQUIRED_STATES = _states.REQUIRED_STATES
except Exception:  # noqa: BLE001 - a run that never loads the pipeline
    REAL_REQUIRED_STATES = None


@pytest.fixture(autouse=True)
def _toy_required_states(monkeypatch):
    """The rebuild refuses a region missing a required state's boundary, or
    whose boundary holds no way (pipeline.states). The toy extracts carry DC,
    Virginia and Maryland boundaries (rebuild_fixtures.STATE_BOXES), but their
    roads are all in the District and Virginia, so the toy region requires the
    District only; tests/test_states.py holds the refusal to the real list."""
    from pipeline import states

    monkeypatch.setattr(states, "REQUIRED_STATES", ("DC",))


@pytest.fixture
def weekend_rows_read(monkeypatch):
    """The real `_weekend_is_promoted`, reading the settings rows."""
    from core import routing

    monkeypatch.setattr(routing, "_weekend_is_promoted", _REAL_WEEKEND_CHECK["check"])
