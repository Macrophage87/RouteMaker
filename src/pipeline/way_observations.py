"""Measured or modelled inputs for single ways: the adapter for the classifier's two
optional inputs, `observed_speed_mph` and `estimated_aadt` (`routemaker.stress.classify`).

NO SOURCE IS INSTALLED TODAY. The rebuild looks for one optional file,
`<reference_dir>/way-observations.json`, and where it is absent (every rebuild so far)
nothing changes: the classifier reads the limit and the usual count of the road's class.
The file is the seam a speed dataset (85th-percentile speeds), a modelled traffic volume
or, later, rider reports would be written to by its own importer; the classifier never
learns which.

    {"version": 1,
     "source": "who measured or modelled this, and when",
     "ways": {"<osm way id>": {"observed_speed_mph": 34.0, "estimated_aadt": 2600}}}

Either field may be left out of a way. A real traffic count on the way still outranks
`estimated_aadt`, and the posted limit is still what the road panel and the junction model
are told; `observed_speed_mph` only chooses the table column.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FILE_NAME = "way-observations.json"
# Outside these the file is refused: a typo, or a unit that is not mph or vehicles a day.
MAX_SPEED_MPH = 100.0
MAX_AADT = 400_000


class ObservationsRefused(ValueError):
    """The file is malformed."""


@dataclass(frozen=True)
class Observation:
    observed_speed_mph: float | None = None
    estimated_aadt: int | None = None


NONE = Observation()


def _number(value, top: float, where: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= top:
        raise ObservationsRefused(f"{where} must be a number above 0 and at most {top:g}")
    return float(value)


def load(reference_dir: Path | None) -> dict[int, Observation]:
    """{way id: Observation} from `<reference_dir>/way-observations.json`, or {} where there
    is no such file."""
    path = Path(reference_dir) / FILE_NAME if reference_dir is not None else None
    if path is None or not path.is_file():
        return {}
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ObservationsRefused(f"{path.name} is not a version 1 observations file")
    if not isinstance(document.get("source"), str) or not document["source"].strip():
        raise ObservationsRefused(f"{path.name} does not say its source")
    ways = document.get("ways")
    if not isinstance(ways, dict):
        raise ObservationsRefused(f"{path.name} has no ways")
    out: dict[int, Observation] = {}
    for key, row in ways.items():
        where = f"{path.name} way {key}"
        if not str(key).isdigit() or not isinstance(row, dict):
            raise ObservationsRefused(f"{where}: an OSM way id and an object are needed")
        unknown = set(row) - {"observed_speed_mph", "estimated_aadt"}
        if unknown:
            raise ObservationsRefused(f"{where}: unknown fields {sorted(unknown)}")
        speed = _number(row.get("observed_speed_mph"), MAX_SPEED_MPH, f"{where} speed")
        count = _number(row.get("estimated_aadt"), MAX_AADT, f"{where} count")
        out[int(key)] = Observation(speed, None if count is None else int(count))
    return out
