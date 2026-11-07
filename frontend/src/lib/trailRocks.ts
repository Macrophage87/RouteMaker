/**
 * Mountain-bike trails on the route (Stephen 2026-11-07: "Use the trail color in the ribbon and brown dots that look
 * like rocks on the edges", then of the route line, "Put that on the main track too", "and map, makes it easy to tell
 * you're on a mtb trail"): the line there in the trail's colour (its level's, or the unrated trails' brown), with brown
 * stones along both edges. Shared by the ride's ribbon (AheadGraph.tsx) and the route line (lib/routeTrailLayers.ts).
 */
export const TRAIL_ROCK = { fill: "#8a5a2e", edge: "#4a2c12" } as const;
