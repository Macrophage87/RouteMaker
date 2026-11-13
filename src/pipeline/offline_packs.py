"""Builds the region packs for off-grid riding (`core.offline_packs`) from the live
`offline_way` table, after a map swap.

Each pack is the region's ways and those within `OVERLAP_M` of its border, cut at their
junctions (`core.offline_network.graph_of`), as gzip JSON. The packs of one build are written
to `<dir>/packs-<build id>.part/`, renamed into place when all are written, and only then is
`<dir>/manifest.json` replaced (one rename) to name them, so the API never lists half a build.
The two newest builds are kept, so a phone part way through a download when the manifest moves
still finishes it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import time
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


def pack_dir_name(build_id: str) -> str:
    """The folder a build's packs are written to. Not a bare build id, so the tile builds'
    pruning (`retention.prune_tile_builds`) and the beta ship script's graph walk never take
    it for a router graph."""
    return f"packs-{build_id}"


def build_packs(
    schema: str, out_dir: Path, build_id: str, coverage_box, now: datetime | None = None
) -> dict:
    """Write every region's pack for `build_id` and then the manifest that names them; the
    manifest. A build whose packs are already written (a retry with the same id: the same map)
    is not written again."""
    out_dir.mkdir(parents=True, exist_ok=True)
    name = pack_dir_name(build_id)
    final = out_dir / name
    if final.is_dir() and (final / "packs.json").is_file():
        packs = json.loads((final / "packs.json").read_text())
    else:
        part = out_dir / f"{name}.part"
        if part.exists():
            shutil.rmtree(part)
        part.mkdir()
        packs = []
        for region in REGIONS:
            ways = region_ways(schema, region_wkt(region, coverage_box))
            graph = offline_network.graph_of(ways)
            file = f"{region.id}.json.gz"
            size, digest = _write_pack(part / file, graph)
            count = len(ways)
            del ways, graph
            packs.append(
                {
                    "id": region.id,
                    "name": region.name,
                    "file": file,
                    "bytes": size,
                    "ways": count,
                    "sha256": digest,
                }
            )
            logger.info("offline pack %s: %d ways, %d bytes", region.id, count, size)
        (part / "packs.json").write_text(json.dumps(packs, indent=1))
        if final.exists():
            shutil.rmtree(final)
        part.rename(final)
    found = {
        "v": PACKS_VERSION,
        "build_id": build_id,
        "dir": name,
        "built_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "graph_v": offline_network.VERSION,
        "packs": packs,
    }
    # The manifest last, in one rename: before it, the API still lists the previous build,
    # whose files are all there.
    staged = out_dir / "manifest.json.next"
    staged.write_text(json.dumps(found, indent=1))
    os.replace(staged, out_dir / "manifest.json")
    _prune(out_dir, keep=name)
    return found


def _prune(out_dir: Path, keep: str) -> None:
    """Keep the manifest's build and the newest KEEP_BUILDS - 1 others (a phone part way
    through a download when the manifest moves still finishes it); remove a half-written
    build left more than a day ago (one written now may be another run's)."""
    builds = sorted(
        (p for p in out_dir.iterdir() if p.is_dir() and p.name.startswith("packs-")),
        key=lambda p: p.name,
        reverse=True,
    )
    older = [b for b in builds if b.name != keep and not b.name.endswith(".part")]
    for build in older[KEEP_BUILDS - 1 :]:
        shutil.rmtree(build, ignore_errors=True)
    stale = time.time() - 86_400
    for build in builds:
        if build.name.endswith(".part") and build.stat().st_mtime < stale:
            shutil.rmtree(build, ignore_errors=True)
