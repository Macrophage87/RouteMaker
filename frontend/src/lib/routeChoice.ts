/**
 * Go's routes to choose from on the map (the owner, 2026-10-19: "I'd like to see the main route, then the more direct
 * route, and the trailmaxxed route ... together. Give the selected route a higher alpha and color code the three
 * routes. You should be able to press on the route and start."). Every route in the choice is drawn: the one chosen as
 * the route always is, in its stress colours, inside a casing of its own colour; each of the others as one line in its
 * colour, fainter and under it, named on the map at the place it parts most from the chosen one. A press on one of
 * them chooses it (MapView); the same choice is the route panel's radio group, where each row carries a swatch of the
 * colour, so the map is never the only way to choose, and the colour never the only thing that tells them apart.
 */
import type { RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { formatDistanceChange, formatDuration } from "./format.ts";
import { NEIGHBOUR_NAME } from "./neighbours.ts";
import { routeCasing } from "./routeColours.ts";

/**
 * The colours: the rider's own route keeps the route's blue (its casing in the High contrast palette); More direct a
 * near-black and Trailmaxxed a teal, both away from the stress tiers' greens, amber, red and violet; the router's own
 * other routes (at the top of the slider) a grey. Each is at least 4.5:1 on white, the halo its name is drawn on.
 */
export const CHOICE_DIRECT = "#1f2937";
export const CHOICE_TRAILMAXXED = "#0f766e";
export const CHOICE_OTHER = "#4b5563";

/** A route's colour by its row: the rider's own first, then More direct, Trailmaxxed, and the router's others. */
export function choiceColour(route: RouteResponse, index: number): string {
  if (index === 0) return routeCasing();
  if (route.neighbour?.kind === "direct") return CHOICE_DIRECT;
  if (route.neighbour?.kind === "calmer") return CHOICE_TRAILMAXXED;
  return CHOICE_OTHER;
}

/** The routes in the choice: the answer and its routes to choose from, in row order. */
export function choiceRoutes(picked: RouteResponse | null): RouteResponse[] {
  return picked ? [picked, ...(picked.candidates ?? [])] : [];
}

/** Each row's colour, or null where there is one route only (nothing to tell apart). */
export function choiceColours(picked: RouteResponse | null): string[] | null {
  const routes = choiceRoutes(picked);
  return routes.length < 2 ? null : routes.map(choiceColour);
}

/** A route's name on the map: "Your route", "More direct", "Trailmaxxed", "Route 2". */
export function choiceName(route: RouteResponse, index: number): string {
  if (index === 0) return "Your route";
  if (route.neighbour) return NEIGHBOUR_NAME[route.neighbour.kind];
  return `Route ${index + 1}`;
}

/** Points sampled along a line, at most `max`, ends included. */
function sample(line: readonly LonLat[], max: number): LonLat[] {
  if (line.length <= max) return [...line];
  const step = (line.length - 1) / (max - 1);
  return Array.from({ length: max }, (_v, i) => line[Math.round(i * step)]);
}

/** Squared distance in degrees, longitude scaled by the latitude's cosine: enough to compare nearness. */
function near(a: LonLat, b: LonLat, cos: number): number {
  const dx = (a[0] - b[0]) * cos;
  const dy = a[1] - b[1];
  return dx * dx + dy * dy;
}

/** Where on `line` to name it: the point farthest from `from` (the route chosen), so the name sits where it parts. */
export function labelPoint(line: readonly LonLat[], from: readonly LonLat[]): LonLat | null {
  if (line.length === 0) return null;
  const mine = sample(line, 120);
  const theirs = sample(from, 120);
  if (theirs.length === 0) return mine[Math.floor(mine.length / 2)];
  const cos = Math.cos((mine[0][1] * Math.PI) / 180);
  let best = mine[Math.floor(mine.length / 2)];
  let far = -1;
  for (const p of mine) {
    let d = Infinity;
    for (const q of theirs) d = Math.min(d, near(p, q, cos));
    if (d > far) {
      far = d;
      best = p;
    }
  }
  return best;
}

/** Metres on busy streets: LTS 3, LTS 4 and Avoid. */
function busyM(route: RouteResponse): number {
  const s = route.stress_m ?? {};
  return (s["3"] ?? 0) + (s["4"] ?? 0) + (s["5"] ?? 0);
}

/** Below these a change is not said: under a minute, and under about 250 ft (80 m). */
const SAID_S = 60;
const SAID_M = 80;

/**
 * What a route trades against the rider's own, for its name on the map (the owner, 2026-10-19: "write what they are
 * on each, and something like +5 min, - x miles of high stress and vice versa"): "+5 min, −0.6 mi (1.0 km) high-stress",
 * "−4 min, +0.6 mi (1.0 km) high-stress", "about the same time and traffic".
 */
export function choiceTradeoff(route: RouteResponse, own: RouteResponse): string {
  const parts: string[] = [];
  const dt = route.duration_s - own.duration_s;
  if (Math.abs(dt) >= SAID_S) parts.push(`${dt > 0 ? "+" : "\u2212"}${formatDuration(Math.abs(dt))}`);
  const dBusy = busyM(route) - busyM(own);
  if (Math.abs(dBusy) >= SAID_M) parts.push(`${dBusy > 0 ? "+" : "\u2212"}${formatDistanceChange(dBusy)} high-stress`);
  return parts.length > 0 ? parts.join(", ") : "about the same time and traffic";
}

/** A route's words on the map: its name, then its time (the rider's own) or what it trades against the rider's own. */
export function choiceLabel(routes: readonly RouteResponse[], index: number): string {
  const route = routes[index];
  const name = choiceName(route, index);
  return index === 0 ? `${name}, ${formatDuration(route.duration_s)}` : `${name}\n${choiceTradeoff(route, routes[0])}`;
}

/**
 * The map's data for the routes in the choice: a line for each one not chosen (`index`, `color`), and for every route,
 * the chosen one too, a point where its words are drawn, where it parts most from the others. Empty with one route, or
 * where `chosen` is out of range.
 */
export function choiceFeatures(picked: RouteResponse | null, chosen: number): { type: "FeatureCollection"; features: object[] } {
  const routes = choiceRoutes(picked);
  if (routes.length < 2 || !routes[chosen]) return { type: "FeatureCollection", features: [] };
  const lines: object[] = [];
  const names: object[] = [];
  routes.forEach((route, index) => {
    const line = route.geometry.coordinates as LonLat[];
    if (line.length < 2) return;
    const color = choiceColour(route, index);
    if (index !== chosen) lines.push({ type: "Feature", properties: { index, color }, geometry: route.geometry });
    const others = routes.flatMap((r, i) => (i === index ? [] : (r.geometry.coordinates as LonLat[])));
    const at = labelPoint(line, others);
    if (at) names.push({ type: "Feature", properties: { index, color, name: choiceLabel(routes, index) }, geometry: { type: "Point", coordinates: at } });
  });
  return { type: "FeatureCollection", features: [...lines, ...names] };
}
