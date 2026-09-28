"""GET /api/coverage: the area the planner routes in, which the map greys out
the rest of (owner request of 2026-09-27, "grey out all the parts of the map
that don't have support").

The property that matters is that the shape served is the shape the route
endpoint enforces, so each edge is checked against the route validator from
both sides.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from test_ratelimit import in_one_window

from core import ratelimit
from core.api import RouteIn

db = pytest.mark.django_db(transaction=True)

PATH = "/api/coverage"


def ring(client) -> list[list[float]]:
    response = client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "Feature"
    assert body["geometry"]["type"] == "Polygon"
    (outer,) = body["geometry"]["coordinates"]
    return outer


def accepted(lon: float, lat: float) -> bool:
    """Whether POST /api/route's body model takes a short route from here."""
    try:
        RouteIn(points=[[lon, lat], [lon, lat]], preset="default")
    except ValidationError:
        return False
    return True


@db
class TestCoverage:
    def test_a_closed_ring_served_signed_out_and_cacheable(self, client) -> None:
        response = client.get(PATH)
        assert response.status_code == 200
        assert "public" in response["Cache-Control"]
        assert "max-age=" in response["Cache-Control"]
        outer = ring(client)
        assert outer[0] == outer[-1]
        assert len(outer) >= 4

    def test_counter_clockwise_as_rfc_7946_asks(self, client) -> None:
        outer = ring(client)
        area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(outer, outer[1:], strict=False))
        assert area2 > 0

    def test_its_edges_are_the_route_validators(self, client) -> None:
        """Just inside every edge is routable and just outside is refused."""
        outer = ring(client)
        lons = [p[0] for p in outer]
        lats = [p[1] for p in outer]
        west, east, south, north = min(lons), max(lons), min(lats), max(lats)
        mid_lon, mid_lat = (west + east) / 2, (south + north) / 2
        eps = 1e-4
        for inside, outside in [
            ((west + eps, mid_lat), (west - eps, mid_lat)),
            ((east - eps, mid_lat), (east + eps, mid_lat)),
            ((mid_lon, south + eps), (mid_lon, south - eps)),
            ((mid_lon, north - eps), (mid_lon, north + eps)),
        ]:
            assert accepted(*inside), inside
            assert not accepted(*outside), outside

    def test_only_get(self, client) -> None:
        assert client.post(PATH).status_code == 405

    def test_in_the_openapi_schema(self, client) -> None:
        assert PATH in client.get("/api/openapi.json").json()["paths"]

    def test_limited_per_address_apart_from_routing_and_the_tiles(self, client) -> None:
        limit = ratelimit.COVERAGE
        assert limit.scope not in {ratelimit.ROUTING.scope, ratelimit.TILES.scope}

        def attempt(n):
            headers = {"HTTP_X_FORWARDED_FOR": f"198.51.100.{60 + 100 * n}"}
            statuses = {client.get(PATH, **headers).status_code for _ in range(limit.requests)}
            return statuses, client.get(PATH, **headers)

        statuses, refused = in_one_window(limit.window_s, attempt)
        assert statuses == {200}
        assert refused.status_code == 429
        assert refused["Retry-After"]
        assert refused.json()["error"]
