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

    def fake(url, payload, timeout):
        assert url.endswith("/locate")
        if Fake.down:
            raise routing.RouterUnavailable("down")
        return [
            {
                "edges": [
                    {"edge_info": {"way_id": way, "names": [name]}}
                    for way, name in Fake.by_way.items()
                ]
            }
            for _ in payload["locations"]
        ]

    monkeypatch.setattr(routing, "_transport", fake)
    segment_info.forget_columns()
    yield Fake
    segment_info.forget_columns()


def get(client, miles=5, point=SPOT):
    return client.get(URL, {"lon": point[0], "lat": point[1], "miles": miles}, **fresh_client())


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
        names.by_way = {12: "Peach Tree Road", 21: "Moore Road"}
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
