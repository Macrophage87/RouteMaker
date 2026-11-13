"""Region packs for riding off grid (core.offline_packs, pipeline.offline_packs), 2026-11-13.
Synthetic ways only."""

from __future__ import annotations

import gzip
import json
import math

import pytest
from django.db import connection

from core import offline_packs
from pipeline import offline_packs as builder
from pipeline.offline_network import offline_way
from pipeline.writers import OfflineWayWriter

db = pytest.mark.django_db(transaction=True)
SCHEMA = "packs_test"
K_LAT = 111_195


def _at(lon: float, lat: float, east_m: float = 0.0, north_m: float = 0.0):
    return (lon + east_m / (K_LAT * math.cos(math.radians(lat))), lat + north_m / K_LAT)


def test_the_regions_are_his_riding_areas_and_cover_the_map() -> None:
    assert [r.id for r in offline_packs.REGIONS] == [
        "beltway",
        "nova",
        "nw-exurbs",
        "baltimore",
        "rest",
    ]
    assert sum(r.outline is None for r in offline_packs.REGIONS) == 1, "one region is the rest"
    for region in offline_packs.REGIONS:
        if region.outline is not None:
            assert region.outline[0] == region.outline[-1], region.id


@pytest.fixture
def ways():
    """Four streets: one downtown DC, one in Arlington, one in Baltimore, one in La Plata."""
    from pipeline.schema import SEGMENT_DDL  # noqa: F401 - the table's DDL is the rebuild's own

    with connection.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        cursor.execute(f"CREATE SCHEMA {SCHEMA}")
        cursor.execute(
            f"CREATE TABLE {SCHEMA}.offline_way (osm_way_id bigint PRIMARY KEY,"
            " node_ids bigint[] NOT NULL, geometry geometry(LineString, 4326) NOT NULL,"
            " level2 smallint NOT NULL, flags smallint NOT NULL, direction smallint NOT NULL,"
            " name text)"
        )
    writer = OfflineWayWriter.__new__(OfflineWayWriter)
    writer.schema, writer.pending, writer.written = SCHEMA, [], 0
    places = {
        1: ("K Street", (-77.03, 38.90)),
        2: ("Wilson Boulevard", (-77.10, 38.88)),
        3: ("Charles Street", (-76.615, 39.30)),
        4: ("Charles Street", (-76.98, 38.53)),
    }
    for way_id, (name, (lon, lat)) in places.items():
        points = [_at(lon, lat), _at(lon, lat, east_m=200)]
        writer.add(
            offline_way(
                way_id,
                {"highway": "residential", "name": name},
                [way_id * 10, way_id * 10 + 1],
                [0, 1],
                points,
                tier=1,
                half=False,
                access_reason=None,
                walk_bike=False,
                unpaved=False,
                mtb_only=False,
            )
        )
    writer.close()
    yield
    with connection.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")


@db
def test_each_pack_holds_its_regions_ways_and_current_names_the_build(
    ways, tmp_path, settings
) -> None:
    settings.TILES_DIR = tmp_path
    out = tmp_path / "offline-packs"
    found = builder.build_packs(SCHEMA, out, "20261113T030000Z", settings.COVERAGE_BBOX)
    by_id = {p["id"]: p for p in found["packs"]}

    def names(region: str) -> set[str]:
        graph = json.loads(gzip.decompress((out / "current" / by_id[region]["file"]).read_bytes()))
        assert graph["v"] == 1
        return set(graph["names"])

    assert names("beltway") == {"K Street", "Wilson Boulevard"}
    assert names("nova") == set(), "Arlington is inside the Beltway, not cut twice"
    assert names("baltimore") == {"Charles Street"}
    assert names("rest") == {"Charles Street"}, "La Plata is in the rest of the map"
    assert names("nw-exurbs") == set()
    assert all(p["bytes"] > 0 and len(p["sha256"]) == 64 for p in found["packs"])
    assert (out / "current").is_symlink() and (out / "current").resolve().name == found["build_id"]
    assert offline_packs.manifest()["build_id"] == "20261113T030000Z"
    # The same map gives the same bytes.
    again = builder.build_packs(SCHEMA, out, "20261113T040000Z", settings.COVERAGE_BBOX)
    assert [p["sha256"] for p in again["packs"]] == [p["sha256"] for p in found["packs"]]


@db
def test_two_builds_are_kept_and_a_half_written_one_never_served(ways, tmp_path, settings) -> None:
    out = tmp_path / "offline-packs"
    (out / "20261101T000000Z.part").mkdir(parents=True)
    for build in ("20261110T000000Z", "20261111T000000Z", "20261112T000000Z"):
        builder.build_packs(SCHEMA, out, build, settings.COVERAGE_BBOX)
    kept = sorted(p.name for p in out.iterdir())
    assert kept == ["20261111T000000Z", "20261112T000000Z", "current"]


@db
def test_the_list_names_each_pack_and_its_address(ways, tmp_path, settings, client) -> None:
    settings.TILES_DIR = tmp_path
    headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.120"}
    before = client.get("/api/offline/packs", **headers)
    assert before.status_code == 503 and before.json() == {"error": "not_built"}
    builder.build_packs(
        SCHEMA, tmp_path / "offline-packs", "20261113T030000Z", settings.COVERAGE_BBOX
    )
    answer = client.get("/api/offline/packs?preset=novice", **headers)
    assert answer.status_code == 200
    body = answer.json()
    assert body["build_id"] == "20261113T030000Z"
    assert [p["id"] for p in body["packs"]] == [r.id for r in offline_packs.REGIONS]
    assert body["packs"][0]["url"] == "/offline-packs/20261113T030000Z/beltway.json.gz"
    assert len(body["level_factor"]) == 11
    foreign = client.get("/api/offline/packs", HTTP_SEC_FETCH_SITE="cross-site", **headers)
    assert foreign.status_code == 403


def test_both_web_servers_serve_only_pack_files_to_this_site() -> None:
    """The Caddyfile (compose) and the beta nginx template serve the same files under the
    same guard: a build's pack files only, never the manifest or `current`, same-site only."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    caddy = (repo / "Caddyfile").read_text()
    block = caddy[caddy.index("handle /offline-packs/* {") :]
    block = block[: block.index("\n\t}\n")]
    assert r"path_regexp ^/offline-packs/[0-9A-Za-z_-]+/[a-z-]+\.json\.gz$" in block
    assert "respond @foreign 403" in block and "root * /srv/tiles" in block
    nginx = (repo / "deploy" / "beta" / "nginx-routemaker.conf.template").read_text()
    location = nginx[nginx.index("location ~ ^/offline-packs/") :]
    location = location[: location.index("\n    }\n")]
    assert r"([0-9A-Za-z_-]+/[a-z-]+\.json\.gz)$" in location
    assert "$rmbeta_basemap_foreign" in location
    assert "alias @DATA_ROOT@/tiles/offline-packs/$1;" in location
