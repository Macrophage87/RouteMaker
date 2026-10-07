#!/usr/bin/env python3
# ruff: noqa: E501
"""Mutation pass over the NO-BIKE-PATHS rules (OWNER-DECISIONS 278, 280, 281, 291).

Each mutant changes one line of `routemaker.trailaccess`, `routemaker.zoo`,
`routemaker.surfaces` or `pipeline.trail_closures`; the focused tests must fail. Run from the repository
root, one pytest process at a time:

    PGDATABASE=routemaker_nobike python scripts/mutants_nobike.py

Exit 0 when every mutant is killed. The source file is restored after each.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TA = "src/routemaker/trailaccess.py"
ZOO = "src/routemaker/zoo.py"
TC = "src/pipeline/trail_closures.py"
SURF = "src/routemaker/surfaces.py"
TESTS = [
    "tests/test_trailaccess.py",
    "tests/test_zoo.py",
    "tests/test_trail_closures.py",
    "tests/test_surfaces.py",
]

MUTANTS: list[tuple[str, str, str, str]] = [
    (
        "private_drops_permit",
        TA,
        'PRIVATE_ACCESS = frozenset({"private", "permit", ',
        'PRIVATE_ACCESS = frozenset({"private", ',
    ),
    (
        "private_bicycle_drops_residents",
        TA,
        '{"private", "permit", "residents"}',
        '{"private", "permit"}',
    ),
    (
        "upstream_footway_open",
        TA,
        '    return highway == "path"\n\n\ndef _kept_by_class',
        "    return True\n\n\ndef _kept_by_class",
    ),
    (
        "ncn_exemption_dropped",
        TA,
        "    if routes.keeping_route:\n        return None\n    hard =",
        "    hard =",
    ),
    (
        "rcn_keeps",
        TA,
        'KEEPING_NETWORKS = frozenset({"ncn", "icn"})',
        'KEEPING_NETWORKS = frozenset({"ncn", "icn", "rcn"})',
    ),
    (
        "sac_scale_closes_paved",
        TA,
        'if tags.get("sac_scale") is not None and not hard:',
        'if tags.get("sac_scale") is not None:',
    ),
    ("informal_inverted", TA, 'tags.get("informal") == "yes"', 'tags.get("informal") == "no"'),
    (
        "foot_designated_closes_paved",
        TA,
        'in ("designated", "official") and not hard:',
        'in ("designated", "official"):',
    ),
    (
        "visibility_drops_intermediate",
        TA,
        '{"intermediate", "bad", "poor", "horrible", "very_bad", "no"}',
        '{"bad", "poor", "horrible", "very_bad", "no"}',
    ),
    (
        "hiking_ignores_bicycle_route",
        TA,
        "if routes.hiking and not routes.bicycle_route and not hard:",
        "if routes.hiking and not hard:",
    ),
    (
        "width_limit_raised",
        TA,
        "width >= 2.0:\n        return True\n    return _scale",
        "width >= 3.0:\n        return True\n    return _scale",
    ),
    ("tracktype_drops_grade3", TA, '{"grade1", "grade2", "grade3"}', '{"grade1", "grade2"}'),
    (
        "smoothness_intermediate_counts",
        TA,
        'SMOOTH_ENOUGH = frozenset({"excellent", "good"})',
        'SMOOTH_ENOUGH = frozenset({"excellent", "good", "intermediate"})',
    ),
    ("park_path_with_surface", TA, '        and tags.get("surface") is None\n', ""),
    (
        "park_path_everywhere",
        TA,
        "        in_park\n        and not routes.bicycle_route",
        "        not routes.bicycle_route",
    ),
    (
        "park_path_ignores_routes",
        TA,
        "        in_park\n        and not routes.bicycle_route",
        "        in_park",
    ),
    (
        "mtb_smoothness_bad_dropped",
        TA,
        '{"bad", "very_bad", "horrible", "very_horrible", "impassable"}',
        '{"very_bad", "horrible", "very_horrible", "impassable"}',
    ),
    (
        "mtb_takes_singletrack",
        TA,
        "if _kept_by_class(tags) or singletrack.is_singletrack(tags):\n        return False",
        "if _kept_by_class(tags):\n        return False",
    ),
    (
        "mtb_paved_too",
        TA,
        '    if _hard_or_loose(tags) or routes.keeping_route:\n        return False\n    if tags.get("tracktype")',
        '    if routes.keeping_route:\n        return False\n    if tags.get("tracktype")',
    ),
    (
        "explicit_bicycle_ignored",
        TA,
        "    if bicycle is not None and bicycle not in PRIVATE_BICYCLE:\n        return MTB if is_mtb_class(tags, routes) else None\n",
        "",
    ),
    (
        "dismount_limit_inclusive",
        TA,
        "if metres < DISMOUNT_KEEP_M}",
        "if metres <= DISMOUNT_KEEP_M}",
    ),
    ("dismount_limit_raised", TA, "DISMOUNT_KEEP_M = 150.0", "DISMOUNT_KEEP_M = 250.0"),
    (
        "dismount_chain_not_joined",
        TA,
        "            if other != osm_id:\n                parent[find(osm_id)] = find(other)\n",
        "            pass\n",
    ),
    # The hard-surface lists moved to `routemaker.surfaces` (OWNER-DECISIONS 440).
    (
        "hard_surface_prefix_dropped",
        SURF,
        'SEALED_PREFIXES = ("concrete:", "paving_stones:", "asphalt:")',
        'SEALED_PREFIXES = ("paving_stones:", "asphalt:")',
    ),
    (
        "wooden_footbridge_counts_as_hard",
        SURF,
        "return surface_of(tags) not in WOOD_SURFACES or is_bike_bridge(tags)",
        "return True",
    ),
    (
        "sidewalk_not_kept",
        TA,
        "if not upstream_open(tags) or _kept_by_class(tags):",
        "if not upstream_open(tags):",
    ),
    (
        "zoo_streets_closed",
        ZOO,
        '    if tags.get("highway") in spec["open_highways"]:\n        return True',
        "    pass",
    ),
    ("zoo_spur_closed", ZOO, "or osm_id in spur_ways():", "or False:"),
    (
        "zoo_midpoint_ignored",
        ZOO,
        "    if not contains(midpoint(coords), polygons):\n        return False",
        "    pass",
    ),
    ("zoo_redirect_off", ZOO, "return racks() if contains((lon, lat)) else None", "return None"),
    (
        "zoo_cycleway_closed",
        ZOO,
        'return tags.get("highway") == trail["highway"] and tags.get("bicycle") in trail["bicycle"]',
        "return False",
    ),
    (
        "offroad_keeps_singletrack",
        TC,
        "OFFROAD_KEEPS = frozenset({trailaccess.MTB})",
        "OFFROAD_KEEPS = frozenset({trailaccess.MTB, singletrack.NO_BICYCLE})",
    ),
    (
        "mtb_only_drops_singletrack",
        TC,
        "MTB_ONLY = frozenset({trailaccess.MTB, singletrack.NO_BICYCLE})",
        "MTB_ONLY = frozenset({trailaccess.MTB})",
    ),
    (
        "zoo_after_singletrack",
        TC,
        "        elif zoo.closed_way(osm_id, tags, way.coordinates, zoo_polygon):\n            reason = zoo.NO_BICYCLE\n        elif singletrack.is_singletrack(tags):\n            reason = singletrack.NO_BICYCLE",
        "        elif singletrack.is_singletrack(tags):\n            reason = singletrack.NO_BICYCLE\n        elif zoo.closed_way(osm_id, tags, way.coordinates, zoo_polygon):\n            reason = zoo.NO_BICYCLE",
    ),
    (
        "walk_not_flagged",
        TC,
        "        elif osm_id in kept:\n            result.walk_bike.add(osm_id)",
        "        elif osm_id in kept:\n            pass",
    ),
    (
        "spur_not_destination_only",
        TC,
        "            result.destination_only.add(osm_id)\n",
        "            pass\n",
    ),
    ("long_dismount_kept", TC, "if reason is None and osm_id in long_dismount:", "if False:"),
]


def run_tests() -> bool:
    """True when the focused tests pass."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTS, "-x", "-q", "-p", "no:randomly"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main() -> int:
    if not run_tests():
        print("the unmutated tests do not pass", file=sys.stderr)
        return 2
    survivors = []
    for name, path, old, new in MUTANTS:
        target = REPO / path
        original = target.read_text()
        if original.count(old) != 1:
            print(f"BAD   {name}: pattern found {original.count(old)} times in {path}")
            survivors.append(name)
            continue
        try:
            target.write_text(original.replace(old, new))
            killed = not run_tests()
        finally:
            target.write_text(original)
        print(f"{'killed ' if killed else 'SURVIVED'} {name}")
        if not killed:
            survivors.append(name)
    print(f"{len(MUTANTS) - len(survivors)} of {len(MUTANTS)} killed")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
