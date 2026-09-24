"""Approved override rows, applied during preprocessing.

The override table is the plan's sole path for access corrections. Until the
stage these tests cover existed, it was a table the admin could edit and no stage
ever read: a row could be written, reviewed and approved, and the graph was built
exactly as if it were not there.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rebuild_fixtures import write_reference_data

from pipeline.overrides import (
    Override,
    OverrideRefused,
    apply_access,
    apply_jurisdiction,
    apply_stress,
    load_approved,
)
from routemaker.stress import Stress, StressResult


class Way:
    def __init__(self, osm_id: int, **tags: str) -> None:
        self.osm_id = osm_id
        self.tags = dict(tags)


def test_an_access_override_rewrites_the_tag_before_the_transform() -> None:
    """Applied before the extract is written, so Valhalla derives its access
    attributes from the corrected value rather than from the original."""
    way = Way(1, highway="secondary", bicycle="no")
    applied, unmatched, superseding = apply_access(
        [way], [Override("access", 1, {"bicycle": "yes"})]
    )
    assert (applied, unmatched) == (1, [])
    assert way.tags["bicycle"] == "yes"
    assert superseding == {1: frozenset({"forward", "backward"})}, (
        "and the way is reported as one the crossings fixture loses in both directions"
    )


def test_an_access_override_may_not_write_outside_the_access_keys() -> None:
    """An override is a correction to what a rider may legally do, not a second
    tag editor. `highway` sets the hierarchy level an edge lands on, whether
    shortcuts are built over it, and whether a maneuver is emitted at all."""
    way = Way(1, highway="secondary")
    with pytest.raises(OverrideRefused, match="not an access key"):
        apply_access([way], [Override("access", 1, {"highway": "residential"})])
    assert way.tags["highway"] == "secondary", "and nothing was written"


def test_a_stress_override_replaces_the_tier_and_says_so() -> None:
    """After classification rather than before: there is no set of tags the rule
    "this road is LTS2, whatever the table says" corresponds to."""
    classified = {1: StressResult(Stress.LTS4, "mixed traffic, 35 mph or above", ("maxspeed",))}
    applied, unmatched = apply_stress(
        classified, [Override("stress", 1, {"tier": 2, "reason": "resurfaced with a shoulder"})]
    )
    assert (applied, unmatched) == (1, [])
    assert classified[1].tier is Stress.LTS2
    assert "override" in classified[1].rule
    assert "resurfaced with a shoulder" in classified[1].rule
    assert classified[1].assumed == ("maxspeed",), "the provenance of the inputs survives"


def test_a_jurisdiction_override_replaces_the_authority_assignment() -> None:
    way = Way(1, highway="secondary")
    way.tags["_jurisdictions"] = "Fairfax County"
    applied, _unmatched = apply_jurisdiction(
        [way], [Override("jurisdiction", 1, {"authorities": ["National Park Service"]})]
    )
    assert applied == 1
    assert way.tags["_jurisdictions"] == "National Park Service"


def test_a_jurisdiction_override_naming_nothing_is_refused() -> None:
    """Silently clearing the authority would read as "no authority applies",
    which is the one answer the jurisdiction layer must never invent."""
    with pytest.raises(OverrideRefused, match="names no authorities"):
        apply_jurisdiction([Way(1)], [Override("jurisdiction", 1, {"authorities": []})])


def test_an_override_matching_no_way_is_reported_rather_than_dropped() -> None:
    """An approved correction that reaches nothing is a correction that is not in
    force. The clip moved, or the way was replaced upstream, and either way
    someone needs told."""
    applied, unmatched, superseding = apply_access(
        [Way(1)], [Override("access", 999, {"bicycle": "yes"})]
    )
    assert (applied, unmatched, superseding) == (0, [999], {})


def test_each_kind_only_applies_to_its_own_stage() -> None:
    """The three kinds correct three different things and land in three different
    places; a stress row reaching the access stage would be a tag written from a
    tier."""
    rows = [
        Override("access", 1, {"bicycle": "yes"}),
        Override("stress", 1, {"tier": 1}),
        Override("jurisdiction", 1, {"authorities": ["DDOT"]}),
    ]
    way = Way(1, highway="secondary")
    assert apply_access([way], rows)[0] == 1
    assert apply_stress({1: StressResult(Stress.LTS3, "x")}, rows)[0] == 1
    assert apply_jurisdiction([way], rows)[0] == 1


@pytest.mark.django_db
def test_only_approved_rows_reach_the_pipeline() -> None:
    """Approval crosses guilds - a correction to a Virginia parkway is not
    Arlington's to make alone - so an unapproved row is a proposal, and a
    proposal that changed the graph while it waited would make the review
    meaningless. Filtered in the query, so no later stage can decide to apply
    one."""
    from core.models import Override as OverrideRow

    OverrideRow.objects.create(
        kind="access",
        osm_way_id=1,
        value={"bicycle": "yes"},
        reason="r",
        evidence="e",
        approved=True,
    )
    OverrideRow.objects.create(
        kind="access",
        osm_way_id=2,
        value={"bicycle": "yes"},
        reason="r",
        evidence="e",
    )

    loaded = load_approved()
    assert [row.osm_way_id for row in loaded] == [1]


@pytest.mark.django_db
def test_the_rebuild_stage_applies_every_kind_and_reports_what_it_did(tmp_path) -> None:
    """The wiring, not the functions. The stage sits after jurisdiction tagging
    and before the extract is written, which is the one position that is late
    enough for all three kinds and early enough for the graph."""
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, build_handlers

    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
    )
    way = Way(1, highway="secondary", bicycle="no")
    context.ways = [way]
    context.stress_by_way = {1: StressResult(Stress.LTS4, "mixed traffic, 35 mph or above")}

    rows = [
        Override("access", 1, {"bicycle": "yes"}),
        Override("stress", 1, {"tier": 2, "reason": "reviewed"}),
        Override("jurisdiction", 1, {"authorities": ["DDOT"]}),
    ]
    handlers = build_handlers(context, load_overrides=lambda: rows)
    handlers[Stage.APPLY_OVERRIDES]()

    assert way.tags["bicycle"] == "yes"
    assert context.stress_by_way[1].tier is Stress.LTS2
    assert way.tags["_jurisdictions"] == "DDOT"
    assert context.override_report.total == 3
    assert context.override_report.unmatched_way_ids == ()


def test_the_stage_runs_after_jurisdiction_tagging_and_before_the_extract_is_written() -> None:
    from pipeline.rebuild import Stage

    order = list(Stage)
    assert order.index(Stage.TAG_JURISDICTIONS) < order.index(Stage.APPLY_OVERRIDES)
    assert order.index(Stage.CLASSIFY_STRESS) < order.index(Stage.APPLY_OVERRIDES)
    assert order.index(Stage.APPLY_OVERRIDES) < order.index(Stage.INJECT_TAGS)


# --- The corrected value reaching the graph -------------------------------------

# The way the source leaves open and the way the source bars.
OPEN_WAY = 100
BARRED_WAY = 200


def _write_access_extract(path: Path) -> None:
    """Two roads: one the source says nothing about, one the source bars.

    The two directions an access correction runs in. A row that bars a way the
    tags leave open has to add a key the source PBF does not carry, and a row
    that opens a way the tags bar has to overwrite one it does. Both are
    written from the source file by `write_extract`, so both are only in the
    variant extracts if `inject_tags` says so.
    """
    import osmium

    Path(path).unlink(missing_ok=True)  # osmium refuses to overwrite
    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, (lon, lat) in {
            1: (-77.02, 38.90),
            2: (-77.01, 38.90),
            3: (-77.02, 38.91),
            4: (-77.01, 38.91),
        }.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=OPEN_WAY,
                nodes=[1, 2],
                version=1,
                tags={"highway": "secondary", "name": "Open Road"},
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=BARRED_WAY,
                nodes=[3, 4],
                version=1,
                tags={"highway": "residential", "name": "Barred Road", "bicycle": "no"},
            )
        )
    finally:
        writer.close()


def _inject_through_the_real_stages(tmp_path, rows, legality=(), context_out=None):
    """APPLY_OVERRIDES then INJECT_TAGS, from the production handler set, and
    the variant extracts they leave on disk read back with the real reader."""
    from pipeline.extract import read_ways
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, ReferenceData, build_handlers
    from pipeline.variants import Variant

    source_pbf = tmp_path / "source.osm.pbf"
    _write_access_extract(source_pbf)
    reference_dir = write_reference_data(tmp_path, legality=legality)

    context = RebuildContext(
        source_pbf=source_pbf,
        work_dir=tmp_path / "work",
        reference_dir=reference_dir,
        tiles_dir=tmp_path / "tiles",
    )
    context.ways = read_ways(source_pbf)
    context.ways_by_id = {way.osm_id: way for way in context.ways}
    context.reference = ReferenceData.load(reference_dir, context.ways)

    handlers = build_handlers(context, load_overrides=lambda: rows)
    handlers[Stage.APPLY_OVERRIDES]()
    handlers[Stage.INJECT_TAGS]()

    if context_out is not None:
        context_out.append(context)
    return {
        variant: {way.osm_id: way.tags for way in read_ways(context.variant_pbf(variant))}
        for variant in Variant
    }


@pytest.mark.django_db
def test_an_approved_access_override_reaches_every_variants_extract(tmp_path) -> None:
    """The override table is the plan's sole audited path for access
    corrections, and until this passed it changed nothing about the graph.

    `apply_access` rewrote `Way.tags` in memory; `inject_tags` then wrote out
    only the keys where the variant's tags differed from `way.tags` - which is
    the object the override had just been written onto - so for the standard
    and no-trail variants, whose `inject` hands the same tags straight back, the
    correction diffed away against itself. `write_extract` rebuilds each way's
    tags from the source PBF, so a key that never reaches that diff never
    reaches the file, the transform, or Valhalla. A row could be written,
    reviewed and approved across guilds and the graph was built exactly as if
    it were not there.

    Both directions, because they fail differently: barring a way the source
    leaves open means adding a key the source PBF does not carry, and opening a
    way the source bars means overwriting one it does.
    """
    from pipeline.variants import Variant

    by_variant = _inject_through_the_real_stages(
        tmp_path,
        [
            Override("access", OPEN_WAY, {"bicycle": "no"}),
            Override("access", BARRED_WAY, {"bicycle": "yes"}),
        ],
    )

    assert set(by_variant) == set(Variant), "every variant is built from the same correction"
    for variant, tags in by_variant.items():
        assert tags[OPEN_WAY]["bicycle"] == "no", (
            f"the {variant.value} extract does not carry the approved bar on {OPEN_WAY}"
        )
        assert tags[BARRED_WAY]["bicycle"] == "yes", (
            f"the {variant.value} extract still carries the source's bar on {BARRED_WAY}"
        )
        assert tags[OPEN_WAY]["highway"] == "secondary", "and the rest of the way is untouched"
        assert tags[BARRED_WAY]["name"] == "Barred Road"


@pytest.mark.django_db
def test_an_extract_never_carries_an_underscore_key(tmp_path) -> None:
    """`_jurisdictions` is an annotation for this process, not an OSM key.

    It reaches `Way.tags` from two places - the jurisdiction stage and an
    approved jurisdiction override - and once the tag diff is taken against the
    source's tags rather than against the working copy, anything written onto
    that copy is a candidate for the file. An invented key on a real way in a
    PBF is a thing every later reader of that file has to trip over, so the
    whole prefix is filtered out of the diff.
    """
    by_variant = _inject_through_the_real_stages(
        tmp_path,
        [
            Override("access", OPEN_WAY, {"bicycle": "no"}),
            Override("jurisdiction", OPEN_WAY, {"authorities": ["DDOT", "National Park Service"]}),
        ],
    )

    for variant, tags in by_variant.items():
        written = sorted(key for way_tags in tags.values() for key in way_tags)
        assert not [key for key in written if key.startswith("_")], (
            f"the {variant.value} extract carries an internal key: {written}"
        )
        assert tags[OPEN_WAY]["bicycle"] == "no", (
            "and the filter has not swallowed the correction it sits next to"
        )


# --- The audited table against the checked-in fixture ------------------------------


def test_only_a_bicycle_key_is_reported_as_superseding_the_fixture() -> None:
    """The report is of a collision, not of an override.

    `rm:bridge_bicycle` decides the `bicycle` key and nothing else, and
    `bridge_may_be_granted` already refuses to widen over an `access`
    restriction, so a row writing only `access` collides with nothing and the
    fixture keeps its say. Reporting it anyway would withhold a checked-in
    legality row on the strength of a correction that never touched it.
    """
    ways = [Way(1, highway="secondary"), Way(2, highway="secondary"), Way(3, highway="secondary")]
    applied, _unmatched, superseding = apply_access(
        ways,
        [
            Override("access", 1, {"access": "no"}),
            Override("access", 2, {"bicycle:forward": "no", "oneway:bicycle": "yes"}),
            Override("access", 3, {"oneway:bicycle": "no"}),
        ],
    )
    assert applied == 3
    assert superseding == {2: frozenset({"forward"})}, (
        f"only the row that wrote a bicycle key, for the direction it wrote: {superseding}"
    )


@pytest.mark.django_db
def test_an_access_override_outranks_the_crossings_fixture_on_the_same_way(tmp_path) -> None:
    """Both directions of the collision the fixture used to win.

    `inject_tags` emitted `rm:bridge_bicycle` for every way the fixture has an
    opinion about, whatever the override table said, and the transform writes
    the `bicycle` key from that tag: `bicycle=no` (legality false) and, through
    `bridge_may_be_granted`, `bicycle=yes` (legality true). That guard reads
    `access` and `vehicle` and never the bicycle keys - correctly, because a
    legality row is itself a correction to OSM's `bicycle` tagging - so on all
    eighteen fixture rows the checked-in file overwrote the approved,
    cross-guild-reviewed row in whichever direction it ran. The audited table is
    the plan's sole path for an access correction (PLAN:18, :28), so the tag is
    withheld on exactly those ways, on every variant.
    """
    from pipeline.variants import Variant

    contexts: list = []
    by_variant = _inject_through_the_real_stages(
        tmp_path,
        [
            # Fixture-legal, reviewer bars it: without the fix the extract
            # carried bicycle=no *and* rm:bridge_bicycle=yes, and the transform
            # granted bicycle=yes back over the row.
            Override("access", OPEN_WAY, {"bicycle": "no"}),
            # Fixture-illegal, reviewer opens it: the `false` half writes
            # bicycle=no unconditionally, with no guard at all.
            Override("access", BARRED_WAY, {"bicycle": "yes"}),
        ],
        legality={OPEN_WAY: True, BARRED_WAY: False},
        context_out=contexts,
    )

    for variant, tags in by_variant.items():
        for way_id, expected in ((OPEN_WAY, "no"), (BARRED_WAY, "yes")):
            assert "rm:bridge_bicycle" not in tags[way_id], (
                f"the {variant.value} extract still hands the transform the fixture's "
                f"legality on way {way_id}, which is what overwrites the approved row"
            )
            assert tags[way_id]["bicycle"] == expected, (
                f"the {variant.value} extract does not carry the approved value on {way_id}"
            )
    assert set(by_variant) == set(Variant)

    report = contexts[0].override_report
    assert report.access == 2
    assert report.fixture_rows_superseded == 2, (
        "an operator reading the rebuild log is told a checked-in row was overruled"
    )
    both = frozenset({"forward", "backward"})
    assert contexts[0].bicycle_override_directions == {OPEN_WAY: both, BARRED_WAY: both}


@pytest.mark.django_db
def test_an_override_with_nothing_to_supersede_leaves_the_fixture_alone(tmp_path) -> None:
    """The withholding is scoped to the collision.

    A row writing only `access=no` says nothing about the bicycle key, and
    `bridge_may_be_granted` refuses to widen over an `access` restriction
    anyway, so the fixture's legality still reaches the transform; and a way the
    fixture has no opinion about was never a collision at all. Without this the
    fix would silently disable the crossings fixture on any bridge carrying any
    access row.
    """
    contexts: list = []
    by_variant = _inject_through_the_real_stages(
        tmp_path,
        [
            Override("access", OPEN_WAY, {"access": "no"}),
            Override("access", BARRED_WAY, {"bicycle": "yes"}),
        ],
        legality={OPEN_WAY: True},
        context_out=contexts,
    )

    for variant, tags in by_variant.items():
        assert tags[OPEN_WAY]["rm:bridge_bicycle"] == "yes", (
            f"the {variant.value} extract lost a legality row nothing overruled"
        )
        assert tags[OPEN_WAY]["access"] == "no", "and the correction itself is still there"
        assert "rm:bridge_bicycle" not in tags[BARRED_WAY], "the fixture has no opinion here"

    report = contexts[0].override_report
    assert report.fixture_rows_superseded == 0, (
        "a bicycle key on a way the fixture says nothing about supersedes nothing"
    )


@pytest.mark.django_db
def test_the_superseded_way_is_named_in_one_info_line(tmp_path, caplog) -> None:
    """A checked-in row being overruled is a thing an operator reading the
    rebuild log should be able to see per way, not only as a count."""
    import logging

    with caplog.at_level(logging.INFO, logger="pipeline.run"):
        _inject_through_the_real_stages(
            tmp_path,
            [Override("access", OPEN_WAY, {"bicycle": "no"})],
            legality={OPEN_WAY: True},
        )

    lines = [
        record.getMessage()
        for record in caplog.records
        if "crossings fixture" in record.getMessage()
    ]
    assert len(lines) == 1, lines
    assert str(OPEN_WAY) in lines[0] and "Open Road" in lines[0]


@pytest.mark.django_db
def test_an_approved_row_of_a_kind_no_applier_handles_is_refused(tmp_path) -> None:
    """A kind outside the three is a row that was written, reviewed and approved
    and then did nothing at all - the failure this stage exists to end, arriving
    a second way. The model's `Kind` choices are a form-level guard, not a column
    constraint, so a fourth kind added there without an applier here would be
    inert rather than refused. Terminal, not retried: a fifth attempt applies it
    no more than the first.
    """
    from config.procrastinate import terminal_causes
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, ValidationFailed, build_handlers

    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
    )
    context.ways = [Way(1, highway="secondary")]
    rows = [Override("surface", 1, {"surface": "asphalt"})]
    handlers = build_handlers(context, load_overrides=lambda: rows)

    with pytest.raises(ValidationFailed, match="surface") as raised:
        handlers[Stage.APPLY_OVERRIDES]()
    assert "way 1" in str(raised.value), "the row is named, not only the kind"
    assert isinstance(raised.value, terminal_causes()), "and a retry cannot fix it"
    assert context.override_report is None, "nothing was applied on the way past it"


@pytest.mark.django_db
def test_a_row_the_appliers_refuse_stops_the_rebuild_rather_than_retrying_it(tmp_path) -> None:
    """The other refusal, through the same door.

    An approved row that writes outside the access keys, or a jurisdiction row
    naming no authority, is answered by editing the row. `OverrideRefused` is a
    plain ValueError and nothing listed it as terminal, so each one was retried
    five times - five full rebuilds, hours apiece - before the alert said
    anything an operator could act on.
    """
    from config.procrastinate import terminal_causes
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, ValidationFailed, build_handlers

    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
    )
    context.ways = [Way(1, highway="secondary")]
    handlers = build_handlers(
        context, load_overrides=lambda: [Override("access", 1, {"highway": "residential"})]
    )

    with pytest.raises(ValidationFailed, match="not an access key") as raised:
        handlers[Stage.APPLY_OVERRIDES]()
    assert isinstance(raised.value, terminal_causes())
    assert context.ways[0].tags["highway"] == "secondary", "and nothing was written"


def test_a_stress_override_keeps_the_counts_provenance_beside_the_agency():
    """The override replaces the tier and the rule; the count that reached the
    way, its year and its agency are facts about the way that the override does
    not change, and the published derivative asks which segments a source
    touched. Dropping any of the three here would make an overridden segment
    look untouched by the agency whose count it carries."""
    current = StressResult(
        Stress.LTS3, "x", (), volume_source="mdot-sha", volume_aadt=12_000, volume_year=2022
    )
    rows = [Override("stress", 1, {"tier": 1, "reason": "field check"})]
    stress_by_way = {1: current}
    assert apply_stress(stress_by_way, rows)[0] == 1
    result = stress_by_way[1]
    assert result.tier is Stress.LTS1
    assert (result.volume_source, result.volume_aadt, result.volume_year) == (
        "mdot-sha",
        12_000,
        2022,
    )


# --- what the variant extracts are diffed against -------------------------------


def _per_way_tags_for(tmp_path, monkeypatch, rows) -> dict:
    """The mapping `inject_tags` hands `write_extract`, for the standard variant.

    Captured rather than read back off the file, because the file cannot tell
    the two apart: `write_extract` rebuilds every way's tags from the source
    PBF and lays this mapping over them, so a mapping that restates a tag the
    source already carries produces a byte-identical way. The mapping is the
    diff, and whether it is a diff at all is what this checks.
    """
    from pipeline import extract as extract_module
    from pipeline.extract import read_ways
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, ReferenceData, build_handlers
    from pipeline.variants import Variant

    source_pbf = tmp_path / "source.osm.pbf"
    _write_access_extract(source_pbf)
    reference_dir = write_reference_data(tmp_path)

    context = RebuildContext(
        source_pbf=source_pbf,
        work_dir=tmp_path / "work",
        reference_dir=reference_dir,
        tiles_dir=tmp_path / "tiles",
    )
    context.ways = read_ways(source_pbf)
    context.ways_by_id = {way.osm_id: way for way in context.ways}
    context.reference = ReferenceData.load(reference_dir, context.ways)

    seen: dict = {}
    real = extract_module.write_extract

    def capture(source, destination, way_tags, *args, **kwargs):
        if destination == context.variant_pbf(Variant.STANDARD):
            seen.update({way_id: dict(tags) for way_id, tags in way_tags.items()})
        return real(source, destination, way_tags, *args, **kwargs)

    monkeypatch.setattr(extract_module, "write_extract", capture)
    handlers = build_handlers(context, load_overrides=lambda: rows)
    handlers[Stage.APPLY_OVERRIDES]()
    handlers[Stage.INJECT_TAGS]()
    return seen


@pytest.mark.django_db
def test_a_way_nothing_corrected_contributes_no_osm_tags_to_the_diff(tmp_path, monkeypatch) -> None:
    """The diff is against the tags the source carried, so a way no stage wrote
    on has nothing to say about its own OSM keys.

    Diffed against an empty snapshot instead, every key the way carries reads as
    a change and the mapping becomes a restatement of the whole extract - which
    is byte-identical on the way out and so invisible in the file, but means the
    diff has stopped being a diff and an override is no longer distinguishable
    from the source's own tagging.
    """
    from pipeline.extract import DERIVED_PREFIX

    per_way = _per_way_tags_for(tmp_path, monkeypatch, rows=[])

    assert set(per_way) == {OPEN_WAY, BARRED_WAY}, per_way
    for way_id, tags in per_way.items():
        source_keys = {
            key: value for key, value in tags.items() if not key.startswith(DERIVED_PREFIX)
        }
        assert source_keys == {}, (
            f"way {way_id} is unchanged by every stage and still contributes "
            f"{source_keys} to the variant extract's tag diff"
        )


@pytest.mark.django_db
def test_an_approved_correction_is_the_only_osm_key_in_the_diff(tmp_path, monkeypatch) -> None:
    """And the other side of it: the one key a reviewer corrected is exactly
    what the diff carries, so what the extract gains over the source is the
    correction and nothing else."""
    from pipeline.extract import DERIVED_PREFIX

    per_way = _per_way_tags_for(
        tmp_path, monkeypatch, rows=[Override("access", OPEN_WAY, {"bicycle": "no"})]
    )

    corrected = {
        key: value for key, value in per_way[OPEN_WAY].items() if not key.startswith(DERIVED_PREFIX)
    }
    assert corrected == {"bicycle": "no"}, corrected
    untouched = {
        key: value
        for key, value in per_way[BARRED_WAY].items()
        if not key.startswith(DERIVED_PREFIX)
    }
    assert untouched == {}, untouched


def test_an_override_can_never_write_a_derived_key() -> None:
    """Why `inject_tags` can merge the derived tags over the corrections without
    choosing between them: the two key spaces do not meet.

    Every tag this pipeline derives is written under `rm:` (`extract.derived_tags`),
    and the only keys that reach the diff from the tag side are the ones a stage
    wrote - `apply_access`, which refuses anything outside `ACCESS_KEYS`, and
    `variants.inject`. A source key the source itself still carries is equal to
    the snapshot and never reaches the diff at all. So the merge order of
    `{**changes, **derived}` is unobservable, and it is unobservable because of
    this refusal rather than by luck - which is what makes it worth stating.
    """
    from pipeline.extract import DERIVED_PREFIX
    from pipeline.overrides import ACCESS_KEYS

    assert not any(key.startswith(DERIVED_PREFIX) for key in ACCESS_KEYS), (
        f"an access override may write a {DERIVED_PREFIX} key, so a correction and a "
        "derived value can now collide and the merge order in `inject_tags` decides "
        "which one the graph is built from"
    )
    way = Way(OPEN_WAY, highway="secondary")
    with pytest.raises(OverrideRefused, match="not an access key"):
        apply_access([way], [Override("access", OPEN_WAY, {f"{DERIVED_PREFIX}stress_tier": "1"})])
    assert way.tags == {"highway": "secondary"}, "and nothing was written"
