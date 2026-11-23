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
        "all",
    ]
    assert sum(r.outline is None and not r.whole for r in offline_packs.REGIONS) == 1, (
        "one region is the rest"
    )
    assert [r.id for r in offline_packs.REGIONS if r.whole] == ["all"], "one pack is the whole map"
    for region in offline_packs.REGIONS:
        if region.outline is not None:
            assert region.outline[0] == region.outline[-1], region.id


@pytest.fixture
def ways():
    """Streets in downtown DC, Arlington, Baltimore, La Plata, Potomac, Martinsburg and Bowie."""
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
        4: ("La Plata Road", (-76.98, 38.53)),
        5: ("River Road", (-77.18, 39.00)),
        # Martinsburg, West Virginia: south of the Potomac, so with Northern Virginia.
        6: ("Queen Street", (-77.964, 39.456)),
        # Bowie, Prince George's north of Upper Marlboro: with Baltimore.
        7: ("Annapolis Road", (-76.73, 38.96)),
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
        build = out / found["dir"]
        graph = json.loads(gzip.decompress((build / by_id[region]["file"]).read_bytes()))
        assert graph["v"] == 1
        return set(graph["names"])

    assert names("beltway") == {"K Street", "Wilson Boulevard"}
    assert names("nova") == {"Queen Street"}, (
        "Arlington is inside the Beltway, not cut twice; Martinsburg is south of the Potomac"
    )
    assert names("baltimore") == {"Charles Street", "Annapolis Road"}
    assert names("rest") == {"La Plata Road"}, "La Plata is in Southern Maryland"
    assert names("nw-exurbs") == {"River Road"}, "Potomac, Maryland is not left to the rest"
    assert names("all") == {
        "K Street",
        "Wilson Boulevard",
        "Charles Street",
        "La Plata Road",
        "River Road",
        "Queen Street",
        "Annapolis Road",
    }, "everything is every street"
    assert all(p["bytes"] > 0 and len(p["sha256"]) == 64 for p in found["packs"])
    assert found["dir"] == "packs-20261113T030000Z"
    assert offline_packs.manifest()["build_id"] == "20261113T030000Z"
    # The same map gives the same bytes.
    again = builder.build_packs(SCHEMA, out, "20261113T040000Z", settings.COVERAGE_BBOX)
    assert [p["sha256"] for p in again["packs"]] == [p["sha256"] for p in found["packs"]]


@db
def test_two_builds_are_kept_and_a_half_written_one_never_served(ways, tmp_path, settings) -> None:
    out = tmp_path / "offline-packs"
    import os

    stale = out / "packs-20261101T000000Z.part"
    stale.mkdir(parents=True)
    os.utime(stale, (0, 0))
    for build in ("20261110T000000Z", "20261111T000000Z", "20261112T000000Z"):
        builder.build_packs(SCHEMA, out, build, settings.COVERAGE_BBOX)
    kept = sorted(p.name for p in out.iterdir())
    # A half-written build from more than a day ago goes; the manifest names the newest.
    assert kept == ["manifest.json", "packs-20261111T000000Z", "packs-20261112T000000Z"]
    assert json.loads((out / "manifest.json").read_text())["dir"] == "packs-20261112T000000Z"


@db
def test_a_retry_with_the_same_build_keeps_its_packs_and_the_tile_pruning_never_touches_them(
    ways, tmp_path, settings
) -> None:
    from pipeline import retention

    tiles = tmp_path / "tiles"
    out = tiles / "offline-packs"
    first = builder.build_packs(SCHEMA, out, "20261113T030000Z", settings.COVERAGE_BBOX)
    written = (out / first["dir"] / "beltway.json.gz").stat().st_mtime_ns
    again = builder.build_packs(SCHEMA, out, "20261113T030000Z", settings.COVERAGE_BBOX)
    assert again["packs"] == first["packs"]
    assert (out / first["dir"] / "beltway.json.gz").stat().st_mtime_ns == written
    # The worker's prune after every rebuild walks every folder under tiles as a router's.
    retention.prune_tile_builds(tiles, keep=0, protect=["20261113T030000Z"])
    assert (out / first["dir"] / "beltway.json.gz").is_file()


def test_a_manifest_of_another_version_lists_nothing(tmp_path, settings) -> None:
    settings.TILES_DIR = tmp_path
    (tmp_path / "offline-packs").mkdir()
    (tmp_path / "offline-packs" / "manifest.json").write_text('{"v": 99, "dir": "packs-x"}')
    assert offline_packs.manifest() is None


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
    assert body["packs"][0]["url"] == "/offline-packs/packs-20261113T030000Z/beltway.json.gz"
    assert len(body["level_factor"]) == 11
    # Each pack's area, for the phone's map and its pick of the pack to open for a ride.
    areas = {p["id"]: p["area"] for p in body["packs"]}
    assert areas["beltway"]["outline"][0] == areas["beltway"]["outline"][-1]
    assert not areas["beltway"]["outside_beltway"] and areas["nova"]["outside_beltway"]
    assert areas["rest"] == {"outline": None, "outside_beltway": False, "whole": False}
    assert areas["all"] == {"outline": None, "outside_beltway": False, "whole": True}
    assert body["box"] == list(settings.COVERAGE_BBOX)
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
    assert r"path_regexp ^/offline-packs/packs-[0-9]+T[0-9]+Z(-[0-9]+)?/[a-z-]+\.json\.gz$" in block
    # The day-long header has a path matcher, so the refusal's no-store runs after it.
    assert 'header /offline-packs/* Cache-Control "private, max-age=86400"' in block
    assert 'header @foreign Cache-Control "no-store"' in block
    assert "respond @foreign 403" in block and "root * /srv/tiles" in block
    nginx = (repo / "deploy" / "beta" / "nginx-routemaker.conf.template").read_text()
    location = nginx[nginx.index("location ~ ^/offline-packs/") :]
    location = location[: location.index("\n    }\n")]
    assert r"(?P<rm_pack>packs-[0-9]+T[0-9]+Z(?:-[0-9]+)?/[a-z-]+\.json\.gz)$" in location
    assert "$rmbeta_basemap_foreign" in location
    # A named capture: the same-site map is a regex map, which resets $1 (#1295).
    assert "alias @DATA_ROOT@/tiles/offline-packs/$rm_pack;" in location


def test_a_later_area_is_a_pack_of_its_own(settings) -> None:
    """Southwest Florida (the owner, 2026-11-23) is its own pack, its box the outline, with
    nothing cut out of it; the home regions are unchanged."""
    assert [r.id for r in offline_packs.regions()] == [r.id for r in offline_packs.REGIONS]
    settings.COVERAGE_AREAS = {
        "dc-baltimore": settings.COVERAGE_BBOX,
        "southwest-florida": settings.SOUTHWEST_FLORIDA_BBOX,
    }
    *home, florida = offline_packs.regions()
    assert [r.id for r in home] == [r.id for r in offline_packs.REGIONS]
    assert (florida.id, florida.name) == ("southwest-florida", "Southwest Florida")
    area = offline_packs.area_of("southwest-florida")
    assert area["outline"][0] == area["outline"][-1]
    assert area["outside_beltway"] is False and area["whole"] is False
