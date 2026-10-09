"""The road panel's stress editor, phase 1 (OWNER-DECISIONS 441g, 441h, 460; core.stress_edits).

Against a real live segment table (the `segment_schemas` fixture) and the real limiter, session
middleware and CSRF check. What is pinned here: an instance admin's change applies at once, in
one transaction (the approved override row, the live rows, the edit history, the audit entry,
the tile generation and the cache), a superseded file row can never be brought back by reloading
its file, a rebuild or rollback re-applies the edits it missed, and the endpoints refuse everyone
else.
"""

from __future__ import annotations

import io
import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import Client
from django.utils import timezone
from test_ratelimit import in_one_window
from test_stress_tiles import tile_of, url

from core import ratelimit, segment_info, stress_edits, stress_tiles, tile_cache
from core.models import (
    AuditLogEntry,
    LiveEditGeneration,
    Override,
    Session,
    StressEdit,
    User,
)
from pipeline import overrides as pipeline_overrides
from routemaker.stress import Stress, StressResult

db = pytest.mark.django_db(transaction=True)

WAY = 5001
OTHER_WAY = 5002
LON, LAT = -77.0300, 38.8990
FAR = (-77.2500, 38.9900)
REASON = "PRIVATE-REASON-7731: the owner rode it and the light never lets a bike through"
RULE = "mixed traffic, 30 mph, single lane"


def make_segment(schema, way, tier=3, *, ordinal=0, lon=LON, lat=LAT, rule=RULE, **columns):
    values = {
        "osm_way_id": way,
        "ordinal": ordinal,
        "stress_tier": tier,
        "stress_rule": rule,
        **columns,
    }
    names = ", ".join(values)
    marks = ", ".join("%s" for _ in values)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment ({names}, geometry) VALUES ({marks}, "
            "ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)))",
            [*values.values(), lon, lat, lon + 0.002, lat],
        )


def live_row(schema, way=WAY, ordinal=0) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT * FROM {schema}.segment WHERE osm_way_id = %s AND ordinal = %s", [way, ordinal]
        )
        names = [d[0] for d in cursor.description]
        return dict(zip(names, cursor.fetchone(), strict=True))


@pytest.fixture(autouse=True)
def _columns():
    segment_info.forget_columns()
    yield
    segment_info.forget_columns()


@pytest.fixture
def live(segment_schemas):
    schema, _staging = segment_schemas
    make_segment(schema, WAY, 3)
    make_segment(schema, OTHER_WAY, 2, lon=FAR[0], lat=FAR[1])
    return schema


_next_id = iter(range(7000, 8000))


def make_user(*, admin=True, **fields) -> User:
    return User.objects.create(discord_user_id=next(_next_id), is_instance_admin=admin, **fields)


def sign_in(client, user):
    client.force_login(user)
    now = timezone.now()
    Session.objects.create(
        session_key=client.session.session_key,
        user=user,
        issued_epoch=user.session_epoch,
        created_at=now,
        last_seen_at=now,
    )
    return client


def spec(tier=4, **overrides) -> stress_edits.Spec:
    return stress_edits.Spec(
        tier=overrides.pop("tier", tier),
        at_least=overrides.pop("at_least", False),
        category=overrides.pop("category", "speed"),
        reason=overrides.pop("reason", REASON),
        public_note=overrides.pop("public_note", None),
        display=overrides.pop("display", "route_only"),
    )


def token(schema, way=WAY) -> str:
    columns = stress_edits.edit_columns(schema)
    rows = stress_edits.read_rows(schema, columns, [way])
    return stress_edits.token_for(rows, stress_edits._live_override([way]))


def edit(schema, admin, tier=4, way=WAY, **kwargs):
    return stress_edits.apply(admin, [way], spec(tier, **kwargs), token(schema, way))


# --- The service ---------------------------------------------------------------------


