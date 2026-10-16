"""Share the identical route (v0.7.0; core.shared_routes): POST /api/shared-routes keeps the exact
line under the link's 128-bit id, and GET /api/shared-routes/{id} gives it back unchanged.

Signed out works; nothing of the sharer is kept but, signed in, the account (no address, no
weight); a taken id is never replaced; a route is at most 2 MB; it is kept a year after it was
last opened.
"""

from __future__ import annotations

import json
import secrets
from datetime import timedelta
from itertools import count
from pathlib import Path

import pytest
from django.test import Client
from django.utils import timezone

from core import ratelimit, shared_routes
from core.models import SharedRoute

db = pytest.mark.django_db(transaction=True)
REPO = Path(__file__).resolve().parents[1]
URL = "/api/shared-routes"

_clients = count(10)

LINE = [[-77.03651, 38.89768, 12.5], [-77.03012, 38.90011, 14.0], [-77.02101, 38.90455, 16.25]]
INPUTS = {
    "hash": "#p=-77.03651,38.89768;-77.02101,38.90455&preset=default&v=2",
    "points": [[-77.03651, 38.89768], [-77.02101, 38.90455]],
    "preset": "default",
    "dials": {"stress": 70, "hills": 0},
}


def addr() -> dict:
    return {"HTTP_X_FORWARDED_FOR": f"198.51.100.{next(_clients) % 250}"}


def new_id() -> str:
    return secrets.token_hex(16)


def planned(**changes) -> dict:
    """A real planner answer (tests/data/route_answer.json, the /api/route answer of
    test_route_api's standard route), with a rider's weight in its dials."""
    answer = json.loads((REPO / "tests" / "data" / "route_answer.json").read_text())
    answer["dials"]["system_weight_kg"] = 82
    answer["effort_m"] = 1700.0
    return {**answer, **changes}


def body(**changes) -> dict:
    return {
        "id": new_id(),
        "name": "Lincoln Memorial to Logan Circle",
        "source": "plan",
        "line": LINE,
        "distance_m": 1520.4,
        "inputs": INPUTS,
        "answer": planned(),
        **changes,
    }


def post(client: Client, payload, **extra):
    return client.post(
        URL, data=json.dumps(payload), content_type="application/json", **addr(), **extra
    )


