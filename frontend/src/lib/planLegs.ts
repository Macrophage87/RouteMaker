/**
 * Plan's legs as the rider planned them (v0.10.0, Stephen 2026-10-20: "Show faint straight lines between points
 * while being planned. Solid for routed, dashed for manual."): a faint straight line from each point to the next
 * while there is no route for the points as they are, dashed where the leg is drawn by hand (manual mode,
 * lib/pointKinds.ts); and, on the route itself, the drawn legs dashed.
 */
import type { LonLat } from "./geo.ts";
import { legPoints, validLegEnds } from "./lineEdit.ts";

/** What shows that manual mode is on, beside the switch (Stephen 2026-10-20: "make it clear that manual mode is being used"). */
export const MANUAL_BADGE = "Manual mode: taps join with straight lines";

type Line = { type: "Feature"; properties: { drawn: boolean }; geometry: { type: "LineString"; coordinates: number[][] } };
export type LegLines = { type: "FeatureCollection"; features: Line[] };

const line = (coordinates: readonly LonLat[], drawn: boolean): Line => ({
  type: "Feature",
  properties: { drawn },
  geometry: { type: "LineString", coordinates: coordinates.map((c) => [c[0], c[1]]) },
});

/**
 * A straight line between each pair of points in turn, `drawn` on the legs the rider drew; in a loop the rider chose,
 * one more from the last point back to the start (lineEdit.ts legPoints), so the plan shows how it closes (Stephen
 * 2026-10-20: "make the straight line more apparent ... and know how they are connected").
 */
export function planLegLines(points: readonly LonLat[], drawn: readonly number[], loop = false): LegLines {
  const marked = new Set(drawn);
  const ends = points.length >= 2 ? legPoints(points, loop) : [];
  const features: Line[] = [];
  for (let i = 0; i + 1 < ends.length; i++) features.push(line([ends[i], ends[i + 1]], marked.has(i)));
  return { type: "FeatureCollection", features };
}

/**
 * The plan's straight lines as a line that can be dragged (Stephen 2026-10-20: "allow for users to drag that to make
 * more via points"): the same shape as the route's (MapView LineEdit), each leg one segment, so a drag drops a via
 * into the leg grabbed, as a drag of the route does. Null with fewer than two points.
 */
export function planLegEdit(
  points: LonLat[],
  loop: boolean,
): { path: LonLat[]; ends: number[]; points: LonLat[]; legPoints: LonLat[]; dragOnly: true } | null {
  if (points.length < 2) return null;
  const legs = legPoints(points, loop);
  return { path: legs, ends: legs.slice(1).map((_, i) => i + 1), points, legPoints: legs, dragOnly: true };
}

/**
 * The route's drawn legs (the API's `drawn_legs`), each cut from its line at its leg ends (`leg_ends`, the index
 * of each leg's last vertex) for the `pointCount` points it was planned through. None when the route has no drawn
 * legs or its leg ends do not fit its line and points (lib/lineEdit.ts validLegEnds).
 */
export function routeDrawnLines(
  route: { geometry: { coordinates: LonLat[] }; leg_ends?: number[]; drawn_legs?: number[] | null } | null,
  pointCount: number,
): LegLines {
  const path = route?.geometry.coordinates ?? [];
  const ends = route?.leg_ends;
  const features: Line[] = [];
  if (!route?.drawn_legs || !validLegEnds(ends, path.length, pointCount)) return { type: "FeatureCollection", features };
  for (const leg of route.drawn_legs) {
    const from = leg === 0 ? 0 : ends[leg - 1];
    const to = ends[leg];
    if (to === undefined || to <= from) continue;
    features.push(line(path.slice(from, to + 1), true));
  }
  return { type: "FeatureCollection", features };
}