@db
class TestApply:
    def test_the_change_is_written_everywhere_in_one_go(self, live) -> None:
        admin = make_user()
        before = LiveEditGeneration.objects.count()
        result = edit(live, admin, 4)
        assert before == 0 and result.generation == 1
        assert result.ways == [{"osm_way_id": WAY, "step": 4, "changed": True}]

        row = live_row(live)
        assert row["stress_tier"] == 4
        assert row["stress_rule"].startswith("override: stress adjustment edit-")

        override = Override.objects.get()
        assert (override.kind, override.approved, override.source) == ("stress", True, "panel")
        assert override.created_by_user_id == admin.pk == override.approved_by_user_id
        assert override.reason == REASON
        assert override.superseded_by_id is None
        assert pipeline_overrides.stress_value_problem(override.value) is None
        assert override.value["adjustment_id"] == f"edit-{override.pk}"
        assert row["stress_rule"].endswith(override.value["adjustment_id"])

        history = StressEdit.objects.get()
        assert (history.action, history.override_id, history.actor_user_id) == (
            "set",
            override.pk,
            admin.pk,
        )
        assert history.before == {f"{WAY}:0": {**history.before[f"{WAY}:0"], "stress_tier": 3}}
        assert history.after[f"{WAY}:0"]["stress_tier"] == 4
        assert history.generation == 1
        assert history.applied_to == stress_edits.live_oid(live)

        entry = AuditLogEntry.objects.get(action="stress_edit")
        assert entry.outcome == "allowed" and entry.actor_user_id == admin.pk
        assert "LTS 3 -> 4" in entry.detail
        assert LiveEditGeneration.objects.get().generation == 1

    def test_the_private_reason_is_nowhere_a_rider_or_a_log_can_read(self, live) -> None:
        admin = make_user()
        edit(live, admin, 4, public_note="Heavy turning traffic at the light")
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT row_to_json(s)::text FROM {live}.segment s")
            segments = " ".join(r[0] for r in cursor.fetchall())
        logged = " ".join(
            f"{e.detail} {e.model} {e.object_id}" for e in AuditLogEntry.objects.all()
        )
        history = " ".join(json.dumps([e.before, e.after]) for e in StressEdit.objects.all())
        for place in (segments, logged, history):
            assert "PRIVATE-REASON-7731" not in place
            assert "discord" not in place.lower()
        assert "Heavy turning traffic" in segments

    def test_a_hidden_adjustment_says_only_that_the_tier_was_adjusted(self, live) -> None:
        edit(live, make_user(), 4)
        row = live_row(live)
        assert row["stress_adjustment_id"].startswith("edit-")
        for column in (
            "stress_computed_tier",
            "stress_adjustment_direction",
            "stress_adjustment_category",
            "stress_adjustment_note",
            "stress_adjustment_display",
        ):
            assert row[column] is None

    def test_a_public_note_shows_its_category_direction_and_the_tier_it_replaced(
        self, live
    ) -> None:
        edit(live, make_user(), 4, public_note="Heavy turning traffic", display="map")
        row = live_row(live)
        assert row["stress_computed_tier"] == 3
        assert row["stress_adjustment_direction"] == "up"
        assert row["stress_adjustment_category"] == "speed"
        assert row["stress_adjustment_note"] == "Heavy turning traffic"
        assert row["stress_adjustment_display"] == "map"

    def test_the_panel_says_owner_override_and_names_nobody(self, live) -> None:
        edit(live, make_user(), 2, public_note="Calm in practice", display="map")
        row = segment_info.nearest_row(LAT, LON + 0.001)
        rows = segment_info.stress_rows(row)
        assert rows[0]["value"] == "LTS 2: Fine for adults"
        assert rows[0]["source"] == segment_info.OWNER
        assert "discord" not in json.dumps(rows).lower()

    def test_a_floor_the_road_already_meets_changes_nothing(self, live) -> None:
        result = edit(live, make_user(), 2, at_least=True)
        assert result.ways[0]["changed"] is False
        row = live_row(live)
        assert (row["stress_tier"], row["stress_rule"]) == (3, RULE)
        assert row["stress_adjustment_id"] is None
        override = Override.objects.get()
        assert override.value["at_least"] is True and override.approved

    def test_a_floor_above_the_road_raises_it(self, live) -> None:
        result = edit(live, make_user(), 5, at_least=True)
        assert result.ways[0] == {"osm_way_id": WAY, "step": 5, "changed": True}
        assert live_row(live)["stress_tier"] == 5

    def test_the_same_level_again_reports_no_change(self, live) -> None:
        result = edit(live, make_user(), 3)
        assert result.ways[0]["step"] == 3

    @pytest.mark.parametrize("classifier", [1, 2, 3, 4, 5])
    @pytest.mark.parametrize("tier", [1, 2, 3, 4, 5])
    @pytest.mark.parametrize("at_least", [False, True])
    @pytest.mark.parametrize("note", [None, "A note"])
    def test_it_gives_what_the_rebuild_gives(self, classifier, tier, at_least, note) -> None:
        """`new_state` is `apply_stress` in place: same tier, same rule, same exposed columns."""
        s = spec(tier, at_least=at_least, public_note=note, display="map")
        value = s.value("edit-9")
        results = {1: StressResult(tier=Stress(classifier), rule=RULE)}
        pipeline_overrides.apply_stress(
            results, [pipeline_overrides.Override(kind="stress", osm_way_id=1, value=value)]
        )
        built = results[1]
        row = {
            "stress_tier": classifier,
            "stress_rule": RULE,
            **dict.fromkeys(stress_edits.ADJUSTMENT_COLUMNS),
        }
        state = stress_edits.new_state(row, s, "edit-9", classifier)
        assert state["stress_tier"] == int(built.tier)
        assert state["stress_rule"] == built.rule
        exposed = built.adjustment.exposed() if built.adjustment else {}
        assert state["stress_adjustment_id"] == exposed.get("adjustment_id")
        for column, key in (
            ("stress_computed_tier", "computed_tier"),
            ("stress_adjustment_direction", "direction"),
            ("stress_adjustment_category", "category"),
            ("stress_adjustment_note", "public_note"),
            ("stress_adjustment_display", "display"),
        ):
            assert state[column] == exposed.get(key)


