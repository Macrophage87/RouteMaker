"""Review: the instance admin's queue of roads to rule on (core.stress_review; the owner,
2026-10-16: "Add a mode that will allow people with admin access the ability to look at these
roads and make a ruling").

Against a real live/staging pair. Pinned here: the rebuild's changes are precomputed correctly
from the two tables, the disagreements from every rating a road holds (a pending agency's
included, and kept off the public road panel), a ruling writes the road panel's own override and
edit (or an access override for a reopening), a batch rules on many roads, every ruling is
audited and can be undone in the window, and only an instance admin reaches any of it.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.db import connection
from django.test import Client
from test_stress_edits import addr, live_row, make_segment, make_user, post, sign_in

from core import segment_info, stress_edits, stress_review
from core.management.commands.import_cloud_build import later_overrides, review_reopenings
from core.models import (
    AuditLogEntry,
    Override,
    ReviewItem,
    ReviewQueueState,
    ReviewRuling,
    StressEdit,
)
from routemaker import agency_lts

db = pytest.mark.django_db(transaction=True)

BUILD = "20261016T120000Z"
DROP, SAME, CLOSED, RISE, NEW_ONLY, RATED, CLOSE_RATED, NARROW = range(9001, 9009)
LON, LAT = -77.0300, 38.8990
RATINGS = {
    "formula": 4,
    "formula_rule": "mixed traffic, 35 mph",
    "agencies": [{"agency": "moco", "name": "Montgomery County Planning", "level": 2}],
    "used": "moco",
}
ME = "/api/me"
ITEMS = "/api/review/items"
RULE = "/api/review/rulings"


def lon_of(way: int) -> float:
    return LON + (way - 9000) * 0.01


def seg(schema, way, tier, **columns):
    make_segment(schema, way, tier, lon=lon_of(way), lat=LAT, **columns)


@pytest.fixture(autouse=True)
def _quiet_router(monkeypatch):
    segment_info.forget_columns()

    def silent(lat, lon, costing, timeout_s=None):
        raise segment_info.RouterSilent("no router in these tests")

    monkeypatch.setattr(segment_info, "locate_edges", silent)
    yield
    segment_info.forget_columns()


@pytest.fixture
def tables(segment_schemas):
    live, staging = segment_schemas
    seg(live, DROP, 4)
    seg(staging, DROP, 2, rule="agency rating: Montgomery County Planning LTS 2")
    seg(live, SAME, 2, map_class="road")
    seg(staging, SAME, 2, map_class="road")
    seg(live, CLOSED, 3)
    seg(staging, CLOSED, 3, map_class="barred")
    seg(live, RISE, 1)
    seg(staging, RISE, 2, trail_name="Oak Street")
    seg(staging, NEW_ONLY, 4)
    for schema in (live, staging):
        seg(
            schema,
            RATED,
            2,
            rule="agency rating: Montgomery County Planning LTS 2",
            stress_ratings=json.dumps(RATINGS),
        )
        seg(
            schema,
            CLOSE_RATED,
            3,
            stress_ratings=json.dumps(
                {
                    **RATINGS,
                    "formula": 3,
                    "agencies": [
                        {"agency": "moco", "name": "Montgomery County Planning", "level": 2.5}
                    ],
                }
            ),
        )
        seg(schema, NARROW, 2, rule="mixed traffic, 25 mph, single lane, narrow rural road")
    return live, staging


def items(queue) -> dict[int, ReviewItem]:
    return {i.osm_way_id: i for i in ReviewItem.objects.filter(queue=queue)}


@db
class TestPrecompute:
    def test_the_rebuild_changes_are_the_ways_whose_level_or_access_changed(self, tables) -> None:
        live, staging = tables
        assert stress_review.compute_rebuild(BUILD, live, staging) == 3
        found = items("rebuild")
        assert set(found) == {DROP, CLOSED, RISE}
        drop = found[DROP]
        assert (drop.kind, drop.old_step, drop.new_step, drop.build_id) == ("4-2", 4, 2, BUILD)
        assert drop.length_m > 100 and drop.geometry is not None and drop.score > 0
        assert found[CLOSED].kind == "closed" and found[CLOSED].new_closed
        assert found[RISE].kind == "1-2" and found[RISE].name == "Oak Street"
        out = stress_review.item_out(drop)
        assert out["kind_label"] == "LTS 4 to LTS 2" and out["reason"] == "LTS 4 to LTS 2"
        # The words are made when shown, from the rows the item keeps.
        assert out["new_source"] == "Montgomery County Planning"
        assert out["old_source"] == "RouteMaker's formula"
        # The queue's order: the size of the change along the road, a closure counted as 4.
        assert found[CLOSED].score > found[DROP].score > found[RISE].score
        assert out["length"].endswith("km)") and " mi (" in out["length"]
        # Computed again, the queue is replaced, not doubled.
        stress_review.compute_rebuild(BUILD, live, staging)
        assert ReviewItem.objects.filter(queue="rebuild").count() == 3

    def test_disagreements_count_a_whole_step_and_a_pending_agency(self, tables) -> None:
        _live, staging = tables
        pending = {SAME: [("arlington", 4.0)]}
        stress_review.compute_disagreements(staging, pending=pending)
        found = items("disagreement")
        assert set(found) == {RATED, SAME}
        rated = found[RATED]
        assert rated.spread == 2 and rated.sources == ["formula", "moco"]
        same = found[SAME]
        assert same.sources == ["arlington", "formula"]
        named = {s["key"]: s for s in same.details["sources"]}
        assert named["arlington"]["name"] == "Arlington (pending permission)"
        assert named["arlington"]["pending"] is True
        # Filtered by a source in the disagreement.
        assert [r.osm_way_id for r in stress_review.items_of("disagreement", source="moco")] == [
            RATED
        ]

    def test_the_area_is_the_stress_change_reports_county(self, tables, settings, tmp_path) -> None:
        """One county source: reference/counties.geojson, as stress_changes reads it."""
        live, staging = tables
        settings.REBUILD_REFERENCE_DIR = tmp_path
        stress_review.compute_rebuild(BUILD, live, staging)
        assert {i.area for i in items("rebuild").values()} == {""}
        west = [[-77.1, 38.8], [-77.0, 38.8], [-77.0, 39.0], [-77.1, 39.0], [-77.1, 38.8]]
        (tmp_path / "counties.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"NAMELSAD": "Montgomery County", "STATEFP": "24"},
                            "geometry": {"type": "Polygon", "coordinates": [west]},
                        }
                    ],
                }
            )
        )
        stress_review.compute_rebuild(BUILD, live, staging)
        found = items("rebuild")
        # DROP lies just east of -77.03 (inside); RISE further east (outside).
        assert lon_of(DROP) < -77.0 < lon_of(RISE)
        assert found[DROP].area == "Montgomery County, MD" and found[RISE].area == ""
        assert stress_review.page("rebuild", area="Montgomery County, MD")["total"] == 1

    def test_the_narrow_rural_roads(self, tables) -> None:
        _live, staging = tables
        assert stress_review.compute_narrow_rural(staging) == 1
        assert "25 mph (40 km/h)" in items("narrow_rural")[NARROW].reason

    def test_a_queue_with_no_report_is_left_unwired(self, tables, tmp_path) -> None:
        live, staging = tables
        (tmp_path / "override-rematch.csv").write_text(
            "kind,old_way_id,outcome,new_way_ids,name,reason\n"
            "stress,777,failed,,Elm Street,two candidates\n"
            "stress,778,rematched,9001,,\n"
        )
        (tmp_path / "use-sidepath-no-path.csv").write_text(f"osm_way_id\n{SAME}\n")
        counts = stress_review.compute_all(BUILD, live, staging, tmp_path)
        assert counts["rematch"] == 1 and counts["sidepath"] == 1
        assert counts["works_closure"] is None
        assert items("rematch")[777].name == "Elm Street"
        assert stress_review.actions(items("rematch")[777]) == ["accept"]
        # The next build sent no reports: its file queues are cleared and say so, never the
        # last build's rows shown as current.
        counts = stress_review.compute_all("20261017T120000Z", live, staging, None)
        assert counts["sidepath"] is None and items("sidepath") == {}
        summary = {q["queue"]: q for q in stress_review.queue_summary()}
        assert summary["sidepath"]["note"] == "No report from this build"
        assert summary["sidepath"]["wired"] is False and summary["sidepath"]["total"] == 0
        assert summary["disagreement"]["note"] == "" and summary["disagreement"]["wired"]

    def test_a_cloud_build_never_reads_this_computers_reports(self, settings, tmp_path) -> None:
        (tmp_path / "reports").mkdir()
        settings.REBUILD_WORK_DIR = tmp_path
        assert stress_review.reports_dir("") is None
        assert stress_review.reports_dir("", own=True) == tmp_path / "reports"
        assert stress_review.reports_dir("reports") == tmp_path / "reports"
        assert stress_review.reports_dir("missing") is None

    def test_the_tables_are_compared_in_one_sort_each_and_null_safe(self) -> None:
        """DISTINCT ON (one sort of each table, never an array of every piece), and IS DISTINCT
        FROM, so a value missing on one side is still a change."""
        import inspect

        sql = stress_review._agg_sql.__doc__ or ""
        assert "DISTINCT ON" in sql
        body = inspect.getsource(stress_review.compute_rebuild)
        assert "o.step IS DISTINCT FROM n.step OR o.closed IS DISTINCT FROM n.closed" in body
        assert "array_agg" not in inspect.getsource(stress_review)

    def test_the_map_is_written_with_the_queue_in_its_order(self, tables) -> None:
        live, staging = tables
        stress_review.compute_rebuild(BUILD, live, staging)
        state = ReviewQueueState.objects.get(queue="rebuild")
        low, high, points = (
            json.loads(m) for m in (state.map_low, state.map_high, state.map_points)
        )
        ways = [f["properties"]["way"] for f in low["features"]]
        assert ways == [r["osm_way_id"] for r in stress_review.page("rebuild")["items"]]
        assert [f["properties"]["order"] for f in low["features"]] == [1, 2, 3]
        assert {f["geometry"]["type"] for f in points["features"]} == {"Point"}
        assert len(high["features"]) == 3 and state.build_id == BUILD
        payload = json.loads(stress_review.map_payload("rebuild"))
        assert payload["lines"] == low and payload["points"] == points and payload["ruled"] == []
        assert json.loads(stress_review.map_payload("rebuild", "high"))["points"]["features"] == []


@pytest.fixture
def queued(tables):
    live, staging = tables
    stress_review.compute_all(BUILD, live, staging, None)
    return live


@db
class TestRulings:
    def test_reject_keeps_the_old_level_as_an_owner_override(self, queued) -> None:
        admin = make_user()
        made, refused = stress_review.rule(admin, "rebuild", [DROP], "reject")
        assert refused == []
        ruling = made[0]
        row = Override.objects.get(osm_way_id=DROP, kind="stress", approved=True)
        assert row.value["tier"] == 4 and row.source == Override.Source.PANEL
        assert row.evidence == stress_review.EVIDENCE
        assert row.reason.startswith("Admin review, ")
        assert ruling.edit == StressEdit.objects.get(override=row)
        assert live_row(queued, DROP)["stress_rule"].startswith("override: stress adjustment")
        assert AuditLogEntry.objects.filter(
            action="review_ruling", object_id=str(ruling.pk)
        ).exists()

    def test_change_lts_by_half_steps_and_accept_records_only(self, queued) -> None:
        admin = make_user()
        stress_review.rule(admin, "rebuild", [RISE], "set", step=2.5, reason="rode it")
        row = Override.objects.get(osm_way_id=RISE, kind="stress", approved=True)
        assert (row.value["tier"], row.value.get("half")) == (2, True)
        assert row.reason == "rode it"
        made, _ = stress_review.rule(admin, "disagreement", [RATED], "accept")
        assert made[0].edit is None
        assert not Override.objects.filter(osm_way_id=RATED).exists()

    def test_reject_of_a_newly_closed_road_reopens_it_at_the_next_rebuild(self, queued) -> None:
        admin = make_user()
        made, _ = stress_review.rule(admin, "rebuild", [CLOSED], "reject")
        access = made[0].access_override
        assert access.kind == "access" and access.value == {"bicycle": "yes"} and access.approved
        # Told apart by its source, never its words.
        assert access.source == Override.Source.REVIEW
        # Meant for the next rebuild, so the swap does not refuse over it, but lists it.
        long_ago = datetime(2020, 1, 1, tzinfo=UTC)
        assert access.pk not in later_overrides(long_ago)
        assert review_reopenings(long_ago) == ([access.pk], [])
        Override.objects.filter(pk=access.pk).update(evidence="something else")
        assert review_reopenings(long_ago) == ([access.pk], [])
        made, refused = stress_review.rule(admin, "rebuild", [CLOSED], "set", step=2)
        assert made == [] and "not offered" in refused[0]["error"]

    def test_a_batch_and_what_it_cannot_rule_on(self, queued) -> None:
        admin = make_user()
        made, refused = stress_review.rule(admin, "rebuild", [DROP, RISE, NEW_ONLY], "accept")
        assert sorted(r.osm_way_id for r in made) == [DROP, RISE]
        assert refused == [{"osm_way_id": NEW_ONLY, "error": "That road is not in this queue."}]
        unruled, total, build = stress_review.unruled_rebuild_changes()
        assert (unruled, total, build) == (1, 3, BUILD)
        assert stress_review.page("rebuild")["total"] == 1

    def test_undo_within_the_window_and_not_twice(self, queued) -> None:
        admin = make_user()
        made, _ = stress_review.rule(admin, "rebuild", [DROP], "reject")
        ruling, generation = stress_review.undo(admin, made[0].pk)
        assert ruling.undone_at is not None and generation is not None
        assert not Override.objects.filter(
            osm_way_id=DROP, kind="stress", approved=True, superseded_by__isnull=True
        ).exists()
        with pytest.raises(stress_edits.Stale):
            stress_review.undo(admin, made[0].pk)
        made, _ = stress_review.rule(admin, "rebuild", [CLOSED], "reject")
        later = made[0].at + stress_edits.UNDO_WINDOW + timedelta(seconds=1)
        with pytest.raises(stress_edits.Stale):
            stress_review.undo(admin, made[0].pk, now=later)
        read_at = made[0].at + timedelta(seconds=1)
        stress_review.undo(admin, made[0].pk, now=made[0].at + timedelta(seconds=2))
        access = Override.objects.get(pk=made[0].access_override_id)
        assert access.approved is False and access.approved_at is None
        assert AuditLogEntry.objects.filter(action="review_ruling_undo").count() == 2
        # Undone after the box's copy was read: the build has it open, and the import says so.
        assert review_reopenings(read_at) == ([], [access.pk])

    def test_a_batch_level_is_one_edit_one_generation_and_one_undo(self, queued) -> None:
        admin = make_user()
        before = StressEdit.objects.count()
        made, refused = stress_review.rule(admin, "rebuild", [DROP, RISE], "set", step=3)
        assert refused == [] and len(made) == 2
        assert StressEdit.objects.count() == before + 1
        edit = StressEdit.objects.latest("id")
        assert sorted(edit.osm_way_ids) == [DROP, RISE]
        assert {r.edit_id for r in made} == {edit.pk}
        # Undoing one undoes the batch: both rulings, both roads.
        ruling, generation = stress_review.undo(admin, made[1].pk)
        assert generation is not None
        assert ReviewRuling.objects.filter(undone_at__isnull=False).count() == 2
        assert not Override.objects.filter(
            osm_way_id__in=[DROP, RISE], kind="stress", approved=True, superseded_by__isnull=True
        ).exists()
        assert stress_review.page("rebuild")["total"] == 3

    def test_a_batch_reject_is_one_edit_a_level_it_puts_back(self, queued) -> None:
        made, _ = stress_review.rule(make_user(), "rebuild", [DROP, RISE], "reject")
        assert sorted((r.osm_way_id, r.step) for r in made) == [(DROP, 4), (RISE, 1)]
        assert len({r.edit_id for r in made}) == 2

    def test_an_accept_lapses_when_a_build_changes_what_the_road_was_listed_for(
        self, tables
    ) -> None:
        live, staging = tables
        stress_review.compute_narrow_rural(staging)
        admin = make_user()
        stress_review.rule(admin, "narrow_rural", [NARROW], "accept")
        assert stress_review.page("narrow_rural")["total"] == 0
        # Computed again from the same build: the ruling stands.
        stress_review.compute_narrow_rural(staging)
        assert stress_review.page("narrow_rural")["total"] == 0
        # A build that changes the road's level: listed again, for a new look.
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {staging}.segment SET stress_tier = 3 WHERE osm_way_id = %s", [NARROW]
            )
        stress_review.compute_narrow_rural(staging)
        assert stress_review.page("narrow_rural")["total"] == 1
        summary = {q["queue"]: q for q in stress_review.queue_summary()}
        assert summary["narrow_rural"]["reviewed"] == 0

    def test_the_road_detail_has_the_facts_and_the_history(self, queued) -> None:
        stress_review.rule(make_user(), "rebuild", [DROP], "reject")
        detail = stress_review.road_detail(DROP)
        assert any(f["label"] == "Level" for f in detail["facts"])
        assert any("Review" in h["what"] for h in detail["history"])
        assert detail["new_facts"] == []

    def test_a_rebuild_change_shows_the_new_builds_facts_beside_lives(self, queued) -> None:
        detail = stress_review.road_detail(RISE, "rebuild")
        level = {f["label"]: f["value"] for f in detail["facts"]}["Level"]
        new_level = {f["label"]: f["value"] for f in detail["new_facts"]}["Level"]
        assert level != new_level


@db
class TestPendingAgenciesStayPrivate:
    def test_no_pending_agency_can_decide_or_is_confirmed(self) -> None:
        for agency in agency_lts.PENDING_AGENCIES:
            assert agency not in agency_lts.AGENCIES
        # Arlington has not answered; Alexandria confirmed CC0 on 2026-10-16.
        assert agency_lts.public_use_confirmed("arlington") is False
        assert agency_lts.public_use_confirmed("alexandria") is True
        assert agency_lts.public_use_confirmed("moco") is True

    def test_one_switch_confirms_an_agencys_public_use(self, monkeypatch) -> None:
        monkeypatch.setitem(agency_lts.PUBLIC_USE_CONFIRMED, "alexandria", True)
        assert agency_lts.review_name("alexandria") == "Alexandria"
        assert agency_lts.review_name("arlington") == "Arlington (pending permission)"
        sources = stress_review.rating_sources(
            {"step": 2.0}, pending=[("alexandria", 4.0), ("arlington", 4.0)]
        )
        pending = {s["key"]: s["pending"] for s in sources}
        assert pending == {"formula": False, "alexandria": False, "arlington": True}

    def test_the_public_road_panel_never_names_them(self, queued, client, tmp_path) -> None:
        (tmp_path / "arlington-ratings.csv").write_text(f"osm_way_id,level\n{SAME},4\n")
        assert stress_review.pending_ratings(tmp_path) == {SAME: [("arlington", 4.0)]}
        stress_review.compute_disagreements(queued, pending=stress_review.pending_ratings(tmp_path))
        r = client.get("/api/segment-info", {"lat": LAT, "lon": lon_of(SAME) + 0.001}, **addr())
        assert r.status_code == 200 and r.json()["osm_way_id"] == SAME
        assert "rlington" not in r.content.decode()
        assert "pending" not in r.content.decode()


def admin_client(admin=True):
    client = Client(enforce_csrf_checks=True)
    sign_in(client, make_user(admin=admin))
    client.get(ME, **addr())
    # The short form's ticket sets the token for anyone, so a refusal below is the account's.
    client.get("/api/stress-suggestions/ticket", {"way": DROP}, **addr())
    return client, client.cookies["csrftoken"].value


@db
class TestEndpoints:
    def test_only_an_instance_admin(self, queued) -> None:
        assert Client().get(ITEMS, **addr()).status_code == 401
        rider, csrf = admin_client(admin=False)
        for url in (ITEMS, "/api/review/queues", f"/api/review/road/{DROP}", "/api/review/rulings"):
            assert rider.get(url, **addr()).status_code == 403, url
        for url in ("/api/review/map", "/api/review/street-photo?lon=-77&lat=38.9"):
            assert rider.get(url, **addr()).status_code == 403, url
        r = post(
            rider, RULE, {"queue": "rebuild", "osm_way_ids": [DROP], "decision": "accept"}, csrf
        )
        assert r.status_code == 403
        assert not ReviewRuling.objects.exists()
        made, _ = stress_review.rule(make_user(), "rebuild", [DROP], "accept")
        assert post(rider, f"{RULE}/{made[0].pk}/undo", {}, csrf).status_code == 403
        assert ReviewRuling.objects.get(pk=made[0].pk).undone_at is None

    def test_a_write_without_the_csrf_token_is_refused(self, queued) -> None:
        client, _csrf = admin_client()
        body = {"queue": "rebuild", "osm_way_ids": [DROP], "decision": "accept"}
        r = client.post(RULE, json.dumps(body), content_type="application/json", **addr())
        assert r.status_code == 403
        assert not ReviewRuling.objects.exists()
        made, _ = stress_review.rule(make_user(), "rebuild", [DROP], "accept")
        r = client.post(
            f"{RULE}/{made[0].pk}/undo", "{}", content_type="application/json", **addr()
        )
        assert r.status_code == 403
        assert ReviewRuling.objects.get(pk=made[0].pk).undone_at is None

    def test_reviews_reads_and_writes_have_their_own_counts(self) -> None:
        from core import api, ratelimit

        assert ratelimit.REVIEW_READS.scope not in {
            ratelimit.STRESS_EDIT_CLIENT.scope,
            ratelimit.STREET_PHOTO.scope,
            ratelimit.SEGMENT_INFO.scope,
        }
        assert ratelimit.REVIEW_READS.requests >= 600
        names = {getattr(g, "__qualname__", "") for g in api.REVIEW_READ + api.REVIEW_RULING_WRITE}
        assert names  # the guards are decorators
        source = Path(api.__file__).read_text()
        review = source[source.index("# ---- Review: the instance admin's queue") :]
        assert "STRESS_EDIT_CLIENT" not in review and "REVIEW_WRITE)" not in review
        assert "ratelimit.REVIEW_READS" in review and "ratelimit.REVIEW_RULINGS)" in review

    def test_list_rule_and_undo(self, queued) -> None:
        client, csrf = admin_client()
        queues = {
            q["queue"]: q for q in client.get("/api/review/queues", **addr()).json()["queues"]
        }
        assert queues["rebuild"]["total"] == 3 and queues["rebuild"]["reviewed"] == 0
        assert {k["kind"] for k in queues["rebuild"]["kinds"]} == {"4-2", "closed", "1-2"}
        body = client.get(ITEMS, {"queue": "rebuild", "kind": "4-2"}, **addr()).json()
        assert [i["osm_way_id"] for i in body["items"]] == [DROP]
        assert body["items"][0]["actions"] == ["accept", "reject", "set"]
        assert r_cache(client.get(ITEMS, **addr())) == "no-store"
        r = post(
            client,
            RULE,
            {"queue": "rebuild", "osm_way_ids": [DROP, RISE], "decision": "set", "step": 3.0},
            csrf,
        )
        assert r.status_code == 200, r.content
        assert r.json()["message"] == "2 roads ruled."
        ruling = r.json()["rulings"][0]
        assert ruling["can_undo"] and ruling["summary"] == "Set to LTS 3"
        r = post(client, f"{RULE}/{ruling['id']}/undo", {}, csrf)
        assert r.status_code == 200 and r.json()["ruling"]["undone"]
        r = post(client, RULE, {"queue": "rebuild", "osm_way_ids": [DROP], "decision": "set"}, csrf)
        assert r.status_code == 400
        r = client.get("/api/review/map", {"queue": "rebuild"}, **addr())
        assert r_cache(r) == "no-store"
        features = r.json()["lines"]["features"]
        assert {f["properties"]["way"] for f in features} == {DROP, CLOSED, RISE}
        assert {f["properties"]["queue"] for f in features} == {"rebuild"}
        high = client.get("/api/review/map", {"queue": "rebuild", "detail": "high"}, **addr())
        assert len(high.json()["lines"]["features"]) == 3
        detail = client.get(f"/api/review/road/{RISE}", {"queue": "rebuild"}, **addr()).json()
        assert detail["new_facts"]


def r_cache(response) -> str:
    return response["Cache-Control"]


REPO = Path(__file__).resolve().parents[1]
# Every module that may read Review's tables: the review itself, its endpoints and commands, the
# models and migrations, and the import that reports on it. Nothing that draws a tile, writes an
# export, a share card or a link preview, or answers a rider.
REVIEW_READERS = {
    "src/core/models.py",
    "src/core/stress_review.py",
    "src/core/api.py",
    "src/core/management/commands/import_cloud_build.py",
    "src/core/management/commands/compute_review_queue.py",
}


# What reads Review's tables in code: its models, their tables by name, or the module itself.
READS_REVIEW = re.compile(
    r"\b(ReviewItem|ReviewRuling|ReviewQueueState)\b|['\"]review_(item|ruling|queue_state)\b"
    r"|import stress_review|stress_review import|stress_review\.\w+\("
)


def test_only_reviews_own_code_reads_its_tables() -> None:
    readers = set()
    for path in (REPO / "src").rglob("*.py"):
        relative = str(path.relative_to(REPO))
        if "/migrations/" not in relative and READS_REVIEW.search(path.read_text()):
            readers.add(relative)
    assert readers == REVIEW_READERS, readers ^ REVIEW_READERS
    # In the API, only Review's own section reads them: not the tiles, exports, share cards,
    # link previews, or the road panel above it.
    source = (REPO / "src" / "core" / "api.py").read_text()
    head = source[: source.index("# ---- Review: the instance admin's queue")]
    assert not READS_REVIEW.search(head)
