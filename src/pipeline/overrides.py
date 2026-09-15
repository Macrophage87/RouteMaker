"""Applying approved override rows during preprocessing.

The override table is the sole path for access corrections, and until this
existed it was a table the admin could edit and no stage ever read: a row could
be written, reviewed and approved, and the graph would be built exactly as if it
were not there.

Three kinds, and they land in different places because they are different
claims. An access override rewrites tags before the tag transform sees them, so
Valhalla derives from the corrected value. A stress override replaces the
classifier's tier after classification, because re-deriving from a corrected tier
would mean inventing the tags that would have produced it. A jurisdiction
override replaces the authority assignment, which is not a routing input at all.

Unapproved rows are inert rather than applied-and-flagged. Approval crosses
guilds - a correction to a Virginia parkway is not Arlington's to make alone -
so an unapproved row is a proposal, and a proposal that changed the graph while
it waited would make the review meaningless.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# What an access override may write. Deliberately not the whole tag space: an
# override is a correction to what a rider may legally do, not a second tag
# editor, and `highway` in particular sets the hierarchy level an edge lands on,
# whether shortcuts are built over it, and whether a maneuver is emitted at all.
ACCESS_KEYS = frozenset(
    {"bicycle", "bicycle:forward", "bicycle:backward", "access", "oneway:bicycle"}
)


class OverrideRefused(ValueError):
    """An approved row asks for something an override may not do."""


@dataclass(frozen=True)
class Override:
    """One approved correction, independent of Django so this stays testable."""

    kind: str
    osm_way_id: int
    value: dict


@dataclass(frozen=True)
class OverrideReport:
    """What was applied, for the rebuild log and the drift report."""

    access: int = 0
    stress: int = 0
    jurisdiction: int = 0
    unmatched_way_ids: tuple[int, ...] = ()

    @property
    def total(self) -> int:
        return self.access + self.stress + self.jurisdiction


def load_approved(model=None) -> list[Override]:
    """Approved rows from the database, as plain values.

    Filtered in the query rather than in Python: an unapproved row must not
    travel into the pipeline at all, so that no later stage can decide to apply
    one.
    """
    if model is None:
        from core.models import Override as model

    return [
        Override(kind=row.kind, osm_way_id=row.osm_way_id, value=row.value)
        for row in model.objects.filter(approved=True).order_by("osm_way_id", "id")
    ]


def apply_access(ways: Sequence, overrides: Iterable[Override]) -> tuple[int, list[int]]:
    """Rewrite tags on the ways an access override names.

    Applied before the tag transform, so Valhalla derives its access attributes
    from the corrected value rather than from the original.
    """
    by_id = {way.osm_id: way for way in ways}
    applied = 0
    unmatched: list[int] = []

    for override in overrides:
        if override.kind != "access":
            continue
        way = by_id.get(override.osm_way_id)
        if way is None:
            # The clip moved, or the way was replaced upstream. Reported rather
            # than skipped quietly: an approved correction that reaches nothing
            # is a correction that is not in force.
            unmatched.append(override.osm_way_id)
            continue
        for key, value in override.value.items():
            if key not in ACCESS_KEYS:
                raise OverrideRefused(
                    f"override on way {override.osm_way_id} writes {key!r}, which is not "
                    f"an access key; permitted keys are {sorted(ACCESS_KEYS)}"
                )
            way.tags[key] = str(value)
        applied += 1

    return applied, unmatched


def apply_stress(stress_by_way: dict, overrides: Iterable[Override]) -> tuple[int, list[int]]:
    """Replace a classified tier where an approved row says otherwise.

    After classification rather than before, because a corrected tier cannot be
    fed back through the classifier: there is no set of tags the rule "this road
    is LTS2, whatever the table says" corresponds to.
    """
    from routemaker.stress import Stress, StressResult

    applied = 0
    unmatched: list[int] = []

    for override in overrides:
        if override.kind != "stress":
            continue
        current = stress_by_way.get(override.osm_way_id)
        if current is None:
            unmatched.append(override.osm_way_id)
            continue
        tier = Stress(int(override.value["tier"]))
        stress_by_way[override.osm_way_id] = StressResult(
            tier=tier,
            # The provenance says an override produced it, so a reviewer
            # comparing a tier against crash history is not left thinking the
            # classifier reached it from the tags.
            rule=f"override: {override.value.get('reason', 'approved correction')}",
            assumed=getattr(current, "assumed", ()),
            volume_source=getattr(current, "volume_source", None),
        )
        applied += 1

    return applied, unmatched


def apply_jurisdiction(ways: Sequence, overrides: Iterable[Override]) -> tuple[int, list[int]]:
    """Replace the authority assignment on the ways a jurisdiction override names."""
    by_id = {way.osm_id: way for way in ways}
    applied = 0
    unmatched: list[int] = []

    for override in overrides:
        if override.kind != "jurisdiction":
            continue
        way = by_id.get(override.osm_way_id)
        if way is None:
            unmatched.append(override.osm_way_id)
            continue
        authorities = override.value.get("authorities")
        if not authorities:
            raise OverrideRefused(
                f"jurisdiction override on way {override.osm_way_id} names no authorities"
            )
        way.tags["_jurisdictions"] = ",".join(sorted(authorities))
        applied += 1

    return applied, unmatched
