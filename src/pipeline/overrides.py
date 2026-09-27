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
`apply_access` reports, per way, the directions an approved row wrote a bicycle
key for, and `run.inject_tags` withholds `rm:bridge_bicycle` where a row has
overruled the fixture in both, on every variant: the fixture keeps its say
wherever no reviewer has overruled it, and loses it where one has.

In both, because the fixture's legality is bidirectional and a row need not be.
A row writing only `bicycle:forward=no` on a bridge the fixture opens over
OSM's own `bicycle=no` has said nothing about the other direction; withholding
the tag there took the grant away backward too, and served the bridge barred
both ways. Kept, the transform writes the plain `bicycle` key from the fixture
and Valhalla's own transform lets `bicycle:forward` and `bicycle:backward`
override it one direction at a time, which is the row's reach exactly.

Unapproved rows are inert rather than applied-and-flagged. Approval crosses
guilds - a correction to a Virginia parkway is not Arlington's to make alone -
so an unapproved row is a proposal, and a proposal that changed the graph while
it waited would make the review meaningless.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

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
# reviewer overruling the checked-in file, which is what supersedes it - in the
# directions the key speaks for and no others. The fixture writes only the plain
# `bicycle` key, and Valhalla's transform reads `bicycle:forward` and
# `bicycle:backward` after it, each overriding one direction, so a directional
# row overrules the fixture in its own direction whether or not the fixture's
# tag is emitted, and the fixture still decides the other.
#
# `access` and `oneway:bicycle` are deliberately not here. `access=no` is not a
# claim about the bicycle key - the transform's grant already refuses to widen
# over it, so the two do not collide - and `oneway:bicycle` says which direction
# may be ridden, not whether the way may be.
FORWARD = "forward"
BACKWARD = "backward"
BOTH_DIRECTIONS = frozenset({FORWARD, BACKWARD})
BICYCLE_ACCESS_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "bicycle": BOTH_DIRECTIONS,
        "bicycle:forward": frozenset({FORWARD}),
        "bicycle:backward": frozenset({BACKWARD}),
    }
)

# The kinds the three appliers below handle, which is what `run.apply_overrides`
# refuses an approved row outside of. A kind no applier handles is a row that was
# written, reviewed and approved and then quietly did nothing - the exact failure
# the whole stage exists to end - and the model's `Kind` choices are not a guard:
# they are enforced on a form, not by the column, and a fourth kind added there
# without an applier here would be inert rather than refused.
HANDLED_KINDS = frozenset({"access", "stress", "jurisdiction"})


class OverrideRefused(ValueError):
    """An approved row asks for something an override may not do."""


# A stress row's value: the tier, and why the stretch deviates from the tier
# its tags give it (`routemaker.stress.StressAdjustment`; the owner's request of
# 2026-09-27 for a clickable "why", perhaps hidden). One adjustment may span
# several ways, which share its id and everything but the way.
STRESS_REQUIRED_KEYS = frozenset(
    {"tier", "adjustment_id", "category", "visibility", "annotation_status", "display"}
)
STRESS_KEYS = STRESS_REQUIRED_KEYS | {"public_note"}
STRESS_TIER_MIN, STRESS_TIER_MAX = 1, 5
# Stable, readable, and safe in a URL, a tile attribute and a CSS selector.
ADJUSTMENT_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
ADJUSTMENT_ID_MAX = 64
PUBLIC_NOTE_MAX = 200
# The owner's rule for a public note: it describes the road and its traffic,
# never a neighbourhood or its people. Review is the rule's real guard; this
# refuses the words a note that broke it would most likely use.
PUBLIC_NOTE_REFUSED_WORDS = re.compile(
    r"\b(neighbou?rhoods?|residents?|locals?|communit(?:y|ies)|people|crime|ward|"
    r"homeless|gangs?|poor|wealthy|rich)\b",
    re.IGNORECASE,
)


