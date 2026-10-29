"""The owner's reference LTS 4 road, read back at VALIDATE_SEGMENTS (OWNER-DECISIONS 408, 409).

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

And the owner's rating rules read back over the whole table (review 2026-10-29), so a
regression in the order the rating steps run is refused before promotion rather than left
to the unit tests: no rural road open to cars at LTS 1 without an override (the rural
floor), no Montgomery 5 at a level other than 4.5, and no road MDOT SHA bans left open
for no listed reason.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from django.db import connection

from routemaker import agency_lts

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


# --- Owner-rated stretches (OWNER-DECISIONS 432) ------------------------------------

_STRETCH_SQL = """
SELECT COALESCE(sum(len), 0), COALESCE(sum(len) FILTER (WHERE stress_tier = %s), 0)
FROM (
    SELECT ST_Length(geometry::geography) AS len,
           ST_Y(ST_LineInterpolatePoint(geometry, 0.5)) AS lat,
           stress_tier
    FROM {schema}.segment
    WHERE attr_sources -> 'blocks' ?| %s::text[] AND map_class = 'road'
) AS rows
WHERE lat BETWEEN %s AND %s
"""


@dataclass(frozen=True)
class Stretch:
    """A stretch of a street the owner gave a tier: the agency's street name
    (`ROUTENAME`), the latitudes of its ends (a row counts by its middle), the tier,
    the share of the stretch's rows that must carry it, and the decision."""

    street: str
    south_lat: float
    north_lat: float
    tier: int
    min_share: float
    decision: str

    @classmethod
    def of(cls, row: Sequence) -> Stretch:
        street, south, north, tier, share, decision = row
        return cls(str(street), float(south), float(north), int(tier), float(share), str(decision))


@dataclass(frozen=True)
class StretchTiers:
    stretch: Stretch
    total_m: float
    at_tier_m: float

    @property
    def share(self) -> float:
        return self.at_tier_m / self.total_m if self.total_m else 0.0


def stretch_tiers(schema: str, stretch: Stretch, ids: Sequence[str]) -> StretchTiers:
    """Read the stretch's rows back from the built table."""
    schema = validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(
            _STRETCH_SQL.format(schema=schema),
            [stretch.tier, list(ids), stretch.south_lat, stretch.north_lat],
        )
        total, at_tier = (float(value) for value in cursor.fetchone())
    return StretchTiers(stretch, total, at_tier)


def stretch_problems(tiers: StretchTiers) -> list[str]:
    """What is wrong with the stretch's tiers, in words; empty when it holds. Exactly the
    owner's tier: a stretch left at Avoid by a row the decision replaced is a failure."""
    s = tiers.stretch
    where = f"{s.street} from {s.south_lat:.4f} N to {s.north_lat:.4f} N"
    if tiers.total_m <= 0:
        return [f"no segment row is matched to {where}, so {s.decision} was not checked"]
    if tiers.share < s.min_share:
        return [
            f"only {tiers.share:.0%} of {where} ({_mi(tiers.at_tier_m)} of "
            f"{_mi(tiers.total_m)}) is at tier {s.tier}, under {s.min_share:.0%} "
            f"({s.decision}); an approved stress override row on its ways outranks the "
            "named corridor; load the file that retires it before the rebuild"
        ]
    return []


# --- The owner's rating rules over the whole table (review 2026-10-29) ---------------------

# How many way ids a refusal names; the count is always given.
SAMPLE_WAYS = 10

# Rural road rows at LTS 1 that no override row set. The classifier's tier on a rural road
# open to cars is raised to LTS 2 after every agency rating (`stress.rural_floor`); the
# candidates are read back here, and the caller drops those its tags exempt (a road closed to
# cars, a separated track alongside), which the table does not record.
_RURAL_LTS1_SQL = """
SELECT DISTINCT osm_way_id FROM {schema}.segment
WHERE stress_tier = 1 AND road_urban IS FALSE AND NOT is_trail_class
  AND stress_adjustment_id IS NULL AND map_class IN ('road', 'alley')
ORDER BY osm_way_id
"""

