"""GPX reading, limited to what the measurements and the import path need.

Uses defusedxml where available, since an import is an untrusted file and the
plan requires XML entity attacks be refused rather than parsed.
"""

from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - exercised by whichever branch is installed
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET  # noqa: N817

from .geo import Point

GPX_NAMESPACES = (
    "http://www.topografix.com/GPX/1/1",
    "http://www.topografix.com/GPX/1/0",
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_track_points(path: str | Path) -> list[Point]:
    """Every trackpoint in a GPX file, in order, across all tracks and segments.

    Accepts GPX 1.0 and 1.1, which is what the import path accepts; exports are
    always 1.1, since 1.0 has no copyright element to carry attribution in.
    """
    root = ET.parse(str(path)).getroot()
    points: list[Point] = []
    for element in root.iter():
        if _local(element.tag) != "trkpt":
            continue
        ele: float | None = None
        for child in element:
            if _local(child.tag) == "ele" and child.text:
                ele = float(child.text)
                break
        points.append(Point(float(element.get("lon")), float(element.get("lat")), ele))
    return points


def read_waypoint_names(path: str | Path) -> list[str]:
    """Names of any `wpt` elements, which the import path promotes to control points."""
    root = ET.parse(str(path)).getroot()
    names = []
    for element in root.iter():
        if _local(element.tag) != "wpt":
            continue
        for child in element:
            if _local(child.tag) == "name" and child.text:
                names.append(child.text)
    return names
