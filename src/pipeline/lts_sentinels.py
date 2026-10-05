"""The owner's reference LTS 4 road, read back at VALIDATE (OWNER-DECISIONS 408, 409).

The owner, 2026-10-05: "Most of Conn Ave is LTS4. It's the road I'd keep using as an
example of LTS4." and "I'd say it's LTS4 north of R." So a rebuild whose classifier, its
inputs (DC's Roadway Block: speeds, lanes, counts) or the named corridor that lifts R St to
Calvert St (fixtures/corridors/) came out different is refused before it is promoted, as
a lost column or a lost long trail is.

The street is found by the agency's own name (`ROUTENAME`, e.g. "CONNECTICUT AVE NW") on
the installed Roadway Block blocks, and its rows by the blocks the classifier matched
them to (`segment.attr_sources->'blocks'`), never by OSM way id, which drifts between
extracts. Lengths are of the segment rows, so a divided stretch counts both carriageways.
A row counts as LTS 4 at tier 4 or Avoid (5).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from django.db import connection

from .schema import validate_schema_name

_TIERS_SQL = """
SELECT COALESCE(sum(len), 0),
       COALESCE(sum(len) FILTER (WHERE stress_tier >= 4), 0),
       COALESCE(sum(len) FILTER (WHERE lat >= %s), 0),
       COALESCE(sum(len) FILTER (WHERE lat >= %s AND stress_tier >= 4), 0)
FROM (
    SELECT ST_Length(geometry::geography) AS len,
           ST_Y(ST_LineInterpolatePoint(geometry, 0.5)) AS lat,
           stress_tier
    FROM {schema}.segment
    WHERE attr_sources -> 'blocks' ?| %s::text[] AND map_class = 'road'
) AS rows
"""


@dataclass(frozen=True)
class StreetTiers:
    """A street's segment rows, metres: all of them and those at LTS 4 or Avoid, and the
    same north of `north_of_lat` (the latitude of a row's middle)."""

    street: str
    north_of_lat: float
    total_m: float
    lts4_m: float
    north_m: float
    north_lts4_m: float

    @property
    def share(self) -> float:
        return self.lts4_m / self.total_m if self.total_m else 0.0

    @property
    def north_share(self) -> float:
        return self.north_lts4_m / self.north_m if self.north_m else 0.0


def block_ids(road_blocks: Iterable, street: str) -> list[str]:
    """The installed agency blocks of `street` (the agency's name, any case)."""
    wanted = street.strip().upper()
    return sorted(
        block.feature_id
        for block in road_blocks
        if (getattr(block.facts, "name", None) or "").strip().upper() == wanted
    )


def street_tiers(schema: str, street: str, ids: Sequence[str], north_of_lat: float) -> StreetTiers:
    """Read the street's rows back from the built table."""
    schema = validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(_TIERS_SQL.format(schema=schema), [north_of_lat, north_of_lat, list(ids)])
        total, lts4, north, north_lts4 = (float(value) for value in cursor.fetchone())
    return StreetTiers(street, north_of_lat, total, lts4, north, north_lts4)


def _mi(metres: float) -> str:
    return f"{metres / 1609.344:.2f} mi ({metres / 1000:.2f} km)"


def problems(tiers: StreetTiers, min_share: float, north_min_share: float) -> list[str]:
    """What is wrong with the street's tiers, in words; empty when it holds."""
    if tiers.total_m <= 0:
        return [
            f"no segment row is matched to a Roadway Block block of {tiers.street}, so the "
            "owner's reference LTS 4 road (OWNER-DECISIONS 408) was not rated at all"
        ]
    found = []
    if tiers.share < min_share:
        found.append(
            f"only {tiers.share:.0%} of {tiers.street} ({_mi(tiers.lts4_m)} of "
            f"{_mi(tiers.total_m)}) is LTS 4, under {min_share:.0%}: the owner's reference "
            'LTS 4 road (OWNER-DECISIONS 408, "Most of Conn Ave is LTS4") came out calmer'
        )
    if tiers.north_m <= 0 or tiers.north_share < north_min_share:
        found.append(
            f"{tiers.north_share:.0%} of {tiers.street} north of {tiers.north_of_lat:.4f} N "
            f"({_mi(tiers.north_lts4_m)} of {_mi(tiers.north_m)}) is LTS 4, under "
            f"{north_min_share:.0%} (OWNER-DECISIONS 409, \"I'd say it's LTS4 north of R\")"
        )
    return found