# Montgomery's 5 is our 4.5 (`agency_lts.READ_AS`; the owner, 2026-10-19), from the live
# layer or from a 2026-10-01 row: a row the county's 5 set, at any other level.
_COUNTY_FIVE_SQL = """
SELECT DISTINCT osm_way_id FROM {schema}.segment
WHERE ((stress_adjustment_id IS NULL AND starts_with(stress_rule, %s))
       OR starts_with(stress_adjustment_id, %s))
  AND NOT (stress_tier = 4 AND stress_half)
ORDER BY osm_way_id
"""

# A way MDOT SHA's 5 bans (`agency_lts.PROHIBITING_LEVELS`) still drawn as a road and with no
# access reason at all: the closure did not reach it. The caller drops the ways the closure
# listed as left open (a path or track, a bridge, an owner's override).
_OPEN_BAN_SQL = """
SELECT DISTINCT osm_way_id FROM {schema}.segment
WHERE stress_ratings -> 'agencies' @> %s::jsonb
  AND map_class IN ('road', 'alley') AND bike_access_reason IS NULL
ORDER BY osm_way_id
"""


def _way_ids(sql: str, schema: str, params: Sequence = ()) -> list[int]:
    schema = validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(sql.format(schema=schema), list(params))
        return [int(row[0]) for row in cursor.fetchall()]


def rural_lts1_ways(schema: str) -> list[int]:
    """The rural road ways at LTS 1 with no override row (`_RURAL_LTS1_SQL`)."""
    return _way_ids(_RURAL_LTS1_SQL, schema)


def county_five_prefixes() -> tuple[str, str]:
    """The rule a Montgomery 5 sets (`agency_lts.apply`) and the ids of its 2026-10-01 rows."""
    name = agency_lts.AGENCIES["moco"][0]
    row_prefix = next(p for p, source in agency_lts.ADJUSTMENT_SOURCES if source == "moco")
    return f"{agency_lts.AGENCY_RULE}: {name} LTS 5", row_prefix


def county_five_ways(schema: str) -> list[int]:
    """The ways a Montgomery 5 set at a level other than 4.5 (`_COUNTY_FIVE_SQL`)."""
    return _way_ids(_COUNTY_FIVE_SQL, schema, county_five_prefixes())


def open_ban_ways(schema: str) -> list[int]:
    """The ways an MDOT SHA ban left drawn with no access reason (`_OPEN_BAN_SQL`)."""
    bans = [
        {"agency": agency, "level": level}
        for agency, level in agency_lts.PROHIBITING_LEVELS.items()
    ]
    found: set[int] = set()
    for ban in bans:
        found.update(_way_ids(_OPEN_BAN_SQL, schema, [json.dumps([ban])]))
    return sorted(found)


def _named(ways: Sequence[int]) -> str:
    shown = ", ".join(str(way) for way in ways[:SAMPLE_WAYS])
    more = len(ways) - SAMPLE_WAYS
    if more > 0:
        shown += f", +{more} more"
    return f"{len(ways)} way{'s' if len(ways) != 1 else ''} ({shown})"


def rating_rule_problems(
    rural_lts1: Sequence[int], county_five: Sequence[int], open_bans: Sequence[int]
) -> list[str]:
    """What is wrong with the table's ratings, in words; empty when every rule holds."""
    found = []
    if rural_lts1:
        found.append(
            f"{_named(rural_lts1)} on a rural road open to cars came out LTS 1 with no "
            "override row: the owner's rural floor is LTS 2 (stress.rural_floor)"
        )
    if county_five:
        found.append(
            f"{_named(county_five)} rated 5 by Montgomery came out at a level other than "
            "4.5: the county's 5 is our 4.5 (agency_lts.READ_AS)"
        )
    if open_bans:
        found.append(
            f"{_named(open_bans)} MDOT SHA bans (its 5) are still drawn as roads with no "
            "access reason and are not listed as left open (reports/agency-prohibited.csv)"
        )
    return found