@db
class TestRefusals:
    def test_a_stale_edit_is_refused_and_leaves_nothing(self, live) -> None:
        admin = make_user()
        stale = token(live)
        edit(live, admin, 4)
        with pytest.raises(stress_edits.Stale):
            stress_edits.apply(admin, [WAY], spec(1), stale)
        assert Override.objects.count() == 1 and StressEdit.objects.count() == 1
        assert live_row(live)["stress_tier"] == 4

    def test_a_rebuilt_table_makes_the_open_editor_stale(self, live) -> None:
        stale = token(live)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {live}.segment SET stress_tier = 2 WHERE osm_way_id = %s", [WAY]
            )
        with pytest.raises(stress_edits.Stale):
            stress_edits.apply(make_user(), [WAY], spec(4), stale)

    def test_a_failure_halfway_rolls_everything_back(self, live, monkeypatch) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("the cache write failed")

        monkeypatch.setattr(tile_cache, "rekey_after_edit", boom)
        with pytest.raises(RuntimeError):
            edit(live, make_user(), 4)
        assert Override.objects.count() == StressEdit.objects.count() == 0
        assert AuditLogEntry.objects.filter(action="stress_edit").count() == 0
        assert LiveEditGeneration.objects.count() == 0
        assert live_row(live)["stress_tier"] == 3

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"tier": 6}, "step"),
            ({"tier": 0}, "step"),
            ({"category": "mood"}, "category"),
            ({"reason": "   "}, "reason"),
            ({"reason": "x" * 501}, "reason"),
            ({"public_note": "The residents dislike it"}, "public_note"),
            ({"public_note": "n" * 201}, "public_note"),
            ({"display": "everywhere"}, "display"),
        ],
    )
    def test_a_bad_value_is_refused_naming_its_field(self, live, change, field) -> None:
        with pytest.raises(stress_edits.Invalid) as refused:
            stress_edits.apply(make_user(), [WAY], spec(**change), token(live))
        assert refused.value.field == field
        assert Override.objects.count() == 0

    def test_a_road_that_is_not_in_the_data_is_not_found(self, live) -> None:
        with pytest.raises(stress_edits.NotFound):
            stress_edits.apply(make_user(), [999], spec(), "x")

    def test_one_road_piece_at_a_time(self, live) -> None:
        with pytest.raises(stress_edits.Invalid):
            stress_edits.apply(make_user(), [WAY, OTHER_WAY], spec(), "x")

    def test_a_floor_is_refused_where_a_hidden_adjustment_hides_the_classifiers_level(
        self, live
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {live}.segment SET stress_adjustment_id = 'owner-x', "
                "stress_rule = 'override: stress adjustment owner-x' WHERE osm_way_id = %s",
                [WAY],
            )
        admin = make_user()
        with pytest.raises(stress_edits.Invalid) as refused:
            stress_edits.apply(admin, [WAY], spec(5, at_least=True), token(live))
        assert refused.value.code == "classifier_hidden" and refused.value.field == "at_least"
        # An exact level still works, and says nothing of a direction it cannot know.
        edit(live, admin, 2, public_note="Calm")
        row = live_row(live)
        assert row["stress_tier"] == 2 and row["stress_adjustment_direction"] is None


@db
class TestSupersede:
    def file_row(self, way=WAY, tier=2, **extra):
        return Override.objects.create(
            kind="stress",
            osm_way_id=way,
            value={
                "tier": tier,
                "adjustment_id": "owner-file",
                "category": "speed",
                "visibility": "hidden",
                "annotation_status": "proposed",
                "display": "route_only",
            },
            reason="the file",
            evidence="the file",
            approved=True,
            approved_at=timezone.now(),
            **extra,
        )

    def test_the_old_row_is_marked_not_unapproved(self, live) -> None:
        old = self.file_row()
        edit(live, make_user(), 4)
        old.refresh_from_db()
        new = Override.objects.get(source="panel")
        assert old.approved is True and old.superseded_by_id == new.pk
        assert old.superseded_at is not None
        assert StressEdit.objects.get().replaced_id == old.pk

    def test_the_rebuild_reads_only_the_live_row(self, live) -> None:
        self.file_row()
        edit(live, make_user(), 4)
        rows = pipeline_overrides.load_approved(fingerprints={})
        assert [r.value["tier"] for r in rows] == [4]

    def test_two_live_stress_rows_on_a_way_are_refused_by_the_database(self, live) -> None:
        self.file_row()
        with pytest.raises(IntegrityError), transaction.atomic():
            self.file_row(tier=3)

    def test_reloading_the_old_file_cannot_undo_the_edit(self, live, tmp_path) -> None:
        from core.management.commands import load_access_overrides as loader

        old = self.file_row()
        admin = make_user()
        edit(live, admin, 4)
        document = {
            "version": 1,
            "rows": [
                {
                    "kind": "stress",
                    "osm_way_id": WAY,
                    "value": old.value,
                    "reason": "the file",
                    "evidence": "the file",
                }
            ],
        }
        path = tmp_path / "old.json"
        path.write_text(json.dumps(document))
        out = io.StringIO()
        call_command(
            "load_access_overrides",
            str(path),
            actor=admin.discord_user_id,
            confirm=True,
            stdout=out,
        )
        assert "superseded: way" in out.getvalue() and "superseded by panel edit" in out.getvalue()
        old.refresh_from_db()
        assert old.approved is True and old.superseded_by_id is not None
        assert [r.value["tier"] for r in pipeline_overrides.load_approved(fingerprints={})] == [4]
        assert loader.plan(document["rows"])[0][0] == "superseded"

    def test_a_file_row_that_disagrees_with_the_edit_is_refused_naming_it(self, live) -> None:
        from core.management.commands import load_access_overrides as loader

        self.file_row()
        edit(live, make_user(), 4)
        panel = Override.objects.get(source="panel")
        newer = [
            {
                "kind": "stress",
                "osm_way_id": WAY,
                "value": {**Override.objects.first().value, "tier": 1},
            }
        ]
        with pytest.raises(CommandError) as refused:
            loader.plan(newer)
        assert f"override {panel.pk}" in str(refused.value) and "road panel" in str(refused.value)


