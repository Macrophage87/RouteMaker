"""Builds the region packs for off-grid riding (`core.offline_packs`) from the live
`offline_way` table, after a map swap.

Each pack is the region's ways and those within `OVERLAP_M` of its border, cut at their
junctions (`core.offline_network.graph_of`), as gzip JSON. The packs of one build are written
to `<dir>/<build id>.part/`, renamed into place when all are written, and `current` is then
pointed at them in one rename, so the web server never serves half a build. The two newest
builds are kept, so a phone part way through a download when `current` moves still finishes it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from django.db import connection

from core import offline_network
from core.offline_packs import OVERLAP_M, PACKS_VERSION, REGIONS, Region
from pipeline.schema import validate_schema_name

logger = logging.getLogger(__name__)

# Builds kept beside `current` (the newest is current). Our default.
KEEP_BUILDS = 2


def _polygon_wkt(outline) -> str:
    return "POLYGON((" + ",".join(f"{lon} {lat}" for lon, lat in outline) + "))"


def _box_wkt(box) -> str:
    west, south, east, north = box
    return _polygon_wkt(((west, south), (east, south), (east, north), (west, north), (west, south)))


def region_wkt(region: Region, coverage_box) -> str:
    """The region's area as WKT: its outline less the Beltway (outside it), or for the rest
    of the map the coverage box less every other region."""
    beltway = next(r for r in REGIONS if not r.outside_beltway)
    with connection.cursor() as cursor:
        if region.outline is None:
            others = [_polygon_wkt(r.outline) for r in REGIONS if r.outline is not None]
            cursor.execute(
                "SELECT ST_AsText(ST_Difference(ST_GeomFromText(%s, 4326),"
                " ST_Union(ARRAY(SELECT ST_GeomFromText(w, 4326) FROM unnest(%s::text[]) AS w))))",
                [_box_wkt(coverage_box), others],
            )
        elif region.outside_beltway:
            cursor.execute(
                "SELECT ST_AsText(ST_Difference(ST_GeomFromText(%s, 4326),"
                " ST_GeomFromText(%s, 4326)))",
                [_polygon_wkt(region.outline), _polygon_wkt(beltway.outline)],
            )
        else:
            return _polygon_wkt(region.outline)
        return cursor.fetchone()[0]


def region_ways(schema: str, area_wkt: str) -> list:
    """The ways of `schema`.offline_way in the area or within OVERLAP_M of it."""
    validate_schema_name(schema)
    query = f"""
        WITH area AS (
            SELECT ST_Buffer(ST_GeomFromText(%s, 4326)::geography, %s)::geometry AS g
        ),
        pieces AS (SELECT ST_Subdivide(area.g, 64) AS p FROM area),
        near AS (
            SELECT DISTINCT w.osm_way_id
            FROM pieces JOIN {schema}.offline_way AS w ON ST_Intersects(w.geometry, pieces.p)
        )
        SELECT w.osm_way_id, w.node_ids, ST_AsText(w.geometry), w.level2, w.flags,
               w.direction, w.name
        FROM near JOIN {schema}.offline_way AS w USING (osm_way_id)
        ORDER BY w.osm_way_id
    """
    with connection.cursor() as cursor:
        cursor.execute(query, [area_wkt, OVERLAP_M])
        rows = cursor.fetchall()
    return offline_network.ways_of(rows)


def _write_pack(path: Path, graph: dict) -> tuple[int, str]:
    raw = json.dumps(graph, separators=(",", ":")).encode()
    # mtime 0: the same network gives the same bytes, so its checksum says whether it changed.
    packed = gzip.compress(raw, compresslevel=9, mtime=0)
    path.write_bytes(packed)
    return len(packed), hashlib.sha256(packed).hexdigest()


def build_packs(
    schema: str, out_dir: Path, build_id: str, coverage_box, now: datetime | None = None
) -> dict:
    """Write every region's pack for `build_id` and point `current` at them; the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    part = out_dir / f"{build_id}.part"
    if part.exists():
        shutil.rmtree(part)
    part.mkdir()
    packs = []
    for region in REGIONS:
        ways = region_ways(schema, region_wkt(region, coverage_box))
        graph = offline_network.graph_of(ways)
        file = f"{region.id}.json.gz"
        size, digest = _write_pack(part / file, graph)
        packs.append(
            {
                "id": region.id,
                "name": region.name,
                "file": file,
                "bytes": size,
                "ways": len(ways),
                "sha256": digest,
            }
        )
        logger.info("offline pack %s: %d ways, %d bytes", region.id, len(ways), size)
    found = {
        "v": PACKS_VERSION,
        "build_id": build_id,
        "built_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "graph_v": offline_network.VERSION,
        "packs": packs,
    }
    (part / "manifest.json").write_text(json.dumps(found, indent=1))
    final = out_dir / build_id
    if final.exists():
        shutil.rmtree(final)
    part.rename(final)
    # Relative, so the link resolves wherever the folder is mounted (the API and the web server
    # mount it at their own paths).
    link = out_dir / "current.next"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(build_id)
    os.replace(link, out_dir / "current")
    _prune(out_dir, keep=build_id)
    return found


def _prune(out_dir: Path, keep: str) -> None:
    builds = sorted(
        (p for p in out_dir.iterdir() if p.is_dir() and not p.is_symlink()),
        key=lambda p: p.name,
        reverse=True,
    )
    older = [b for b in builds if b.name != keep and not b.name.endswith(".part")]
    for build in older[KEEP_BUILDS - 1 :]:
        shutil.rmtree(build, ignore_errors=True)
    for build in builds:
        if build.name.endswith(".part"):
            shutil.rmtree(build, ignore_errors=True)
