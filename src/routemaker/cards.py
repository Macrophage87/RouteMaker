"""Thumbnails and social share cards.

What a card may contain is decided by the viewer's standing on the route, not by
the route's tier, for the same reason everything else operational is: the tiers
are cumulative, so a tier-based rule reads backwards.

A card travels further than any other artifact here. Chat and social platforms
fetch and cache an OpenGraph image on first paste and keep serving it after the
origin refuses anonymous reads, so a card is effectively unrecallable once
posted. That is why suppression happens at render time rather than at serve
time: a card that should not have shown a marshal post cannot be unshown.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .geo import METRES_PER_FOOT, METRES_PER_MILE


class CardStyle(Enum):
    """What the card shows of the route itself."""

    FULL_ROUTE = "full_route"
    START_ONLY = "start_only"  # carries no route geometry at all


# Rendered at several sizes for different platforms. Attribution appears at every
# one of them, including the smallest, rather than being dropped when it gets
# tight.
CARD_SIZES = {
    "og": (1200, 630),
    "square": (1080, 1080),
    "story": (1080, 1920),
    "thumb": (400, 210),
}

# Control point types that never appear on a card at any size or style. A page
# that plots where your people will be tells that to everyone, including
# agencies you have not spoken to.
OPERATIONAL_POINTS = frozenset({"marshal", "sag", "medical", "sweep", "bailout", "regroup"})
PUBLIC_POINTS = frozenset({"start", "finish", "rest"})


@dataclass(frozen=True)
class CardRequest:
    style: CardStyle
    size: str
    include_elevation: bool = False
    include_qr: bool = False
    viewer_has_operational_access: bool = False


@dataclass(frozen=True)
class CardContent:
    """What the renderer will actually draw."""

    width: int
    height: int
    show_geometry: bool
    control_points: frozenset[str]
    show_elevation: bool
    show_qr: bool
    attribution: str
    distance_mi: float
    gain_ft: float


def build(
    request: CardRequest,
    distance_m: float,
    gain_m: float,
    attribution: str = "© OpenStreetMap contributors, © Protomaps",
) -> CardContent:
    """Decide the card's contents.

    Operational control points are dropped unless the viewer holds standing for
    them, and are dropped in the start-only style regardless, since that style
    exists precisely to publish a ride without publishing its route.
    """
    points = set(PUBLIC_POINTS)
    if request.viewer_has_operational_access and request.style is CardStyle.FULL_ROUTE:
        points |= OPERATIONAL_POINTS

    width, height = CARD_SIZES[request.size]
    return CardContent(
        width=width,
        height=height,
        show_geometry=request.style is CardStyle.FULL_ROUTE,
        control_points=frozenset(points),
        show_elevation=request.include_elevation and request.style is CardStyle.FULL_ROUTE,
        show_qr=request.include_qr,
        attribution=attribution,
        distance_mi=distance_m / METRES_PER_MILE,
        gain_ft=gain_m / METRES_PER_FOOT,
    )
