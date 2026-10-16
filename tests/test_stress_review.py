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
from datetime import UTC, datetime, timedelta

import pytest
from django.test import Client
from test_stress_edits import addr, live_row, make_segment, make_user, post, sign_in

from core import segment_info, stress_edits, stress_review
from core.management.commands.import_cloud_build import later_overrides
from core.models import AuditLogEntry, Override, ReviewItem, ReviewRuling, StressEdit
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
        assert drop.details["new"]["source"] == "moco"
        assert drop.details["old"]["source"] == "formula"
        assert drop.length_m > 100 and drop.geometry is not None
        assert found[CLOSED].kind == "closed" and found[CLOSED].new_closed
        assert found[RISE].kind == "1-2" and found[RISE].name == "Oak Street"
        out = stress_review.item_out(drop)
        assert out["kind_label"] == "LTS 4 to LTS 2"
        assert out["new_source"] == "Montgomery County Planning"
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
        counts = stress_review.compute_all(BUILD, live, staging, tmp_path)
        assert counts["rematch"] == 1 and counts["sidepath"] is None
        assert items("rematch")[777].name == "Elm Street"
        assert stress_review.actions(items("rematch")[777]) == ["accept"]


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
        # Meant for the next rebuild, so the swap does not refuse over it.
        assert access.pk not in later_overrides(datetime(2020, 1, 1, tzinfo=UTC))
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
        stress_review.undo(admin, made[0].pk)
        assert Override.objects.get(pk=made[0].access_override_id).approved is False
        assert AuditLogEntry.objects.filter(action="review_ruling_undo").count() == 2

    def test_the_road_detail_has_the_facts_and_the_history(self, queued) -> None:
        stress_review.rule(make_user(), "rebuild", [DROP], "reject")
        detail = stress_review.road_detail(DROP)
        assert any(f["label"] == "Level" for f in detail["facts"])
        assert any("Review" in h["what"] for h in detail["history"])


@db
class TestPendingAgenciesStayPrivate:
    def test_no_pending_agency_can_decide_or_is_confirmed(self) -> None:
        for agency in agency_lts.PENDING_AGENCIES:
            assert agency not in agency_lts.AGENCIES
            assert agency_lts.public_use_confirmed(agency) is False

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
        r = post(
            rider, RULE, {"queue": "rebuild", "osm_way_ids": [DROP], "decision": "accept"}, csrf
        )
        assert r.status_code == 403
        assert not ReviewRuling.objects.exists()

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
        box = {"queue": "rebuild", "west": -78, "south": 38, "east": -76, "north": 40}
        features = client.get("/api/review/map", box, **addr()).json()["features"]
        assert {f["properties"]["way"] for f in features} == {DROP, CLOSED, RISE}


def r_cache(response) -> str:
    return response["Cache-Control"]
