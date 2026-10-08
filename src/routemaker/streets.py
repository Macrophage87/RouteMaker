"""Street names as the pipeline compares them."""

from __future__ import annotations

# The District's quadrants as OSM spells them at the end of a street's name,
# longest first so " Northwest" is taken before a bare direction.
QUADRANT_SUFFIXES = (
    " northwest",
    " northeast",
    " southwest",
    " southeast",
    " nw",
    " ne",
    " sw",
    " se",
)


def street_key(name: str | None) -> str | None:
    """The street a name belongs to: case-folded, space-collapsed, without its
    quadrant, or None for an unnamed way. `1st Street Northwest` and `1st
    Street Northeast` are one street's two sides of the Capitol, and `North
    Capitol Street` keeps its leading North."""
    if not name:
        return None
    key = " ".join(name.casefold().split())
    for suffix in QUADRANT_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)]
            break
    return key or None
