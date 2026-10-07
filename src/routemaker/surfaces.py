"""Which `surface` values are paved: one definition for the whole pipeline.

OWNER-DECISIONS 440 (2026-10-06): the Anacostia Riverwalk Trail near the Navy
Yard was "marked unpaved, but it's very much paved", and the Matthew Henson
Trail, "continuously paved", showed unpaved sections. The cause was a list of
five values (asphalt, concrete, paved, paving_stones, chipseal) that read every
other surface as unpaved, so `surface=wood` boardwalks and trail bridges, metal
bridge decks, brick, sett and `concrete:plates` all drew brown and counted as
unpaved region-wide. The owner's rule: hard surfaces count as paved, and
cobblestone and unhewn cobblestone count as paved but rough.

Three readings come out of it, and they differ on purpose:

- `is_paved` is the surface as the map, the segment table's `is_unpaved`, the
  unpaved ranking and the graph's surface price read it (`stress.is_unpaved`,
  `lua/routemaker_remap.lua` `M.is_paved`, kept equal by
  tests/test_surfaces.py).
- `is_sealed` is the narrower road paving (asphalt, concrete, paved, paving
  stones, chipseal and their `:` variants). It is what lets a way out of
  singletrack (`routemaker.singletrack`): a mountain-bike rating of one or more
  on a wooden ladder, berm or skinny is an MTB feature, not a trail bridge, and
  in the 2026-10-03 extract every one of the ~170 rated wooden ways is one
  (The Boss Trail's "Rollercoaster Wooden Feature", tagged highway=cycleway, as
  much as the bicycle=designated jump lines), so no closure there is widened.
- `is_hard_for_access` is what the no-bike-path rules' hard-surface exemption
  reads (`routemaker.trailaccess`): every paved surface but wood, which counts
  only on a bridge or boardwalk that is a cycleway or bicycle=designated (the
  design rule set under OWNER-DECISIONS 440, not the owner's words: a wooden
  bridge on a designated bike path counts as paved for access, and nothing else
  about access widens). A wooden footbridge on a hiking path keeps its closure,
  as before.
"""

from __future__ import annotations

# Road paving: what a road bike rides without a thought.
SEALED_SURFACES = frozenset({"asphalt", "concrete", "paved", "paving_stones", "chipseal"})
# `concrete:plates`, `concrete:lanes`, `paving_stones:lanes`, `asphalt:lanes`...
SEALED_PREFIXES = ("concrete:", "paving_stones:", "asphalt:")
# Wooden decks: boardwalks and trail bridges. `boardwalk` is wood under another
# name (14 ways in the 2026-10-03 extract).
WOOD_SURFACES = frozenset({"wood", "boardwalk"})
# Paved but rough (440): `stress.is_rough` reads these too.
ROUGH_PAVED_SURFACES = frozenset({"cobblestone", "unhewn_cobblestone"})
# Every hard surface (440). `metal_grid` is a metal deck.
PAVED_SURFACES = (
    SEALED_SURFACES
    | WOOD_SURFACES
    | ROUGH_PAVED_SURFACES
    | frozenset({"metal", "metal_grid", "brick", "bricks", "sett", "tartan", "rubber"})
)


def surface_of(tags: dict[str, str]) -> str:
    return tags.get("surface") or ""


def is_paved_surface(surface: str | None) -> bool:
    surface = surface or ""
    return surface in PAVED_SURFACES or surface.startswith(SEALED_PREFIXES)


def is_paved(tags: dict[str, str]) -> bool:
    """A hard surface: road paving, wood, metal, brick, sett, tartan, rubber,
    cobblestone. False when `surface` is absent (unknown is the caller's)."""
    return is_paved_surface(surface_of(tags))


def is_rough_paved(tags: dict[str, str]) -> bool:
    return surface_of(tags) in ROUGH_PAVED_SURFACES


def is_sealed(tags: dict[str, str]) -> bool:
    """Road paving only: asphalt, concrete, paved, paving stones, chipseal and
    their `:` variants. What lets a rated way out of singletrack."""
    surface = surface_of(tags)
    return surface in SEALED_SURFACES or surface.startswith(SEALED_PREFIXES)


def is_bridge_or_boardwalk(tags: dict[str, str]) -> bool:
    return tags.get("bridge", "no") not in ("", "no") or tags.get("boardwalk") == "yes"


def is_bike_bridge(tags: dict[str, str]) -> bool:
    """A bridge or boardwalk on a bike path: a cycleway, or bicycle=designated."""
    return is_bridge_or_boardwalk(tags) and (
        tags.get("highway") == "cycleway" or tags.get("bicycle") == "designated"
    )


def is_hard_for_access(tags: dict[str, str]) -> bool:
    """The no-bike-path rules' hard surface: paved, but a wooden deck only on a
    bike path's bridge or boardwalk."""
    if not is_paved(tags):
        return False
    return surface_of(tags) not in WOOD_SURFACES or is_bike_bridge(tags)
