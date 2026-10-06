"""`manage.py load_access_overrides`, and the owner's file of 2026-09-26 it loads.

The owner's answers of 2026-09-26 correct OSM's `bicycle=no` on twelve ways -
Key Bridge's two Virginia approaches, and the 11th Street local span's south
landing with its run onto Martin Luther King Jr Avenue SE - and the plan's one
audited path for an access correction is an approved `Override` row. These
tests hold the file to what the owner said, and the command to what the admin
path writes: the row, approved, with an audit entry for the add and for the
approval, attributed to the instance admin named by `--actor`, and nothing at
all the second time.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.commands.load_access_overrides import ACTOR_NOTE

REPO = Path(__file__).resolve().parents[1]
OWNER_FILE = REPO / "fixtures" / "overrides" / "2026-09-26-owner-bicycle-access.json"

# Typed in by hand from the owner's answers, not read from the file.
KEY_BRIDGE_VIRGINIA_APPROACHES = {50426889, 116044202}
ELEVENTH_STREET_SOUTH_LANDING = {546095996, 546096006, 546095995, 546095994}
# The rest of that landing, which the owner ruled on in a second answer the
# same day: three more 11th Street SE ways and Martin Luther King Jr Avenue SE.
ELEVENTH_STREET_LANDING_ONWARD = {546095992, 546095991, 546095993, 589551026, 371431399, 589551027}
# Chain Bridge's District approach, which must never appear in an override file
# that opens ways: Canal Road NW (397297433, 469107787, 50773201), to which the
# owner said "No", and the Clara Barton Parkway (889043769), which was not part
# of that question and stays as OSM tags it, with no owner answer recorded.
CHAIN_BRIDGE_DC_APPROACH = {397297433, 469107787, 50773201, 889043769}


def owner_rows() -> list[dict]:
    return json.loads(OWNER_FILE.read_text())["rows"]


class TestTheOwnersFile:
    def test_it_opens_exactly_the_ways_the_owner_named(self) -> None:
        ways = {row["osm_way_id"] for row in owner_rows()}
        assert ways == (
            KEY_BRIDGE_VIRGINIA_APPROACHES
            | ELEVENTH_STREET_SOUTH_LANDING
            | ELEVENTH_STREET_LANDING_ONWARD
        )
        assert not ways & CHAIN_BRIDGE_DC_APPROACH

    def test_every_row_is_a_bicycle_grant_with_the_decision_and_its_date(self) -> None:
        for row in owner_rows():
            assert row["kind"] == "access"
            assert row["value"] == {"bicycle": "yes"}
            assert "2026-09-26" in row["reason"]
            assert row["evidence"].strip()

    def test_the_owners_words_are_quoted(self) -> None:
        by_way = {row["osm_way_id"]: row["reason"] for row in owner_rows()}
        for way in KEY_BRIDGE_VIRGINIA_APPROACHES:
            assert "Bikes are legal, but there's a side path" in by_way[way]
        for way in ELEVENTH_STREET_SOUTH_LANDING:
            assert "Yes, legal for all" in by_way[way]
        for way in ELEVENTH_STREET_LANDING_ONWARD:
            assert "Legal for all. It might be discouraged as it's a very busy road" in by_way[way]

    def test_a_road_that_might_be_discouraged_is_still_opened_not_barred(self) -> None:
        """ "Legal for all. It might be discouraged": the discouragement is not
        an access decision, so those rows grant exactly what the others do."""
        values = {row["osm_way_id"]: row["value"] for row in owner_rows()}
        for way in ELEVENTH_STREET_LANDING_ONWARD:
            assert values[way] == {"bicycle": "yes"}

    def test_a_second_load_after_the_file_grew_adds_only_the_new_rows(self, admin, tmp_path):
        """The file grew from six rows to twelve on 2026-09-26. A deployment
        that loaded the first six loads the grown file and gains six rows, not
        twelve, and audits only those."""
        from core.models import AuditLogEntry, Override

        document = json.loads(OWNER_FILE.read_text())
        first = tmp_path / "first.json"
        first.write_text(json.dumps({**document, "rows": document["rows"][:6]}))
        load(str(first), "--actor", str(admin.discord_user_id), "--confirm")
        assert Override.objects.count() == 6
        load(str(OWNER_FILE), "--actor", str(admin.discord_user_id), "--confirm")
        assert Override.objects.count() == len(owner_rows()) == 12
        assert AuditLogEntry.objects.count() == 2 * 12


CAPITOL_FILE = REPO / "fixtures" / "overrides" / "2026-09-30-owner-capitol-drives.json"
# Typed in from the survey of the AOC polygon, not read from the file.
CAPITOL_CIRCLE_DRIVE = {6054909, 6054780, 6061713, 297214549, 1013992304}
CAPITOL_PEDESTRIAN_DRIVES = {903994651, 903994652, 904481923, 904481924}
# A pedestrian area on the grounds (area=yes): upstream does not route it.
CAPITOL_PLAZA = 1263873629


EAST_FILE = REPO / "fixtures" / "overrides" / "2026-09-30-owner-arterials-east-of-anacostia.json"
STRESS_FILE = REPO / "fixtures" / "overrides" / "2026-09-27-owner-stress.json"
# Typed in from the survey, not read from the file (OWNER-DECISIONS 144).
EAST_STRUCK = {
    # "11th St SE"
    546095991,
    546095992,
    546095993,
    546095994,
    546095995,
    546095996,
    546096006,
    # "Ridge Rd SE"
    6054136,
    203010872,
    203010879,
    590581494,
    590581503,
    590581523,
    661646845,
    661647036,
    695842773,
    1111067879,
    1409720439,
    1526267910,
    1526267933,
    # "River bridges": Benning Road, the Douglass Bridge, Whitney Young Memorial Bridge
    135146249,
    910656491,
    50716085,
    130714970,
}
# Already approved in the 2026-09-27 file: MLK Jr Ave SE at 4 (a different
# tier, so left out) and Pennsylvania Ave SE at 5 (left to that file).
EAST_ALREADY_CURATED = {
    371431399,
    589551026,
    589551027,
    50715834,
    696737927,
    919160290,
    936339897,
    946400435,
    1120042712,
}


class TestTheArterialsEastOfTheAnacostiaFile:
    """OWNER-DECISIONS 141 (b) and 144."""

    def rows(self) -> list[dict]:
        return json.loads(EAST_FILE.read_text())["rows"]

    def test_it_parses_as_approved_hidden_tier_5_rows(self) -> None:
        from core.management.commands.load_access_overrides import parse_file

        rows = parse_file(EAST_FILE.read_text(), EAST_FILE.name)
        assert len(rows) == 772
        for row in rows:
            assert row["kind"] == "stress"
            value = row["value"]
            assert value["tier"] == 5
            assert value["visibility"] == "hidden"
            assert value["annotation_status"] == "approved"
            assert "public_note" not in value
            assert value["adjustment_id"].startswith("east-anacostia-")

    def test_the_struck_and_curated_ways_are_left_out(self) -> None:
        ways = {row["osm_way_id"] for row in self.rows()}
        assert not ways & EAST_STRUCK
        assert not ways & EAST_ALREADY_CURATED
        curated = {r["osm_way_id"] for r in json.loads(STRESS_FILE.read_text())["rows"]}
        assert not ways & curated

    def test_every_row_quotes_items_141_and_144(self) -> None:
        document = json.loads(EAST_FILE.read_text())
        assert "PROPOSED" not in json.dumps(document)
        for row in self.rows():
            assert (
                "I d put most of the Arterials east of the Anacostia river as avoid"
                in row["reason"]
            )
            assert '"River bridges"' in row["reason"]

    def test_it_loads_beside_the_curated_tiers_without_a_conflict(self, admin) -> None:
        from core.models import Override

        load(str(STRESS_FILE), "--actor", str(admin.discord_user_id), "--confirm")
        before = Override.objects.count()
        out = load(str(EAST_FILE), "--actor", str(admin.discord_user_id))
        assert out.count("create: way ") == 772
        assert Override.objects.count() == before


class TestTheCapitolDrivesFile:
    """OWNER-DECISIONS 130, "Yes, open them"."""

    def rows(self) -> dict[int, dict]:
        return {r["osm_way_id"]: r for r in json.loads(CAPITOL_FILE.read_text())["rows"]}

    def test_the_private_drives_are_opened_through_not_only_to_bicycles(self) -> None:
        rows = self.rows()
        assert CAPITOL_CIRCLE_DRIVE <= set(rows)
        drives = [r for r in rows.values() if "access" in r["value"]]
        assert len(drives) == 25
        for r in drives:
            # bicycle=yes alone leaves upstream's destination-only flag on.
            assert r["value"] == {"access": "permissive", "bicycle": "yes", "motor_vehicle": "no"}

    def test_the_pedestrian_drives_get_bicycle_yes_and_the_plazas_nothing(self) -> None:
        rows = self.rows()
        pedestrian = {w for w, r in rows.items() if r["value"] == {"bicycle": "yes"}}
        assert pedestrian == CAPITOL_PEDESTRIAN_DRIVES
        assert CAPITOL_PLAZA not in rows
        assert len(rows) == 29

    def test_every_row_quotes_the_owner(self) -> None:
        for r in self.rows().values():
            assert r["kind"] == "access"
            assert '"Yes, open them"' in r["reason"]
            assert "2026-09-30" in r["reason"]

    def test_a_dry_run_would_create_every_row_and_writes_nothing(self, admin) -> None:
        from core.models import AuditLogEntry, Override

        out = load(str(CAPITOL_FILE), "--actor", str(admin.discord_user_id))
        assert out.count("create: way ") == 29
        assert "dry run: nothing written" in out
        assert Override.objects.count() == AuditLogEntry.objects.count() == 0


@pytest.fixture
def admin(db):
    from core.models import User

    return User.objects.create(discord_user_id=881001, is_instance_admin=True)


def load(*args: str, stdin: str | None = None) -> str:
    out = io.StringIO()
    if stdin is not None:
        import sys

        old, sys.stdin = sys.stdin, io.StringIO(stdin)
        try:
            call_command("load_access_overrides", *args, stdout=out)
        finally:
            sys.stdin = old
    else:
        call_command("load_access_overrides", *args, stdout=out)
    return out.getvalue()


# A stress row's adjustment fields (pipeline.overrides.stress_value_problem).
ADJUSTMENT = {
    "tier": 5,
    "adjustment_id": "a-stretch",
    "category": "sightlines",
    "visibility": "public",
    "annotation_status": "proposed",
    "display": "route_only",
    "public_note": "Off-ramp traffic merges in at a blind corner.",
}

ROW = {
    "kind": "access",
    "osm_way_id": 42,
    "value": {"bicycle": "yes"},
    "reason": "r",
    "evidence": "e",
}


def write_rows(tmp_path, rows) -> str:
    path = tmp_path / "rows.json"
    path.write_text(json.dumps({"version": 1, "rows": rows}))
    return str(path)


def counts() -> tuple[int, int]:
    from core.models import AuditLogEntry, Override

    return Override.objects.count(), AuditLogEntry.objects.count()


@pytest.mark.django_db
class TestTheCommand:
    def test_a_dry_run_writes_nothing(self, admin) -> None:
        output = load(str(OWNER_FILE), "--actor", str(admin.discord_user_id))
        assert counts() == (0, 0)
        assert "dry run" in output
        assert output.count("create:") == len(owner_rows())

    def test_confirm_writes_approved_rows_audited_to_the_actor(self, admin) -> None:
        from core.models import AuditLogEntry, Override

        load(str(OWNER_FILE), "--actor", str(admin.discord_user_id), "--confirm")

        rows = list(Override.objects.order_by("osm_way_id"))
        assert {row.osm_way_id for row in rows} == {r["osm_way_id"] for r in owner_rows()}
        by_way = {r["osm_way_id"]: r for r in owner_rows()}
        for row in rows:
            source = by_way[row.osm_way_id]
            assert row.kind == "access" and row.value == {"bicycle": "yes"}
            assert row.approved and row.approved_at is not None
            assert (row.reason, row.evidence) == (source["reason"], source["evidence"])
            entries = AuditLogEntry.objects.filter(model="override", object_id=str(row.pk))
            assert sorted(entries.values_list("action", flat=True)) == ["add", "approve"]
            for entry in entries:
                assert entry.outcome == AuditLogEntry.Outcome.ALLOWED
                assert (entry.actor_id, entry.actor_user_id) == (admin.pk, admin.pk)
                # Attributed to a name typed on the command line, and every
                # entry says that is all it is.
                assert ACTOR_NOTE in entry.detail
            # A row the loader created had no proposal before it, so its
            # approval claims to have replaced nothing.
            assert "were:" not in entries.get(action="approve").detail

    def test_the_actor_note_says_the_actor_is_unproven(self) -> None:
        """What the owner's decision needs each entry to say: the actor is the
        one named by `--actor`, and nothing authenticated it."""
        assert "--actor" in ACTOR_NOTE and "not authenticated" in ACTOR_NOTE

    def test_loading_twice_is_a_no_op(self, admin) -> None:
        load(str(OWNER_FILE), "--actor", str(admin.discord_user_id), "--confirm")
        after_first = counts()
        output = load(str(OWNER_FILE), "--actor", str(admin.discord_user_id), "--confirm")
        assert counts() == after_first
        assert output.count("present:") == len(owner_rows())

    def test_the_file_can_come_from_standard_input(self, admin) -> None:
        """The api image carries `src/` and not `fixtures/`."""
        load("-", "--actor", str(admin.discord_user_id), "--confirm", stdin=OWNER_FILE.read_text())
        assert counts()[0] == len(owner_rows())

    def test_an_unapproved_matching_row_is_approved_not_duplicated(self, admin) -> None:
        from core.models import AuditLogEntry, Override

        way = owner_rows()[0]["osm_way_id"]
        proposal = Override.objects.create(
            kind="access", osm_way_id=way, value={"bicycle": "yes"}, reason="r", evidence="e"
        )
        load(str(OWNER_FILE), "--actor", str(admin.discord_user_id), "--confirm")
        proposal.refresh_from_db()
        assert proposal.approved and proposal.approved_at is not None
        assert Override.objects.filter(osm_way_id=way).count() == 1
        actions = AuditLogEntry.objects.filter(object_id=str(proposal.pk))
        assert list(actions.values_list("action", flat=True)) == ["approve"]
        # What the row now says is why it was approved - the file's decision -
        # and what the proposer wrote is kept in the approval's audit entry.
        source = owner_rows()[0]
        assert (proposal.reason, proposal.evidence) == (source["reason"], source["evidence"])
        detail = actions.get().detail
        assert json.dumps("r") in detail and json.dumps("e") in detail
        assert ACTOR_NOTE in detail

    def test_a_pending_proposal_that_disagrees_is_left_pending(self, admin, tmp_path) -> None:
        """An unapproved row on the same way with another value is somebody's
        proposal, not a decision: the file's row is created beside it, and the
        proposal is neither approved nor a reason to refuse the file."""
        from core.models import Override

        proposal = Override.objects.create(
            kind="access", osm_way_id=42, value={"bicycle": "no"}, reason="r", evidence="e"
        )
        load(write_rows(tmp_path, [ROW]), "--actor", str(admin.discord_user_id), "--confirm")
        proposal.refresh_from_db()
        assert not proposal.approved and proposal.approved_at is None
        approved = Override.objects.filter(osm_way_id=42, approved=True)
        assert [row.value for row in approved] == [{"bicycle": "yes"}]

    @pytest.mark.parametrize(
        "other",
        [
            # Another access key on the same way: compatible, not a conflict.
            {"kind": "access", "value": {"foot": "yes"}},
            # The same key with the same answer, beside another key.
            {"kind": "access", "value": {"bicycle": "yes", "foot": "no"}},
            # Not an access row at all, whatever its value says.
            {"kind": "stress", "value": {"bicycle": "no"}},
            {"kind": "stress", "value": {"bicycle": "yes"}},
        ],
    )
    def test_an_approved_row_that_does_not_answer_the_same_key_differently(
        self, admin, tmp_path, other
    ) -> None:
        """Only an approved access row writing one of the file's keys to a
        different value is a conflict. Anything else on the way is left alone
        and the file's row is created beside it."""
        from core.models import Override

        Override.objects.create(osm_way_id=42, reason="r", evidence="e", approved=True, **other)
        output = load(
            write_rows(tmp_path, [ROW]), "--actor", str(admin.discord_user_id), "--confirm"
        )
        assert "create: way 42" in output
        assert Override.objects.filter(osm_way_id=42).count() == 2
        assert Override.objects.filter(
            kind="access", osm_way_id=42, value={"bicycle": "yes"}, approved=True
        ).exists()

    def test_the_pipeline_applies_what_was_loaded(self, admin, tmp_path) -> None:
        """Through the real APPLY_OVERRIDES stage, reading the database."""
        from pipeline.rebuild import Stage
        from pipeline.run import RebuildContext, build_handlers

        class Way:
            def __init__(self, osm_id: int) -> None:
                self.osm_id = osm_id
                self.tags = {"highway": "trunk", "bicycle": "no", "foot": "no"}

        load(str(OWNER_FILE), "--actor", str(admin.discord_user_id), "--confirm")
        context = RebuildContext(
            source_pbf=tmp_path / "source.osm.pbf",
            work_dir=tmp_path / "work",
            reference_dir=tmp_path / "reference",
        )
        context.ways = [Way(row["osm_way_id"]) for row in owner_rows()] + [Way(397297433)]
        build_handlers(context)[Stage.APPLY_OVERRIDES]()

        tags = {way.osm_id: way.tags for way in context.ways}
        for row in owner_rows():
            assert tags[row["osm_way_id"]]["bicycle"] == "yes"
        assert tags[397297433]["bicycle"] == "no", "Chain Bridge's DC approach stays barred"
        assert context.override_report.access == len(owner_rows())


