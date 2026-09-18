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

"Valhalla derives from the corrected value" is true of the tag as written and
was not true of what the graph ended up saying, on the one class of way where
something else writes the same key. The crossings fixture's per-way legality
column reaches the extract as `rm:bridge_bicycle`, and the transform turns it
into `bicycle=no` (legality false) or `bicycle=yes` (legality true, through
`bridge_may_be_granted`, which reads `access` and `vehicle` and never the
bicycle keys - by design, since a legality row *is* a correction to OSM's own
`bicycle` tagging). So on an eighteen-row fixture bridge, whichever value an
approved row wrote was overwritten by the checked-in file. The audited table is
the plan's sole path for an access correction and it outranks the fixture, so
`apply_access` reports the ways it wrote a bicycle key onto and `run.inject_tags`
withholds `rm:bridge_bicycle` on exactly those ways, on every variant: the
fixture keeps its say wherever no reviewer has overruled it, and loses it where
one has.

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

# The subset of those keys that states whether a bicycle may use the way at all,
# and so the subset the crossings fixture's legality column competes with: the
# transform writes `bicycle` from `rm:bridge_bicycle` and reads none of these in
# deciding whether it may. A row writing one of them on a fixture bridge is a
# reviewer overruling the checked-in file, which is what supersedes it.
#
# `access` and `oneway:bicycle` are deliberately not here. `access=no` is not a
# claim about the bicycle key - the transform's grant already refuses to widen
# over it, so the two do not collide - and `oneway:bicycle` says which direction
# may be ridden, not whether the way may be.
BICYCLE_ACCESS_KEYS = frozenset({"bicycle", "bicycle:forward", "bicycle:backward"})

# The kinds the three appliers below handle, which is what `run.apply_overrides`
# refuses an approved row outside of. A kind no applier handles is a row that was
# written, reviewed and approved and then quietly did nothing - the exact failure
# the whole stage exists to end - and the model's `Kind` choices are not a guard:
# they are enforced on a form, not by the column, and a fourth kind added there
# without an applier here would be inert rather than refused.
HANDLED_KINDS = frozenset({"access", "stress", "jurisdiction"})


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
    # Ways where an approved access override wrote a bicycle key onto a way the
    # crossings fixture also has a legality opinion about, so the fixture's
    # `rm:bridge_bicycle` was withheld and the reviewed row is what the graph
    # carries. Counted separately from `access` rather than folded into it,
    # because it is not another correction applied: it is the same correction
    # taking effect over a checked-in file, which is the thing an operator
    # reading this report wants named.
    fixture_rows_superseded: int = 0

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


def apply_access(ways: Sequence, overrides: Iterable[Override]) -> tuple[int, list[int], list[int]]:
    """Rewrite tags on the ways an access override names.

    Written onto the way's working copy (`Way.tags`), which is not by itself
    what reaches Valhalla: `write_extract` rebuilds every way's tags from the
    source PBF, so what lands in a variant extract is the diff `run.inject_tags`
    hands it. That diff is taken against `Way.source_tags` - the tags the source
    carried - which is what carries the correction into all three variants and
    into the tag transform that derives access from it.

    Taken against the working copy instead, as it was until the diff moved, the
    correction cancelled against itself: this function wrote `bicycle=yes`,
    `variants.inject` handed the same tags back, and no variant extract carried
    the key at all. An approved, reviewed, cross-guild correction changed
    nothing about the graph.

    Returns (applied, unmatched way ids, ways a bicycle key was written onto).
    The third list is what lets `run.inject_tags` withhold the crossings
    fixture's `rm:bridge_bicycle` on those ways: the transform writes `bicycle`
    from that tag without consulting the bicycle keys, so on a fixture bridge
    the checked-in file overwrote whatever a reviewer had approved, in both
    directions. Recorded here rather than recomputed there because this is the
    only place that knows which keys a row actually wrote.
    """
    by_id = {way.osm_id: way for way in ways}
    applied = 0
    unmatched: list[int] = []
    superseding: list[int] = []

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
            if key in BICYCLE_ACCESS_KEYS and override.osm_way_id not in superseding:
                superseding.append(override.osm_way_id)
        applied += 1

    return applied, unmatched, superseding


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
            # The count's provenance travels with the way, not with the tier:
            # an overridden segment was still touched by whichever agency's
            # count reached it, and the published derivative asks which
            # segments a source touched, not which ones it decided.
            volume_source=getattr(current, "volume_source", None),
            volume_aadt=getattr(current, "volume_aadt", None),
            volume_year=getattr(current, "volume_year", None),
        )
        applied += 1

    return applied, unmatched


def apply_jurisdiction(ways: Sequence, overrides: Iterable[Override]) -> tuple[int, list[int]]:
    """Replace the authority assignment on the ways a jurisdiction override names.

    In memory and no further, today. The `_jurisdictions` key this writes has no
    reader: it is deliberately excluded from the variant extracts (an underscore
    key is not an OSM key and `run.inject_tags` filters the whole prefix out),
    the tag transform never sees it, and the segment table has no jurisdiction
    column for it to be written into. So an approved jurisdiction override is
    counted, logged and applied to this process's copy of the way, and nothing
    downstream of the rebuild can observe it.

    Kept rather than removed because the assignment itself - `jurisdiction.assign_way`
    and `run.authorities_for` - is real and tested, and what is missing is the
    consumer: a column on the segment table, which the permit workflow reads.
    Recorded in handoff.md section 7 against PLAN.md:28 and :151 so it is a
    named gap rather than a stage that looks wired.
    """
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
