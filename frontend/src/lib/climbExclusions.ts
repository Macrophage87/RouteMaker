/**
 * Climbs taken off the map by hand, by climb id: the same list as
 * src/routemaker/climb_exclusions.py (tests/test_climb_exclusions.py holds them equal), where
 * each id's reason and source are. The owner, 2026-10-12: "Ensure only public roads open to bikes
 * are marked." A listed climb is dropped as the file is read, so the committed climbs.json need
 * not be rewritten for it.
 */
export const EXCLUDED_CLIMB_IDS: ReadonlySet<string> = new Set([
  "bd93dd04dc", // Travilah quarry haul road (landuse=quarry), owner report 2026-10-12
]);