@pytest.mark.django_db
class TestWhatTheCommandRefuses:
    ROW = ROW

    def write(self, tmp_path, rows) -> str:
        return write_rows(tmp_path, rows)

    @pytest.mark.parametrize(
        "flags",
        [
            {"is_instance_admin": False},
            {"is_instance_admin": True, "is_banned": True},
            {"is_instance_admin": True, "is_deleted": True},
        ],
    )
    def test_an_actor_who_is_not_an_active_instance_admin(self, tmp_path, flags) -> None:
        from core.models import AuditLogEntry, Override, User

        user = User.objects.create(discord_user_id=881002, **flags)
        with pytest.raises(CommandError, match="not an active instance admin"):
            load(self.write(tmp_path, [self.ROW]), "--actor", "881002", "--confirm")
        assert Override.objects.count() == 0
        refusal = AuditLogEntry.objects.get()
        assert refusal.outcome == AuditLogEntry.Outcome.REFUSED
        assert refusal.actor_user_id == user.pk
        assert ACTOR_NOTE in refusal.detail

    def test_a_refused_dry_run_writes_nothing(self, tmp_path) -> None:
        """A dry run is not an attempt, so even its refusal is not audited: it
        is what an operator runs to read the plan against a live database."""
        from core.models import User

        User.objects.create(discord_user_id=881003)
        with pytest.raises(CommandError, match="not an active instance admin"):
            load(self.write(tmp_path, [self.ROW]), "--actor", "881003")
        assert counts() == (0, 0)

    def test_an_actor_nobody_is(self, tmp_path) -> None:
        with pytest.raises(CommandError, match="no account"):
            load(self.write(tmp_path, [self.ROW]), "--actor", "881999", "--confirm")
        assert counts() == (0, 0)

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"value": {"highway": "cycleway"}}, "not an access key"),
            ({"kind": "jurisdiction"}, "kind must be one of"),
            ({"kind": "stress"}, "names its adjustment"),
            ({"kind": "stress", "value": {"tier": 5}}, "names its adjustment"),
            ({"kind": "stress", "value": {**ADJUSTMENT, "tier": 6}}, "tier must be 1 to 5"),
            ({"kind": "stress", "value": {**ADJUSTMENT, "tier": 0}}, "tier must be 1 to 5"),
            ({"kind": "stress", "value": {**ADJUSTMENT, "tier": "5"}}, "tier is an integer"),
            ({"kind": "stress", "value": {**ADJUSTMENT, "tier": True}}, "tier is an integer"),
            ({"kind": "stress", "value": {**ADJUSTMENT, "bicycle": "no"}}, "has no"),
            ({"kind": "stress", "value": {**ADJUSTMENT, "category": "x"}}, "category must be"),
            ({"kind": "stress", "value": {**ADJUSTMENT, "visibility": "x"}}, "visibility must"),
            (
                {"kind": "stress", "value": {**ADJUSTMENT, "annotation_status": "x"}},
                "annotation_status must",
            ),
            ({"kind": "stress", "value": {**ADJUSTMENT, "adjustment_id": "A b"}}, "adjustment_id"),
            (
                {"kind": "stress", "value": {**ADJUSTMENT, "public_note": "Locals speed here."}},
                "never a neighbourhood or its people",
            ),
            ({"osm_way_id": 0}, "positive integer"),
            # Only the two kinds the pipeline applies (mutation review r1, L6).
            ({"kind": "tier", "value": {"tier": 5}}, "kind must be one of"),
            ({"kind": "Access"}, "kind must be one of"),
            ({"reason": " "}, "reason is required"),
            ({"evidence": " "}, "evidence is required"),
            ({"evidence": None}, "evidence is required"),
            ({"value": {"bicycle": ""}}, "non-empty string"),
            ({"value": {"bicycle": 1}}, "non-empty string"),
            ({"value": {}}, "non-empty object"),
            ({"value": ["bicycle"]}, "non-empty object"),
            ({"osm_way_id": True}, "positive integer"),
            ({"osm_way_id": "42"}, "positive integer"),
            ({"osm_way_id": -42}, "positive integer"),
        ],
    )
    def test_a_malformed_row_refuses_the_whole_file(self, admin, tmp_path, change, message):
        good = dict(self.ROW, osm_way_id=41)
        bad = {**self.ROW, **change}
        with pytest.raises(CommandError, match=message):
            load(
                self.write(tmp_path, [good, bad]),
                "--actor",
                str(admin.discord_user_id),
                "--confirm",
            )
        assert counts() == (0, 0)

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("{not json", "is not JSON"),
            (json.dumps({"version": 2, "rows": [ROW]}), "not a version 1"),
            (json.dumps([ROW]), "not a version 1"),
            (json.dumps({"version": 1, "rows": []}), "has no rows"),
            (json.dumps({"version": 1}), "has no rows"),
            (json.dumps({"version": 1, "rows": ["x"]}), "is not an object"),
        ],
        ids=["not-json", "version-2", "a-bare-list", "no-rows", "rows-absent", "row-not-object"],
    )
    def test_a_malformed_file_is_refused_before_anything_is_written(
        self, admin, tmp_path, text, message
    ) -> None:
        path = tmp_path / "rows.json"
        path.write_text(text)
        with pytest.raises(CommandError, match=message):
            load(str(path), "--actor", str(admin.discord_user_id), "--confirm")
        assert counts() == (0, 0)

    def test_a_way_named_twice(self, admin, tmp_path) -> None:
        with pytest.raises(CommandError, match="twice"):
            load(self.write(tmp_path, [self.ROW, self.ROW]), "--actor", str(admin.discord_user_id))

    def test_an_approved_row_that_disagrees(self, admin, tmp_path) -> None:
        from core.models import Override

        Override.objects.create(
            kind="access",
            osm_way_id=42,
            value={"bicycle": "no"},
            reason="r",
            evidence="e",
            approved=True,
        )
        with pytest.raises(CommandError, match="disagrees"):
            load(
                self.write(tmp_path, [self.ROW]), "--actor", str(admin.discord_user_id), "--confirm"
            )
        assert Override.objects.count() == 1


