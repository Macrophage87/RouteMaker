"""Flashing beacons the map has as traffic signals, read at plan time.

The owner, 2026-10-20, at Connecticut Ave (MD 185) and Baltimore St, Kensington: "a
traffic light that's a blinking red against free flowing traffic. It wasn't passable",
and "At rush hour that felt completely impassable". OSM has a signal there, so the
junction model priced the crossing as signalised (600 ft, 0.11 calm mi, for an LTS 4
road); MDOT SHA lists the device as a Warning Beacon. Each active `FlashingSignal` row
makes the junction model price a signalised junction within
`intersections.BEACON_MATCH_M` of it with no signal (`intersections.with_beacons`):
for a rider crossing Connecticut Ave from Baltimore St, the stopped side's 6,000 ft or
more (1.1 calm mi), and more at rush hour.

Read once a plan, as the junction ratings are (`core.junction_suggestions.approved_ratings`),
and kept between plans until the table changes: the list is a state's beacons (some
hundreds), so a plan asks only whether it changed.
"""

from __future__ import annotations

import hashlib
import logging
import threading

from django.db import DatabaseError
from django.db.models import Count, Max, Q

from routemaker.intersections import Beacon

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_memo: tuple[tuple, tuple[Beacon, ...], str] | None = None


def _version() -> tuple:
    from .models import FlashingSignal

    # A load adds rows (the count and the last id); an update or a withdrawal touches
    # `updated_at`; a deleted row lowers the count.
    seen = FlashingSignal.objects.aggregate(
        n=Count("id"),
        last=Max("id"),
        changed=Max("updated_at"),
        active=Count("id", filter=Q(active=True)),
    )
    return (seen["n"], seen["last"], seen["changed"], seen["active"])


def _read() -> tuple[tuple, tuple[Beacon, ...], str]:
    global _memo
    from .models import FlashingSignal

    version = _version()
    with _lock:
        if _memo is not None and _memo[0] == version:
            return _memo
    rows = FlashingSignal.objects.filter(active=True).only("id", "location").order_by("id")
    beacons = tuple(Beacon(row.id, row.location.x, row.location.y) for row in rows)
    digest = hashlib.sha256(repr(beacons).encode()).hexdigest()[:16]
    with _lock:
        _memo = (version, beacons, digest)
    return _memo


def active() -> tuple[Beacon, ...]:
    """The active beacons, for the junction model. Empty when there are none or when the
    table cannot be read: a plan is never refused for want of them."""
    try:
        return _read()[1]
    except DatabaseError:
        logger.warning("the flashing beacons could not be read", exc_info=True)
        return ()


def digest() -> str:
    """A short digest of the active beacons, for the route cache's key."""
    try:
        return _read()[2]
    except DatabaseError:
        return ""
