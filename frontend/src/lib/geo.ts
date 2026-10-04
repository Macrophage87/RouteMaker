/** Plain geometry the planner needs: distances, the point list, the coverage box. */

export type LonLat = [number, number];

/**
 * settings.COVERAGE_BBOX, (west, south, east, north). tests/test_frontend.py
 * holds the two equal, so a change to the region is a change here too.
 */
export const COVERAGE_BBOX: readonly [number, number, number, number] = [-78.0, 38.2, -76.02, 39.72];

/** The API's ceiling on points per request (2 to 25). */
export const MAX_POINTS = 25;

const EARTH_RADIUS_M = 6_371_008.8;

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

export function haversineM(a: LonLat, b: LonLat): number {
  const dLat = toRadians(b[1] - a[1]);
  const dLon = toRadians(b[0] - a[0]);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRadians(a[1])) * Math.cos(toRadians(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function pathLengthM(points: readonly LonLat[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) total += haversineM(points[i - 1], points[i]);
  return total;
}

export function insideCoverage([lon, lat]: LonLat): boolean {
  const [west, south, east, north] = COVERAGE_BBOX;
  return lon >= west && lon <= east && lat >= south && lat <= north;
}

/**
 * The point list after one more click. The first click is the start and the
 * second the end; after that a click is a via, inserted on the leg it lengthens
 * least, so the start and end stay where the rider put them. Past the API's
 * ceiling the list is returned unchanged.
 *
 * With `loop` on (OWNER-DECISIONS 374) the ride is a cycle that starts and
 * finishes at the first point, so every click after the start is a via: even
 * the second click (no end to place), and the closing leg, last point back to
 * the start, is a slot too. Choosing it appends the click as the new last
 * point, and a tie with another leg goes to the closing one. The tie decides
 * the second stop (the third point): with a start and one stop the closing
 * leg costs exactly what the way out does, so the stop is appended and the
 * stops are visited in the order they were clicked.
 */
export function addPoint(points: readonly LonLat[], point: LonLat, loop = false): LonLat[] {
  if (points.length >= MAX_POINTS) return [...points];
  if (points.length < 2) return [...points, point];
  let bestIndex = 1;
  let bestCost = Number.POSITIVE_INFINITY;
  for (let i = 1; i < points.length; i += 1) {
    const cost =
      haversineM(points[i - 1], point) + haversineM(point, points[i]) - haversineM(points[i - 1], points[i]);
    if (cost < bestCost) {
      bestCost = cost;
      bestIndex = i;
    }
  }
  if (loop) {
    const last = points[points.length - 1];
    const closing = haversineM(last, point) + haversineM(point, points[0]) - haversineM(last, points[0]);
    if (closing <= bestCost) return [...points, point];
  }
  return [...points.slice(0, bestIndex), point, ...points.slice(bestIndex)];
}

/**
 * How much longer the route is than the straight lines between its points.
 * Flagged when it is at least twice as long and at least 3 km more, which is
 * where a rider would want to know why (a Mass Ride with no roadway crossing
 * nearby, today, can run to many times the straight line).
 */
export function detour(points: readonly LonLat[], routeM: number): { ratio: number; flagged: boolean } {
  const straight = pathLengthM(points);
  if (!(straight > 0) || !(routeM > 0)) return { ratio: 1, flagged: false };
  const ratio = routeM / straight;
  return { ratio, flagged: ratio >= 2 && routeM - straight >= 3000 };
}

/** The slippy-map tile holding a point at zoom z. */
export function lonLatToTile([lon, lat]: LonLat, z: number): { x: number; y: number; z: number } {
  const n = 2 ** z;
  const x = Math.floor(((lon + 180) / 360) * n);
  const latRad = toRadians(lat);
  const y = Math.floor(((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n);
  return { x: Math.min(n - 1, Math.max(0, x)), y: Math.min(n - 1, Math.max(0, y)), z };
}