@pytest.mark.django_db
def test_a_stress_row_loads_as_an_approved_stress_override(tmp_path) -> None:
    from core.models import Override, User

    admin = User.objects.create(discord_user_id=881111, is_instance_admin=True)
    row = {
        "kind": "stress",
        "osm_way_id": 42,
        "value": ADJUSTMENT,
        "reason": "r",
        "evidence": "e",
    }
    path = tmp_path / "stress.json"
    path.write_text(
        json.dumps(
            {"version": 1, "rows": [row, {**row, "kind": "access", "value": {"bicycle": "yes"}}]}
        )
    )
    call_command(
        "load_overrides",
        str(path),
        "--actor",
        str(admin.discord_user_id),
        "--confirm",
        stdout=io.StringIO(),
    )
    stress = Override.objects.get(kind="stress")
    assert (stress.osm_way_id, stress.value, stress.approved) == (42, ADJUSTMENT, True)
    assert Override.objects.filter(kind="access", osm_way_id=42).exists(), "one way, two kinds"
    # A second run is a no-op; a different tier on the same way is a conflict.
    call_command(
        "load_overrides",
        str(path),
        "--actor",
        str(admin.discord_user_id),
        "--confirm",
        stdout=io.StringIO(),
    )
    assert Override.objects.count() == 2
    path.write_text(
        json.dumps({"version": 1, "rows": [{**row, "value": {**ADJUSTMENT, "tier": 4}}]})
    )
    with pytest.raises(CommandError, match="disagrees"):
        call_command(
            "load_overrides", str(path), "--actor", str(admin.discord_user_id), "--confirm"
        )


