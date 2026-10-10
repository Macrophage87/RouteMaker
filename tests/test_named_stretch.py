"""The whole named stretch at once (HALF-STEP-EDITOR phase 5; core.stress_edits.named_stretch).

What is pinned here: the stretch is the road pieces of one name connected end to end, by the
router's names as the road panel shows them (the table's where the router is silent); it ends
at a junction with a road of another name at 2.5 or above (a high-stress crossing, the
cautious reading) and at MAX_STRETCH_WAYS pieces; one change writes one override row a way
sharing one adjustment id, and Undo puts every way back; a single piece's token is unchanged.
"""

from __future__ import annotations

import pytest
import test_stress_edits
from django.db import connection
from test_stress_edits import (
    CREATE,
    LAT,
    LON,
    REASON,
    STATE,
    addr,
    admin_client,
    live_row,
    make_segment,
    make_user,
    post,
    spec,
)

from core import segment_info, stress_edits
from core.models import Override, StressEdit
from pipeline import overrides as pipeline_overrides

db = pytest.mark.django_db(transaction=True)

A, B, C, D = 5101, 5102, 5103, 5104
CROSS = 6101
STEP = 0.002  # each piece runs this far east (about 570 ft, 173 m)
NAMES = {A: "Oak Street", B: "Oak Street", C: "oak street", D: "Pine Street", CROSS: "Elm Street"}


def cross(schema, way, lon, tier, *, half=False, name=None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, stress_tier, stress_rule, "
            "stress_half, trail_name, map_class, geometry) VALUES (%s, 0, %s, 'r', %s, %s, 'road', "
            "ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)))",
            [way, tier, half, name, lon, LAT - 0.001, lon, LAT + 0.001],
        )


@pytest.fixture(autouse=True)
def router(monkeypatch):
    """Names every way it is told of, wherever asked; `down` makes it silent."""

    class Fake:
        names = dict(NAMES)
        down = False
        calls = 0

    def fake(lat, lon, costing):
        Fake.calls += 1
        if Fake.down:
            raise segment_info.RouterSilent("down")
        return [{"edge_info": {"way_id": w, "names": [n]}} for w, n in Fake.names.items()]

    monkeypatch.setattr(segment_info, "locate_edges", fake)
    segment_info.forget_columns()
    yield Fake
    segment_info.forget_columns()


@pytest.fixture
def road(segment_schemas):
    """Oak Street in three pieces west to east, Pine Street on past its end, and Elm Street
    crossing between the second and third piece (calm, LTS 2, unless a test raises it)."""
    schema, _staging = segment_schemas
    for i, way in enumerate((A, B, C, D)):
        make_segment(schema, way, 3, lon=LON + i * STEP, map_class="road")
    cross(schema, CROSS, LON + 2 * STEP, 2)
    return schema


def set_cross(schema, tier, half=False) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {schema}.segment SET stress_tier = %s, stress_half = %s WHERE osm_way_id = %s",
            [tier, half, CROSS],
        )


def stretch_token(schema, ways) -> str:
    columns = stress_edits.edit_columns(schema)
    return stress_edits.token_of(stress_edits.read_rows(schema, columns, ways), ways)


@db
class TestTheStretch:
    def test_the_pieces_of_one_name_end_to_end_and_not_the_next_road(self, road) -> None:
        found = stress_edits.named_stretch(road, B)
        assert found["name"] == "Oak Street"
        assert found["ways"] == [A, B, C] and found["pieces"] == 3 and not found["capped"]
        assert 3 * 160 < found["length_m"] < 3 * 190

    def test_every_piece_finds_the_same_stretch(self, road) -> None:
        assert stress_edits.named_stretch(road, A)["ways"] == [A, B, C]
        assert stress_edits.named_stretch(road, C)["ways"] == [A, B, C]

    @pytest.mark.parametrize(
        "tier, half, ends", [(2, False, False), (2, True, True), (3, False, True), (5, False, True)]
    )
    def test_it_ends_at_a_crossing_of_2_5_or_more(self, road, tier, half, ends) -> None:
        set_cross(road, tier, half)
        found = stress_edits.named_stretch(road, A)
        assert found["ways"] == ([A, B] if ends else [A, B, C])

    def test_the_unsmoothed_level_counts_as_the_junction_model_reads_it(self, road) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {road}.segment SET stress_unsmoothed_tier = 3 WHERE osm_way_id = %s",
                [CROSS],
            )
        assert stress_edits.named_stretch(road, A)["ways"] == [A, B]

    def test_an_unnamed_road_or_a_lone_piece_has_none(self, road, router) -> None:
        router.names = {**NAMES, A: "", B: ""}
        assert stress_edits.named_stretch(road, A) is None
        assert stress_edits.named_stretch(road, D) is None

    def test_with_the_router_silent_the_tables_names_stand(self, road, router) -> None:
        router.down = True
        assert stress_edits.named_stretch(road, A) is None
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {road}.segment SET trail_name = 'Oak Street' WHERE osm_way_id IN (%s, %s)",
                [A, B],
            )
        assert stress_edits.named_stretch(road, A)["ways"] == [A, B]

    def test_it_stops_at_the_most_one_change_takes(self, road, monkeypatch) -> None:
        monkeypatch.setattr(stress_edits, "MAX_STRETCH_WAYS", 2)
        found = stress_edits.named_stretch(road, A)
        assert found["ways"] == [A, B] and found["capped"]

    def test_the_router_is_asked_once_a_spot(self, road, router) -> None:
        stress_edits.named_stretch(road, A)
        # Four distinct ends (three pieces in a row), one costing each: bicycle names them all.
        assert router.calls == 4


