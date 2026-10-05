"""The Mass Ride capacity column: what VALIDATE reads back before a promotion.

`segment.mass_capacity_rpm` is written by the segment writer from
`routemaker.massflow` (OWNER-DECISIONS 325-327, 387) and read by the stress tiles
(`core.stress_tiles`, the `rpm` property) and by the route's coloured sections
(`core.routing`). The tiles carry it silently and the map colours by it, so a
pass that wrote nothing, or wrote it wrongly, would promote a Mass Ride map of
one colour (or the old LTS map, as the tiles fall back without the column).
`assert_mass_capacity` is the sentinel, as `run.assert_long_trails` is for the
long trails: the figure is on nearly every road and path row, and its
distribution is plausible.

Kept in a module of its own so a rebuild bundle that touches `pipeline.run` and
`pipeline.schema` merges around it.
"""

from __future__ import annotations

from typing import NamedTuple

from routemaker.massflow import MIN_USABLE_WIDTH_M, RPM_PER_METRE

from .schema import MASS_CAPACITY_COLUMN, validate_schema_name

# The share of road rows, and of path rows, that must carry a figure. A row has
# none only where `routemaker.massflow` could not read a width (no `highway`, or a
# class it has no default for); nearly every row has one.
MIN_SHARE = 0.98

# The plausible range of a road's figure: no row under one lane's worth of the
# narrowest usable width (a bicycle's own lane), none over a 40 m carriageway.
FLOOR_RPM = round(MIN_USABLE_WIDTH_M * RPM_PER_METRE)
CEILING_RPM = round(40 * RPM_PER_METRE)

# The median road, riders a minute: a two-lane street is about 200 and a one-way
# street or alley about 100, and most of the region is residential. Wide
# enough that a rebuild of the regional extract is never refused for being a
# little different, narrow enough to catch a model that came out in the wrong
# units (a factor of 60) or a constant of zero. Measured on the live table's
# widths and lanes before the first rebuild (docs/DEVELOPMENT.md).
MEDIAN_RANGE_RPM = (90, 260)


class CapacitySummary(NamedTuple):
    """What VALIDATE reads of the capacity column."""

    road_rows: int
    road_with: int
    path_rows: int
    path_with: int
    road_min: int | None
    road_max: int | None
    road_median: float | None


def capacity_summary(schema: str) -> CapacitySummary:
    """Count the staging schema's road and path rows, and those with a figure."""
    from django.db import connection

    validate_schema_name(schema)
    col = MASS_CAPACITY_COLUMN
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT count(*) FILTER (WHERE map_class = 'road' AND NOT is_trail_class),
                       count({col}) FILTER (WHERE map_class = 'road' AND NOT is_trail_class),
                       count(*) FILTER (WHERE is_trail_class),
                       count({col}) FILTER (WHERE is_trail_class),
                       min({col}) FILTER (WHERE map_class = 'road' AND NOT is_trail_class),
                       max({col}) FILTER (WHERE map_class = 'road' AND NOT is_trail_class),
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY {col})
                           FILTER (WHERE map_class = 'road' AND NOT is_trail_class)
                FROM {schema}.segment"""
        )
        return CapacitySummary(*cursor.fetchone())


def problems(summary: CapacitySummary, min_share: float = MIN_SHARE) -> list[str]:
    """Why the column is not fit to promote; empty when it is."""
    found = []
    for name, rows, have in (
        ("road", summary.road_rows, summary.road_with),
        ("path", summary.path_rows, summary.path_with),
    ):
        if rows and have / rows < min_share:
            found.append(
                f"only {have} of {rows} {name} rows carry a capacity, under {min_share:.0%}: "
                "the capacity was not written (or the width could not be read)"
            )
    if summary.road_with:
        if summary.road_min < FLOOR_RPM or summary.road_max > CEILING_RPM:
            found.append(
                f"road capacities run {summary.road_min} to {summary.road_max} riders a minute, "
                f"outside the plausible {FLOOR_RPM} to {CEILING_RPM}"
            )
        low, high = MEDIAN_RANGE_RPM
        if not low <= summary.road_median <= high:
            found.append(
                f"the median road carries {summary.road_median:.0f} riders a minute, outside "
                f"{low} to {high}: the model's units or constants are wrong"
            )
    return found
