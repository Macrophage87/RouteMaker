"""Trails a land manager lists for biking open where OSM is silent (`routemaker.trail_uses`,
`pipeline.trail_uses`; the owner, 2026-11-25: "Most of the trails that are advertised for
biking are closed for biking")."""

from __future__ import annotations

import json

from pipeline import trail_uses as matcher
from pipeline.extract import Way
from routemaker import trail_uses

# A straight tram road in a preserve, ~1 km east-west; the state's line 5 m north of it.
LINE = [(-81.640 + i * 0.001, 26.300) for i in range(11)]
STATE_LINE = [(x, y + 0.000045) for x, y in LINE]


def _record(kind: str, object_id: int = 7) -> dict:
    return {
        "attributes": {
            "OBJECTID": object_id,
            "SEGMENT_NAME": "Main Tram - West",
            "TYPE": kind,
            "MANAGING_SITE": "Corkscrew Regional Ecosystem Watershed",
        },
        "geometry": {"paths": [[list(p) for p in STATE_LINE]]},
    }


def _way(osm_id: int, tags: dict) -> Way:
    way = Way(osm_id=osm_id, tags=dict(tags), node_ids=list(range(len(LINE))))
    way.coordinates = list(LINE)
    way.located = list(range(len(LINE)))
    return way


def test_only_the_trails_listed_for_biking_are_kept() -> None:
    records = [_record("Hiking/Biking"), _record("Hiking", 8), _record("Paddling", 9)]
    document = {"features": records}
    rows, dropped = trail_uses.fl_ogt_rows(document)
    assert [(r["id"], r["uses"], r["name"]) for r in rows] == [
        ("fl-ogt-7-0", "Hiking/Biking", "Main Tram - West")
    ]
    assert dropped == 2
    geojson = {
        "features": [
            {
                "properties": {"OBJECTID": 3, "TYPE": "Multi-Use", "TRAIL_NAME": "Paved Loop"},
                "geometry": {"type": "LineString", "coordinates": [list(p) for p in STATE_LINE]},
            }
        ]
    }
    assert trail_uses.fl_ogt_rows(geojson)[0][0]["name"] == "Paved Loop"


def test_a_listing_opens_only_a_silent_public_trail() -> None:
    assert trail_uses.opens({"highway": "path", "foot": "yes", "surface": "grass"})
    assert trail_uses.opens({"highway": "track"})
    assert not trail_uses.opens({"highway": "path", "bicycle": "no"})  # OSM's own tag wins
    assert not trail_uses.opens({"highway": "path", "access": "private"})
    assert not trail_uses.opens({"highway": "residential"})


def test_the_trail_along_a_listed_line_is_opened_and_its_neighbours_are_not(tmp_path) -> None:
    rows, _ = trail_uses.fl_ogt_rows({"features": [_record("Hiking/Biking")]})
    path = tmp_path / matcher.FILE_NAME
    path.write_text(json.dumps(rows))
    features = matcher.load(path)
    tram = _way(1, {"highway": "path", "foot": "yes", "surface": "grass"})
    closed = _way(2, {"highway": "path", "bicycle": "no"})
    far = _way(3, {"highway": "path"})
    far.coordinates = [(x, y + 0.01) for x, y in LINE]  # a kilometre north
    opened = matcher.open_listed([tram, closed, far], features)
    assert opened == {1: trail_uses.FL_OGT_SOURCE}
    assert tram.tags["bicycle"] == "yes"
    assert closed.tags["bicycle"] == "no" and "bicycle" not in far.tags


def test_without_the_file_no_trail_is_opened(tmp_path) -> None:
    assert matcher.load(tmp_path / matcher.FILE_NAME) == ()
    assert matcher.open_listed([_way(1, {"highway": "path"})], ()) == {}