@db
class TestChangingTheStretch:
    def test_one_row_a_way_one_adjustment_every_piece_changed(self, road) -> None:
        old = test_stress_edits.TestSupersede().file_row(way=B)
        admin = make_user()
        ways = [A, B, C]
        result = stress_edits.apply(admin, ways, spec(4), stretch_token(road, ways))
        rows = Override.objects.filter(source="panel").order_by("osm_way_id")
        assert [r.osm_way_id for r in rows] == ways
        assert len({r.value["adjustment_id"] for r in rows}) == 1
        assert rows[0].value["adjustment_id"] == f"edit-{min(r.pk for r in rows)}"
        assert all(live_row(road, w)["stress_tier"] == 4 for w in ways)
        assert live_row(road, D)["stress_tier"] == 3
        old.refresh_from_db()
        assert old.superseded_by_id == rows[1].pk
        edit = result.edit
        assert edit.osm_way_ids == ways and len(edit.override_rows) == 3
        assert {p["way"]: p["replaced"] for p in edit.override_rows} == {
            A: None,
            B: old.pk,
            C: None,
        }
        assert [w["osm_way_id"] for w in result.ways] == ways and all(
            w["changed"] for w in result.ways
        )
        # The rebuild reads one live row a way, all from the one change.
        loaded = pipeline_overrides.load_approved(fingerprints={})
        assert sorted(r.osm_way_id for r in loaded) == ways

    def test_undo_puts_every_piece_back_and_reinstates_the_replaced_row(self, road) -> None:
        old = test_stress_edits.TestSupersede().file_row(way=C)
        admin = make_user()
        ways = [A, B, C]
        done = stress_edits.apply(admin, ways, spec(4), stretch_token(road, ways))
        undone = stress_edits.undo(admin, done.edit.pk)
        assert all(live_row(road, w)["stress_tier"] == 3 for w in ways)
        old.refresh_from_db()
        assert old.superseded_by_id is None and old.approved
        assert not Override.objects.filter(
            source="panel", approved=True, superseded_by__isnull=True
        ).exists()
        assert {p["way"]: p["override"] for p in undone.edit.override_rows} == {
            A: None,
            B: None,
            C: old.pk,
        }
        assert StressEdit.objects.count() == 2

    def test_a_set_that_is_not_the_stretch_is_refused(self, road) -> None:
        for ways in ([A, B], [A, C, D], [A, D]):
            with pytest.raises(stress_edits.Invalid):
                stress_edits.apply(make_user(), ways, spec(4), stretch_token(road, ways))
        assert not Override.objects.exists()

    def test_a_change_to_any_piece_makes_the_stretch_stale(self, road) -> None:
        ways = [A, B, C]
        expected = stretch_token(road, ways)
        stress_edits.apply(make_user(), [C], spec(5), stretch_token(road, [C]))
        with pytest.raises(stress_edits.Stale):
            stress_edits.apply(make_user(), ways, spec(4), expected)

    def test_a_single_pieces_token_is_as_before(self, road) -> None:
        columns = stress_edits.edit_columns(road)
        rows = stress_edits.read_rows(road, columns, [A])
        assert stress_edits.token_of(rows, [A]) == stress_edits.token_for(rows, None)


@db
class TestTheEndpoints:
    def test_the_editor_state_offers_the_stretch_with_its_own_token(self, road) -> None:
        client, csrf = admin_client()
        state = client.get(STATE.format(B), **addr()).json()
        stretch = state["stretch"]
        assert stretch["name"] == "Oak Street" and stretch["osm_way_ids"] == [A, B, C]
        assert stretch["pieces"] == 3 and not stretch["capped"]
        assert stretch["expected"] != state["expected"]
        r = post(
            client,
            CREATE,
            {
                "osm_way_ids": stretch["osm_way_ids"],
                "step": 3.5,
                "at_least": False,
                "category": "speed",
                "reason": REASON,
                "expected": stretch["expected"],
            },
            csrf,
        )
        assert r.status_code == 200, r.json()
        assert [w["step"] for w in r.json()["ways"]] == [3.5, 3.5, 3.5]

    def test_a_lone_piece_has_no_stretch(self, road) -> None:
        client, _csrf = admin_client()
        assert client.get(STATE.format(D), **addr()).json()["stretch"] is None

    def test_more_than_40_pieces_is_400(self, road) -> None:
        client, csrf = admin_client()
        payload = {
            "osm_way_ids": list(range(1, 42)),
            "step": 4,
            "at_least": False,
            "category": "speed",
            "reason": REASON,
            "expected": "x",
        }
        r = post(client, CREATE, payload, csrf)
        assert r.status_code == 400 and r.json().get("field") == "osm_way_ids"