@pytest.mark.django_db
class TestStressAdjustments:
    """The adjustment fields of a stress row (the owner, 2026-09-27: "something
    clickable as a link to why", "perhaps hidden")."""

    @pytest.fixture
    def admin(self):
        from core.models import User

        return User.objects.create(discord_user_id=881112, is_instance_admin=True)

    def rows(self, *values: dict) -> list[dict]:
        return [
            {"kind": "stress", "osm_way_id": 100 + i, "value": v, "reason": "r", "evidence": "e"}
            for i, v in enumerate(values)
        ]

    def test_the_ways_of_one_adjustment_must_agree(self, admin, tmp_path) -> None:
        rows = self.rows(ADJUSTMENT, {**ADJUSTMENT, "public_note": "Another note."})
        with pytest.raises(CommandError, match="also row 0"):
            load(write_rows(tmp_path, rows), "--actor", str(admin.discord_user_id))
        rows = self.rows(ADJUSTMENT, {**ADJUSTMENT, "tier": 4})
        with pytest.raises(CommandError, match="also row 0"):
            load(write_rows(tmp_path, rows), "--actor", str(admin.discord_user_id))

    def test_two_adjustments_may_differ(self, admin, tmp_path) -> None:
        rows = self.rows(ADJUSTMENT, {**ADJUSTMENT, "adjustment_id": "b", "tier": 2})
        load(write_rows(tmp_path, rows), "--actor", str(admin.discord_user_id), "--confirm")
        assert counts()[0] == 2

    def test_a_down_adjustment_loads(self, admin, tmp_path) -> None:
        from core.models import Override

        down = {**ADJUSTMENT, "tier": 1, "category": "better_among_alternatives"}
        load(
            write_rows(tmp_path, self.rows(down)),
            "--actor",
            str(admin.discord_user_id),
            "--confirm",
        )
        assert Override.objects.get().value["tier"] == 1

    def test_a_hidden_adjustment_may_have_no_note(self, admin, tmp_path) -> None:
        hidden = {k: v for k, v in ADJUSTMENT.items() if k != "public_note"}
        hidden["visibility"] = "hidden"
        load(write_rows(tmp_path, self.rows(hidden)), "--actor", str(admin.discord_user_id))

    def test_new_fields_on_the_same_tier_update_the_row_in_place(self, admin, tmp_path) -> None:
        from core.models import AuditLogEntry, Override

        path = write_rows(tmp_path, self.rows(ADJUSTMENT))
        load(path, "--actor", str(admin.discord_user_id), "--confirm")
        (row,) = Override.objects.all()
        approved = {**ADJUSTMENT, "annotation_status": "approved"}
        # The owner's words and the evidence for the approval are the new
        # row's, not the old one's (L3).
        path = write_rows(
            tmp_path,
            [
                {**row, "reason": "Approved as written.", "evidence": "owner, 2026-09-28"}
                for row in self.rows(approved)
            ],
        )
        assert "update: way 100" in load(path, "--actor", str(admin.discord_user_id))
        assert Override.objects.get().value == ADJUSTMENT, "a dry run writes nothing"
        load(path, "--actor", str(admin.discord_user_id), "--confirm")
        (after,) = Override.objects.all()
        assert (after.pk, after.value, after.approved) == (row.pk, approved, True)
        assert (after.reason, after.evidence) == ("Approved as written.", "owner, 2026-09-28")
        change = AuditLogEntry.objects.get(action="change")
        assert '"proposed"' in change.detail and '"approved"' in change.detail
        assert "update" not in load(path, "--actor", str(admin.discord_user_id)), "then present"

    def test_a_legacy_row_is_updated_to_the_adjustment(self, admin, tmp_path) -> None:
        from core.models import Override

        Override.objects.create(
            kind="stress",
            osm_way_id=100,
            value={"tier": 5},
            reason="r",
            evidence="e",
            approved=True,
        )
        load(
            write_rows(tmp_path, self.rows(ADJUSTMENT)),
            "--actor",
            str(admin.discord_user_id),
            "--confirm",
        )
        assert Override.objects.get().value == ADJUSTMENT

    def test_a_different_tier_is_still_a_conflict(self, admin, tmp_path) -> None:
        from core.models import Override

        Override.objects.create(
            kind="stress",
            osm_way_id=100,
            value={**ADJUSTMENT, "tier": 4},
            reason="r",
            evidence="e",
            approved=True,
        )
        with pytest.raises(CommandError, match="disagrees"):
            load(
                write_rows(tmp_path, self.rows(ADJUSTMENT)),
                "--actor",
                str(admin.discord_user_id),
                "--confirm",
            )
        assert Override.objects.get().value["tier"] == 4


