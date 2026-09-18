"""Jurisdiction crossings along a route, and the rules for which ones to keep.

A crossing list that reports every sliver is unreadable, and one that collapses
by length alone drops exactly the crossings that decide whose permit is needed.
The NPS land at the foot of Memorial Bridge, the Capitol grounds clip at 1st and
Louisiana, and the Secret Service edge of President's Park are all short, and
short is not the same as unimportant.

Reported rather than warned about: what changes at a line is which laws apply
and which body issues a permit. Nothing here characterizes what any of them
provide, which is the info cards' job under their own not-legal-advice line.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from routemaker.geo import METRES_PER_MILE

# Crossings shorter than this collapse into their neighbours, unless a carve-out
# applies. Configurable per deployment; the default is a tenth of a mile.
DEFAULT_MIN_CROSSING_M = 0.1 * METRES_PER_MILE


@dataclass(frozen=True)
class Crossing:
    """One continuous stretch of route inside one authority on one layer."""

    layer: str
    authority: str
    start_m: float
    end_m: float
    is_federal_enclave: bool = False
    contains_control_point: bool = False
    # A boundary street's centreline is the line itself, so both authorities
    # apply along its length. A ride on Eastern Avenue really does involve
    # Prince George's County and an organizer needs to see that, rather than the
    # report silently calling the whole thing DC.
    also_authority: str | None = None

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m


def collapse_short_crossings(
    crossings: Sequence[Crossing], minimum_m: float = DEFAULT_MIN_CROSSING_M
) -> list[Crossing]:
    """Drop crossings below the minimum, except where a carve-out applies.

    Two carve-outs, and both exist because length is a bad proxy for importance:
    a crossing containing a control point is kept, because the route stops
    there; and a crossing into or out of a federal enclave is kept at any
    length, because that is precisely where the permit question changes.
    """
    return [
        crossing
        for crossing in crossings
        if crossing.length_m >= minimum_m
        or crossing.is_federal_enclave
        or crossing.contains_control_point
    ]


def distinct_authorities(crossings: Sequence[Crossing]) -> dict[str, list[str]]:
    """Authorities touched, per layer, in the order first encountered.

    All three layers, not the police layer alone: the body that issues a permit
    is frequently not a police agency. The W&OD is NOVA Parks, the Capital
    Crescent and Sligo Creek are M-NCPPC, the towpath and the Mount Vernon Trail
    are the Park Service as land manager, and public space in the District is
    DDOT.

    Both authorities on a boundary street, not just the first. `also_authority`
    is what `Crossing` carries a boundary centreline in - a ride on Eastern
    Avenue really is in the District and in Prince George's County at once - and
    until now nothing anywhere read it, so the one field that exists to stop the
    report silently calling a boundary street DC was inert on every consumer.
    The pair is emitted in the order it is encountered, `authority` first,
    because that is the order the row states them in and neither is the
    "primary" one; a permit application needs both names, not a winner.
    """
    out: dict[str, list[str]] = {}
    for crossing in crossings:
        names = out.setdefault(crossing.layer, [])
        for authority in (crossing.authority, crossing.also_authority):
            if authority and authority not in names:
                names.append(authority)
    return out


def state_line_crossings(crossings: Sequence[Crossing], home_state: str) -> list[Crossing]:
    """Crossings that leave the route's home jurisdiction.

    Kept separate from the general list because the state line is the one that
    changes which laws apply, and because it is symmetric: leaving and returning
    are both crossings. Crossing one is routine here and is never avoided by
    default; the reporting exists for permitting, not for risk.
    """
    return [c for c in crossings if c.layer == "state" and c.authority != home_state]