@db
class TestUndo:
    def test_it_puts_back_what_was_there_and_reinstates_the_replaced_row(self, live) -> None:
        old = TestSupersede().file_row()
        admin = make_user()
        done = edit(live, admin, 4)
        undone = stress_edits.undo(admin, done.edit.pk)
        row = live_row(live)
        assert (row["stress_tier"], row["stress_rule"]) == (3, RULE)
        old.refresh_from_db()
        assert old.superseded_by_id is None and old.approved
        panel = Override.objects.get(source="panel")
        assert panel.superseded_by_id == old.pk
        assert undone.edit.action == "undo" and undone.edit.undoes_id == done.edit.pk
        assert undone.generation == 2
        assert [r.value["tier"] for r in pipeline_overrides.load_approved(fingerprints={})] == [2]
        assert AuditLogEntry.objects.filter(action="stress_edit_undo").count() == 1

    def test_with_no_earlier_row_the_way_is_left_with_none(self, live) -> None:
        admin = make_user()
        done = edit(live, admin, 4)
        stress_edits.undo(admin, done.edit.pk)
        assert pipeline_overrides.load_approved(fingerprints={}) == []
        assert Override.objects.get().approved is False

    def test_any_instance_admin_may_undo(self, live) -> None:
        done = edit(live, make_user(), 4)
        stress_edits.undo(make_user(), done.edit.pk)
        assert live_row(live)["stress_tier"] == 3

    def test_not_twice(self, live) -> None:
        admin = make_user()
        done = edit(live, admin, 4)
        stress_edits.undo(admin, done.edit.pk)
        with pytest.raises(stress_edits.Stale) as refused:
            stress_edits.undo(admin, done.edit.pk)
        assert refused.value.code == "already_undone"

    def test_not_after_30_minutes(self, live) -> None:
        admin = make_user()
        done = edit(live, admin, 4)
        later = done.edit.at + stress_edits.UNDO_WINDOW + timedelta(seconds=1)
        with pytest.raises(stress_edits.Stale) as refused:
            stress_edits.undo(admin, done.edit.pk, now=later)
        assert refused.value.code == "too_old"
        stress_edits.undo(admin, done.edit.pk, now=done.edit.at + stress_edits.UNDO_WINDOW)

    def test_not_after_a_later_edit_of_the_same_road(self, live) -> None:
        admin = make_user()
        first = edit(live, admin, 4)
        edit(live, admin, 5)
        with pytest.raises(stress_edits.Stale) as refused:
            stress_edits.undo(admin, first.edit.pk)
        assert refused.value.code == "later_edit"
        assert live_row(live)["stress_tier"] == 5

    def test_an_edit_of_another_road_does_not_stop_it(self, live) -> None:
        admin = make_user()
        first = edit(live, admin, 4)
        edit(live, admin, 4, way=OTHER_WAY)
        stress_edits.undo(admin, first.edit.pk)
        assert live_row(live)["stress_tier"] == 3

    def test_not_when_the_table_changed_under_it(self, live) -> None:
        admin = make_user()
        done = edit(live, admin, 4)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {live}.segment SET stress_tier = 1 WHERE osm_way_id = %s", [WAY]
            )
        with pytest.raises(stress_edits.Stale) as refused:
            stress_edits.undo(admin, done.edit.pk)
        assert refused.value.code == "table_changed"

    def test_an_undo_cannot_be_undone(self, live) -> None:
        admin = make_user()
        done = edit(live, admin, 4)
        undone = stress_edits.undo(admin, done.edit.pk)
        with pytest.raises(stress_edits.Invalid):
            stress_edits.undo(admin, undone.edit.pk)

    def test_unknown_edit(self, live) -> None:
        with pytest.raises(stress_edits.NotFound):
            stress_edits.undo(make_user(), 123456)


# --- Tiles and the cache --------------------------------------------------------------


def seed_cache(version: str, z: int, x: int, y: int) -> None:
    tile_cache.put(version, z, x, y, b"body")