@db
class TestSharedRoutes:
    def test_signed_out_a_planned_line_is_kept_and_opened_verbatim(self) -> None:
        client = Client(enforce_csrf_checks=True)
        sent = body()
        r = post(client, sent)
        assert r.status_code == 201 and r.json() == {"id": sent["id"]}
        got = client.get(f"{URL}/{sent['id']}", **addr())
        assert got.status_code == 200 and got["Cache-Control"] == "no-store"
        out = got.json()
        # The exact line, elevations and order and all; the inputs for Update route.
        assert out["line"] == LINE and out["inputs"] == INPUTS
        assert out["distance_m"] == 1520.4 and out["source"] == "plan"
        assert out["name"] == "Lincoln Memorial to Logan Circle"
        assert out["answer"]["distance_m"] == 2200.0
        assert out["answer"]["stress_m"] == sent["answer"]["stress_m"]

    def test_the_answer_is_read_as_the_planners_own(self) -> None:
        """The answer is served back as planner output, so it is read through RouteOut: a key
        the planner never writes is dropped, a malformed answer or an overlong string is
        refused."""
        client = Client()
        sent = body(
            answer=planned(script="<x>", geometry={"type": "LineString", "coordinates": []})
        )
        sent["answer"]["profile"] = None
        assert post(client, sent).status_code == 201
        kept = SharedRoute.objects.get(pk=sent["id"]).answer
        assert "script" not in kept and kept["preset"] == "default"
        for bad in (
            {"distance_m": 1520.4, "geometry": {"type": "LineString"}},
            planned(preset="nope"),
            planned(stress_m="lots"),
            planned(attribution=["x" * 2001]),
            [1, 2],
        ):
            r = post(client, body(answer=bad))
            assert r.status_code == 400 and r.json()["field"] == "answer", bad

    def test_no_weight_and_nothing_of_the_sharer_is_kept(self) -> None:
        client = Client()
        sent = body()
        post(client, sent, HTTP_USER_AGENT="Phone 1.0")
        row = SharedRoute.objects.get(pk=sent["id"])
        # OWNER-DECISIONS 313: the weight never leaves the rider, nor the effort weighed with it.
        assert row.answer["dials"]["system_weight_kg"] is None and row.answer["effort_m"] is None
        assert row.answer["candidates"] is None
        fields = {f.name for f in SharedRoute._meta.get_fields()}
        assert fields == {
            "id",
            "name",
            "source",
            "line",
            "distance_m",
            "inputs",
            "answer",
            "gpx",
            "created_at",
            "last_opened_at",
            "keep",
            "delete_after",
            # Shared signed in, the account (and nothing else of it), so only it can turn the
            # link off; and the link preview's image (core.share_preview).
            "owner",
            "revoked_at",
            "preview_image",
            "preview_zone",
            "preview_key",
            "preview_png",
        }
        assert "198.51.100" not in json.dumps([row.name, row.line, row.inputs, row.answer, row.gpx])
        # A position, an account or anything else not part of a route is refused, not kept.
        for extra in ({"position": [-77.0, 38.9]}, {"user": 1}):
            r = post(client, body(**extra))
            assert r.status_code == 400

    def test_an_answer_without_a_weight_keeps_its_effort(self) -> None:
        client = Client()
        answer = planned()
        answer["dials"]["system_weight_kg"] = None
        sent = body(answer=answer)
        post(client, sent)
        assert SharedRoute.objects.get(pk=sent["id"]).answer["effort_m"] == 1700.0

    def test_a_gpx_file_is_kept_byte_for_byte(self) -> None:
        client = Client()
        line = [[-80.5, 40.0], *LINE]
        text = '<?xml version="1.0"?>\n<gpx version="1.1"><trk><trkseg/></trk></gpx>\n'
        sent = body(source="gpx", line=line, answer=None, gpx=text)
        assert post(client, sent).status_code == 201
        out = client.get(f"{URL}/{sent['id']}", **addr()).json()
        assert out["line"] == line and out["gpx"] == text and out["answer"] is None
        assert post(client, body(gpx=text)).status_code == 400

    def test_a_taken_id_is_never_replaced(self) -> None:
        client = Client()
        sent = body()
        assert post(client, sent).status_code == 201
        again = post(client, {**sent, "line": [[-77.0, 38.9], [-77.01, 38.91]]})
        assert again.status_code == 409 and again.json()["code"] == "taken"
        assert SharedRoute.objects.get(pk=sent["id"]).line == LINE

    @pytest.mark.parametrize(
        "changes",
        [
            {"id": "abc"},
            {"id": "G" * 32},
            {"id": "0" * 31},
            {"id": None},
            {"name": "x" * 121},
            {"line": [[-77.0, 38.9]]},
            {"line": [[-80.5, 40.0], [-80.6, 40.1]]},
            {"distance_m": 0},
            {"inputs": {"secret": 1}},
            {"source": "strava"},
        ],
    )
    def test_a_bad_route_is_refused(self, changes) -> None:
        r = post(Client(), body(**changes))
        assert r.status_code == 400 and r.json()["error"]
        assert not SharedRoute.objects.exists()

    def test_a_deeply_nested_body_is_a_400(self) -> None:
        """Nesting past the JSON parser's stack raises RecursionError: refused, not a 500."""
        deep = "[" * 200_000 + "]" * 200_000
        r = Client().post(URL, data=deep, content_type="application/json", **addr())
        assert r.status_code == 400 and r.json()["error"] == "The body is not JSON."

    def test_at_most_2_mb(self) -> None:
        assert shared_routes.MAX_BYTES == 2 * 1024 * 1024
        big = body(source="gpx", answer=None, gpx="x" * shared_routes.MAX_BYTES)
        r = post(Client(), big)
        assert r.status_code == 400 and "larger" in r.json()["error"]
        assert not SharedRoute.objects.exists()

    def test_a_foreign_page_cannot_store_or_read(self) -> None:
        sent = body()
        r = post(Client(), sent, HTTP_SEC_FETCH_SITE="cross-site")
        assert r.status_code == 403 and not SharedRoute.objects.exists()
        post(Client(), sent)
        got = Client().get(f"{URL}/{sent['id']}", HTTP_SEC_FETCH_SITE="cross-site", **addr())
        assert got.status_code == 403

    def test_an_unknown_or_malformed_id_is_not_found(self) -> None:
        client = Client()
        assert client.get(f"{URL}/{new_id()}", **addr()).status_code == 404
        r = client.get(f"{URL}/not-an-id", **addr())
        assert r.status_code == 404 and r.json()["code"] == "not_found"

    def test_kept_a_year_after_it_was_last_opened(self) -> None:
        client = Client()
        old, fresh, opened = body(), body(), body()
        for sent in (old, fresh, opened):
            post(client, sent)
        now = timezone.now()
        SharedRoute.objects.filter(pk=old["id"]).update(last_opened_at=now - timedelta(days=366))
        SharedRoute.objects.filter(pk=fresh["id"]).update(last_opened_at=now - timedelta(days=364))
        SharedRoute.objects.filter(pk=opened["id"]).update(
            created_at=now - timedelta(days=700), last_opened_at=now - timedelta(days=300)
        )
        # Opening one moves its year on.
        assert client.get(f"{URL}/{opened['id']}", **addr()).status_code == 200
        assert SharedRoute.objects.get(pk=opened["id"]).last_opened_at > now - timedelta(minutes=1)
        # An expired one is gone, and goes at the next open or share.
        assert client.get(f"{URL}/{old['id']}", **addr()).status_code == 404
        assert not SharedRoute.objects.filter(pk=old["id"]).exists()
        assert SharedRoute.objects.filter(pk=fresh["id"]).exists()
        SharedRoute.objects.filter(pk=fresh["id"]).update(last_opened_at=now - timedelta(days=400))
        post(client, body())
        assert not SharedRoute.objects.filter(pk=fresh["id"]).exists()

    def test_the_sharer_may_keep_it_permanently_or_until_a_date(self) -> None:
        """The owner, 2026-10-16: a year is the default; "keep permanently" and "delete after
        <date>" are the sharer's to pick."""
        client = Client()
        today = timezone.localdate()
        year, forever = body(), body(keep="forever")
        until = body(keep="until", delete_after=(today + timedelta(days=30)).isoformat())
        for sent in (year, forever, until):
            assert post(client, sent).status_code == 201
        assert SharedRoute.objects.get(pk=year["id"]).keep == "year"
        got = client.get(f"{URL}/{until['id']}", **addr()).json()
        assert got["keep"] == "until" and got["delete_after"] == until["delete_after"]

        long_ago = timezone.now() - timedelta(days=3000)
        SharedRoute.objects.update(last_opened_at=long_ago)
        # Permanently: never pruned, however long unopened.
        assert client.get(f"{URL}/{forever['id']}", **addr()).status_code == 200
        # Until a date: kept through it whatever the last open, gone the day after.
        assert client.get(f"{URL}/{until['id']}", **addr()).status_code == 200
        assert client.get(f"{URL}/{year['id']}", **addr()).status_code == 404
        SharedRoute.objects.filter(pk=until["id"]).update(delete_after=today - timedelta(days=1))
        assert client.get(f"{URL}/{until['id']}", **addr()).status_code == 404
        assert set(SharedRoute.objects.values_list("pk", flat=True)) == {forever["id"]}

    @pytest.mark.parametrize(
        "changes",
        [
            {"keep": "decade"},
            {"keep": "until"},
            {"keep": "until", "delete_after": "2026-13-01"},
            {"keep": "until", "delete_after": "tomorrow"},
            {"keep": "year", "delete_after": "2099-01-01"},
        ],
    )
    def test_a_bad_keeping_is_refused(self, changes) -> None:
        r = post(Client(), body(**changes))
        assert r.status_code == 400 and r.json()["error"]
        assert not SharedRoute.objects.exists()

    def test_a_delete_date_is_today_or_later(self) -> None:
        """Today, in UTC: the page offers the sharer's own tomorrow or later, which west of UTC
        in the evening is UTC's today."""
        today = timezone.localdate()
        r = post(Client(), body(keep="until", delete_after=(today - timedelta(days=1)).isoformat()))
        assert r.status_code == 400 and r.json()["field"] == "delete_after"
        assert post(Client(), body(keep="until", delete_after=today.isoformat())).status_code == 201

    def test_sharing_is_rate_limited_per_client(self) -> None:
        client = Client()
        here = {"HTTP_X_FORWARDED_FOR": "203.0.113.9"}
        for _ in range(ratelimit.SHARED_ROUTE_WRITES.requests):
            r = client.post(URL, data=json.dumps(body()), content_type="application/json", **here)
            assert r.status_code == 201
        r = client.post(URL, data=json.dumps(body()), content_type="application/json", **here)
        assert r.status_code == 429


def test_the_table_is_never_shipped_to_the_beta_and_is_documented() -> None:
    ship = (REPO / "scripts" / "beta" / "ship-data.sh").read_text()
    assert "shared_route" in ship.split("EXCLUDED_TABLE_DATA=(", 1)[1].split(")", 1)[0]
    operations = (REPO / "docs" / "OPERATIONS.md").read_text()
    assert "### Shared routes (v0.7.0)" in operations
    assert "| `shared_route` rows" in operations and "1 year after" in operations
    assert "0022_shared_route" in operations


def test_the_migration_follows_the_newest() -> None:
    migrations = sorted((REPO / "src" / "core" / "migrations").glob("0*.py"))
    assert migrations[-3].name == "0022_shared_route.py"
    assert '("core", "0021_signed_out_suggestions")' in migrations[-3].read_text()
    assert migrations[-2].name == "0023_shared_route_keep.py"
    assert '("core", "0022_shared_route")' in migrations[-2].read_text()
    assert migrations[-1].name == "0024_shared_route_owner_preview.py"
    assert '("core", "0023_shared_route_keep")' in migrations[-1].read_text()
