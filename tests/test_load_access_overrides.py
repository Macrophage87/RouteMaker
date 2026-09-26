"""`manage.py load_access_overrides`, and the owner's file of 2026-09-26 it loads.

The owner's answers of 2026-09-26 correct OSM's `bicycle=no` on six ways - Key
Bridge's two Virginia approaches and the 11th Street local span's south landing
- and the plan's one audited path for an access correction is an approved
`Override` row. These tests hold the file to what the owner said, and the
command to what the admin path writes: the row, approved, with an audit entry
for the add and for the approval, attributed to the instance admin who ran it,
and nothing at all the second time.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

REPO = Path(__file__).resolve().parents[1]
OWNER_FILE = REPO / "fixtures" / "overrides" / "2026-09-26-owner-bicycle-access.json"

# Typed in by hand from the owner's answers, not read from the file.
KEY_BRIDGE_VIRGINIA_APPROACHES = {50426889, 116044202}
ELEVENTH_STREET_SOUTH_LANDING = {546095996, 546096006, 546095995, 546095994}
# The owner said "No" to these, on Chain Bridge's District approach: they must
# never appear in an override file that opens ways.
CHAIN_BRIDGE_DC_APPROACH = {397297433, 469107787, 50773201, 889043769}


def owner_rows() -> list[dict]:
    return json.loads(OWNER_FILE.read_text())["rows"]


class TestTheOwnersFile:
    def test_it_opens_exactly_the_ways_the_owner_named(self) -> None:
        ways = {row["osm_way_id"] for row in owner_rows()}
        assert ways == KEY_BRIDGE_VIRGINIA_APPROACHES | ELEVENTH_STREET_SOUTH_LANDING
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
    def write(self, tmp_path, rows) -> str:
        path = tmp_path / "rows.json"
        path.write_text(json.dumps({"version": 1, "rows": rows}))
        return str(path)

    ROW = {
        "kind": "access",
        "osm_way_id": 42,
        "value": {"bicycle": "yes"},
        "reason": "r",
        "evidence": "e",
    }

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
            ({"kind": "stress"}, "kind must be 'access'"),
            ({"osm_way_id": 0}, "positive integer"),
            ({"reason": " "}, "reason is required"),
            ({"value": {"bicycle": ""}}, "non-empty string"),
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