@db
class TestTiles:
    def test_the_etag_carries_the_generation_and_fits_the_cache_key(self, live) -> None:
        oid, optional, generation = stress_tiles.live_state()
        plain = stress_tiles.etag_for(oid, optional, generation)
        assert generation == 0 and "-e" not in plain
        edit(live, make_user(), 4)
        _, _, generation = stress_tiles.live_state()
        edited = stress_tiles.etag_for(oid, optional, generation)
        assert generation == 1 and edited != plain and "-e1-" in edited
        assert (
            len(stress_tiles.etag_for(10**10 - 1, frozenset(stress_tiles.ETAG_LETTERS), 999999))
            < 64
        )
        from core import mass_tiles

        assert mass_tiles.etag_for(oid, optional, 1) != mass_tiles.etag_for(oid, optional, 0)
        assert len(mass_tiles.etag_for(10**10 - 1, frozenset(mass_tiles.TAG_COLUMNS), 999999)) < 64

    def test_a_304_for_the_old_tile_does_not_survive_an_edit(self, client, live) -> None:
        z, x, y = tile_of(LON, LAT, 14)
        first = client.get(url(z, x, y))
        assert first.status_code == 200
        again = client.get(url(z, x, y), HTTP_IF_NONE_MATCH=first["ETag"])
        assert again.status_code == 304
        edit(live, make_user(), 4)
        after = client.get(url(z, x, y), HTTP_IF_NONE_MATCH=first["ETag"])
        assert after.status_code == 200 and after["ETag"] != first["ETag"]

    def test_other_riders_keep_a_tile_for_five_minutes(self, client, live) -> None:
        z, x, y = tile_of(LON, LAT, 14)
        assert "max-age=300" in client.get(url(z, x, y))["Cache-Control"]

    def test_the_edit_shows_in_the_tile_at_once(self, client, live) -> None:
        from mvt import decode

        z, x, y = tile_of(LON, LAT, 14)

        def tiers() -> set:
            layers = decode(client.get(url(z, x, y)).content)
            return {
                dict(f.props).get("tier") if hasattr(f, "props") else None
                for f in layers["stress"].features
            }

        before = client.get(url(z, x, y)).content
        edit(live, make_user(), 5)
        assert client.get(url(z, x, y)).content != before
        assert tiers() is not None

    def test_only_the_tiles_over_the_road_are_deleted_and_the_rest_stay_warm(self, live) -> None:
        oid, optional, generation = stress_tiles.live_state()
        old = stress_tiles.etag_for(oid, optional, generation)
        near = [tile_of(LON, LAT, z) for z in (10, 12, 14, 16)]
        far = [tile_of(*FAR, z) for z in (12, 14, 16)]  # z10 is one tile wide of both
        for z, x, y in [*near, *far]:
            seed_cache(old, z, x, y)
        assert tile_cache.get(old, *near[0]) is not None
        edit(live, make_user(), 4)
        new = stress_tiles.etag_for(*stress_tiles.live_state()[:2], 1)
        for tile in near:
            assert tile_cache.get(old, *tile) is None
            assert tile_cache.get(new, *tile) is None
        for tile in far:
            assert tile_cache.get(old, *tile) is None
            assert tile_cache.get(new, *tile) == b"body"

    def test_a_neighbouring_tile_is_drawn_again_too(self, live) -> None:
        oid, optional, generation = stress_tiles.live_state()
        old = stress_tiles.etag_for(oid, optional, generation)
        z, x, y = tile_of(LON, LAT, 14)
        seed_cache(old, z, x + 1, y)
        edit(live, make_user(), 4)
        new = stress_tiles.etag_for(*stress_tiles.live_state()[:2], 1)
        assert tile_cache.get(new, z, x + 1, y) is None

    def test_the_mass_ride_tiles_are_re_keyed_with_them(self, live) -> None:
        from core import mass_tiles

        oid, optional, generation = stress_tiles.live_state()
        mass_old = mass_tiles.etag_for(oid, optional, generation)
        near = tile_of(LON, LAT, 13)
        far = tile_of(*FAR, 13)
        seed_cache(mass_old, *near)
        seed_cache(mass_old, *far)
        edit(live, make_user(), 4)
        mass_new = mass_tiles.etag_for(oid, optional, 1)
        assert tile_cache.get(mass_new, *near) is None
        assert tile_cache.get(mass_new, *far) == b"body"


# --- Rebuilds and rollbacks -----------------------------------------------------------


def rebuild_without_the_edit(schema) -> None:
    """The live table replaced by one a rebuild made from the rows it read before the edit."""
    from pipeline.schema import create_segment_schema, drop_segment_schema

    drop_segment_schema(schema)
    create_segment_schema(schema)
    make_segment(schema, WAY, 3)
    make_segment(schema, OTHER_WAY, 2, lon=FAR[0], lat=FAR[1])
    segment_info.forget_columns()


@db
class TestPromotion:
    def test_an_edit_made_during_a_rebuild_survives_the_swap(self, live) -> None:
        read_at = timezone.now() - timedelta(minutes=5)
        edit(live, make_user(), 4)
        rebuild_without_the_edit(live)
        assert stress_edits.after_promotion(read_at) == 1
        assert live_row(live)["stress_tier"] == 4
        new_oid = stress_edits.live_oid(live)
        assert LiveEditGeneration.objects.get(table_oid=new_oid).overrides_read_at == read_at
        assert StressEdit.objects.get().reapplied_to == [new_oid]

    def test_an_edit_the_rebuild_already_read_is_not_re_applied(self, live) -> None:
        edit(live, make_user(), 4)
        read_at = timezone.now() + timedelta(seconds=1)
        rebuild_without_the_edit(live)
        # The rebuild read the row, so its table carries the edit by its own rules; nothing here.
        assert stress_edits.after_promotion(read_at) == 0
        assert live_row(live)["stress_tier"] == 3

    def test_an_undo_during_a_rebuild_survives_the_swap(self, live) -> None:
        admin = make_user()
        done = edit(live, admin, 4)
        read_at = timezone.now() - timedelta(minutes=5)
        # The rebuild read the approved edit; its table has the override applied.
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {live}.segment SET stress_tier = 4 WHERE osm_way_id = %s", [WAY]
            )
        stress_edits.undo(admin, done.edit.pk)
        rebuild_without_the_edit(live)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {live}.segment SET stress_tier = 4 WHERE osm_way_id = %s", [WAY]
            )
        stress_edits.after_promotion(read_at)
        assert live_row(live)["stress_tier"] == 3

    def test_replaying_is_idempotent(self, live) -> None:
        edit(live, make_user(), 4)
        rebuild_without_the_edit(live)
        assert stress_edits.reapply_since(None) == 1
        assert stress_edits.reapply_since(None) == 0
        assert live_row(live)["stress_tier"] == 4

    def test_edits_replay_in_order(self, live) -> None:
        admin = make_user()
        edit(live, admin, 4)
        edit(live, admin, 5)
        rebuild_without_the_edit(live)
        stress_edits.reapply_since(None)
        assert live_row(live)["stress_tier"] == 5

    def test_a_rollback_replays_every_edit_the_older_table_never_saw(self, live) -> None:
        edit(live, make_user(), 4)
        rebuild_without_the_edit(live)
        assert stress_edits.after_rollback() == 1
        assert live_row(live)["stress_tier"] == 4

    def test_a_rollback_to_a_table_that_read_the_edit_replays_nothing(self, live) -> None:
        edit(live, make_user(), 4)
        rebuild_without_the_edit(live)
        oid = stress_edits.live_oid(live)
        LiveEditGeneration.objects.create(
            table_oid=oid, overrides_read_at=timezone.now() + timedelta(seconds=1)
        )
        assert stress_edits.after_rollback() == 0

    def test_a_failure_replaying_never_fails_the_promotion(self, live, monkeypatch) -> None:
        edit(live, make_user(), 4)
        monkeypatch.setattr(stress_edits, "reapply_since", lambda since: 1 / 0)
        assert stress_edits.after_promotion(timezone.now() - timedelta(hours=1)) == -1

    def test_perform_swap_re_applies_them(
        self, live, segment_schemas, monkeypatch, tmp_path
    ) -> None:
        from pipeline import promotion

        _live, staging = segment_schemas
        make_segment(staging, WAY, 3)
        edit(live, make_user(), 4)
        monkeypatch.setattr(promotion.tiles, "links", lambda *a, **k: None)
        monkeypatch.setattr(promotion.tiles, "promote", lambda *a, **k: None)
        monkeypatch.setattr(promotion, "upstream_states", lambda *a, **k: {})
        monkeypatch.setattr(promotion, "repoint_upstreams", lambda *a, **k: None)
        outcome = promotion.perform_swap(
            tmp_path, "b1", {}, overrides_read_at=timezone.now() - timedelta(minutes=5)
        )
        assert outcome.edits_reapplied == 1
        assert live_row(live)["stress_tier"] == 4

    def test_the_rebuild_records_when_it_read_the_overrides(self) -> None:
        from pipeline.run import RebuildContext

        assert "overrides_read_at" in RebuildContext.__dataclass_fields__


