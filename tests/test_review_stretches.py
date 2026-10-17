"""Review's stretches (core.stress_review.group_stretches; the owner, 2026-10-17: "Also, for
review, merge stretches. Go at least from major intersection to major intersection").

Pinned here: the listed ways of one road that join end to end with the same change are one row,
its length the sum and its lines all of theirs; a residential side street does not end it, a
secondary road does; a different change on the next way is a row of its own; a ruling on the
stretch is written a way, as a ruling on each way alone is, and Undo undoes them all.
"""

from __future__ import annotations

import pytest
from django.db import connection
from test_stress_edits import LAT, LON, make_segment, make_user

from core import segment_info, stress_edits, stress_review
from core.models import Override, ReviewItem, ReviewRuling, StressEdit

db = pytest.mark.django_db(transaction=True)

BUILD = "20261017T110000Z"
A, B, C = 7201, 7202, 7203
CROSS = 7301
STEP = 0.002  # each piece runs this far east (about 570 ft, 173 m)
NAMES = {A: "Oak Street", B: "Oak Street", C: "oak street", CROSS: "Elm Street"}


@pytest.fixture(autouse=True)
def router(monkeypatch):
    """Names and classes every way it is told of, wherever asked; `down` makes it silent."""

    class Fake:
        names = dict(NAMES)
        classes = {A: "tertiary", B: "tertiary", C: "tertiary", CROSS: "residential"}
        down = False
        calls = 0

    def fake(lat, lon, costing, timeout_s=None):
        Fake.calls += 1
        # Never asked while a transaction holds the queue's rows.
        assert not connection.in_atomic_block
        if Fake.down:
            raise segment_info.RouterSilent("down")
        return [
            {
                "edge_info": {"way_id": w, "names": [n]},
                "edge": {"classification": {"classification": Fake.classes.get(w, "")}},
            }
            for w, n in Fake.names.items()
        ]

    monkeypatch.setattr(segment_info, "locate_edges", fake)
    segment_info.forget_columns()
    yield Fake
    segment_info.forget_columns()


def cross(schema, way, lon, tier) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, stress_tier, stress_rule, "
            "map_class, geometry) VALUES (%s, 0, %s, 'r', 'road', "
            "ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)))",
            [way, tier, lon, LAT - 0.001, lon, LAT + 0.001],
        )


@pytest.fixture
def road(segment_schemas):
    """Oak Street in three pieces west to east, LTS 2 in the map and LTS 4 in the new build, and
    Elm Street crossing between the second and third piece (calm, LTS 2)."""
    live, staging = segment_schemas
    for schema, tier in ((live, 2), (staging, 4)):
        for i, way in enumerate((A, B, C)):
            make_segment(schema, way, tier, lon=LON + i * STEP, map_class="road")
        cross(schema, CROSS, LON + 2 * STEP, 2)
    return live, staging


def rows() -> list[dict]:
    return stress_review.page("rebuild", open_only=False)["items"]


