"""Curated speed limits: a posted speed the map is missing, read at classify time.

OWNER-DECISIONS 131, of the Montgomery County parkways with no posted speed
(Sligo Creek Parkway, Little Falls Parkway, Beach Drive): "Set them to 25 mph
(Recommended)". Unposted, they took Maryland's urban default - 30 mph on a
tertiary, 35 on a secondary - and came out LTS 3 and 4 where the posted
stretches of the same roads are LTS 2.

Why a checked-in file and not an override row. An access override is applied
after classification (Stage.APPLY_OVERRIDES follows CLASSIFY_STRESS), so a
`maxspeed` written by one would never reach the tier; and a stress override
writes a tier, where the owner's answer is a speed and the tier should follow
from it by the same tables as every other road. So the correction is a
reviewed file under `fixtures/speed/`, like the CBD boundary: a row per way,
the speed, and the owner's words and the map evidence, audited by the change
that adds it. The pipeline image carries `fixtures/`.

A correction fills a gap and never overrules the map: where the way now
carries a posted `maxspeed` of its own, that is read instead and the row is
reported (`corrected`). It changes what the classifier reads, not the tags
written to the graph: the rider's stress is what the owner decided, and what
Valhalla does with a car's speed is not this file's business.
"""

from __future__ import annotations

import json
from pathlib import Path

from .tags import maxspeed_is_unitless, parse_maxspeed_mph

SPEED_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "speed"


class SpeedCorrectionRefused(ValueError):
    """A correction file is malformed, or two rows disagree about one way."""


def load(directory: Path | None = None) -> dict[int, str]:
    """{way id: maxspeed} from every correction file in `directory` (SPEED_DIR)."""
    speeds: dict[int, str] = {}
    for path in sorted(Path(directory or SPEED_DIR).glob("*.json")):
        document = json.loads(path.read_text())
        if not isinstance(document, dict) or document.get("version") != 1:
            raise SpeedCorrectionRefused(f"{path.name} is not a version 1 speed file")
        rows = document.get("rows")
        if not isinstance(rows, list) or not rows:
            raise SpeedCorrectionRefused(f"{path.name} has no rows")
        for index, row in enumerate(rows):
            where = f"{path.name} row {index}"
            way = row.get("osm_way_id") if isinstance(row, dict) else None
            if not isinstance(way, int) or isinstance(way, bool) or way <= 0:
                raise SpeedCorrectionRefused(f"{where}: osm_way_id must be a positive integer")
            speed = row.get("maxspeed")
            if (
                not isinstance(speed, str)
                or parse_maxspeed_mph(speed) is None
                or maxspeed_is_unitless(speed)
            ):
                raise SpeedCorrectionRefused(f"{where}: maxspeed must be a speed with its unit")
            for field in ("reason", "evidence"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise SpeedCorrectionRefused(f"{where}: {field} is required")
            if speeds.get(way, speed) != speed:
                raise SpeedCorrectionRefused(
                    f"{where}: way {way} is also corrected to {speeds[way]}, not {speed}"
                )
            speeds[way] = speed
    return speeds


def corrected(tags: dict[str, str], speed: str | None) -> tuple[dict[str, str], bool]:
    """The tags the classifier reads, and whether the correction was used. A
    posted `maxspeed` on the way wins."""
    if speed is None or tags.get("maxspeed"):
        return tags, False
    return {**tags, "maxspeed": speed}, True