# --- The endpoints --------------------------------------------------------------------

ME, STATE, CREATE = "/api/me", "/api/stress-edits/way/{}", "/api/stress-edits"
_clients = iter(range(1, 250))


def addr() -> dict:
    return {"HTTP_X_FORWARDED_FOR": f"198.51.100.{next(_clients)}"}


def body(schema=None, **change) -> dict:
    expected = change.pop("expected", None) or (token(schema) if schema else "x")
    return {
        "osm_way_ids": [WAY],
        "step": 4,
        "at_least": False,
        "category": "speed",
        "reason": REASON,
        "expected": expected,
        **change,
    }


def post(client, url_, payload, csrf=None, **headers):
    extra = {"HTTP_X_CSRFTOKEN": csrf} if csrf else {}
    return client.post(
        url_,
        data=json.dumps(payload),
        content_type="application/json",
        **extra,
        **addr(),
        **headers,
    )


def admin_client(*, enforce=True):
    client = Client(enforce_csrf_checks=enforce)
    sign_in(client, make_user())
    assert client.get(ME, **addr()).status_code == 200
    return client, client.cookies["csrftoken"].value


@db
class TestMe:
    def test_signed_out_gets_three_no(self, client) -> None:
        r = client.get(ME, **addr())
        assert r.status_code == 200 and r.json() == {
            "signed_in": False,
            "can_change_lts": False,
            "can_suggest": False,
        }
        assert r["Cache-Control"] == "no-store" and "csrftoken" not in r.cookies

    def test_a_signed_in_non_admin_is_signed_in_and_nothing_more(self, live) -> None:
        client = sign_in(Client(), make_user(admin=False))
        r = client.get(ME, **addr())
        assert r.json() == {"signed_in": True, "can_change_lts": False, "can_suggest": False}
        assert "csrftoken" not in r.cookies

    def test_an_admin_may_and_gets_the_csrf_cookie(self, live) -> None:
        client = sign_in(Client(), make_user())
        r = client.get(ME, **addr())
        assert r.json() == {"signed_in": True, "can_change_lts": True, "can_suggest": False}
        assert "csrftoken" in r.cookies

    def test_a_banned_admin_is_signed_out_and_may_not(self, live) -> None:
        make_user()  # another admin, so this one is not the last
        user = make_user()
        client = sign_in(Client(), user)
        user.is_banned = True
        user.save()
        r = client.get(ME, **addr())
        assert r.json()["can_change_lts"] is False and r.json()["signed_in"] is False

    def test_no_name_no_id(self, live) -> None:
        user = make_user()
        text = sign_in(Client(), user).get(ME, **addr()).content.decode()
        assert str(user.discord_user_id) not in text and set(json.loads(text)) == {
            "signed_in",
            "can_change_lts",
            "can_suggest",
        }

    def test_a_foreign_page_is_refused(self, client) -> None:
        assert client.get(ME, HTTP_SEC_FETCH_SITE="cross-site", **addr()).status_code == 403


@db
class TestStateEndpoint:
    def test_signed_out_is_401_and_a_non_admin_403(self, client, live) -> None:
        assert client.get(STATE.format(WAY), **addr()).status_code == 401
        member = sign_in(Client(), make_user(admin=False))
        assert member.get(STATE.format(WAY), **addr()).status_code == 403

    def test_an_admin_gets_the_editors_starting_state(self, live) -> None:
        client, _ = admin_client()
        r = client.get(STATE.format(WAY), **addr())
        assert r.status_code == 200 and r["Cache-Control"] == "no-store"
        state = r.json()
        assert state["classifier_step"] == 3 and state["can_raise_only"] is True
        assert state["current"]["source"] == "classifier" and state["current"]["step"] == 3
        assert [s["value"] for s in state["steps"]] == [1, 2, 3, 4, 5]
        assert state["steps"][1]["words"] == "Fine for adults"
        assert state["steps"][4]["words"] == "Avoid"
        assert {c["id"] for c in state["categories"]} >= {"speed", "other"}
        assert state["expected"] and state["reason_max"] == 500 and state["note_max"] == 200

    def test_after_an_edit_it_says_whose_and_offers_the_undo(self, live) -> None:
        client, csrf = admin_client()
        assert post(client, CREATE, body(live), csrf).status_code == 200
        state = client.get(STATE.format(WAY), **addr()).json()
        assert state["current"]["source"] == "panel" and state["current"]["by"] == "you"
        assert state["current"]["private_reason"] == REASON
        assert state["recent_edit"]["can_undo"] is True

    def test_an_unknown_way_is_404(self, live) -> None:
        client, _ = admin_client()
        assert client.get(STATE.format(31337), **addr()).status_code == 404