def stress_value_problem(value: object) -> str | None:
    """Why `value` is not a stress row's value, or None if it is.

    Shared by the loader, which refuses the file, and by `apply_stress`, which
    refuses the rebuild, so an admin-typed row meets the same rule as a file.
    """
    from routemaker.stress import (
        ADJUSTMENT_CATEGORIES,
        ADJUSTMENT_DISPLAYS,
        ADJUSTMENT_VISIBILITIES,
        ANNOTATION_STATUSES,
    )

    if not isinstance(value, dict):
        return "a stress value is an object"
    missing = STRESS_REQUIRED_KEYS - set(value)
    if missing:
        return f"a stress value names its adjustment; missing {sorted(missing)}"
    extra = set(value) - STRESS_KEYS
    if extra:
        return f"a stress value has no {sorted(extra)}; its keys are {sorted(STRESS_KEYS)}"
    tier = value["tier"]
    if not isinstance(tier, int) or isinstance(tier, bool):
        return "a stress value's tier is an integer"
    if not STRESS_TIER_MIN <= tier <= STRESS_TIER_MAX:
        return f"tier must be {STRESS_TIER_MIN} to {STRESS_TIER_MAX}, not {tier}"
    adjustment_id = value["adjustment_id"]
    if (
        not isinstance(adjustment_id, str)
        or len(adjustment_id) > ADJUSTMENT_ID_MAX
        or not ADJUSTMENT_ID.fullmatch(adjustment_id)
    ):
        return (
            f"adjustment_id is lower-case words joined by hyphens, at most "
            f"{ADJUSTMENT_ID_MAX} characters, not {adjustment_id!r}"
        )
    for key, allowed in (
        ("category", ADJUSTMENT_CATEGORIES),
        ("visibility", ADJUSTMENT_VISIBILITIES),
        ("annotation_status", ANNOTATION_STATUSES),
        ("display", ADJUSTMENT_DISPLAYS),
    ):
        if value[key] not in allowed:
            return f"{key} must be one of {list(allowed)}, not {value[key]!r}"
    if "public_note" in value:
        note = value["public_note"]
        if not isinstance(note, str) or not note.strip() or note != note.strip():
            return "public_note is non-empty text without surrounding space, or absent"
        if len(note) > PUBLIC_NOTE_MAX:
            return f"public_note is at most {PUBLIC_NOTE_MAX} characters, not {len(note)}"
        refused = PUBLIC_NOTE_REFUSED_WORDS.search(note)
        if refused:
            return (
                f"public_note says {refused.group(0)!r}: a note describes the road and its "
                "traffic, never a neighbourhood or its people"
            )
    return None


def stress_adjustment(override: Override, computed):
    """The row's adjustment, for a way the classifier gave `computed`.

    A row without an adjustment id predates the adjustment fields (typed into
    the admin as `{"tier": n}`). It still sets the tier, and is carried as a
    hidden adjustment named for its way, so nothing unreviewed is ever shown.
    """
    from routemaker.stress import Stress, StressAdjustment

    value = override.value
    if "adjustment_id" not in value:
        tier = value.get("tier")
        if (
            not isinstance(tier, int)
            or isinstance(tier, bool)
            or not (STRESS_TIER_MIN <= tier <= STRESS_TIER_MAX)
        ):
            raise OverrideRefused(
                f"stress override on way {override.osm_way_id} has no tier from "
                f"{STRESS_TIER_MIN} to {STRESS_TIER_MAX}: {value!r}"
            )
        return StressAdjustment(
            adjustment_id=f"way-{override.osm_way_id}",
            tier=Stress(tier),
            computed_tier=computed,
            category="other",
            visibility="hidden",
            annotation_status="proposed",
        )
    problem = stress_value_problem(value)
    if problem:
        raise OverrideRefused(f"stress override on way {override.osm_way_id}: {problem}")
    return StressAdjustment(
        adjustment_id=value["adjustment_id"],
        tier=Stress(value["tier"]),
        computed_tier=computed,
        category=value["category"],
        visibility=value["visibility"],
        annotation_status=value["annotation_status"],
        public_note=value.get("public_note"),
        display=value["display"],
    )


@dataclass(frozen=True)
class Override:
    """One approved correction, independent of Django so this stays testable."""

    kind: str
    osm_way_id: int
    value: dict
    # The approved row's own reason, for provenance (a stress row's tier is
    # recorded with it); not part of what the row changes.
    reason: str = ""