@db
class TestGrouping:
    def test_a_side_street_does_not_end_the_stretch(self, road) -> None:
        live, staging = road
        assert stress_review.compute_rebuild(BUILD, live, staging) == 3
        listed = rows()
        assert len(listed) == 1
        one = listed[0]
        assert one["ways"] == [A, B, C] and one["pieces"] == 3
        assert one["name"] == "Oak Street"
        # Its length the sum, its lines every way's, its point on the longest (the lead).
        lengths = {i.osm_way_id: i for i in ReviewItem.objects.filter(stretch=one["osm_way_id"])}
        assert set(lengths) == {A, B, C}
        assert len(one["geometry"]["coordinates"]) == 3
        assert one["length_m"] > 3 * 170
        assert " mi (" in one["length"] and one["length"].endswith("km)")
        summary = {q["queue"]: q for q in stress_review.queue_summary()}
        assert summary["rebuild"]["total"] == 1
        # Any of its ways opens it.
        assert stress_review.page("rebuild", open_only=False, way=B)["items"][0]["ways"] == [
            A,
            B,
            C,
        ]
        view = stress_review.map_view(
            ["rebuild"], (LON - 0.01, LAT - 0.01, LON + 0.02, LAT + 0.01), 15
        )
        assert len(view["lines"]["features"]) == 1

    def test_a_secondary_road_ends_it(self, road, router) -> None:
        live, staging = road
        router.classes[CROSS] = "secondary"
        stress_review.compute_rebuild(BUILD, live, staging)
        assert sorted(r["ways"] for r in rows()) == [[A, B], [C]]

    def test_a_link_of_a_major_road_ends_it(self, road, router) -> None:
        live, staging = road
        # Valhalla classes a link as its road's class.
        router.classes[CROSS] = "primary"
        router.names[CROSS] = ""
        stress_review.compute_rebuild(BUILD, live, staging)
        assert sorted(r["ways"] for r in rows()) == [[A, B], [C]]

    def test_a_different_change_is_a_row_of_its_own(self, road) -> None:
        live, staging = road
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {staging}.segment SET stress_tier = 3 WHERE osm_way_id = %s", [C]
            )
        stress_review.compute_rebuild(BUILD, live, staging)
        listed = sorted(rows(), key=lambda r: r["ways"])
        assert [r["ways"] for r in listed] == [[A, B], [C]]
        assert [r["kind_label"] for r in listed] == ["LTS 2 to LTS 4", "LTS 2 to LTS 3"]

    def test_another_name_is_another_road(self, road, router) -> None:
        live, staging = road
        router.names[C] = "Pine Street"
        stress_review.compute_rebuild(BUILD, live, staging)
        assert sorted(r["ways"] for r in rows()) == [[A, B], [C]]

    def test_with_the_router_silent_unnamed_ways_stay_alone(self, road, router) -> None:
        live, staging = road
        router.down = True
        stress_review.compute_rebuild(BUILD, live, staging)
        assert sorted(r["ways"] for r in rows()) == [[A], [B], [C]]

    def test_the_narrow_rural_and_disagreement_lists_group_too(self, road) -> None:
        _live, staging = road
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {staging}.segment SET stress_rule = "
                "'mixed traffic, 25 mph, single lane, narrow rural road' "
                "WHERE osm_way_id = ANY(%s)",
                [[A, B, C]],
            )
        assert stress_review.compute_narrow_rural(staging) == 3
        assert [r["ways"] for r in stress_review.page("narrow_rural")["items"]] == [[A, B, C]]


@db
class TestRulingAStretch:
    @pytest.fixture
    def listed(self, road):
        live, staging = road
        stress_review.compute_rebuild(BUILD, live, staging)
        (one,) = rows()
        return live, one

    def test_set_lts_writes_every_way_as_one_edit_and_undo_puts_them_back(self, listed) -> None:
        live, one = listed
        admin = make_user()
        made, refused = stress_review.rule(admin, "rebuild", [one["osm_way_id"]], "set", step=3)
        assert refused == []
        assert sorted(r.osm_way_id for r in made) == [A, B, C]
        assert made[0].osm_way_id == one["osm_way_id"]
        # Written as a ruling a way is: an owner override a way, one stress edit for them all.
        assert {r.stretch for r in made} == {one["osm_way_id"]}
        assert len({r.edit_id for r in made}) == 1
        assert StressEdit.objects.count() == 1
        overrides = Override.objects.filter(kind="stress", approved=True)
        assert sorted(o.osm_way_id for o in overrides) == [A, B, C]
        assert stress_review.page("rebuild")["total"] == 0
        assert stress_review.unruled_rebuild_changes()[:2] == (0, 3)
        ruling, _generation = stress_review.undo(admin, made[-1].pk)
        assert ReviewRuling.objects.filter(undone_at__isnull=True).count() == 0
        assert stress_review.page("rebuild")["total"] == 1

    def test_accept_rules_every_way_and_undo_undoes_them_all(self, listed) -> None:
        _live, one = listed
        admin = make_user()
        made, _ = stress_review.rule(admin, "rebuild", [one["osm_way_id"]], "accept")
        assert sorted(r.osm_way_id for r in made) == [A, B, C]
        assert stress_review.page("rebuild")["total"] == 0
        stress_review.undo(admin, made[1].pk)
        assert ReviewRuling.objects.filter(undone_at__isnull=True).count() == 0
        assert stress_review.page("rebuild")["total"] == 1

    def test_a_stretch_with_one_way_unruled_is_still_open(self, listed) -> None:
        _live, one = listed
        admin = make_user()
        other = next(w for w in (A, B, C) if w != one["osm_way_id"])
        ReviewRuling.objects.create(
            queue="rebuild", build_id=BUILD, osm_way_id=one["osm_way_id"], decision="accept"
        )
        assert stress_review.page("rebuild")["total"] == 1
        # Shown open, not with its lead's ruling.
        assert rows()[0]["ruling"] is None
        stress_review.rule(admin, "rebuild", [other], "accept")
        assert stress_review.page("rebuild")["total"] == 0
        assert rows()[0]["ruling"] is not None