@db
class TestCreateEndpoint:
    def test_an_admin_changes_a_road(self, live) -> None:
        client, csrf = admin_client()
        r = post(client, CREATE, body(live), csrf)
        assert r.status_code == 200 and r["Cache-Control"] == "no-store"
        answer = r.json()
        assert answer["ways"] == [{"osm_way_id": WAY, "step": 4, "changed": True}]
        assert answer["generation"] == 1 and answer["edit_id"] == StressEdit.objects.get().pk
        assert answer["undo_until"]
        assert live_row(live)["stress_tier"] == 4

    def test_signed_out_is_401_and_changes_nothing(self, client, live) -> None:
        r = post(client, CREATE, body(live))
        assert r.status_code == 401 and live_row(live)["stress_tier"] == 3

    def test_a_non_admin_is_403_and_it_is_audited(self, live) -> None:
        member = make_user(admin=False)
        client = sign_in(Client(enforce_csrf_checks=False), member)
        r = post(client, CREATE, body(live))
        assert r.status_code == 403 and live_row(live)["stress_tier"] == 3
        entry = AuditLogEntry.objects.get(outcome="refused")
        assert entry.actor_user_id == member.pk and "not an instance admin" in entry.detail

    def test_without_the_csrf_token_it_is_403_and_audited(self, live) -> None:
        client, _csrf = admin_client(enforce=True)
        r = post(client, CREATE, body(live))
        assert r.status_code == 403 and r.json()["code"] == "csrf"
        assert live_row(live)["stress_tier"] == 3
        assert "CSRF" in AuditLogEntry.objects.get(outcome="refused").detail

    def test_a_wrong_csrf_token_is_refused(self, live) -> None:
        client, _csrf = admin_client(enforce=True)
        assert post(client, CREATE, body(live), "not-the-token").status_code == 403

    def test_a_foreign_page_is_refused(self, live) -> None:
        client, csrf = admin_client()
        r = post(client, CREATE, body(live), csrf, HTTP_SEC_FETCH_SITE="cross-site")
        assert r.status_code == 403 and live_row(live)["stress_tier"] == 3

    def test_only_json_is_read(self, live) -> None:
        client, csrf = admin_client()
        r = client.post(
            CREATE, data="step=4", content_type="application/x-www-form-urlencoded",
            HTTP_X_CSRFTOKEN=csrf, **addr(),
        )  # fmt: skip
        assert r.status_code == 400 and Override.objects.count() == 0

    def test_a_large_body_is_refused_unread(self, live) -> None:
        client, csrf = admin_client()
        r = post(client, CREATE, body(live, reason="x" * 20000), csrf)
        assert r.status_code == 400 and Override.objects.count() == 0

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"step": 2.5}, "step"),
            ({"step": "3"}, "step"),
            ({"step": True}, "step"),
            ({"step": 6}, "step"),
            ({"reason": ""}, "reason"),
            ({"reason": "x" * 501}, "reason"),
            ({"category": "mood"}, "category"),
            ({"public_note": "locals avoid it"}, "public_note"),
            ({"display": "all"}, "display"),
            ({"at_least": "yes"}, "at_least"),
            ({"osm_way_ids": []}, "osm_way_ids"),
            ({"osm_way_ids": [WAY, OTHER_WAY]}, "osm_way_ids"),
            ({"osm_way_ids": ["5001"]}, "osm_way_ids"),
            ({"extra": 1}, "extra"),
        ],
    )
    def test_a_bad_body_is_400_naming_the_field(self, live, change, field) -> None:
        client, csrf = admin_client()
        r = post(client, CREATE, body(live, **change), csrf)
        assert r.status_code == 400 and r.json().get("field") == field, r.json()
        assert Override.objects.count() == 0

    def test_a_missing_field_is_400(self, live) -> None:
        client, csrf = admin_client()
        payload = body(live)
        del payload["expected"]
        assert post(client, CREATE, payload, csrf).status_code == 400

    def test_a_stale_edit_is_409_audited_and_changes_nothing(self, live) -> None:
        client, csrf = admin_client()
        stale = token(live)
        assert post(client, CREATE, body(live), csrf).status_code == 200
        r = post(client, CREATE, body(live, step=1, expected=stale), csrf)
        assert r.status_code == 409 and r.json()["code"] == "stale"
        assert live_row(live)["stress_tier"] == 4
        assert (
            AuditLogEntry.objects.filter(outcome="refused", detail__contains="stale").count() == 1
        )

    def test_a_way_not_in_the_data_is_404(self, live) -> None:
        client, csrf = admin_client()
        assert post(client, CREATE, body(live, osm_way_ids=[404]), csrf).status_code == 404

    def test_the_account_is_limited_to_sixty_changes_an_hour(self, live) -> None:
        def attempt(n):
            client, csrf = admin_client()
            user = User.objects.latest("pk")
            key = ratelimit.client_key(f"user:{user.pk}")
            for _ in range(ratelimit.STRESS_EDIT_WRITES.requests):
                ratelimit.hit(ratelimit.STRESS_EDIT_WRITES, key)
            return post(client, CREATE, body(live), csrf)

        r = in_one_window(ratelimit.STRESS_EDIT_WRITES.window_s, attempt)
        assert r.status_code == 429 and "Retry-After" in r and Override.objects.count() == 0

    def test_the_address_is_limited_too(self, client, live) -> None:
        same = {"HTTP_X_FORWARDED_FOR": "203.0.113.77"}

        def attempt(n):
            codes = []
            for _ in range(ratelimit.STRESS_EDIT_CLIENT.requests + 1):
                codes.append(client.get(STATE.format(WAY), **same).status_code)
            return codes

        codes = in_one_window(ratelimit.STRESS_EDIT_CLIENT.window_s, attempt)
        assert codes[0] == 401 and codes[-1] == 429

    def test_the_answer_names_nobody(self, live) -> None:
        client, csrf = admin_client()
        text = post(client, CREATE, body(live), csrf).content.decode()
        assert REASON not in text and "discord" not in text.lower()


