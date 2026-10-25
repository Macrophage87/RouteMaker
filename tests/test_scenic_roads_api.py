"""GET /api/scenic-roads: the rustic roads, byways and named bike routes near a point (v0.12.3,
`core.scenic_near`; the owner, 2026-10-25: "The goal would be for a new user to be able to make
routes like this").

Against a real live segment table (the `segment_schemas` fixture); the router's `/locate` is
replaced at `core.routing._transport`.
"""

from __future__ import annotations

import pytest
from test_segment_info_api import east, fresh_client, insert, north

from core import routing, segment_info

db = pytest.mark.django_db(transaction=True)

URL = "/api/scenic-roads"
# Peach Tree Road near Barnesville, MD, roughly.
SPOT = (-77.3855, 39.1780)
RUSTIC = "Rustic Road (Montgomery County)"
EXCEPTIONAL = "Exceptional Rustic Road (Montgomery County)"


@pytest.fixture
def names(monkeypatch):
    """The router's /locate: each location's edges by way id, from `by_way`."""

    class Fake:
        by_way: dict[int, str] = {}
        down = False
        calls: list[int] = []

    def fake(url, payload, timeout):
        assert url.endswith("/locate")
        if Fake.down:
            raise routing.RouterUnavailable("down")
        Fake.calls.append(len(payload["locations"]))
        # Each location sees every way (a cross street within reach too), so a name must be
        # the edge of its own way's.
        return [
            {
                "edges": [
                    {"edge_info": {"way_id": way, "names": [name] if name else []}}
                    for way, name in Fake.by_way.items()
                ]
            }
            for _ in payload["locations"]
        ]

    monkeypatch.setattr(routing, "_transport", fake)
    segment_info.forget_columns()
    yield Fake
    segment_info.forget_columns()


def get(client, miles=5, point=SPOT, **extra):
    query = {"lon": point[0], "lat": point[1], "miles": miles, **extra}
    return client.get(URL, query, **fresh_client())


@db
class TestScenicRoads:
    def test_each_designated_road_near_is_listed_once_nearest_first(
        self, client, segment_schemas, names
    ) -> None:
        live, _ = segment_schemas
        # Peach Tree Road: two pieces end to end, one LTS 4 and one LTS 2.
        a, b, c = SPOT, east(SPOT, 600), east(SPOT, 1400)
        insert(live, 11, [a, b], stress_tier=4, scenic=RUSTIC)
        insert(live, 12, [b, c], stress_tier=2, scenic=RUSTIC)
        # Moore Road, 2 km north: Exceptional.
        m = north(SPOT, 2000)
        insert(live, 21, [m, east(m, 900)], stress_tier=2, scenic=EXCEPTIONAL)
        # An ordinary road and a far rustic road: not listed.
        insert(live, 31, [north(SPOT, 300), north(SPOT, 800)], stress_tier=2)
        far = north(SPOT, 30_000)
        insert(live, 41, [far, east(far, 900)], stress_tier=1, scenic=RUSTIC)
        names.by_way = {11: "Peach Tree Road", 12: "Peach Tree Road", 21: "Moore Road"}
        response = get(client)
        assert response.status_code == 200
        roads = response.json()["roads"]
        assert [(r["designation"], r["road"]) for r in roads] == [
            (RUSTIC, "Peach Tree Road"),
            (EXCEPTIONAL, "Moore Road"),
        ]
        peach = roads[0]
        assert peach["miles"] == pytest.approx(0.9, abs=0.1)
        assert set(peach["lts_miles"]) == {"LTS 2", "LTS 4"}
        assert peach["away_mi"] == 0.0 and len(peach["lon_lat"]) == 2
        assert roads[1]["away_mi"] == pytest.approx(1.2, abs=0.1)

    def test_roads_meeting_at_a_junction_stay_apart_and_one_road_s_pieces_join(
        self, client, segment_schemas, names
    ) -> None:
        live, _ = segment_schemas
        # Peach Tree Road east, a gap in the designation, then more of it as a bike route too;
        # Moore Road leaves it at the junction going north. Way 13 is unnamed in the router.
        a, b, c, d = SPOT, east(SPOT, 600), east(SPOT, 800), east(SPOT, 1400)
        insert(live, 11, [a, b], stress_tier=2, scenic=RUSTIC)
        insert(live, 12, [c, d], stress_tier=2, scenic=f"{RUSTIC} · USBR 50")
        insert(live, 21, [b, north(b, 900)], stress_tier=1, scenic=EXCEPTIONAL)
        insert(live, 13, [d, east(d, 500)], stress_tier=3, scenic=RUSTIC)
        names.by_way = {11: "Peach Tree Road", 12: "Peach Tree Road", 21: "Moore Road", 13: None}
        roads = {r["road"]: r for r in get(client).json()["roads"]}
        assert set(roads) == {"Peach Tree Road", "Moore Road", None}
        assert roads["Peach Tree Road"]["designation"] == f"{RUSTIC} · USBR 50"
        assert roads["Peach Tree Road"]["miles"] == pytest.approx(0.7, abs=0.1)
        assert roads["Moore Road"]["designation"] == EXCEPTIONAL
        assert names.calls == [4]
        only = get(client, designation="exceptional").json()["roads"]
        assert [r["road"] for r in only] == ["Moore Road"]

    def test_names_are_null_when_the_router_is_down(self, client, segment_schemas, names) -> None:
        live, _ = segment_schemas
        insert(live, 11, [SPOT, east(SPOT, 600)], stress_tier=2, scenic=RUSTIC)
        names.down = True
        roads = get(client).json()["roads"]
        assert [r["road"] for r in roads] == [None]

    def test_a_point_outside_the_map_and_a_wide_ask_are_refused(
        self, client, segment_schemas, names
    ) -> None:
        assert get(client, point=(-80.0, 40.0)).status_code == 400
        assert get(client, miles=40).status_code == 400


@db
class TestClimbsNear:
    def test_climbs_near_a_point_are_listed_and_a_missing_file_is_503(
        self, client, monkeypatch
    ) -> None:
        from core import hillseek

        line = ((-77.3855, 39.178), (-77.39, 39.18))
        found = hillseek.Climb(
            id="ab", category="4", length_m=1600.0, gain_m=80.0, grade_pct=5.0, line=line
        )
        monkeypatch.setattr(hillseek, "load", lambda: (found,))
        query = {"lon": SPOT[0], "lat": SPOT[1], "miles": 2}
        response = client.get("/api/climbs-near", query, **fresh_client())
        assert response.status_code == 200
        (climb,) = response.json()["climbs"]
        assert climb["id"] == "ab" and climb["surface"] == "road" and climb["through"]
        monkeypatch.setattr(hillseek, "load", lambda: None)
        assert client.get("/api/climbs-near", query, **fresh_client()).status_code == 503
        assert client.get("/api/climbs-near", {**query, "miles": 40}).status_code == 400