@pytest.mark.django_db
def test_a_file_of_block_corrections_only_has_nothing_to_load(admin, tmp_path) -> None:
    """OWNER-DECISIONS 197: the Canal Road and Whitehurst Freeway file withholds two
    DC blocks' speed, which the rebuild reads from the image (`agency_blocks`). The
    loader, given every file in fixtures/overrides/, writes nothing for it."""
    path = REPO / "fixtures" / "overrides" / "2026-10-02-owner-canal-whitehurst.json"
    output = load(str(path), "--actor", str(admin.discord_user_id), "--confirm")
    assert "has no rows to load" in output
    assert counts() == (0, 0)
    # A file with neither rows nor block corrections is still refused.
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"version": 1, "rows": [], "agency_blocks": []}))
    with pytest.raises(CommandError, match="has no rows"):
        load(str(empty), "--actor", str(admin.discord_user_id))


# --- Retiring rows a later decision withdraws (OWNER-DECISIONS 432, 433) ----------

DESIGNATED = {"kind": "access", "osm_way_id": 42, "value": {"bicycle": "designated"}}


def write_file(tmp_path, rows, retire, name="retire.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps({"version": 1, "rows": rows, "retire": retire}))
    return str(path)


@pytest.mark.django_db
class TestRetire:
    def test_a_retired_row_is_deleted_audited_and_its_replacement_loaded(self, admin, tmp_path):
        """433: the north sidewalk's bicycle=designated row is withdrawn and the way
        closed in one load, which a plain file would refuse as a conflict."""
        from core.models import AuditLogEntry, Override

        actor = str(admin.discord_user_id)
        load(
            write_rows(tmp_path, [{**DESIGNATED, "reason": "r", "evidence": "e"}]),
            "--actor",
            actor,
            "--confirm",
        )
        (old,) = Override.objects.all()
        closing = {
            "kind": "access",
            "osm_way_id": 42,
            "value": {"bicycle": "no"},
            "reason": "433",
            "evidence": "e",
        }
        with pytest.raises(CommandError, match="disagrees"):
            load(write_rows(tmp_path, [closing]), "--actor", actor)
        path = write_file(tmp_path, [closing], [{**DESIGNATED, "reason": "OWNER-DECISIONS 433"}])
        dry = load(path, "--actor", actor)
        assert f"retire: way 42 {{'bicycle': 'designated'}} (override {old.pk})" in dry
        assert "create: way 42" in dry and Override.objects.count() == 1
        load(path, "--actor", actor, "--confirm")
        (new,) = Override.objects.all()
        assert new.value == {"bicycle": "no"} and new.approved and new.pk != old.pk
        deleted = AuditLogEntry.objects.get(action="delete", object_id=str(old.pk))
        assert "retired" in deleted.detail and "OWNER-DECISIONS 433" in deleted.detail
        assert ACTOR_NOTE in deleted.detail
        # Again: nothing to retire, the new row present.
        again = load(path, "--actor", actor, "--confirm")
        assert "absent: way 42" in again and "present: way 42" in again
        assert Override.objects.count() == 1

    def test_only_the_exact_value_is_retired(self, admin, tmp_path):
        from core.models import Override

        actor = str(admin.discord_user_id)
        load(
            write_rows(
                tmp_path,
                [{**DESIGNATED, "value": {"bicycle": "yes"}, "reason": "r", "evidence": "e"}],
            ),
            "--actor",
            actor,
            "--confirm",
        )
        load(
            write_file(tmp_path, [], [{**DESIGNATED, "reason": "x"}]), "--actor", actor, "--confirm"
        )
        assert [o.value for o in Override.objects.all()] == [{"bicycle": "yes"}]

    def test_a_stress_row_is_retired_and_a_retire_only_file_loads(self, admin, tmp_path):
        """433's 23 Montgomery Planning rows: retired, nothing new loaded."""
        from core.models import Override

        actor = str(admin.discord_user_id)
        value = {**ADJUSTMENT, "annotation_status": "approved"}
        stress = [
            {"kind": "stress", "osm_way_id": w, "value": value, "reason": "r", "evidence": "e"}
            for w in (7, 8)
        ]
        load(write_rows(tmp_path, stress), "--actor", actor, "--confirm")
        out = load(
            write_file(
                tmp_path, [], [{"kind": "stress", "osm_way_id": 7, "value": value, "reason": "433"}]
            ),
            "--actor",
            actor,
            "--confirm",
        )
        assert "retired 1 rows" in out
        assert [o.osm_way_id for o in Override.objects.all()] == [8]

    @pytest.mark.parametrize(
        "entry, problem",
        [
            ({"kind": "access", "osm_way_id": 1, "value": {"bicycle": "yes"}}, "reason"),
            (
                {"kind": "other", "osm_way_id": 1, "value": {"bicycle": "yes"}, "reason": "r"},
                "kind",
            ),
            (
                {"kind": "access", "osm_way_id": 0, "value": {"bicycle": "yes"}, "reason": "r"},
                "osm_way_id",
            ),
            ({"kind": "access", "osm_way_id": 1, "value": {}, "reason": "r"}, "value"),
        ],
    )
    def test_a_malformed_retire_entry_is_refused(self, admin, tmp_path, entry, problem):
        with pytest.raises(CommandError, match=problem):
            load(write_file(tmp_path, [], [entry]), "--actor", str(admin.discord_user_id))


class TestTheRetiringFiles:
    """The checked-in files that retire rows (OWNER-DECISIONS 432, 433)."""

    def test_432_retires_the_five_south_capitol_avoid_rows(self):
        from core.management.commands.load_access_overrides import parse_retired

        text = EAST_FILE.read_text()
        retired = parse_retired(text, EAST_FILE.name)
        assert {r["osm_way_id"] for r in retired} == {
            468820704,
            590525532,
            455234174,
            468820714,
            1528642818,
        }
        assert all(r["value"]["tier"] == 5 and "432" in r["reason"] for r in retired)
        assert not {r["osm_way_id"] for r in json.loads(text)["rows"]} & {
            r["osm_way_id"] for r in retired
        }

    def test_433_retires_the_23_veirs_mill_moco_rows_and_keeps_the_rest(self):
        from core.management.commands.load_access_overrides import parse_file, parse_retired

        moco = REPO / "fixtures" / "overrides" / "2026-10-01-owner-moco-lts5-avoid.json"
        text = moco.read_text()
        retired = parse_retired(text, moco.name)
        assert len(retired) == 23
        assert {r["value"]["adjustment_id"] for r in retired} == {"moco-lts5-veirs-mill-road"}
        rows = parse_file(text, moco.name)
        assert len(rows) == 386
        assert not any(r["value"]["adjustment_id"] == "moco-lts5-veirs-mill-road" for r in rows)
        assert all("433" in r["reason"] for r in retired)

    def test_437_reopens_the_military_ways_and_retires_saint_elizabeths_avoid_rows(
        self, admin, tmp_path
    ):
        """OWNER-DECISIONS 437.6, 437a-c: 55 bicycle=yes rows and Saint Elizabeths Rd SE
        at tier 4, which first withdraws the two Avoid rows the east-of-the-Anacostia
        file loaded on 2026-09-30 (that file no longer carries them)."""
        from core.management.commands.load_access_overrides import parse_retired
        from core.models import Override

        path = REPO / "fixtures" / "overrides" / "2026-10-06-owner-military-reopenings.json"
        text = path.read_text()
        retired = parse_retired(text, path.name)
        assert {r["osm_way_id"] for r in retired} == {316866053, 1181165198}
        actor = str(admin.discord_user_id)
        # The two rows as the live database holds them since the 2026-09-30 load.
        old = [{**r, "reason": "141", "evidence": "e"} for r in retired]
        load(write_rows(tmp_path, old), "--actor", actor, "--confirm")
        assert Override.objects.count() == 2
        dry = load(str(path), "--actor", actor)
        assert dry.count("retire: way ") == 2 and dry.count("create: way ") == 57
        assert "disagrees" not in dry and Override.objects.count() == 2
        load(str(path), "--actor", actor, "--confirm")
        assert Override.objects.count() == 57
        tiers = set(
            Override.objects.filter(
                kind="stress", osm_way_id__in=[316866053, 1181165198]
            ).values_list("value__tier", flat=True)
        )
        assert tiers == {4}