@db
class TestUndoEndpoint:
    def undo_url(self, edit_id) -> str:
        return f"/api/stress-edits/{edit_id}/undo"

    def test_an_admin_undoes_a_change(self, live) -> None:
        client, csrf = admin_client()
        done = post(client, CREATE, body(live), csrf).json()
        r = post(client, self.undo_url(done["edit_id"]), {}, csrf)
        assert r.status_code == 200 and r.json()["generation"] == 2
        assert live_row(live)["stress_tier"] == 3

    def test_signed_out_non_admin_and_missing_token(self, client, live) -> None:
        admin = make_user()
        done = edit(live, admin, 4)
        assert post(client, self.undo_url(done.edit.pk), {}).status_code == 401
        member = sign_in(Client(), make_user(admin=False))
        assert post(member, self.undo_url(done.edit.pk), {}).status_code == 403
        enforcing, _ = admin_client(enforce=True)
        assert post(enforcing, self.undo_url(done.edit.pk), {}).status_code == 403
        assert live_row(live)["stress_tier"] == 4

    def test_twice_is_409_and_unknown_is_404(self, live) -> None:
        client, csrf = admin_client()
        done = post(client, CREATE, body(live), csrf).json()
        assert post(client, self.undo_url(done["edit_id"]), {}, csrf).status_code == 200
        r = post(client, self.undo_url(done["edit_id"]), {}, csrf)
        assert r.status_code == 409 and r.json()["code"] == "already_undone"
        assert post(client, self.undo_url(9999), {}, csrf).status_code == 404

    def test_a_body_with_extra_fields_is_refused(self, live) -> None:
        client, csrf = admin_client()
        done = post(client, CREATE, body(live), csrf).json()
        assert post(client, self.undo_url(done["edit_id"]), {"x": 1}, csrf).status_code == 400


@db
class TestAdmin:
    def test_the_history_and_the_rows_are_read_only_pages(self, live, settings) -> None:
        from django.urls import reverse

        admin = make_user()
        edit(live, admin, 4)
        client = sign_in(Client(), admin)
        changelist = reverse("routemaker_admin:core_stressedit_changelist")
        r = client.get(changelist)
        assert r.status_code == 200 and f"user {admin.pk}".encode() in r.content
        assert f"discord:{admin.discord_user_id}".encode() not in r.content
        pk = StressEdit.objects.get().pk
        page = client.get(reverse("routemaker_admin:core_stressedit_change", args=[pk]))
        assert page.status_code == 200 and b"<form" in page.content
        override = Override.objects.get()
        row = client.get(reverse("routemaker_admin:core_override_change", args=[override.pk]))
        assert row.status_code == 200
        assert f"discord:{admin.discord_user_id}".encode() not in row.content


@db
class TestReapplyCommand:
    def run(self, *args, **options) -> str:
        out = io.StringIO()
        call_command("reapply_stress_edits", *args, stdout=out, **options)
        return out.getvalue()

    def test_it_is_dry_by_default_and_lists_what_it_would_replay(self, live) -> None:
        edit(live, make_user(), 4)
        rebuild_without_the_edit(live)
        said = self.run(since="all")
        assert "1 edits" in said and "set of way(s) [5001]" in said and "dry run" in said
        assert live_row(live)["stress_tier"] == 3

    def test_confirm_replays_and_a_second_run_changes_nothing(self, live) -> None:
        edit(live, make_user(), 4)
        rebuild_without_the_edit(live)
        assert "1 rows changed" in self.run(since="all", confirm=True)
        assert live_row(live)["stress_tier"] == 4
        assert "0 rows changed" in self.run(since="all", confirm=True)

    def test_without_a_time_it_uses_the_one_the_table_recorded(self, live) -> None:
        edit(live, make_user(), 4)
        rebuild_without_the_edit(live)
        LiveEditGeneration.objects.create(
            table_oid=stress_edits.live_oid(live),
            overrides_read_at=timezone.now() + timedelta(hours=1),
        )
        assert "0 edits" in self.run()
        assert "1 edits" in self.run(since="2000-01-01T00:00:00Z")

    def test_the_time_must_be_a_time(self, live) -> None:
        with pytest.raises(CommandError):
            self.run(since="yesterday")
