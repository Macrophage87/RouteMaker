"""What a mountain-bike trail is like to ride, from its OSM tags, for the road panel.

The owner, 2026-10-19: "Mountain bike trails need to have a key on the map and should have
information related to surface and the like on the map", and "The information should be
available when clicked on". The rebuild keeps a few of a mountain-bike-only way's own tags
(`facts`, written to `segment.trail_tags`), and the road panel says them in words
(`rows`): the surface as mapped (dirt, gravel, rock), how smooth it is, how wide, how easy
the trail is to follow, and its uphill rating. The words are made when the panel asks, so
changing them needs no map rebuild; a tag the way does not carry is left out, never
guessed.

Sources: the OSM wiki's pages for each key (Key:surface, Key:smoothness, Key:width,
Key:trail_visibility, Key:mtb:scale, Key:sac_scale).
"""

from __future__ import annotations

import re

# The tags kept, in the order the panel says them.
KEYS = (
    "surface",
    "smoothness",
    "width",
    "trail_visibility",
    "mtb:scale:uphill",
    "sac_scale",
)

# A kept value is at most this long (a tag is free text; the panel needs a word or two).
MAX_VALUE = 40

FEET_PER_METRE = 3.28084

SURFACE_WORDS = {
    "ground": "Dirt",
    "dirt": "Dirt",
    "earth": "Dirt",
    "mud": "Mud",
    "gravel": "Gravel",
    "fine_gravel": "Fine gravel",
    "compacted": "Packed gravel",
    "pebblestone": "Loose stones",
    "rock": "Rock",
    "stone": "Rock",
    "sand": "Sand",
    "grass": "Grass",
    "woodchips": "Wood chips",
    "wood": "Wood (boardwalk or bridge)",
    "unpaved": "Unpaved",
    "paved": "Paved",
    "asphalt": "Asphalt",
    "concrete": "Concrete",
    "roots": "Roots",
}

# Key:smoothness, with the wheels the wiki says each needs.
SMOOTHNESS_WORDS = {
    "excellent": "Excellent (any bike)",
    "good": "Good (any bike)",
    "intermediate": "Fair (most bikes)",
    "bad": "Bumpy (wide tyres)",
    "very_bad": "Very bumpy (a mountain bike)",
    "horrible": "Rough (a mountain bike, skill needed)",
    "very_horrible": "Very rough (expert riding)",
    "impassable": "Impassable",
}

# Key:trail_visibility.
VISIBILITY_WORDS = {
    "excellent": "Very easy to follow",
    "good": "Easy to follow",
    "intermediate": "Mostly easy to follow",
    "bad": "Faint in places",
    "horrible": "Hard to follow",
    "no": "No visible trail",
}

# Key:mtb:scale:uphill, 0 to 5.
UPHILL_WORDS = {
    0: "Easy",
    1: "Moderate",
    2: "Hard in places",
    3: "Hard: steep or loose",
    4: "Very hard: pushing likely",
    5: "Extreme: pushing or carrying",
}

# Key:sac_scale, the hiking scale.
SAC_WORDS = {
    "hiking": "T1, hiking",
    "mountain_hiking": "T2, mountain hiking",
    "demanding_mountain_hiking": "T3, demanding mountain hiking",
    "alpine_hiking": "T4, alpine hiking",
    "demanding_alpine_hiking": "T5, demanding alpine hiking",
    "difficult_alpine_hiking": "T6, difficult alpine hiking",
}

_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m|ft|')?\s*$")
_FEET_INCHES = re.compile(r"^\s*(\d+)\s*'\s*(\d+)\s*\"\s*$")
_GRADE = re.compile(r"^\s*(\d)")


def facts(tags: dict[str, str]) -> dict[str, str] | None:
    """The kept tags of one way (`segment.trail_tags`), or None where it carries none."""
    kept = {}
    for key in KEYS:
        value = (tags.get(key) or "").strip()
        if value:
            kept[key] = value[:MAX_VALUE]
    return kept or None


def width_metres(value: str) -> float | None:
    """A `width` in metres: "1.5", "1.5 m", "3 ft", "3'", "2'6\""; None for anything else."""
    feet_inches = _FEET_INCHES.match(value)
    if feet_inches:
        feet = int(feet_inches.group(1)) + int(feet_inches.group(2)) / 12
        return feet / FEET_PER_METRE
    found = _NUMBER.match(value)
    if not found:
        return None
    number = float(found.group(1))
    if number <= 0:
        return None
    return number / FEET_PER_METRE if found.group(2) in ("ft", "'") else number


def width_words(value: str) -> str | None:
    """'About 2 ft (0.6 m)': US units first, metric in brackets."""
    metres = width_metres(value)
    if metres is None:
        return None
    feet = metres * FEET_PER_METRE
    shown = f"{feet:.1f}".rstrip("0").rstrip(".") if feet < 10 else f"{round(feet):,}"
    return f"{shown} ft ({metres:.1f} m)"


def surface_words(value: str) -> str:
    """The first surface mapped, in words ('dirt;rock' says both)."""
    parts = [p.strip() for p in value.split(";") if p.strip()]
    said = [SURFACE_WORDS.get(p, p.replace("_", " ").capitalize()) for p in parts]
    # "Dirt, rock", not "Dirt, Rock".
    return ", ".join([said[0], *(s.lower() for s in said[1:])]) if said else value


def uphill_words(value: str) -> str | None:
    found = _GRADE.match(value)
    if not found or int(found.group(1)) not in UPHILL_WORDS:
        return None
    grade = int(found.group(1))
    return f"{UPHILL_WORDS[grade]} ({grade} of 5)"


def rows(kept: object) -> list[tuple[str, str, str]]:
    """The panel's lines for a trail's kept tags: (id, label, words), in KEYS's order. A
    value with no words of its own is left out rather than shown raw, except the surface,
    which is said as mapped."""
    if not isinstance(kept, dict):
        return []
    out: list[tuple[str, str, str]] = []

    def text(key: str) -> str | None:
        value = kept.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    if surface := text("surface"):
        out.append(("trail_surface", "Trail surface", surface_words(surface)))
    if (smooth := text("smoothness")) and smooth in SMOOTHNESS_WORDS:
        out.append(("smoothness", "Smoothness", SMOOTHNESS_WORDS[smooth]))
    if (width := text("width")) and (said := width_words(width)):
        out.append(("width", "Width", said))
    if (seen := text("trail_visibility")) and seen in VISIBILITY_WORDS:
        out.append(("visibility", "Trail visibility", VISIBILITY_WORDS[seen]))
    if (uphill := text("mtb:scale:uphill")) and (said := uphill_words(uphill)):
        out.append(("uphill", "Climbing", said))
    if (sac := text("sac_scale")) and sac in SAC_WORDS:
        out.append(("hiking", "Hiking scale", SAC_WORDS[sac]))
    return out