@dataclass(frozen=True)
class OverrideReport:
    """What was applied, for the rebuild log and the run row's detail.

    It was written by the override stage and read by nothing: the per-way INFO
    lines were the whole trail, and the run row an operator reads first said
    nothing about whether a single reviewed correction was in force. `summary`
    is what reaches both, from `run.apply_overrides` and the weekly task.
    """

    access: int = 0
    stress: int = 0
    jurisdiction: int = 0
    unmatched_way_ids: tuple[int, ...] = ()
    # Ways where an approved access override wrote a bicycle key onto a way the
    # crossings fixture also has a legality opinion about, so the reviewed row
    # is what the graph carries in the directions it wrote - the fixture's
    # `rm:bridge_bicycle` withheld where that is both, kept for the other
    # direction where it is one. Counted separately from `access` rather than
    # folded into it, because it is not another correction applied: it is the same correction
    # taking effect over a checked-in file, which is the thing an operator
    # reading this report wants named.
    fixture_rows_superseded: int = 0

    @property
    def total(self) -> int:
        return self.access + self.stress + self.jurisdiction

    # How many unmatched way ids the summary names before it says how many more.
    # The run row's detail is what the operations page shows in a table cell,
    # and the full list is already in the warning `run.apply_overrides` logs.
    SUMMARY_WAY_IDS = 20

    def summary(self) -> str:
        """One line for the rebuild log and the run row's detail.

        Every field, because each answers a different question an operator has
        after a rebuild: whether the reviewed corrections are in force at all,
        which kind, which approved rows reached no way in this week's extract,
        and whether any overruled the checked-in crossings fixture.
        """
        unmatched = self.unmatched_way_ids
        named = ", ".join(str(way_id) for way_id in unmatched[: self.SUMMARY_WAY_IDS])
        if len(unmatched) > self.SUMMARY_WAY_IDS:
            named += f" and {len(unmatched) - self.SUMMARY_WAY_IDS} more"
        return (
            f"overrides applied: {self.access} access, {self.stress} stress, "
            f"{self.jurisdiction} jurisdiction; {self.fixture_rows_superseded} checked-in "
            f"crossing rows superseded; {len(unmatched)} approved rows matched no way"
            + (f" ({named})" if unmatched else "")
        )


def load_approved(model=None) -> list[Override]:
    """Approved rows from the database, as plain values.

    Filtered in the query rather than in Python: an unapproved row must not
    travel into the pipeline at all, so that no later stage can decide to apply
    one.
    """
    if model is None:
        from core.models import Override as model

    return [
        Override(kind=row.kind, osm_way_id=row.osm_way_id, value=row.value, reason=row.reason or "")
        for row in model.objects.filter(approved=True).order_by("osm_way_id", "id")
    ]


def apply_access(
    ways: Sequence, overrides: Iterable[Override]
) -> tuple[int, list[int], dict[int, frozenset[str]]]:
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

    Returns (applied, unmatched way ids, {way id: directions a bicycle key was
    written for}). The mapping is what lets `run.inject_tags` withhold the
    crossings fixture's `rm:bridge_bicycle` where a reviewer overruled it: the
    transform writes `bicycle` from that tag without consulting the bicycle
    keys, so on a fixture bridge the checked-in file overwrote a plain
    `bicycle` row in both directions. Directions rather than way ids, because
    a `bicycle:forward` row leaves the fixture the backward direction, and
    unioned across rows, so one row per direction adds up to both. Recorded
    here rather than recomputed there because this is the only place that
    knows which keys a row actually wrote.
    """
    by_id = {way.osm_id: way for way in ways}
    applied = 0
    unmatched: list[int] = []
    superseding: dict[int, frozenset[str]] = {}

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
            if key in BICYCLE_ACCESS_KEYS:
                superseding[override.osm_way_id] = (
                    superseding.get(override.osm_way_id, frozenset()) | BICYCLE_ACCESS_KEYS[key]
                )
        applied += 1

    return applied, unmatched, superseding


def apply_stress(stress_by_way: dict, overrides: Iterable[Override]) -> tuple[int, list[int]]:
    """Replace a classified tier where an approved row says otherwise.

    After classification rather than before, because a corrected tier cannot be
    fed back through the classifier: there is no set of tags the rule "this road
    is LTS2, whatever the table says" corresponds to.

    Up or down: a curated tier below the classifier's is a down-adjustment, and
    allowed. The result carries the adjustment (`StressResult.adjustment`),
    whose direction is taken against the classifier's tier.
    """
    from routemaker.stress import StressResult

    applied = 0
    unmatched: list[int] = []
    # The classifier's tier, before any row on the way replaced it.
    computed: dict[int, object] = {}

    for override in overrides:
        if override.kind != "stress":
            continue
        current = stress_by_way.get(override.osm_way_id)
        if current is None:
            unmatched.append(override.osm_way_id)
            continue
        computed.setdefault(override.osm_way_id, current.tier)
        adjustment = stress_adjustment(override, computed[override.osm_way_id])
        stress_by_way[override.osm_way_id] = StressResult(
            tier=adjustment.tier,
            # The provenance says an override produced it and names the
            # adjustment, so a reviewer comparing a tier against crash history
            # is not left thinking the classifier reached it from the tags. The
            # row's reason is not copied here: it quotes the owner, and it is
            # for the audit trail, never for anything a rider can read.
            rule=f"override: stress adjustment {adjustment.adjustment_id}",
            adjustment=adjustment,
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