@db
class TestBigBatches:
    @pytest.fixture
    def two(self, road, monkeypatch):
        """Two stretches, A+B and C (C changes to LTS 3), with an edit's cap of two ways."""
        live, staging = road
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {staging}.segment SET stress_tier = 3 WHERE osm_way_id = %s", [C]
            )
        stress_review.compute_rebuild(BUILD, live, staging)
        monkeypatch.setattr(stress_edits, "MAX_BATCH_WAYS", 2)
        return [r["osm_way_id"] for r in rows()]

    def test_change_lts_past_an_edits_cap_is_several_edits_never_refused(self, two) -> None:
        made, refused = stress_review.rule(make_user(), "rebuild", two, "set", step=3)
        assert refused == [] and sorted(r.osm_way_id for r in made) == [A, B, C]
        # A stretch is never split between two edits.
        edits = {r.osm_way_id: r.edit_id for r in made}
        assert edits[A] == edits[B] != edits[C]
        assert StressEdit.objects.count() == 2

    def test_accept_is_never_capped_by_ways(self, two) -> None:
        made, refused = stress_review.rule(make_user(), "rebuild", two, "accept")
        assert refused == [] and len(made) == 3


@db
def test_compute_all_shares_one_router_deadline(road, monkeypatch) -> None:
    live, staging = road
    made = []
    real = stress_review._Router.__init__

    def counted(self, *args, **kwargs):
        made.append(self)
        real(self, *args, **kwargs)

    monkeypatch.setattr(stress_review._Router, "__init__", counted)
    stress_review.compute_all(BUILD, live, staging, None)
    assert len(made) == 1
    assert [r["ways"] for r in rows()] == [[A, B, C]]


@db
def test_undo_after_a_change_past_an_edits_cap_restores_every_road(
    segment_schemas, monkeypatch
) -> None:
    """250 roads set at once are two stress edits (200 ways each at most); one Undo reverts
    the whole request, both edits."""
    live, staging = segment_schemas
    ways = list(range(8000, 8250))
    for schema, tier in ((live, 2), (staging, 4)):
        for n, way in enumerate(ways):
            make_segment(schema, way, tier, lon=LON + n * 0.003, map_class="road")
    stress_review.compute_rebuild(BUILD, live, staging)
    monkeypatch.setattr(stress_review, "BATCH_MAX", 300)
    admin = make_user()
    made, refused = stress_review.rule(admin, "rebuild", ways, "set", step=3)
    assert refused == [] and len(made) == 250
    assert len({r.edit_id for r in made}) == 2
    assert Override.objects.filter(kind="stress", approved=True).count() == 250
    stress_review.undo(admin, made[-1].pk)
    assert ReviewRuling.objects.filter(undone_at__isnull=True).count() == 0
    assert (
        Override.objects.filter(kind="stress", approved=True, superseded_by__isnull=True).count()
        == 0
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT DISTINCT stress_tier FROM {live}.segment WHERE osm_way_id = ANY(%s)", [ways]
        )
        assert [r[0] for r in cursor.fetchall()] == [2]
    assert stress_review.page("rebuild")["total"] == 250
