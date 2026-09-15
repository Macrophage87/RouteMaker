"""Parsing OpenStreetMap tag values into the quantities the classifier reads.

Every parser here returns `None` rather than a guess when a tag is missing or
unreadable. The defaulting happens once, in `stress`, where the rule is to err
toward the higher-stress reading; scattering defaults through the parsers would
hide which values were measured and which were assumed.
"""

from __future__ import annotations

import re

MPH_PER_KMH = 0.621371

# Posted speeds that OSM expresses as a country default rather than a number.
# Conservative readings: a US urban default is 25 mph in most of this region, and
# anything unrecognised is treated as unknown rather than as slow.
IMPLICIT_MAXSPEED_MPH = {
    "US:urban": 25.0,
    "US:residential": 25.0,
    "DC:urban": 20.0,
    "DC:residential": 20.0,
    "MD:urban": 30.0,
    "VA:urban": 25.0,
    "US:rural": 55.0,
    "walk": 5.0,
}

_SPEED = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?\s*$", re.I)


def parse_maxspeed_mph(value: str | None) -> float | None:
    """Posted speed in mph. Bare numbers are km/h per the OSM convention."""
    if not value:
        return None
    if value in IMPLICIT_MAXSPEED_MPH:
        return IMPLICIT_MAXSPEED_MPH[value]
    match = _SPEED.match(value)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "").lower()
    return number if unit == "mph" else number * MPH_PER_KMH


def parse_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_width_m(value: str | None) -> float | None:
    """Width in metres. Accepts bare metres and explicit feet."""
    if not value:
        return None
    text = str(value).strip().lower()
    if text.endswith("'") or text.endswith("ft"):
        try:
            return float(text.rstrip("ft'").strip()) * 0.3048
        except ValueError:
            return None
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


def is_oneway(tags: dict[str, str]) -> bool:
    return tags.get("oneway") in {"yes", "1", "-1", "true"}


def lanes_per_direction(tags: dict[str, str]) -> int | None:
    """Through lanes in the direction of travel.

    `lanes` counts both directions on a two-way road, so comparing a raw `lanes`
    value against a Furth table built on per-direction counts reads every two-way
    street as one class worse than it is.
    """
    for key in ("lanes:forward", "lanes:backward"):
        if (value := parse_int(tags.get(key))) is not None:
            return max(1, value)
    total = parse_int(tags.get("lanes"))
    if total is None:
        return None
    if is_oneway(tags):
        return max(1, total)
    return max(1, total // 2)


def has_parking_lane(tags: dict[str, str]) -> bool | None:
    """Whether on-street parking runs alongside, which changes the bike-lane table.

    Returns None when nothing in the tags speaks to it, since absence of a
    `parking:*` tag is not evidence that parking is absent.
    """
    # Only the schemes that actually describe a parking lane. `parking:condition:*`
    # is not evidence that parking exists.
    prefixes = ("parking:lane", "parking:left", "parking:right", "parking:both")
    values = [v for k, v in tags.items() if k.startswith(prefixes)]
    if not values:
        return None
    # `no_parking`, `no_stopping` and `no_standing` all say parking is absent.
    # Reading them as present flipped the bike-lane width threshold from 1.7 m to
    # 4.1 m and, worse, removed "parking" from the assumed list - so the result
    # claimed the input was measured while reading it backwards.
    absent = {"no", "none", "separate", "no_parking", "no_stopping", "no_standing"}
    return any(v not in absent for v in values)


def cycleway_values(tags: dict[str, str]) -> set[str]:
    """Every cycleway value on the way, from whichever of the tag forms is used."""
    keys = ("cycleway", "cycleway:both", "cycleway:left", "cycleway:right")
    return {tags[k] for k in keys if tags.get(k)}


def has_shoulder(tags: dict[str, str]) -> bool | None:
    for key in ("shoulder", "shoulder:both", "shoulder:left", "shoulder:right"):
        if (value := tags.get(key)) is not None:
            return value not in {"no", "none"}
    return None
